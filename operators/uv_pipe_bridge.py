"""UV Pipe bridge: bmesh to the pure ``utils/uv_pipe_core`` dicts and back.

The core splits the faces into parts (walls, ring strips, disks, free parts) and
proposes every seam. This module reads what it needs from the mesh (``mesh_dicts``,
``single_uvs``, ``seam_edges``, ``sharp_edges``), lays each part out (``lay_out_parts``) and places,
packs and seams the result (``finish_pipe``). Placement is UV Stripe's own
(``uv_stripe_bridge.apply_maps``).

Two steps hand the work to Blender's own UV operators: the free parts and the
*No Stretch* walls are unwrapped by ``bpy.ops.uv.unwrap``, and Pack is
``bpy.ops.uv.pack_islands``. Both act on the selection of every mesh in Edit Mode,
so each call runs inside ``_isolated``: only the faces it is meant for are selected
(UV sync selection on), their pins are cleared, and afterwards the selection, the
active face, the UV selection, the pins, the seams and the UVs of every face the
call must not change are put back exactly.
"""

import math
from contextlib import contextmanager
from dataclasses import dataclass, field

import bmesh
import bpy

from ..utils import uv_pipe_core as pipe
from ..utils import uv_stripe_core as stripe_core
from ..utils import uv_stripe_select_core as select_core
from . import uv_stripe_bridge

LAYOUT_ITEMS = (
    ("RECTANGLE", "Rectangle",
     "Lay each wall out inside a straight rectangle: the seam sides straight and parallel, the ends straight"),
    ("QUADS", "Quads",
     "Make every quad of a regular quad-grid wall a rectangle; other walls fall back to Rectangle"),
    ("TRUE", "No Stretch",
     "Unwrap each wall with Blender's unwrap and straighten only its seam sides; the ends keep their shape"),
)
LOOP_SOURCE_ITEMS = (
    ("GEOMETRY", "Geometry", "Measure the seam loops' angles on the 3D positions"),
    ("UV", "UV", "Measure the seam loops' angles in the UV layout the mesh had before"),
)
QUADS_FALLBACK = "Quads fell back to Rectangle"

# The arguments of Blender's own operators, checked against Blender 5.3 (``get_rna_type()``).
UNWRAP_ARGS = {"method": "ANGLE_BASED", "fill_holes": True, "correct_aspect": True, "use_subsurf_data": False,
               "margin_method": "ADD", "margin": 0.0}
SMART_PROJECT_ARGS = {"island_margin": 0.0, "correct_aspect": True, "scale_to_bounds": False}
PACK_ARGS = {"udim_source": "CLOSEST_UDIM", "rotate": False, "scale": True, "merge_overlap": False,
             "margin_method": "FRACTION", "margin": 0.005, "pin": False, "shape_method": "AABB"}


# --- reading the mesh ------------------------------------------------------------------------------------------------


def mesh_dicts(bm, matrix, face_filter) -> tuple[dict, dict]:
    """The faces passing ``face_filter`` as the core's dicts: verts {BMVert.index: world (x, y, z)} and faces
    {BMFace.index: vertex indices in winding order}. Indices must be current."""
    faces, verts = {}, {}
    for f in bm.faces:
        if not face_filter(f):
            continue
        faces[f.index] = tuple(v.index for v in f.verts)
        for v in f.verts:
            if v.index not in verts:
                verts[v.index] = tuple(matrix @ v.co)
    return verts, faces


def single_uvs(bm, snapshot_uvs=None, faces=None) -> dict | None:
    """{vertex index: (u, v)} for the vertices whose corners all have one UV position, None without a UV layer.

    ``snapshot_uvs`` ({(face index, corner number): (u, v)}) is read instead of the active layer when given (the
    layout the mesh had before a modal changed it); ``faces`` limits the corners looked at to those faces."""
    layer = bm.loops.layers.uv.active
    if layer is None:
        return None
    seen: dict[int, tuple[float, float]] = {}
    split: set[int] = set()
    for f in (bm.faces if faces is None else faces):
        for k, lp in enumerate(f.loops):
            if snapshot_uvs is not None:
                uv = snapshot_uvs.get((f.index, k))
                if uv is None:
                    continue
            else:
                uv = lp[layer].uv
            uv = (float(uv[0]), float(uv[1]))
            vid = lp.vert.index
            old = seen.get(vid)
            if old is None:
                seen[vid] = uv
            elif abs(old[0] - uv[0]) > 1e-6 or abs(old[1] - uv[1]) > 1e-6:
                split.add(vid)
    return {vid: uv for vid, uv in seen.items() if vid not in split}


