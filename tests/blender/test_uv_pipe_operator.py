"""Headless tests of the UV Pipe operator (iops.mesh_uv_pipe) on real meshes in Edit Mode. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_uv_pipe_operator.py

Not collected by pytest (tests/conftest.py ignores tests/blender). The meshes are the synthetic fixtures of
tests/uv_pipe_fixtures.py.
"""
import json
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

ADDON = "InteractionOps"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/: shared fixtures
from uv_pipe_fixtures import bent_pipe, box_tube, capped_cylinder, clean_bend, framed_box, open_tube  # noqa: E402

operator = None


def enable_addon():
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    global operator
    from InteractionOps.operators.mesh_uv_pipe import IOPS_OT_Mesh_UV_Pipe
    operator = IOPS_OT_Mesh_UV_Pipe


# --- mesh builders -------------------------------------------------------------------------------------------------

def _object(mesh, uv_size=None, name="uv_pipe"):
    """A mesh object of a fixture ``(verts, faces)``, active and in Object Mode. Face k of the mesh is the k-th
    fixture face in id order; the fixture's vertex ids are renumbered in id order (``obj["ids"]`` maps them).
    ``uv_size`` adds a UV layer with each loop's UV at its vertex's (x, y) / uv_size + 0.5."""
    verts, faces = mesh
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for other in list(bpy.context.view_layer.objects):
        other.select_set(False)
    order = sorted(verts)
    index = {vid: i for i, vid in enumerate(order)}
    bm = bmesh.new()
    bverts = [bm.verts.new(verts[vid]) for vid in order]
    for fid in sorted(faces):
        bm.faces.new([bverts[index[v]] for v in faces[fid]])
    if uv_size is not None:
        layer = bm.loops.layers.uv.new("UVMap")
        for f in bm.faces:
            for lp in f.loops:
                lp[layer].uv = lp.vert.co.xy / uv_size + Vector((0.5, 0.5))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    obj["ids"] = json.dumps({str(vid): i for vid, i in index.items()})
    return obj


def _vid(obj, fixture_id):
    return json.loads(obj["ids"])[str(fixture_id)]


def _edit(obj, select=None):
    """Edit Mode in face select mode with the faces whose index is in ``select`` selected (None: none)."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(obj.data)
    for f in bm.faces:
        f.select_set(False)
    for f in bm.faces:
        if select is not None and f.index in select:
            f.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    return bm


def _run(**props):
    return bpy.ops.iops.mesh_uv_pipe(**props)


class _OperatorStandIn:
    """Stands in for an operator instance: the operator's defaults and methods, keeping its reports."""

    def __init__(self, **props):
        for prop in bpy.ops.iops.mesh_uv_pipe.get_rna_type().properties:
            if prop.identifier != "rna_type":
                self.__dict__[prop.identifier] = prop.default
        self.__dict__.update(props)
        self.reports = []

    def report(self, kinds, message):
        self.reports.append((set(kinds), message))

    def __getattr__(self, name):
        return getattr(operator, name).__get__(self)


# --- measuring ------------------------------------------------------------------------------------------------------

