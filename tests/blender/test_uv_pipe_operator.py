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
from uv_pipe_fixtures import bent_pipe, box_tube, capped_cylinder, clean_bend, open_tube  # noqa: E402

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
                "pack": True, "offset_axis": "NONE", "offset_seed": 0, "merge_doubles": True, "picks": ""}
    for name, value in expected.items():
        assert props[name].default == value, (name, props[name].default)
    for name, deg in (("loop_angle", 120.0), ("sharp_angle", 60.0), ("bend_angle", 45.0)):
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
    assert _run() == {"FINISHED"}
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
    stand = _OperatorStandIn()
    assert stand.execute(bpy.context) == {"FINISHED"}
    warnings = [m for kinds, m in stand.reports if "WARNING" in kinds]
    assert any("free part" in m for m in warnings), stand.reports
    bm = _bm(obj)
    layer = bm.loops.layers.uv.active
    for f in bm.faces:
        assert abs(_signed([_uv(lp, layer) for lp in f.loops])) > 1e-6, f.index


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
    test_split_at_bends_cuts_the_clean_bend,
    test_picks_property_is_applied_by_execute,
    test_picks_are_taken_before_doubles_are_merged,
    test_free_part_reports_a_warning,
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