def seam_edges(bm, faces) -> frozenset:
    """The seams already on the mesh between two of ``faces``, as edge keys."""
    inside = set(faces)
    return frozenset(
        select_core._edge(e.verts[0].index, e.verts[1].index)
        for f in inside for e in f.edges
        if e.seam and sum(g in inside for g in e.link_faces) == 2)


def sharp_edges(bm, faces) -> frozenset:
    """The edges marked Sharp (``BMEdge.smooth`` off) between two of ``faces``, as edge keys."""
    inside = set(faces)
    return frozenset(
        select_core._edge(e.verts[0].index, e.verts[1].index)
        for f in inside for e in f.edges
        if not e.smooth and sum(g in inside for g in e.link_faces) == 2)


# --- Blender's own UV operators, isolated ----------------------------------------------------------------------------


def _bms(meshes):
    return [bmesh.from_edit_mesh(me) for me in meshes]


def _save_selection(bm):
    return {
        "verts": [v.select for v in bm.verts],
        "edges": [e.select for e in bm.edges],
        "faces": [f.select for f in bm.faces],
        "active": bm.faces.active,
        "history": list(bm.select_history),
        "uv_faces": [getattr(f, "uv_select", None) for f in bm.faces],
        "uv_loops": [(getattr(lp, "uv_select_vert", None), getattr(lp, "uv_select_edge", None))
                     for f in bm.faces for lp in f.loops],
        "uv_valid": getattr(bm, "uv_select_sync_valid", None),
    }


def _restore_selection(bm, saved):
    for v, s in zip(bm.verts, saved["verts"]):
        v.select = s
    for e, s in zip(bm.edges, saved["edges"]):
        e.select = s
    for f, s in zip(bm.faces, saved["faces"]):
        f.select = s
    active = saved["active"]
    bm.faces.active = active if active is not None and active.is_valid else None
    bm.select_history.clear()
    for elem in saved["history"]:
        if elem.is_valid:
            bm.select_history.add(elem)
    for f, s in zip(bm.faces, saved["uv_faces"]):
        if s is not None:
            f.uv_select = s
    loops = [lp for f in bm.faces for lp in f.loops]
    for lp, (sv, se) in zip(loops, saved["uv_loops"]):
        if sv is not None:
            lp.uv_select_vert = sv
        if se is not None:
            lp.uv_select_edge = se
    if saved["uv_valid"] is not None:
        bm.uv_select_sync_valid = saved["uv_valid"]


def _deselect_all(bm):
    for f in bm.faces:
        f.select = False
    for e in bm.edges:
        e.select = False
    for v in bm.verts:
        v.select = False
    bm.select_history.clear()
    if hasattr(bm, "uv_select_sync_valid"):
        bm.uv_select_sync_valid = False      # sync selection reads the mesh selection, not a stored UV one


@contextmanager
def _isolated(bm, mesh, meshes, faces, seams=None, keep=False):
    """Run a ``bpy.ops.uv`` call on exactly ``faces`` of ``bm`` (``mesh``'s edit bmesh).

    Inside: every face of every mesh in ``meshes`` is deselected but ``faces``, UV sync selection is on, the pins
    of ``faces`` are cleared and, when ``seams`` (edge keys) is given, the edges inside ``faces`` are seams exactly
    there. Afterwards the selection, the active face, the select history, the UV selection, the pins, the seams and
    the sync setting are as before, and so are the UVs of every face of ``bm``, except those of ``faces`` when
    ``keep``. The UV layer must exist."""
    tool = bpy.context.scene.tool_settings
    sync = tool.use_uv_select_sync
    others = [(me, b) for me, b in zip(meshes, _bms(meshes)) if me != mesh]
    layer = bm.loops.layers.uv.active
    targets = set(faces)
    saved = [(bm, _save_selection(bm))] + [(b, _save_selection(b)) for _me, b in others]
    old_uvs = [(lp, lp[layer].uv.copy()) for f in bm.faces if not (keep and f in targets) for lp in f.loops]
    pins = [(lp, lp[layer].pin_uv) for f in targets for lp in f.loops]
    edges = {e for f in targets for e in f.edges}
    old_seams = [(e, e.seam) for e in edges]
    try:
        for b, _s in saved:
            _deselect_all(b)
        for f in targets:
            f.select_set(True)
        for lp, _pin in pins:
            lp[layer].pin_uv = False
        if seams is not None:
            for e in edges:
                if sum(g in targets for g in e.link_faces) == 2:
                    e.seam = select_core._edge(e.verts[0].index, e.verts[1].index) in seams
        tool.use_uv_select_sync = True
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        for me, _b in others:
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        yield layer
    finally:
        tool.use_uv_select_sync = sync
        layer = bm.loops.layers.uv.active
        for lp, uv in old_uvs:
            lp[layer].uv = uv
        for lp, pin in pins:
            lp[layer].pin_uv = pin
        for e, seam in old_seams:
            e.seam = seam
        for b, s in saved:
            _restore_selection(b, s)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        for me, _b in others:
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)