def _bm(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    return bm


def _uv(lp, layer):
    return (lp[layer].uv.x, lp[layer].uv.y)


def _islands(obj, faces=None):
    """The UV islands of ``faces`` (indices; None: all) as sorted lists of face indices: faces sharing an edge
    whose two ends have the same UVs in both faces."""
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    chosen = set(range(len(bm.faces))) if faces is None else set(faces)
    parent = {i: i for i in chosen}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def corner(f, v):
        return next(_uv(lp, layer) for lp in f.loops if lp.vert is v)

    for e in bm.edges:
        fs = [f for f in e.link_faces if f.index in chosen]
        if len(fs) != 2:
            continue
        a, b = fs
        if all(math.dist(corner(a, v), corner(b, v)) < 1e-6 for v in e.verts):
            parent[root(a.index)] = root(b.index)
    groups = {}
    for i in chosen:
        groups.setdefault(root(i), []).append(i)
    return sorted(sorted(g) for g in groups.values())


def _signed(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _uv_area(obj, faces):
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    return sum(abs(_signed([_uv(lp, layer) for lp in bm.faces[i].loops])) for i in faces)


def _area(obj, faces):
    bm = _bm(obj)
    m = obj.matrix_world
    total = 0.0
    for i in faces:
        pts = [m @ v.co for v in bm.faces[i].verts]
        n = Vector((0.0, 0.0, 0.0))
        for a, b in zip(pts, pts[1:] + pts[:1]):
            n += a.cross(b)
        total += n.length / 2.0
    return total


def _bbox(obj, faces):
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    pts = [_uv(lp, layer) for i in faces for lp in bm.faces[i].loops]
    us, vs = [p[0] for p in pts], [p[1] for p in pts]
    return min(us), min(vs), max(us), max(vs)


def _density(obj, faces):
    return math.sqrt(_uv_area(obj, faces) / _area(obj, faces))


def _seams(obj):
    return {tuple(sorted(v.index for v in e.verts)) for e in _bm(obj).edges if e.seam}


def _uv_state(obj):
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    return [tuple(round(c, 6) for c in _uv(lp, layer)) for f in bm.faces for lp in f.loops]


def _flipped(obj, faces):
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    return [i for i in faces if _signed([_uv(lp, layer) for lp in bm.faces[i].loops]) <= 0.0]


def _polygon_perimeter(sides, radius=1.0):
    return sides * 2.0 * radius * math.sin(math.pi / sides)


# Reference A face ids (capped_cylinder defaults): the wall, the two bottom rings, the fan, the top ring, the n-gon.
A_WALL = range(128)
A_RINGS = (range(128, 160), range(160, 192), range(224, 256))
A_FAN = range(192, 224)
A_NGON = range(256, 257)
A_GROUPS = (A_WALL, *A_RINGS, A_FAN, A_NGON)


def _column_edges(obj, sides, rows, column):
    """Edge keys (mesh indices) of open_tube's lengthwise column ``column``."""
    return {tuple(sorted((_vid(obj, k * sides + column), _vid(obj, (k + 1) * sides + column)))) for k in range(rows)}


def _edge_indices(obj, keys):
    bm = _bm(obj)
    return [e.index for e in bm.edges if tuple(sorted(v.index for v in e.verts)) in keys]


def _inner_seams(obj, faces):
    """Seam edges with both faces among ``faces``."""
    bm = _bm(obj)
    chosen = set(faces)
    return {tuple(sorted(v.index for v in e.verts)) for e in bm.edges
            if e.seam and sum(f.index in chosen for f in e.link_faces) == 2}


# --- tests ----------------------------------------------------------------------------------------------------------

def test_operator_is_registered():
    assert hasattr(bpy.ops.iops, "mesh_uv_pipe")
    rna = bpy.ops.iops.mesh_uv_pipe.get_rna_type()
    assert rna.name == "UV Pipe"
    props = rna.properties
    expected = {"mode": "FIT", "active_fit": "WIDTH", "orientation": "HORIZONTAL", "layout": "RECTANGLE",
                "loop_source": "GEOMETRY", "split_at_bends": False, "split_at_seams": False, "mark_seams": True,
                "pack": True, "offset_axis": "NONE", "offset_seed": 0, "merge_doubles": True, "picks": "",
                "seam_side": "SHORTEST"}
    for name, value in expected.items():
        assert props[name].default == value, (name, props[name].default)
    for name, deg in (("loop_angle", 120.0), ("sharp_angle", 60.0), ("bend_angle", 45.0), ("hard_angle", 30.0)):
        assert abs(props[name].default - math.radians(deg)) < 1e-6, name
        assert props[name].subtype == "ANGLE"
    assert abs(props["offset_limit"].default - 0.25) < 1e-6
    assert props["picks"].is_hidden and props["picks"].is_skip_save
    assert {"REGISTER", "UNDO"} <= set(operator.bl_options)


def test_reference_a_gives_six_islands():
    obj = _object(capped_cylinder())
    _edit(obj)
    assert _run() == {"FINISHED"}
    islands = _islands(obj)
    assert islands == sorted(sorted(g) for g in A_GROUPS), [len(g) for g in islands]
    densities = [_density(obj, g) for g in A_GROUPS]
    assert max(densities) / min(densities) - 1.0 < 1e-3, densities
    u0, v0, u1, v1 = _bbox(obj, A_WALL)
    assert abs((u1 - u0) / (v1 - v0) - _polygon_perimeter(32) / 2.0) < 1e-3 * _polygon_perimeter(32) / 2.0
    for ring, (outer, inner) in zip(A_RINGS, ((1.0, 0.671), (0.671, 0.493), (1.0, 0.671))):
        mean = (_polygon_perimeter(32, outer) + _polygon_perimeter(32, inner)) / 2.0
        width = _area(obj, ring) / mean          # the ring's real width (its area over its length)
        u0, v0, u1, v1 = _bbox(obj, ring)
        assert abs((u1 - u0) / (v1 - v0) - mean / width) < 1e-3 * mean / width, ((u1 - u0) / (v1 - v0), mean / width)


def test_reference_a_packs_inside_zero_one():
    obj = _object(capped_cylinder())
    _edit(obj)
    assert _run() == {"FINISHED"}
    for u, v in _uv_state(obj):
        assert -1e-6 <= u <= 1.0 + 1e-6 and -1e-6 <= v <= 1.0 + 1e-6, (u, v)
    boxes = [_bbox(obj, g) for g in A_GROUPS]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = min(a[2], b[2]) - max(a[0], b[0]) > 1e-9 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-9
            assert not overlap, (a, b)
    assert max(max(b[2] for b in boxes), max(b[3] for b in boxes)) > 0.9    # packed, not left small


def test_pack_off_stacks_like_uv_stripe():
    obj = _object(capped_cylinder())
    _edit(obj)
    assert _run(pack=False) == {"FINISHED"}
    boxes = sorted((_bbox(obj, g) for g in A_GROUPS), key=lambda b: b[1])
    assert abs(min(b[0] for b in boxes)) < 1e-6 and abs(max(b[2] for b in boxes) - 1.0) < 1e-6
    assert all(abs(b[0]) < 1e-6 for b in boxes)
    assert abs(boxes[0][1]) < 1e-6
    for lo, hi in zip(boxes, boxes[1:]):
        assert abs(hi[1] - lo[3] - 0.01) < 1e-6, (lo, hi)
    densities = [_density(obj, g) for g in A_GROUPS]
    assert max(densities) / min(densities) - 1.0 < 1e-3, densities


def _wall_seam_corner_us(obj, wall):
    """The u of every corner of the wall's faces at a vertex of its seam (seam edges inside the wall)."""
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    seam_verts = {v for key in _inner_seams(obj, wall) for v in key}
    return [(lp.vert.index, _uv(lp, layer)) for i in wall for lp in bm.faces[i].loops if lp.vert.index in seam_verts]


def test_reference_b_wall_is_one_island():
    mesh = bent_pipe()
    obj = _object(mesh)
    _edit(obj)
    assert _run() == {"FINISHED"}
    n = len(mesh[1])
    wall = list(range(n - 2))               # the two n-gon caps come last
    islands = _islands(obj)
    assert len(islands) == 3 and wall in islands, [len(g) for g in islands]
    seam = _inner_seams(obj, wall)
    assert seam and len({v for key in seam for v in key}) == len(seam) + 1     # one open path
    u0, _v0, u1, _v1 = _bbox(obj, wall)
    for vid, (u, _v) in _wall_seam_corner_us(obj, wall):
        assert min(abs(u - u0), abs(u - u1)) < 1e-6, (vid, u, u0, u1)
    assert not _flipped(obj, range(n)), _flipped(obj, range(n))


def test_quads_layout_on_a_clean_tube():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    stand = _OperatorStandIn(layout="QUADS")
    assert stand.execute(bpy.context) == {"FINISHED"}
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    for f in bm.faces:
        pts = [_uv(lp, layer) for lp in f.loops]
        assert len({round(p[0], 6) for p in pts}) == 2 and len({round(p[1], 6) for p in pts}) == 2, pts
    assert not any("Quads fell back" in m for _k, m in stand.reports), stand.reports
    obj = _object(bent_pipe())
    _edit(obj)
    stand = _OperatorStandIn(layout="QUADS")
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert any("Quads fell back to Rectangle" in m for _k, m in stand.reports), stand.reports


def test_no_stretch_layout_keeps_the_seam_sides_straight():
    mesh = clean_bend(12, 4)
    obj = _object(mesh)
    _edit(obj)
    assert _run(layout="TRUE") == {"FINISHED"}
    wall = list(range(len(mesh[1])))
    assert _islands(obj) == [wall]
    corners = _wall_seam_corner_us(obj, wall)
    us = sorted({round(u, 5) for _vid, (u, _v) in corners})
    assert len(us) == 2, us                                   # two straight lines parallel to V
    by_side = {u: sorted(v for _vid, (uu, v) in corners if round(uu, 5) == u) for u in us}
    assert [round(v, 5) for v in by_side[us[0]]] == [round(v, 5) for v in by_side[us[1]]]   # level with each other
    assert not _flipped(obj, wall)


def test_seams_follow_the_parts():
    obj = _object(capped_cylinder())
    _edit(obj)
    bm = _bm(obj)
    for e in bm.edges:            # old seams everywhere: the ones inside a part go
        e.seam = True
    bmesh.update_edit_mesh(obj.data)
    assert _run() == {"FINISHED"}
    bm = _bm(obj)
    group = {i: g for g, faces in enumerate(A_GROUPS) for i in faces}
    between = {tuple(sorted(v.index for v in e.verts)) for e in bm.edges
               if len({group[f.index] for f in e.link_faces}) == 2}
    assert len(between) == 5 * 32
    seams = _seams(obj)
    assert between <= seams
    wall_seam = _inner_seams(obj, A_WALL)
    assert len(wall_seam) == 4
    xy = {(round(bm.verts[v].co.x, 6), round(bm.verts[v].co.y, 6)) for key in wall_seam for v in key}
    assert len(xy) == 1                                       # one lengthwise column
    ring_cuts = [_inner_seams(obj, ring) for ring in A_RINGS]
    assert all(len(cut) == 1 for cut in ring_cuts), ring_cuts   # each ring strip's cut rung
    assert not _inner_seams(obj, A_FAN) and not _inner_seams(obj, A_NGON)
    assert seams == between | wall_seam | set().union(*ring_cuts)


def test_mark_seams_off_leaves_seams_alone():
    obj = _object(capped_cylinder())
    _edit(obj)
    bm = _bm(obj)
    for e in bm.edges:
        e.seam = e.index % 3 == 0
    bmesh.update_edit_mesh(obj.data)
    before = _seams(obj)
    assert _run(mark_seams=False) == {"FINISHED"}
    assert _seams(obj) == before
    assert len(_islands(obj)) == 6


def test_selected_faces_only():
    obj = _object(capped_cylinder(), uv_size=10.0)
    bm = _edit(obj, set(A_WALL))
    layer = bm.loops.layers.uv.active
    caps = [f for f in bm.faces if f.index not in A_WALL]
    caps[0].loops[0][layer].pin_uv = True
    caps[3].loops[1][layer].pin_uv = True
    bm.faces.ensure_lookup_table()
    bm.faces.active = bm.faces[5]
    bmesh.update_edit_mesh(obj.data)
    before = _uv_state(obj)
    selected = [f.select for f in bm.faces]
    edges_selected = [e.select for e in bm.edges]
    for layout in ("RECTANGLE", "TRUE"):          # TRUE goes through Blender's unwrap, then the packer
        assert _run(layout=layout) == {"FINISHED"}
        after = _uv_state(obj)
        bm = _bm(obj)
        layer = bm.loops.layers.uv.active
        k = 0
        for f in bm.faces:
            for _lp in f.loops:
                if f.index not in A_WALL:
                    assert after[k] == before[k], (f.index, before[k], after[k])
                k += 1
        assert after != before
        assert [f.select for f in bm.faces] == selected
        assert [e.select for e in bm.edges] == edges_selected
        assert bm.faces.active is not None and bm.faces.active.index == 5
        pins = [(f.index, n) for f in bm.faces for n, lp in enumerate(f.loops) if lp[layer].pin_uv]
        assert pins == [(caps[0].index, 0), (caps[3].index, 1)], pins
        assert _islands(obj, A_WALL) == [list(A_WALL)]


def test_blender_calls_restore_selection_pins_and_sync():
    # No Stretch unwraps the wall alone with Blender's unwrap, then the packer takes all six parts: in between the
    # selection is only the wall's faces and the pins are cleared; afterwards everything is as it was
    obj = _object(capped_cylinder(), uv_size=10.0)
    bm = _edit(obj, set(range(257)))
    layer = bm.loops.layers.uv.active
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.active = bm.faces[A_RINGS[0][3]]
    bm.select_history.add(bm.faces[A_RINGS[0][3]])
    bm.faces[A_WALL[7]].loops[2][layer].pin_uv = True
    bm.faces[A_FAN[1]].loops[0][layer].pin_uv = True
    bmesh.update_edit_mesh(obj.data)
    tool = bpy.context.scene.tool_settings
    tool.use_uv_select_sync = False
    state = lambda b: ([v.select for v in b.verts], [e.select for e in b.edges], [f.select for f in b.faces])  # noqa: E731
    before = state(bm)
    pins_before = [lp[layer].pin_uv for f in bm.faces for lp in f.loops]
    for pack in (True, False):        # without Pack the wall's unwrap is the last Blender call
        assert _run(layout="TRUE", pack=pack) == {"FINISHED"}
        bm = _bm(obj)
        layer = bm.loops.layers.uv.active
        assert state(bm) == before
        assert bm.faces.active is not None and bm.faces.active.index == A_RINGS[0][3]
        assert [elem.index for elem in bm.select_history] == [A_RINGS[0][3]]
        assert [lp[layer].pin_uv for f in bm.faces for lp in f.loops] == pins_before
        assert tool.use_uv_select_sync is False
        assert len(_islands(obj)) == 6
    tool.use_uv_select_sync = True


def test_free_part_keeps_other_faces_and_selection():
    # a free part goes through Blender's unwrap and the packer; the box's faces are all in scope here, so a second
    # object in Edit Mode carries the faces that must not move or change selection
    box = _object(box_tube(), name="box")
    other = _object(open_tube(8, 2), uv_size=4.0, name="other")
    for o in (box, other):
        o.select_set(True)
    bpy.context.view_layer.objects.active = box
    bpy.ops.object.mode_set(mode="EDIT")
    bm_box = _bm(box)
    for f in bm_box.faces:
        f.select_set(True)
    bm_other = _bm(other)
    for f in bm_other.faces:
        f.select_set(False)
    bmesh.update_edit_mesh(box.data)
    bmesh.update_edit_mesh(other.data)
    before = _uv_state(other)
    assert _run(hard_angle=math.pi) == {"FINISHED"}
    assert _uv_state(other) == before
    assert not any(f.select for f in _bm(other).faces)
    assert all(f.select for f in _bm(box).faces)
    bpy.ops.object.mode_set(mode="OBJECT")
    other.select_set(False)


def test_no_selection_takes_every_visible_face():
    obj = _object(capped_cylinder(), uv_size=10.0)
    bm = _edit(obj)
    bm.faces.ensure_lookup_table()
    bm.faces[A_NGON[0]].hide_set(True)
    bmesh.update_edit_mesh(obj.data)
    before = _uv_state(obj)
    assert _run() == {"FINISHED"}
    visible = [i for i in range(257) if i not in A_NGON]
    islands = _islands(obj, visible)
    assert islands == sorted(sorted(g) for g in (A_WALL, *A_RINGS, A_FAN)), [len(g) for g in islands]
    bm = _bm(obj)
    after = _uv_state(obj)
    k = 0
    for f in bm.faces:
        for _lp in f.loops:
            if f.index in A_NGON:
                assert after[k] == before[k]
            k += 1
    assert bm.faces[A_NGON[0]].hide


def test_object_scale_is_respected():
    obj = _object(open_tube(12, 4))
    obj.scale = (1.0, 1.0, 3.0)
    _edit(obj)
    assert _run() == {"FINISHED"}
    u0, v0, u1, v1 = _bbox(obj, range(48))
    expected = 6.0 / _polygon_perimeter(12)
    assert abs((v1 - v0) / (u1 - u0) - expected) < 1e-3 * expected, ((v1 - v0) / (u1 - u0), expected)


def test_split_at_seams_keeps_an_old_lengthwise_seam():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    column = _column_edges(obj, 12, 4, 3)
    bm = _bm(obj)
    for e in bm.edges:
        e.seam = tuple(sorted(v.index for v in e.verts)) in column
    bmesh.update_edit_mesh(obj.data)
    assert _run(split_at_seams=True) == {"FINISHED"}
    assert _inner_seams(obj, range(48)) == column
    assert _islands(obj) == [list(range(48))]
    _edit(obj)
    assert _run(split_at_seams=False) == {"FINISHED"}
    assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, 6)      # the automatic seam (see core tests)


def _lying(mesh):
    """The fixture turned 90 degrees round X, (x, y, z) -> (x, -z, y): open_tube's axis runs along world Y and its
    ring vertex i sits at x = cos(a), z = sin(a), so column 9 is the bottom (z = -1)."""
    verts, faces = mesh
    return {v: (p[0], -p[2], p[1]) for v, p in verts.items()}, faces


def _world_z(obj, keys):
    bm = _bm(obj)
    return {round((obj.matrix_world @ bm.verts[v].co).z, 6) for key in keys for v in key}


def test_seam_side_bottom_puts_the_seam_lowest():
    obj = _object(_lying(open_tube(12, 4)))
    _edit(obj)
    assert _run(seam_side="BOTTOM") == {"FINISHED"}
    seam = _inner_seams(obj, range(48))
    assert seam == _column_edges(obj, 12, 4, 9) and _world_z(obj, seam) == {-1.0}, _world_z(obj, seam)
    _edit(obj)
    assert _run() == {"FINISHED"}
    assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, 6)      # Shortest: as before
    # the same tube lying by the object's rotation: world space is what counts
    bpy.ops.object.mode_set(mode="OBJECT")
    obj = _object(open_tube(12, 4), name="turned")
    obj.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    _edit(obj)
    assert _run(seam_side="BOTTOM") == {"FINISHED"}
    seam = _inner_seams(obj, range(48))
    assert seam == _column_edges(obj, 12, 4, 9) and _world_z(obj, seam) == {-1.0}, _world_z(obj, seam)
    _edit(obj)
    assert _run(seam_side="TOP") == {"FINISHED"}
    assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, 3)
    bpy.ops.object.mode_set(mode="OBJECT")