def _ensure_layer(bm):
    layer = bm.loops.layers.uv.active
    return layer if layer is not None else bm.loops.layers.uv.new("UVMap")


def _uv_area(uv, part_faces) -> float:
    return sum(stripe_core._signed_area([uv[(fid, v)] for v in face]) for fid, face in part_faces.items())


def _face_area(verts, face) -> float:
    return select_core._area(verts, tuple(face))


def blender_unwrap(bm, faces, seams, *, mesh, meshes) -> dict:
    """{(face index, vertex index): (u, v)} of ``faces`` unwrapped by Blender's unwrap with ``seams`` (edge keys
    inside them) as the only seams; when the unwrap cannot solve them (a closed surface) by Smart UV Project. The
    mesh's UVs are left as they were."""
    _ensure_layer(bm)
    with _isolated(bm, mesh, meshes, faces, seams=seams) as layer:
        for f in faces:
            for lp in f.loops:
                lp[layer].uv = (0.0, 0.0)
        bpy.ops.uv.unwrap(**UNWRAP_ARGS)
        layer = bm.loops.layers.uv.active
        out = {(f.index, lp.vert.index): tuple(lp[layer].uv) for f in faces for lp in f.loops}
        if sum(abs(stripe_core._signed_area([out[(f.index, v.index)] for v in f.verts])) for f in faces) <= 1e-12:
            bpy.ops.uv.smart_project(**SMART_PROJECT_ARGS)
            layer = bm.loops.layers.uv.active
            out = {(f.index, lp.vert.index): tuple(lp[layer].uv) for f in faces for lp in f.loops}
    return out


# --- per-part layout -------------------------------------------------------------------------------------------------


@dataclass
class PartLayout:
    """One laid-out part: its UVs from (0, 0) over ``length`` (u) by ``height`` (v) in world units."""

    part_index: int
    kind: str
    uv: dict                      # {(face index, vertex index): (u, v)}
    length: float
    height: float
    faces: dict                   # face index -> BMFace
    notice: str | None = None     # e.g. QUADS_FALLBACK
    inner_seams: set = field(default_factory=set)   # edge keys inside the part its UVs are cut at


def _normalised(uv: dict) -> tuple[dict, float, float]:
    us = [p[0] for p in uv.values()]
    vs = [p[1] for p in uv.values()]
    u0, v0 = min(us), min(vs)
    return {k: (u - u0, v - v0) for k, (u, v) in uv.items()}, max(us) - u0, max(vs) - v0


def _to_real_area(verts, part, uv: dict) -> dict:
    """``uv`` scaled about the origin so its area equals the part's 3D area."""
    area = abs(_uv_area(uv, part.faces))
    real = sum(_face_area(verts, face) for face in part.faces.values())
    if area <= 1e-18 or real <= 0.0:
        return uv
    s = math.sqrt(real / area)
    return {k: (u * s, v * s) for k, (u, v) in uv.items()}


def _ring_uvs(verts, part, break_edge):
    """A RING part as a straight strip (Even Rows): its UVs and the edge key its ring is cut at."""
    strip = select_core.strip_from_faces(verts, part.faces, near=set(part.boundaries[0]) if part.boundaries else None)
    if not strip.closed:
        strip.layout = "EVEN"
        return stripe_core.stripe_uvs(strip), None
    if break_edge is not None:
        at = select_core.rungs_at(strip, [tuple(sorted(break_edge))])
        if at:
            opened = select_core.open_ring(strip, at[0])
            opened.layout = "EVEN"
            return stripe_core.stripe_uvs(opened), opened.break_edge
    strip.layout = "EVEN"
    k = strip.seam if strip.seam is not None else stripe_core.sharpest_rung(strip)
    return stripe_core.stripe_uvs(strip), select_core.rung_edge(strip, k)