def test_t_cycles_the_seam_side():
    obj = _object(_lying(open_tube(12, 4)))
    _edit(obj)
    op = _modal_on()
    sides = ["SHORTEST", "BOTTOM", "TOP", "LEFT", "RIGHT", "FRONT", "BACK"]
    # along the tube's axis (Y) every column faces Front and Back alike: the shortest, column 6, as Left
    columns = {"SHORTEST": 6, "BOTTOM": 9, "TOP": 3, "LEFT": 6, "RIGHT": 0, "FRONT": 6, "BACK": 6}
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert op.seam_side == "SHORTEST" and params["Seam Side (T)"].value_text() == "Shortest"
    for side in sides[1:] + sides[:1]:
        before = op._result
        assert op._modal(bpy.context, _Event("T")) == {"RUNNING_MODAL"}
        assert op.seam_side == side and op._result is not before, side
        assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, columns[side]), side
    assert op._modal(bpy.context, _Event("T", shift=True)) == {"RUNNING_MODAL"}
    assert op.seam_side == "BACK" and params["Seam Side (T)"].value_text() == "Back (+Y)"
    op._modal(bpy.context, _Event("T", shift=True))
    assert op.seam_side == "FRONT"
    assert op._modal(bpy.context, _Event("ESC")) == {"CANCELLED"}
    assert op.seam_side == "SHORTEST"                                  # cancel restores it


def test_t_drops_the_picked_wall_seam_but_keeps_ring_breaks():
    obj = _object(_lying(open_tube(12, 4)))
    _edit(obj)
    op = _modal_on()
    op._part_under_cursor = lambda _context, _event: (obj, 0)
    assert op._modal(bpy.context, _Event("WHEELUPMOUSE", alt=True)) == {"RUNNING_MODAL"}
    assert len(json.loads(op.picks)[obj.name]["picked"]) == 1
    assert _inner_seams(obj, range(48)) != _column_edges(obj, 12, 4, 9)
    op._modal(bpy.context, _Event("T"))
    assert op.seam_side == "BOTTOM" and json.loads(op.picks)[obj.name]["picked"] == []
    assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, 9)
    op._finish(bpy.context)
    # a ring break on a cap ring survives T; the wall's picked seam does not
    obj = _object(capped_cylinder())
    _edit(obj)
    op = _modal_on()
    radial = _key(obj, 3, 163)                 # between two faces of the outer bottom ring
    assert _commit_by_clicks(op, obj, radial) == "BREAK"
    automatic = _inner_seams(obj, A_WALL)
    wall = next(i for i, p in enumerate(op._result.objects[obj.name].analysis.parts) if p.kind == "WALL")
    op._part_under_cursor = lambda _context, _event: (obj, wall)
    op._modal(bpy.context, _Event("WHEELUPMOUSE", alt=True))
    assert len(json.loads(op.picks)[obj.name]["picked"]) == 2 and _inner_seams(obj, A_WALL) != automatic
    op._modal(bpy.context, _Event("T"))
    picked = json.loads(op.picks)[obj.name]["picked"]
    assert picked == [_edge_indices(obj, {radial})], picked
    assert _inner_seams(obj, A_RINGS[0]) == {radial} and op._result.objects[obj.name].analysis.breaks
    assert _inner_seams(obj, A_WALL) == automatic          # an upright wall faces Bottom alike all round
    op._finish(bpy.context)


def _cube():
    """A 2 x 2 x 2 cube centred on the origin, six quads facing out."""
    verts = {i: (float(2 * (i & 1) - 1), float(2 * ((i >> 1) & 1) - 1), float(2 * (i >> 2) - 1)) for i in range(8)}
    faces = {0: (0, 2, 3, 1), 1: (4, 5, 7, 6), 2: (0, 1, 5, 4), 3: (2, 6, 7, 3), 4: (0, 4, 6, 2), 5: (1, 3, 7, 5)}
    return verts, faces


def _all_edge_keys(obj):
    return {tuple(sorted(v.index for v in e.verts)) for e in _bm(obj).edges}


def test_cube_comes_out_as_six_flat_faces():
    obj = _object(_cube())
    _edit(obj)
    stand = _OperatorStandIn()
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert any("0 wall(s), 0 ring(s), 6 disk(s)" in m for _k, m in stand.reports), stand.reports
    assert not any("could not be laid out" in m or "free part" in m for _k, m in stand.reports), stand.reports
    assert _islands(obj) == [[i] for i in range(6)]
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    for f in bm.faces:                                   # each an axis-aligned rectangle (a square here)
        pts = [_uv(lp, layer) for lp in f.loops]
        assert len({round(p[0], 6) for p in pts}) == 2 and len({round(p[1], 6) for p in pts}) == 2, pts
    densities = [_density(obj, [i]) for i in range(6)]
    assert max(densities) / min(densities) - 1.0 < 1e-3, densities
    for u, v in _uv_state(obj):
        assert -1e-6 <= u <= 1.0 + 1e-6 and -1e-6 <= v <= 1.0 + 1e-6, (u, v)
    boxes = [_bbox(obj, [i]) for i in range(6)]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = min(a[2], b[2]) - max(a[0], b[0]) > 1e-9 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-9
            assert not overlap, (a, b)
    assert _seams(obj) == _all_edge_keys(obj) and len(_seams(obj)) == 12
    assert not _flipped(obj, range(6))


def test_cube_with_sharp_edges_is_cut_only_there():
    obj = _object(_cube())
    bm = _edit(obj)
    bm.edges.ensure_lookup_table()
    ring = set()
    for e in bm.edges:                                   # the top and bottom outlines: z equal at both ends
        flat = abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-9
        e.smooth = not flat
        if flat:
            ring.add(tuple(sorted(v.index for v in e.verts)))
    bmesh.update_edit_mesh(obj.data)
    stand = _OperatorStandIn()
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert len(ring) == 8
    islands = _islands(obj)
    assert sorted(len(g) for g in islands) == [1, 1, 4], islands      # top, bottom, the four sides as one band
    assert _seams(obj) == ring
    assert any("4 faces are no tube" in m for _k, m in stand.reports), stand.reports
    assert not _flipped(obj, range(6))
    # no sharp edge: the 30-degree angle cuts all twelve
    bm = _bm(obj)
    for e in bm.edges:
        e.smooth = True
    bmesh.update_edit_mesh(obj.data)
    assert _run() == {"FINISHED"}
    assert len(_islands(obj)) == 6 and len(_seams(obj)) == 12


def test_split_at_bends_cuts_the_clean_bend():
    mesh = clean_bend(12, 4)
    obj = _object(mesh)
    _edit(obj)
    assert _run() == {"FINISHED"}
    assert len(_islands(obj)) == 1
    _edit(obj)
    assert _run(split_at_bends=True, bend_angle=math.radians(45.0)) == {"FINISHED"}
    islands = _islands(obj)
    assert len(islands) == 2, [len(g) for g in islands]
    assert not _flipped(obj, range(len(mesh[1])))


def test_picks_property_is_applied_by_execute():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    column = _column_edges(obj, 12, 4, 3)
    picks = json.dumps({obj.name: {"picked": [_edge_indices(obj, column)]}})
    assert _run(picks=picks) == {"FINISHED"}
    assert _inner_seams(obj, range(48)) == column
    _edit(obj)
    middle = {tuple(sorted((_vid(obj, 2 * 12 + i), _vid(obj, 2 * 12 + (i + 1) % 12)))) for i in range(12)}
    picks = json.dumps({obj.name: {"added": [_edge_indices(obj, middle)]}})
    assert _run(picks=picks) == {"FINISHED"}
    assert len(_islands(obj)) == 2
    assert middle <= _seams(obj)


def test_picks_are_taken_before_doubles_are_merged():
    verts, faces = open_tube(12, 4)
    extra = len(verts)
    verts = {**verts, extra: verts[0]}                 # a doubled vertex: a zero-length edge in the first face
    faces = dict(faces)
    faces[0] = (faces[0][0], extra, *faces[0][1:])
    obj = _object((verts, faces))
    _edit(obj)
    column = _column_edges(obj, 12, 4, 3)
    picks = json.dumps({obj.name: {"picked": [_edge_indices(obj, column)]}})
    stand = _OperatorStandIn(picks=picks)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert any("merged 1 doubled" in m for _k, m in stand.reports), stand.reports
    bm = _bm(obj)
    assert len(bm.verts) == 60
    seam = {tuple(sorted(v.co[:] for v in e.verts)) for e in bm.edges
            if e.seam and len(e.link_faces) == 2}
    expected = {tuple(sorted((tuple(verts[k * 12 + 3]), tuple(verts[(k + 1) * 12 + 3])))) for k in range(4)}
    rounded = {tuple(tuple(round(c, 5) for c in p) for p in key) for key in seam}
    assert rounded == {tuple(tuple(round(c, 5) for c in p) for p in key) for key in expected}, rounded