def _straight_seam_sides(verts, part, seam, uv: dict) -> dict:
    """A Blender-unwrapped wall turned so its seam runs along +V, both seam sides then snapped onto straight
    vertical lines (each at its side's mean u, v by 3D arc length along the seam), the rest relaxed inside with the
    seam and the end loops held; scaled to the part's real area."""
    uv = _to_real_area(verts, part, uv)
    sides = pipe._seam_sides(part, seam)
    first, last = seam.verts[0], seam.verts[-1]
    ends = {True: {}, False: {}}
    for (fid, vid), left in sides.items():
        ends[left].setdefault(vid, uv[(fid, vid)])
    du = dv = 0.0
    for side in ends.values():
        if first in side and last in side:
            du += side[last][0] - side[first][0]
            dv += side[last][1] - side[first][1]
    turn = math.pi / 2.0 - math.atan2(dv, du) if (du or dv) else 0.0
    c, s = math.cos(turn), math.sin(turn)
    uv = {k: (u * c - v * s, u * s + v * c) for k, (u, v) in uv.items()}
    arc = dict(zip(seam.verts, pipe._cumulative(verts, seam.verts)))
    seam_keys = list(sides)
    v0 = sum(uv[key][1] - arc[key[1]] for key in seam_keys) / len(seam_keys)
    side_u = {}
    for left in (True, False):
        keys = [key for key in seam_keys if sides[key] == left]
        if keys:
            side_u[left] = sum(uv[key][0] for key in keys) / len(keys)
    for key in seam_keys:
        uv[key] = (side_u[sides[key]], v0 + arc[key[1]])
    held = set(seam.verts) | {v for b in part.boundaries if first in b or last in b for v in b}
    size = max(max(p[0] for p in uv.values()) - min(p[0] for p in uv.values()),
               max(p[1] for p in uv.values()) - min(p[1] for p in uv.values()), 1e-9)
    pipe._relax(verts, part, uv, held, size)
    if _uv_area(uv, part.faces) < 0.0:
        uv = {k: (-u, v) for k, (u, v) in uv.items()}
    return _to_real_area(verts, part, uv)


def lay_out_parts(bm, analysis, verts, layout, *, mesh=None, meshes=()) -> list[PartLayout]:
    """Every part of ``analysis`` laid out, in part order, in world units from (0, 0).

    WALL: ``wall_uvs`` under "RECTANGLE" and "QUADS" (with ``QUADS_FALLBACK`` as the notice when it is no regular
    grid); under "TRUE" Blender's unwrap with the wall's seam, its seam sides then made straight and parallel to V
    (``_straight_seam_sides``). RING: a straight strip under Even Rows, opened at the analysis' break, else cut as
    UV Stripe cuts a ring. DISK: ``disk_uvs``. FREE: Blender's unwrap scaled to the real area, cut at the cuts
    inside it, the user's slits (``analysis.slits``) among them, which stay marked as seams. A part whose own
    layout fails is unwrapped as a FREE part, with the reason as its notice. ``verts`` are the core's world-space
    vertices; face ids are ``BMFace.index``. Blender's unwrap needs ``mesh`` (``bm``'s mesh) and ``meshes`` (every
    mesh in Edit Mode, whose selection it changes and restores). The mesh's UVs are not changed."""
    bm.faces.ensure_lookup_table()
    out = []
    for i, part in enumerate(analysis.parts):
        faces = {fid: bm.faces[fid] for fid in part.faces}
        notice, inner, uv, kind = None, set(), None, part.kind
        try:
            if kind == "WALL":
                seam = analysis.seams[i]
                inner = set(seam.edges())
                if layout == "TRUE":
                    unwrapped = blender_unwrap(bm, list(faces.values()), inner | (analysis.cuts & _inner(part)),
                                               mesh=mesh, meshes=meshes)
                    uv = _straight_seam_sides(verts, part, seam, unwrapped)
                else:
                    uv, grid = pipe.wall_uvs(verts, part, seam, quads=layout == "QUADS")
                    if layout == "QUADS" and not grid:
                        notice = QUADS_FALLBACK
            elif kind == "RING":
                uv, cut = _ring_uvs(verts, part, analysis.breaks.get(i))
                inner = {cut} if cut is not None else set()
            elif kind == "DISK":
                uv = pipe.disk_uvs(verts, part)
        except (ValueError, KeyError, ZeroDivisionError) as exc:
            notice = f"a {kind.lower()} of {len(part.faces)} faces could not be laid out ({exc}): unwrapped freely"
            kind, uv, inner = "FREE", None, set()
        if uv is None:
            seams = (analysis.cuts & _inner(part)) | getattr(analysis, "slits", {}).get(i, set())
            uv = _to_real_area(verts, part, blender_unwrap(bm, list(faces.values()), seams, mesh=mesh, meshes=meshes))
            inner = set(seams)
        uv, length, height = _normalised(uv)
        out.append(PartLayout(i, kind, uv, length, height, faces, notice, inner))
    return out


def _inner(part) -> set:
    """Edge keys used by two of the part's faces."""
    return pipe._inner_edges(part)