def test_free_part_reports_a_warning():
    mesh = box_tube()
    obj = _object(mesh)
    _edit(obj)
    stand = _OperatorStandIn(hard_angle=math.pi)        # no edge reaches 180 degrees: the box stays one free part
    assert stand.execute(bpy.context) == {"FINISHED"}
    warnings = [m for kinds, m in stand.reports if "WARNING" in kinds]
    assert any("free part" in m for m in warnings), stand.reports
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    for f in bm.faces:
        assert abs(_signed([_uv(lp, layer) for lp in f.loops])) > 1e-6, f.index


# --- the modal ------------------------------------------------------------------------------------------------------
# A real cursor cannot hover headless: the loops are classified from edge keys (``_classify``) or the hover lookup is
# stood in for; the event handling is the operator's own.

class _Event:
    """Stands in for a modal event."""

    def __init__(self, key, value="PRESS", ctrl=False, shift=False, alt=False):
        self.type, self.value = key, value
        self.ctrl, self.shift, self.alt, self.oskey = ctrl, shift, alt, False
        self.mouse_region_x = self.mouse_region_y = self.mouse_x = self.mouse_y = 0


def _modal_on(**props):
    op = _OperatorStandIn(**props)
    assert op._start(bpy.context), op.reports
    op._build_overlays(None)
    return op


def _key(obj, a, b):
    """The mesh edge key of the fixture vertex ids a, b."""
    return tuple(sorted((_vid(obj, a), _vid(obj, b))))


def _commit_by_clicks(op, obj, key):
    """Select the loop through ``key`` (as LMB does) and mark / unmark it with C through the modal."""
    loop, kind, _part = op._classify(obj, key)
    op._click_loop(bpy.context, obj, loop, kind)
    assert op._pending is not None and op._same(op._pending, (obj, loop))
    picks = op.picks
    assert op._modal(bpy.context, _Event("C")) == {"RUNNING_MODAL"}
    assert op.picks != picks, "C applied nothing"
    assert op._pending is not None and op._same(op._pending, (obj, loop))     # still selected
    return kind


def test_modal_opens_with_the_automatic_layout():
    obj = _object(capped_cylinder())
    _edit(obj)
    op = _modal_on()
    assert _islands(obj) == sorted(sorted(g) for g in A_GROUPS)
    assert op._result.kinds == {"WALL": 1, "RING": 3, "DISK": 2}
    assert op._header() == "1 wall(s), 3 ring(s), 2 disk(s)"
    assert op._result.cut_lines and not op._result.error_lines        # cuts and the wall seam to draw
    modal = _uv_state(obj)
    assert op._modal(bpy.context, _Event("SPACE")) == {"FINISHED"}
    assert _uv_state(obj) == modal
    _edit(obj)
    stand = _OperatorStandIn()
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == modal                                     # the same as execute


def test_click_selects_and_c_marks():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    automatic = _column_edges(obj, 12, 4, 6)
    assert _inner_seams(obj, range(48)) == automatic
    loop, kind, part = op._classify(obj, _key(obj, 3, 15))
    assert (kind, part) == ("LENGTH", 0) and len(loop.verts) == 5
    before = _uv_state(obj)
    # LMB through the modal (the hover stood in for): it selects, twice on the same loop it still only selects
    op._hover_loop = lambda _context, _event: (obj, loop, kind)
    for _ in range(2):
        assert op._modal(bpy.context, _Event("LEFTMOUSE")) == {"RUNNING_MODAL"}
        assert _uv_state(obj) == before and op.picks == "" and op._pending is not None
    assert op._loop_row() == "Selected: Set wall seam"
    assert "selected wall seam" in op._status_text() and "[C] mark / unmark" in op._status_text()
    # C marks it and keeps it selected; C again goes back to the automatic seam exactly
    assert op._modal(bpy.context, _Event("C")) == {"RUNNING_MODAL"}
    assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, 3) and _uv_state(obj) != before
    assert op._pending is not None and op._loop_row() == "Selected: Automatic wall seam"
    assert op._modal(bpy.context, _Event("C")) == {"RUNNING_MODAL"}
    assert _inner_seams(obj, range(48)) == automatic and _uv_state(obj) == before
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    # LMB on another loop moves the selection; C then marks that one
    loop9 = op._classify(obj, _key(obj, 9, 21))
    op._hover_loop = lambda _context, _event: (obj, loop9[0], loop9[1])
    op._modal(bpy.context, _Event("LEFTMOUSE"))
    assert op._same(op._pending, (obj, loop9[0]))
    op._modal(bpy.context, _Event("C"))
    assert _inner_seams(obj, range(48)) == _column_edges(obj, 12, 4, 9)
    # LMB with nothing under the cursor changes nothing
    op._hover_loop = lambda _context, _event: None
    op._modal(bpy.context, _Event("LEFTMOUSE"))
    assert op._same(op._pending, (obj, loop9[0]))
    op._finish(bpy.context)


def test_c_without_a_selection_takes_the_hovered_loop():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    assert "C" not in sys.modules[operator.__module__].PASS_KEYS
    assert op._modal(bpy.context, _Event("C")) == {"RUNNING_MODAL"}
    assert op.picks == "" and op._pending is None and op._loop_row() == "None"   # nothing to mark
    middle = op._classify(obj, _key(obj, 24, 25))
    op._hover_loop = lambda _context, _event: (obj, middle[0], middle[1])
    op._hover = (obj, middle[0], middle[1])
    assert op._loop_row() == "Add ring seam"                         # hovered, not selected
    assert op._modal(bpy.context, _Event("C")) == {"RUNNING_MODAL"}
    assert op._same(op._pending, (obj, middle[0])) and len(_islands(obj)) == 2
    assert op._loop_row() == "Selected: Remove seam"
    # Esc deselects first and the modal goes on; an option key also clears the selection
    assert op._modal(bpy.context, _Event("ESC")) == {"RUNNING_MODAL"} and op._pending is None
    op._modal(bpy.context, _Event("LEFTMOUSE"))
    assert op._pending is not None
    assert op._modal(bpy.context, _Event("E")) == {"RUNNING_MODAL"} and op._pending is None
    op._finish(bpy.context)


def test_c_toggles_every_kind_back_exactly():
    # RING on an open tube
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    start = (_islands(obj), _seams(obj), _uv_state(obj))
    assert _commit_by_clicks(op, obj, _key(obj, 24, 25)) == "RING" and len(_islands(obj)) == 2
    assert _commit_by_clicks(op, obj, _key(obj, 24, 25)) == "RING"
    assert (_islands(obj), _seams(obj), _uv_state(obj)) == start
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    op._finish(bpy.context)
    # CUT on the cube
    obj = _object(_cube())
    _edit(obj)
    op = _modal_on()
    start = (_islands(obj), _seams(obj), _uv_state(obj))
    key = sorted(_all_edge_keys(obj))[0]
    assert _commit_by_clicks(op, obj, key) == "CUT" and len(_islands(obj)) == 5
    assert _commit_by_clicks(op, obj, key) == "CUT"
    assert (_islands(obj), _seams(obj), _uv_state(obj)) == start
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    op._finish(bpy.context)
    # BREAK on a cap ring
    obj = _object(capped_cylinder())
    _edit(obj)
    op = _modal_on()
    start = (_islands(obj), _seams(obj), _uv_state(obj))
    radial = _key(obj, 3, 163)                 # between two faces of the outer bottom ring
    assert _commit_by_clicks(op, obj, radial) == "BREAK" and _inner_seams(obj, A_RINGS[0]) == {radial}
    assert op._loop_row() == "Selected: Remove ring break"
    assert _commit_by_clicks(op, obj, radial) == "BREAK"
    assert (_islands(obj), _seams(obj), _uv_state(obj)) == start
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    op._finish(bpy.context)


def test_escape_drops_the_pending_loop_first():
    obj = _object(open_tube(12, 4), uv_size=4.0)
    _edit(obj)
    original = _uv_state(obj)
    op = _modal_on()
    laid = _uv_state(obj)
    loop, kind, _part = op._classify(obj, _key(obj, 3, 15))
    op._click_loop(bpy.context, obj, loop, kind)
    assert op._modal(bpy.context, _Event("ESC")) == {"RUNNING_MODAL"}
    assert op._pending is None and _uv_state(obj) == laid
    assert op._modal(bpy.context, _Event("RIGHTMOUSE")) == {"CANCELLED"}
    assert _uv_state(obj) == original


def test_ring_click_adds_then_removes_a_ring_seam():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    middle = _key(obj, 24, 25)
    loop, kind, _part = op._classify(obj, middle)
    assert op._loop_text((obj, loop, kind)) == "Add ring seam"
    assert not op._result.user_lines
    op._click_loop(bpy.context, obj, loop, kind)                      # a click only selects it
    assert op._loop_row() == "Selected: Add ring seam"
    op._pending = None
    assert _commit_by_clicks(op, obj, middle) == "RING"
    assert len(_islands(obj)) == 2 and op._result.kinds == {"WALL": 2}
    assert json.loads(op.picks)[obj.name]["added"]
    # the committed ring is drawn as the user's own (12 edges), and a click on it now says it removes the seam
    assert len(op._result.user_lines) == 24
    assert json.loads(op.picks)[obj.name] == {"added": [_edge_indices(obj, set(loop.edges()))],
                                              "removed": [], "picked": []}
    loop, kind, _part = op._classify(obj, middle)
    assert op._loop_text((obj, loop, kind)) == "Remove seam" and op._loop_row() == "Selected: Remove seam"
    assert _commit_by_clicks(op, obj, middle) == "RING"
    assert len(_islands(obj)) == 1
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    op._finish(bpy.context)


def test_removing_a_rim_does_not_come_back_on_relayout():
    obj = _object(capped_cylinder())
    _edit(obj)
    op = _modal_on()
    rim = _key(obj, 0, 1)
    assert rim in _seams(obj)
    assert _commit_by_clicks(op, obj, rim) == "RING"
    assert json.loads(op.picks)[obj.name]["removed"]
    cache = op._result.objects[obj.name]
    assert rim not in cache.analysis.cuts and rim not in _seams(obj)
    for _ in range(2):
        assert op._modal(bpy.context, _Event("E")) == {"RUNNING_MODAL"}
        assert rim not in op._result.objects[obj.name].analysis.cuts and rim not in _seams(obj)
    op._finish(bpy.context)


def test_alt_wheel_steps_the_seam():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    op._part_under_cursor = lambda _context, _event: (obj, 0)
    first = _inner_seams(obj, range(48))
    up = _Event("WHEELUPMOUSE", alt=True)
    assert op._modal(bpy.context, up) == {"RUNNING_MODAL"}
    second = _inner_seams(obj, range(48))
    assert second != first and len(second) == 4
    assert abs(op.loop_angle - math.radians(120.0)) < 1e-6          # Alt + Wheel is not the loop angle
    for _ in range(11):
        op._modal(bpy.context, up)
    assert _inner_seams(obj, range(48)) == first
    assert len(json.loads(op.picks)[obj.name]["picked"]) == 1
    assert op._modal(bpy.context, _Event("WHEELDOWNMOUSE", alt=True)) == {"RUNNING_MODAL"}
    op._part_under_cursor = lambda _context, _event: None             # no wall under the cursor: navigation
    assert op._modal(bpy.context, up) == {"PASS_THROUGH"}
    op._finish(bpy.context)


def test_wheel_changes_loop_angle_and_relays_out():
    obj = _object(box_tube())
    _edit(obj)
    op = _modal_on(hard_angle=math.pi)
    assert op._result.kinds == {"FREE": 1}
    assert op._modal(bpy.context, _Event("WHEELDOWNMOUSE")) == {"PASS_THROUGH"}   # a plain wheel zooms the viewport
    assert op._modal(bpy.context, _Event("WHEELUPMOUSE", ctrl=True, alt=True)) == {"RUNNING_MODAL"}
    assert abs(op.hard_angle - math.pi) < 1e-6                         # clamped at 180
    before = op._result
    assert op._modal(bpy.context, _Event("WHEELDOWNMOUSE", ctrl=True, alt=True)) == {"RUNNING_MODAL"}
    assert abs(op.hard_angle - math.radians(175.0)) < 1e-6 and op._result is not before
    assert op._result.kinds == {"FREE": 1}
    for _ in range(17):
        op._modal(bpy.context, _Event("WHEELDOWNMOUSE", ctrl=True, alt=True))
    assert abs(op.hard_angle - math.radians(90.0)) < 1e-6
    assert op._result.kinds == {"DISK": 6}, op._result.kinds          # the box's 90-degree edges cut now
    for _ in range(18):
        op._modal(bpy.context, _Event("WHEELUPMOUSE", ctrl=True, alt=True))
    assert abs(op.loop_angle - math.radians(120.0)) < 1e-6
    for _ in range(8):
        assert op._modal(bpy.context, _Event("WHEELDOWNMOUSE", ctrl=True)) == {"RUNNING_MODAL"}
    assert abs(op.loop_angle - math.radians(80.0)) < 1e-6
    assert sum(op._result.kinds.values()) > 1, op._result.kinds        # the rims close at 80 degrees
    op._modal(bpy.context, _Event("WHEELUPMOUSE", ctrl=True))
    assert abs(op.loop_angle - math.radians(85.0)) < 1e-6
    op._modal(bpy.context, _Event("WHEELUPMOUSE", shift=True))
    assert abs(op.sharp_angle - math.radians(65.0)) < 1e-6
    op._modal(bpy.context, _Event("WHEELDOWNMOUSE", shift=True, ctrl=True))
    assert abs(op.sharp_angle - math.radians(64.0)) < 1e-6
    bend = _Event("WHEELUPMOUSE", shift=True, alt=True)
    assert op._modal(bpy.context, bend) == {"PASS_THROUGH"}           # Split at Bends off
    assert abs(op.bend_angle - math.radians(45.0)) < 1e-6
    op._modal(bpy.context, _Event("A"))
    assert op._modal(bpy.context, bend) == {"RUNNING_MODAL"}
    assert abs(op.bend_angle - math.radians(50.0)) < 1e-6
    for _ in range(40):
        op._modal(bpy.context, _Event("WHEELUPMOUSE", ctrl=True))
    assert abs(op.loop_angle - math.pi) < 1e-6                        # clamped
    for key in ("MIDDLEMOUSE", "TRACKPADPAN", "NDOF_MOTION", "N"):
        assert op._modal(bpy.context, _Event(key)) == {"PASS_THROUGH"}, key
    assert op._modal(bpy.context, _Event("T")) == {"RUNNING_MODAL"}     # T is Seam Side now
    op._finish(bpy.context)


def _corner_uvs(obj, key):
    """For the edge ``key``: per end vertex, the UVs its two faces give it."""
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    edge = next(e for e in bm.edges if tuple(sorted(v.index for v in e.verts)) == key)
    return {v.index: [next(_uv(lp, layer) for lp in f.loops if lp.vert is v) for f in edge.link_faces]
            for v in edge.verts}


def _opened(obj, key):
    """Whether both faces of the edge ``key`` give one of its ends different UVs: the UVs open along it."""
    return any(math.dist(a, b) > 1e-6 for a, b in _corner_uvs(obj, key).values())