# --- placement, pack and seams ---------------------------------------------------------------------------------------


@dataclass
class PipeSettings:
    """What ``finish_pipe`` reads from the UV Pipe operator."""

    mode: str
    active_fit: str
    orientation: str
    mark_seams: bool
    pack: bool
    offset_axis: str
    offset_limit: float
    offset_seed: int

    @classmethod
    def from_operator(cls, op) -> "PipeSettings":
        return cls(**{name: getattr(op, name) for name in cls.__dataclass_fields__})


def _pack(bm, faces, *, mesh, meshes) -> None:
    """Pack the islands of ``faces`` into 0-1 with Blender's island packer: no rotation, one shared scale."""
    with _isolated(bm, mesh, meshes, faces, keep=True) as layer:
        loops = [lp for f in faces for lp in f.loops]
        us = [lp[layer].uv.x for lp in loops]
        vs = [lp[layer].uv.y for lp in loops]
        span = max(max(us) - min(us), max(vs) - min(vs), 1e-12)
        u0, v0 = min(us), min(vs)
        for lp in loops:       # inside the unit square first, so the packer's closest tile is 0-1
            lp[layer].uv = ((lp[layer].uv.x - u0) / span, (lp[layer].uv.y - v0) / span)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        bpy.ops.uv.pack_islands(**PACK_ARGS)
        layer = bm.loops.layers.uv.active
        loops = [lp for f in faces for lp in f.loops]
        du = math.floor(min(lp[layer].uv.x for lp in loops) + 1e-9)
        dv = math.floor(min(lp[layer].uv.y for lp in loops) + 1e-9)
        if du or dv:
            for lp in loops:
                lp[layer].uv = (lp[layer].uv.x - du, lp[layer].uv.y - dv)


def seam_split(layouts) -> tuple[set, set]:
    """(marked, cleared) BMEdges of the laid-out parts: every part outline and each part's ``inner_seams`` are
    seams, the other edges inside a part are not. What Mark Seams sets, and what the modal draws as seams."""
    marked, cleared = set(), set()
    for lay in layouts:
        inside = set(lay.faces.values())
        for e in {e for f in inside for e in f.edges}:
            inner = sum(g in inside for g in e.link_faces)
            key = select_core._edge(e.verts[0].index, e.verts[1].index)
            if inner == 1 or key in lay.inner_seams:
                marked.add(e)
            elif inner >= 2:
                cleared.add(e)
    return marked, cleared - marked


def _mark_seams(layouts) -> None:
    """Seams on every part outline and on each part's ``inner_seams``; the other edges inside a part cleared; edges
    outside the parts untouched."""
    marked, cleared = seam_split(layouts)
    for e in cleared:
        e.seam = False
    for e in marked:
        e.seam = True


def finish_pipe(bm, layouts, settings: PipeSettings, contexts, *, mesh=None, meshes=()) -> bool:
    """Place the laid-out parts of one mesh, pack them and set their seams, as ``settings`` say.

    Placement is ``uv_stripe_bridge.apply_maps`` with every part in one Fit group (one texel density per object).
    In Fit 0-1 with ``pack`` the parts are then packed into 0-1 by Blender's packer (``PACK_ARGS``: no rotation,
    one shared scale, margin 0.005), and Random Offset is not applied; otherwise Random Offset is applied as in UV
    Stripe. With ``mark_seams`` the seams follow the part outlines, each wall's seam and each ring's cut. Returns
    whether the parts were fitted to an active one. Packing needs ``mesh`` and ``meshes`` (see ``lay_out_parts``).
    """
    if not layouts:
        return False
    faces = {}
    for lay in layouts:
        faces.update(lay.faces)
    vertical = settings.orientation == "VERTICAL"
    packed = settings.mode == "FIT" and settings.pack
    active_face = bm.faces.active if settings.mode == "ACTIVE" else None
    active = next((n for n, lay in enumerate(layouts)
                   if active_face is not None and lay.faces.get(active_face.index) is active_face), None)
    offset = ("NONE", 0.0, 0) if packed else (
        uv_stripe_bridge.offset_axis(settings.offset_axis, vertical), settings.offset_limit, settings.offset_seed)
    fitted = uv_stripe_bridge.apply_maps(
        bm, [lay.uv for lay in layouts], [lay.length for lay in layouts], [lay.height for lay in layouts], faces,
        settings.mode, contexts, [0] * len(layouts), vertical, active, settings.active_fit, offset)
    if packed:
        _pack(bm, list(faces.values()), mesh=mesh, meshes=meshes)
    if settings.mark_seams:
        _mark_seams(layouts)
    return fitted