def test_a_short_loop_is_an_open_seam_that_toggles():
    # no lengthwise loop at 179 degrees on the twisted tube, and nothing reaches the 180-degree hard edge angle:
    # one free part; a loop that stops short is an open seam, committed and taken back like a ring seam
    obj = _object(open_tube(12, 4, twist=math.radians(5.0)))
    _edit(obj)
    op = _modal_on(loop_angle=math.radians(179.0), hard_angle=math.pi)
    assert op._result.kinds == {"FREE": 1}
    key = _key(obj, 3, 15)
    loop, kind, _part = op._classify(obj, key)
    assert kind == "CUT" and loop.edges() == [key], loop.verts
    assert op._loop_text((obj, loop, kind)) == "Add seam"
    assert op._click_loop(bpy.context, obj, loop, kind) is True
    assert "selected open seam" in op._status_text() and op.picks == ""
    assert op._click_loop(bpy.context, obj, loop, kind) is False                 # selected already: nothing
    assert op._modal(bpy.context, _Event("C")) == {"RUNNING_MODAL"}
    assert json.loads(op.picks)[obj.name]["added"] == [_edge_indices(obj, {key})]
    assert key in _seams(obj) and key in op._result.objects[obj.name].analysis.cuts
    assert op._result.objects[obj.name].analysis.slits == {0: {key}}
    assert not any("free part" in w for w in op._result.warnings), op._result.warnings   # the user asked for it
    loop, kind, _part = op._classify(obj, key)
    assert kind == "CUT" and op._loop_text((obj, loop, kind)) == "Remove seam"
    assert _commit_by_clicks(op, obj, key) == "CUT"
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    assert key not in _seams(obj)
    op._finish(bpy.context)


def test_every_hovered_edge_of_a_cube_can_be_cut():
    obj = _object(_cube())
    _edit(obj)
    op = _modal_on()
    cache = op._result.objects[obj.name]
    assert cache.analysis.cuts == _all_edge_keys(obj)
    assert len(op._result.cut_lines) == 24                     # the 12 hard edges are drawn like every cut
    drawn = {tuple(sorted((tuple(round(c, 6) for c in a), tuple(round(c, 6) for c in b))))
             for a, b in zip(op._result.cut_lines[::2], op._result.cut_lines[1::2])}
    bm = _bm(obj)
    expected = {tuple(sorted(tuple(round(c, 6) for c in obj.matrix_world @ v.co) for v in e.verts)) for e in bm.edges}
    assert drawn == expected
    for key in sorted(_all_edge_keys(obj)):
        loop, kind, _part = op._classify(obj, key)
        assert kind == "CUT" and loop.edges() == [key], (key, kind, loop.verts)
        assert op._loop_text((obj, loop, kind)) == "Remove seam"
    key = sorted(_all_edge_keys(obj))[0]
    assert _commit_by_clicks(op, obj, key) == "CUT"
    assert json.loads(op.picks)[obj.name]["removed"] == [_edge_indices(obj, {key})]
    assert key not in _seams(obj) and len(_islands(obj)) == 5
    assert _commit_by_clicks(op, obj, key) == "CUT"           # restored
    assert key in _seams(obj) and len(_islands(obj)) == 6
    op._finish(bpy.context)


def test_a_slit_in_a_flat_frame_is_a_seam_and_toggles():
    obj = _object(framed_box())
    _edit(obj)
    op = _modal_on()
    assert op._result.kinds == {"DISK": 6}, op._result.kinds
    key = _key(obj, 1, 5)                      # between two frame quads, from the rim to the hole
    assert key not in _seams(obj) and not _opened(obj, key)
    loop, kind, _part = op._classify(obj, key)
    assert kind == "CUT" and loop.edges() == [key], loop.verts
    assert op._loop_text((obj, loop, kind)) == "Add seam"
    assert _commit_by_clicks(op, obj, key) == "CUT"
    assert json.loads(op.picks)[obj.name]["added"] == [_edge_indices(obj, {key})]
    assert key in _seams(obj) and op._result.objects[obj.name].analysis.slits
    # the frame is now unwrapped by Blender with the slit as a seam; a flat piece unwraps to its own plane, so the
    # slit's two sides land on the same UVs (a slit opens only where the surface is curved: see the tube below)
    assert op._result.kinds == {"DISK": 5, "FREE": 1}
    assert not _flipped(obj, range(len(framed_box()[1])))
    assert _commit_by_clicks(op, obj, key) == "CUT"
    assert json.loads(op.picks)[obj.name] == {"added": [], "removed": [], "picked": []}
    assert key not in _seams(obj) and not _opened(obj, key) and op._result.kinds == {"DISK": 6}
    op._finish(bpy.context)


def test_a_slit_opens_a_curved_part():
    # a full column added as a cut (not picked as the wall seam): the tube is one free part unwrapped with the column
    # as its only seam, so both sides of every column edge get different UVs
    obj = _object(open_tube(12, 4))
    _edit(obj)
    column = _column_edges(obj, 12, 4, 3)
    stand = _OperatorStandIn(picks=json.dumps({obj.name: {"added": [_edge_indices(obj, column)]}}))
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert any("0 wall(s), 0 ring(s), 0 disk(s), 1 free part(s)" in m for _k, m in stand.reports), stand.reports
    assert not any("faces are no tube" in m for _k, m in stand.reports), stand.reports
    assert _inner_seams(obj, range(48)) == column
    for key in column:
        assert _opened(obj, key), (key, _corner_uvs(obj, key))
    assert len(_islands(obj)) == 1
    assert not _flipped(obj, range(48))


def test_break_click_on_a_ring_strip_sets_its_break():
    obj = _object(capped_cylinder())
    _edit(obj)
    op = _modal_on()
    radial = _key(obj, 3, 163)                 # between two faces of the outer bottom ring
    assert _commit_by_clicks(op, obj, radial) == "BREAK"
    assert len(json.loads(op.picks)[obj.name]["picked"]) == 1
    assert _inner_seams(obj, A_RINGS[0]) == {radial}
    assert op._result.objects[obj.name].analysis.breaks
    assert len(_islands(obj)) == 6
    op._finish(bpy.context)


def test_loop_source_uv_is_unavailable_without_a_uv_layer():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    assert bmesh.from_edit_mesh(obj.data).loops.layers.uv.active is not None
    assert op._modal(bpy.context, _Event("G")) == {"RUNNING_MODAL"}
    assert op.loop_source == "GEOMETRY"
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert not params["Loop Source (G)"].is_visible()
    assert op._modal(bpy.context, _Event("ESC")) == {"CANCELLED"}
    assert bmesh.from_edit_mesh(obj.data).loops.layers.uv.active is None
    obj = _object(open_tube(12, 4), uv_size=4.0)
    _edit(obj)
    op = _modal_on()
    op._modal(bpy.context, _Event("G"))
    assert op.loop_source == "UV" and op._result.objects[obj.name].uv
    op._finish(bpy.context)


def test_cancel_restores_uvs_and_seams_exactly():
    obj = _object(capped_cylinder(), uv_size=10.0)
    _edit(obj)
    bm = _bm(obj)
    for e in bm.edges:
        e.seam = e.index % 5 == 0
    bmesh.update_edit_mesh(obj.data)
    uvs, seams = _uv_state(obj), _seams(obj)
    exact = [tuple(lp[bm.loops.layers.uv.active].uv) for f in bm.faces for lp in f.loops]
    op = _modal_on()
    defaults = {name: getattr(op, name) for name in ("layout", "orientation", "loop_angle", "pack", "picks",
                                                     "hard_angle")}
    for event in (_Event("W"), _Event("E"), _Event("P"), _Event("WHEELDOWNMOUSE", ctrl=True),
                  _Event("WHEELUPMOUSE", ctrl=True, alt=True)):
        op._modal(bpy.context, event)
    _commit_by_clicks(op, obj, _key(obj, 0, 1))
    assert op.picks and _uv_state(obj) != uvs
    assert op._modal(bpy.context, _Event("ESC")) == {"RUNNING_MODAL"}       # deselects
    assert op._modal(bpy.context, _Event("ESC")) == {"CANCELLED"}
    bm = _bm(obj)
    assert [tuple(lp[bm.loops.layers.uv.active].uv) for f in bm.faces for lp in f.loops] == exact
    assert _seams(obj) == seams
    assert {name: getattr(op, name) for name in defaults} == defaults


def test_relayout_starts_from_the_snapshot():
    obj = _object(capped_cylinder(), uv_size=10.0)
    _edit(obj)
    op = _modal_on(layout="TRUE")              # Blender's unwrap and the packer on every pass
    first = _uv_state(obj)
    for _ in range(2):
        op._modal(bpy.context, _Event("X"))
    assert _uv_state(obj) == first             # two passes later: the same, nothing accumulated
    op._finish(bpy.context)
    # the seams a pass marks are no input of the next: with Split at Seams on, a ring seam added and removed again
    # leaves no cut behind
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on(split_at_seams=True)
    middle = _key(obj, 24, 25)
    _commit_by_clicks(op, obj, middle)
    assert len(_islands(obj)) == 2 and middle in _seams(obj)
    _commit_by_clicks(op, obj, middle)
    assert len(_islands(obj)) == 1 and middle not in _seams(obj)
    op._finish(bpy.context)


def test_redo_reproduces_the_modal_result():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    name = obj.name
    op = _modal_on(orientation="VERTICAL")
    _commit_by_clicks(op, obj, _key(obj, 3, 15))
    _commit_by_clicks(op, obj, _key(obj, 24, 25))
    assert op._modal(bpy.context, _Event("RET")) == {"FINISHED"}
    picks, made, seams = op.picks, _uv_state(obj), _seams(obj)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.name = name + "_done"
    fresh = _object(open_tube(12, 4))
    fresh.name = name
    _edit(fresh)
    stand = _OperatorStandIn(orientation="VERTICAL", picks=picks)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_state(fresh) == made and _seams(fresh) == seams


def test_modal_hud_and_help_list_every_key():
    op = _OperatorStandIn()
    op._build_overlays(None)
    params = [p for section in op._hud.param_sections for p in section.params]
    assert [p.name for p in params] == [
        "Mode (Q)", "Fit to Active (D)", "Orientation (W)", "Layout (E)", "Loop (LMB, C)", "Seam Side (T)",
        "Loop Source (G)", "Loop Angle", "Sharp Angle", "Hard Edge Angle", "Split at Bends (A)", "Bend Angle",
        "Split at Seams (S)", "Mark Seams (X)", "Pack (P)", "Random Offset (Z)", "Offset Limit", "Offset Seed (R)",
        "Merge Doubles (F)"]

    def visible():
        return [(p.name, p.value_text()) for p in params if p.is_visible()]

    assert visible() == [
        ("Mode (Q)", "Fit 0–1"), ("Orientation (W)", "Horizontal"), ("Layout (E)", "Rectangle"),
        ("Loop (LMB, C)", "None"), ("Seam Side (T)", "Shortest"), ("Loop Angle", "120°"), ("Sharp Angle", "60°"),
        ("Hard Edge Angle", "30°"), ("Split at Bends (A)", "✗"), ("Split at Seams (S)", "✗"),
        ("Mark Seams (X)", "✓"), ("Pack (P)", "✓"), ("Merge Doubles (F)", "✓")]
    op.mode, op.split_at_bends = "ACTIVE", True          # Active shows Fit to Active and hides Pack; bends show
    names = [name for name, _value in visible()]
    assert "Fit to Active (D)" in names and "Pack (P)" not in names and "Bend Angle" in names
    assert "Random Offset (Z)" in names and "Offset Limit" not in names        # no axis: no limit, no seed
    op.offset_axis = "ALONG"
    assert {"Offset Limit", "Offset Seed (R)"} <= {name for name, _value in visible()}
    op.mode, op.split_at_bends, op.offset_axis = "FIT", False, "NONE"
    labels = [it.label for it in op._help.sections[0].items]
    assert "Select the loop under the cursor" in labels and "Mark / unmark the selected loop as a seam" in labels
    keys = [it.key for it in op._help.sections[0].items]
    for key in ("LMB", "C", "Alt + Wheel", "Ctrl + Wheel", "Shift + Wheel / Ctrl + Shift + Wheel",
                "Shift + Alt + Wheel / Ctrl + Shift + Alt + Wheel", "Ctrl + Alt + Wheel", "G", "A", "S", "Z", "R", "F", "P", "Q", "D", "W",
                "E", "X", "T / Shift + T", "Enter / Space", "Esc / RMB", "H"):
        assert key in keys, key
    assert len(keys) == 23
    text = op._status_text()
    assert "[Enter/Space] finish" in text and "[Esc/RMB] cancel" in text and "(Ctrl+Wheel)" in text
    assert "[LMB] select a loop | [C] mark / unmark it as a seam" in text


def test_modal_keys_toggle_their_options():
    obj = _object(open_tube(12, 4))
    _edit(obj)
    op = _modal_on()
    steps = [("Q", "mode", "IN_PLACE"), ("Q", "mode", "ACTIVE"), ("Q", "mode", "FIT"), ("W", "orientation", "VERTICAL"),
             ("D", "active_fit", "HEIGHT"), ("E", "layout", "QUADS"), ("E", "layout", "TRUE"),
             ("E", "layout", "RECTANGLE"), ("A", "split_at_bends", True), ("S", "split_at_seams", True),
             ("X", "mark_seams", False), ("P", "pack", False), ("Z", "offset_axis", "ALONG"), ("R", "offset_seed", 1),
             ("F", "merge_doubles", False)]
    for key, name, value in steps:
        assert op._modal(bpy.context, _Event(key)) == {"RUNNING_MODAL"}
        assert getattr(op, name) == value, (key, name, getattr(op, name))
    before = _uv_state(obj)
    assert op._modal(bpy.context, _Event("M")) == {"RUNNING_MODAL"}     # an unbound letter changes nothing
    assert _uv_state(obj) == before
    op._finish(bpy.context)


TESTS = [
    test_operator_is_registered,
    test_reference_a_gives_six_islands,
    test_reference_a_packs_inside_zero_one,
    test_pack_off_stacks_like_uv_stripe,
    test_reference_b_wall_is_one_island,
    test_quads_layout_on_a_clean_tube,
    test_no_stretch_layout_keeps_the_seam_sides_straight,
    test_seams_follow_the_parts,
    test_mark_seams_off_leaves_seams_alone,
    test_selected_faces_only,
    test_blender_calls_restore_selection_pins_and_sync,
    test_free_part_keeps_other_faces_and_selection,
    test_no_selection_takes_every_visible_face,
    test_object_scale_is_respected,
    test_split_at_seams_keeps_an_old_lengthwise_seam,
    test_seam_side_bottom_puts_the_seam_lowest,
    test_split_at_bends_cuts_the_clean_bend,
    test_picks_property_is_applied_by_execute,
    test_picks_are_taken_before_doubles_are_merged,
    test_free_part_reports_a_warning,
    test_cube_comes_out_as_six_flat_faces,
    test_cube_with_sharp_edges_is_cut_only_there,
    test_modal_opens_with_the_automatic_layout,
    test_click_selects_and_c_marks,
    test_c_without_a_selection_takes_the_hovered_loop,
    test_c_toggles_every_kind_back_exactly,
    test_escape_drops_the_pending_loop_first,
    test_ring_click_adds_then_removes_a_ring_seam,
    test_removing_a_rim_does_not_come_back_on_relayout,
    test_alt_wheel_steps_the_seam,
    test_wheel_changes_loop_angle_and_relays_out,
    test_a_short_loop_is_an_open_seam_that_toggles,
    test_every_hovered_edge_of_a_cube_can_be_cut,
    test_a_slit_in_a_flat_frame_is_a_seam_and_toggles,
    test_a_slit_opens_a_curved_part,
    test_break_click_on_a_ring_strip_sets_its_break,
    test_loop_source_uv_is_unavailable_without_a_uv_layer,
    test_cancel_restores_uvs_and_seams_exactly,
    test_relayout_starts_from_the_snapshot,
    test_redo_reproduces_the_modal_result,
    test_modal_hud_and_help_list_every_key,
    test_modal_keys_toggle_their_options,
    test_t_cycles_the_seam_side,
    test_t_drops_the_picked_wall_seam_but_keeps_ring_breaks,
]


def main():
    enable_addon()
    failed = 0
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception:
            failed += 1
            print("FAIL", test.__name__)
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
