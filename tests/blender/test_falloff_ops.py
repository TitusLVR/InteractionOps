"""Falloff transform operators (Move / Rotate / Scale / Normal Offset) on the scene field stack.

Drives the operators through ``EXEC_DEFAULT`` (the redo / scripting path). The modal path needs a
window and is checked live.

Run with an isolated user resource folder (the script refuses the real one, see ``_isolation.py``):
``BLENDER_USER_RESOURCES="$TEMP/iops_blender_res" blender --background --factory-startup --python-exit-code 1
--python <this>``.
"""

import math
import os
import sys
import traceback

import bmesh
import bpy
import numpy as np

# refuse to run against the real user resources (enable / disable write there)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolation import require_isolated_user_resources  # noqa: E402

require_isolated_user_resources()

ADDON = "InteractionOps"
TOL = 1e-5


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


# --- fixture (as test_falloff_fields.py) --------------------------------------------------------------------------

def _grid_object(name):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1.0)
    assert len(bm.verts) == 121, len(bm.verts)
    co = np.array([v.co[:] for v in bm.verts])
    span = co.max(axis=0) - co.min(axis=0)
    if abs(span[0] - 2.0) > 1e-5:          # rescale to exactly [-1, 1]
        k = 2.0 / span[0]
        for v in bm.verts:
            v.co.x *= k
            v.co.y *= k
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _clear_objects():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def setup_scene():
    _clear_objects()
    a = _grid_object("A")
    b = _grid_object("B")
    b.location = (3, 0, 0)
    b.rotation_euler = (0, 0, math.radians(45))
    b.scale = (2, 1, 1)
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.mode_set(mode="EDIT")
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()
    s.active_index = 0
    s.use_custom_pivot = False
    s.basis = "LOCAL"
    s.fit_signature = ""
    s.fit_mode = "PCA"
    return a, b


def bm_of(obj):
    return bmesh.from_edit_mesh(obj.data)


def select_where(obj, pred):
    bm = bm_of(obj)
    for v in bm.verts:
        v.select = bool(pred(v.co))
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def local_co(obj):
    return np.array([v.co[:] for v in bm_of(obj).verts], dtype=np.float64)


def co_bytes(obj):
    return np.array([v.co[:] for v in bm_of(obj).verts], dtype=np.float32).tobytes()


def world_co(obj):
    mw = np.array(obj.matrix_world)
    return local_co(obj) @ mw[:3, :3].T + mw[:3, 3]


def restore(obj, co):
    bm = bm_of(obj)
    for v, c in zip(bm.verts, co):
        v.co = tuple(float(x) for x in c)
    bmesh.update_edit_mesh(obj.data)


def set_linear(start=(-1.0, 0.0, 0.0), end=(1.0, 0.0, 0.0)):
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()
    f = s.fields.add()
    f.name = "Falloff 1"
    f.type = "LINEAR"
    f.start = start
    f.end = end
    f.curve = "LINEAR"
    s.active_index = 0
    return f


def field_dict(**over):
    d = dict(name="Falloff 1", type="LINEAR", start=(-1.0, 0.0, 0.0), end=(1.0, 0.0, 0.0),
             radii=(1.0, 1.0), roll=0.0, curve="LINEAR", invert=False, strength=1.0,
             blend="REPLACE", enabled=True)
    d.update(over)
    return d


def ramp(x):
    return np.clip((x + 1.0) / 2.0, 0.0, 1.0)


# --- tests --------------------------------------------------------------------------------------------------------

def test_idnames_resolve():
    for name in ("mesh_falloff_move", "mesh_falloff_rotate", "mesh_falloff_scale",
                 "mesh_falloff_normal_offset"):
        getattr(bpy.ops.iops, name).get_rna_type()


def test_move_ramp():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    w0 = world_co(a)
    r = bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1))
    assert r == {"FINISHED"}, r
    w = world_co(a)
    assert np.allclose(w[:, 2], ramp(w0[:, 0]), atol=TOL), np.abs(w[:, 2] - ramp(w0[:, 0])).max()
    assert np.allclose(w[:, :2], w0[:, :2], atol=TOL)


def test_no_compounding_and_redo_equivalence():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    snap = local_co(a)
    w0 = world_co(a)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    restore(a, snap)
    call = dict(value=(0, 0, 1), stack=[field_dict(curve="SHARP")])
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", **call) == {"FINISHED"}
    w = world_co(a)
    assert np.allclose(w[:, 2], ramp(w0[:, 0]) ** 2, atol=TOL), np.abs(w[:, 2] - ramp(w0[:, 0]) ** 2).max()
    first = co_bytes(a)
    # copy-back of the redo-panel settings onto the scene field
    assert bpy.context.scene.IOPS.falloff.fields[0].curve == "SHARP"
    restore(a, snap)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", **call) == {"FINISHED"}
    assert co_bytes(a) == first, "identical call from the same snapshot differs"


def test_rotate():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    before = local_co(a)
    raw = [np.array(v.co[:], dtype=np.float32).tobytes() for v in bm_of(a).verts]
    r = bpy.ops.iops.mesh_falloff_rotate("EXEC_DEFAULT", angle=math.pi / 2, axis=(0, 0, 1),
                                         pivot=(0, 0, 0))
    assert r == {"FINISHED"}, r
    after = world_co(a)
    verts = list(bm_of(a).verts)
    i_pos = int(np.argmin(np.linalg.norm(before - (1, 0, 0), axis=1)))
    i_neg = int(np.argmin(np.linalg.norm(before - (-1, 0, 0), axis=1)))
    assert np.allclose(after[i_pos], (0, 1, 0), atol=TOL), after[i_pos]
    assert np.array(verts[i_neg].co[:], dtype=np.float32).tobytes() == raw[i_neg], "w=0 vert moved"
    mid = np.nonzero(np.abs(before[:, 0]) < 1e-6)[0]
    assert len(mid) == 11, len(mid)
    c = math.cos(math.pi / 4)
    for i in mid:
        y = before[i, 1]
        assert np.allclose(after[i], (-y * c, y * c, 0.0), atol=TOL), (before[i], after[i])


def test_scale():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    before = world_co(a)
    r = bpy.ops.iops.mesh_falloff_scale("EXEC_DEFAULT", factor=(1, 2, 1),
                                        orient=(1, 0, 0, 0, 1, 0, 0, 0, 1), pivot=(0, 0, 0))
    assert r == {"FINISHED"}, r
    after = world_co(a)
    for x, k in ((1.0, 2.0), (-1.0, 1.0), (0.0, 1.5)):
        rows = np.nonzero(np.abs(before[:, 0] - x) < 1e-6)[0]
        assert len(rows) == 11, (x, len(rows))
        assert np.allclose(after[rows, 1], before[rows, 1] * k, atol=TOL), (x, after[rows, 1])
        assert np.allclose(after[rows, 0], before[rows, 0], atol=TOL)


def test_scale_execute_defaults_to_basis_axes():
    """No `orient` given: the Scale acts along the Basis axes (cursor turned 90 deg about Z: basis Y is
    world -X), as the docs say, not along the world axes."""
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    cur = bpy.context.scene.cursor
    cur.location = (0.0, 0.0, 0.0)
    cur.rotation_mode = "XYZ"
    cur.rotation_euler = (0.0, 0.0, math.radians(90))
    bpy.context.scene.IOPS.falloff.basis = "CURSOR"
    try:
        before = world_co(a)
        r = bpy.ops.iops.mesh_falloff_scale("EXEC_DEFAULT", factor=(1, 2, 1), pivot=(0, 0, 0))
        assert r == {"FINISHED"}, r
        after = world_co(a)
    finally:
        cur.rotation_euler = (0.0, 0.0, 0.0)
        bpy.context.scene.IOPS.falloff.basis = "LOCAL"
    k = 1.0 + ramp(before[:, 0])
    assert np.allclose(after[:, 0], before[:, 0] * k, atol=TOL), np.abs(after[:, 0] - before[:, 0] * k).max()
    assert np.allclose(after[:, 1], before[:, 1], atol=TOL)


def test_normal_offset():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    before = world_co(a)
    r = bpy.ops.iops.mesh_falloff_normal_offset("EXEC_DEFAULT", distance=0.5)
    assert r == {"FINISHED"}, r
    after = world_co(a)
    assert np.allclose(after[:, 2], 0.5 * ramp(before[:, 0]), atol=TOL), after[:, 2]
    assert np.allclose(after[:, :2], before[:, :2], atol=TOL)


def test_normal_offset_uses_current_normals():
    """Verts moved by a script without normal_update: the offset follows the
    geometry's real normal (world -Y or +Y for an XZ plane), not the stale +Z."""
    a, b = setup_scene()
    select_where(a, lambda co: True)
    bm = bm_of(a)
    for v in bm.verts:
        v.co = (v.co.x, 0.0, v.co.y)          # XY plane -> XZ plane, normals now stale
    bmesh.update_edit_mesh(a.data)
    set_linear()
    before = world_co(a)
    assert bpy.ops.iops.mesh_falloff_normal_offset("EXEC_DEFAULT", distance=0.5) == {"FINISHED"}
    d = world_co(a) - before
    assert np.allclose(d[:, 2], 0.0, atol=TOL), np.abs(d[:, 2]).max()
    assert np.allclose(np.abs(d[:, 1]), 0.5 * ramp(before[:, 0]), atol=TOL), d[:, 1]


def test_multi_object():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    select_where(b, lambda co: True)
    set_linear(end=(5.0, 0.0, 0.0))
    wa0, wb0 = world_co(a), world_co(b)
    raw = {o.name: [np.array(v.co[:], dtype=np.float32).tobytes() for v in bm_of(o).verts]
           for o in (a, b)}
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    for obj, w0 in ((a, wa0), (b, wb0)):
        w = world_co(obj)
        expect = np.clip((w0[:, 0] + 1.0) / 6.0, 0.0, 1.0)
        assert np.allclose(w[:, 2], expect, atol=TOL), (obj.name, np.abs(w[:, 2] - expect).max())
        assert np.allclose(w[:, :2], w0[:, :2], atol=TOL), obj.name
        zero = np.nonzero(expect == 0.0)[0]
        verts = list(bm_of(obj).verts)
        for i in zero:
            assert np.array(verts[i].co[:], dtype=np.float32).tobytes() == raw[obj.name][i], \
                (obj.name, i)
    assert len(np.nonzero(np.clip((wa0[:, 0] + 1.0) / 6.0, 0, 1) == 0.0)[0]) == 11


def test_weight_zero_verts_of_transformed_object_keep_their_bits():
    """A field starting inside B's x-range (B is moved, rotated and scaled): B's verts before the start have
    weight 0 and must keep their stored coordinates bit for bit."""
    a, b = setup_scene()
    select_where(a, lambda co: True)
    select_where(b, lambda co: True)
    set_linear(start=(3.0, 0.0, 0.0), end=(5.0, 0.0, 0.0))
    wb0 = world_co(b)
    raw = [np.array(v.co[:], dtype=np.float32).tobytes() for v in bm_of(b).verts]
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    zero = np.nonzero(wb0[:, 0] < 3.0 - 1e-4)[0]
    moved = np.nonzero(wb0[:, 0] > 3.0 + 1e-4)[0]
    assert len(zero) > 20 and len(moved) > 20, (len(zero), len(moved))
    verts = list(bm_of(b).verts)
    for i in zero:
        assert np.array(verts[i].co[:], dtype=np.float32).tobytes() == raw[i], i
    wb = world_co(b)
    expect = np.clip((wb0[:, 0] - 3.0) / 2.0, 0.0, 1.0)
    assert np.allclose(wb[:, 2], expect, atol=TOL), np.abs(wb[:, 2] - expect).max()


def test_nothing_selected_moves_all_visible_and_skips_hidden():
    a, b = setup_scene()
    select_where(a, lambda co: False)
    select_where(b, lambda co: False)
    bm = bm_of(a)
    bm.verts.ensure_lookup_table()
    bm.verts[7].hide_set(True)
    bmesh.update_edit_mesh(a.data)
    bm = bm_of(a)
    bm.verts.ensure_lookup_table()
    hidden = np.array(bm.verts[7].co[:], dtype=np.float32).tobytes()
    wa0, wb0 = world_co(a), world_co(b)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    wa, wb = world_co(a), world_co(b)
    moved_a = np.ones(121, dtype=bool)
    moved_a[7] = False
    assert np.allclose(wa[moved_a] - wa0[moved_a], (0, 0, 1), atol=TOL)
    assert np.allclose(wb - wb0, (0, 0, 1), atol=TOL)
    bm = bm_of(a)
    bm.verts.ensure_lookup_table()
    assert np.array(bm.verts[7].co[:], dtype=np.float32).tobytes() == hidden, "hidden vert moved"


def test_empty_object_cancels():
    setup_scene()
    _clear_objects()
    obj = bpy.data.objects.new("E", bpy.data.meshes.new("E"))
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    for name in ("mesh_falloff_move", "mesh_falloff_rotate", "mesh_falloff_scale",
                 "mesh_falloff_normal_offset"):
        r = getattr(bpy.ops.iops, name)("EXEC_DEFAULT")
        assert r == {"CANCELLED"}, (name, r)


def test_empty_stack_is_weight_one_and_adds_no_field():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    assert len(s.fields) == 0
    w0 = world_co(a)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    assert np.allclose(world_co(a) - w0, (0, 0, 1), atol=TOL)
    assert len(s.fields) == 0, "execute added a field"


def test_disabled_stack_is_weight_one():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    f = set_linear()
    f.enabled = False
    w0 = world_co(a)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    assert np.allclose(world_co(a) - w0, (0, 0, 1), atol=TOL)


def test_active_index_out_of_range():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    bpy.context.scene.IOPS.falloff.active_index = 5
    for name, kw in (("mesh_falloff_move", dict(value=(0, 0, 1))),
                     ("mesh_falloff_rotate", dict(angle=0.3)),
                     ("mesh_falloff_scale", dict(factor=(2, 2, 2))),
                     ("mesh_falloff_normal_offset", dict(distance=0.1))):
        r = getattr(bpy.ops.iops, name)("EXEC_DEFAULT", **kw)
        assert r == {"FINISHED"}, (name, r)


def test_modal_helpers_and_draw_fallback():
    """Pure pieces of the modal (the modal itself needs a window)."""
    import importlib
    base = importlib.import_module(ADDON + ".operators.falloff.base")
    assert base.toggle_axis(None, "X", False) == "X"
    assert base.toggle_axis("X", "X", False) is None
    assert base.toggle_axis(None, "X", True) == "YZ"
    assert base.toggle_axis("YZ", "X", True) is None
    assert base.toggle_axis("X", "Z", False) == "Z"
    assert base.axis_mask(None).tolist() == [1, 1, 1]
    assert base.axis_mask("YZ").tolist() == [0, 1, 1]
    assert abs(base.snap(0.26, 0.1) - 0.3) < 1e-12
    assert abs(base.snap(math.radians(7), math.radians(5)) - math.radians(5)) < 1e-12
    base.draw_begin(None)          # registers / unregisters a running op with draw.py
    base.draw_end(None)
    from types import SimpleNamespace
    op = base.FalloffOpMixin()
    for et in ("MIDDLEMOUSE", "MOUSEROTATE", "MOUSESMARTZOOM", "MOUSEPAN", "WHEELUPMOUSE", "TRACKPADPAN"):
        assert op._modal(None, SimpleNamespace(type=et, value="PRESS")) == {"PASS_THROUGH"}, et


# --- redo panel and stack edge cases ------------------------------------------------------------------------------

class _Layout:
    """Stand-in UI layout: records label / prop calls, hands out child layouts."""

    def __init__(self, log=None):
        self.log = [] if log is None else log
        self.active = True
        self.use_property_split = False

    def label(self, **kw):
        self.log.append(("label", kw.get("text"), self.active))

    def prop(self, data, name, **kw):
        self.log.append(("prop", name, self.active))

    def box(self):
        return _Layout(self.log)

    column = row = box


def _standin(stack_dicts):
    import importlib
    from types import SimpleNamespace
    base = importlib.import_module(ADDON + ".operators.falloff.base")
    op = base.FalloffOpMixin()
    op.layout = _Layout()
    op.stack = [SimpleNamespace(name=d["name"], **{k: v for k, v in d.items() if k != "name"})
                for d in stack_dicts]
    op.pivot = (0.0, 0.0, 0.0)
    op.draw_amount = lambda layout: None
    return op


def test_draw_lists_fields():
    setup_scene()
    for n in (0, 1, 3):
        op = _standin([field_dict(name=f"F{i}") for i in range(n)])
        op.draw(bpy.context)
        props = [(name, active) for kind, name, active in op.layout.log if kind == "prop"]
        for key in ("blend", "strength", "curve", "invert"):
            assert sum(1 for name, _ in props if name == key) == n, (n, key, props)
        assert not any(name in ("start", "end") for name, _ in props), props
        titles = [t for kind, t, _ in op.layout.log if kind == "label"]
        assert titles == [f"F{i}" for i in range(n)], titles
    op = _standin([field_dict(name="Off", enabled=False)])
    op.draw(bpy.context)
    assert all(not active for _, name, active in op.layout.log if name in ("blend", "curve")), op.layout.log


def test_scene_stack_equals_explicit_stack():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()
    dicts = [field_dict(name="F1", curve="SMOOTH"),
             field_dict(name="F2", start=(0.0, -1.0, 0.0), end=(0.0, 1.0, 0.0), blend="MULTIPLY",
                        strength=0.7)]
    for d in dicts:
        f = s.fields.add()
        f.name = d["name"]
        for k, v in d.items():
            if k != "name":
                setattr(f, k, v)
    snap = local_co(a)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1)) == {"FINISHED"}
    implicit = co_bytes(a)
    restore(a, snap)
    assert bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1), stack=dicts) == {"FINISHED"}
    assert co_bytes(a) == implicit
    assert implicit != np.array(snap, dtype=np.float32).tobytes()


def test_stack_length_mismatch_copies_nothing_back():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    set_linear()
    f2 = s.fields.add()
    f2.name = "Falloff 2"
    before = [(f.curve, f.invert, f.strength, f.blend, f.enabled) for f in s.fields]
    r = bpy.ops.iops.mesh_falloff_move("EXEC_DEFAULT", value=(0, 0, 1),
                                       stack=[field_dict(curve="SHARP", strength=0.5, invert=True)])
    assert r == {"FINISHED"}, r
    assert [(f.curve, f.invert, f.strength, f.blend, f.enabled) for f in s.fields] == before


def test_cancel_restores_influence_and_mesh_on_error():
    """Pieces of the modal: influence revert (RMB / Esc) and the mesh revert on an unexpected error."""
    import importlib
    from types import SimpleNamespace
    base = importlib.import_module(ADDON + ".operators.falloff.base")
    domain_mod = importlib.import_module(ADDON + ".operators.falloff.domain")
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    set_linear()
    op = base.FalloffOpMixin()
    op._influence0 = [(f.curve, f.invert) for f in s.fields]
    s.fields[0].curve = "SHARP"
    s.fields[0].invert = True
    op._revert_influence(bpy.context)
    assert s.fields[0].curve == "LINEAR" and s.fields[0].invert is False
    # field count changed meanwhile: leave the scene alone
    op._influence0 = [("SHARP", True), ("SHARP", True)]
    op._revert_influence(bpy.context)
    assert s.fields[0].curve == "LINEAR"

    # unexpected exception in the modal: geometry restored, exception re-raised
    domain = domain_mod.collect_domain(bpy.context)
    P0 = domain.P.copy()
    snap = local_co(a)
    domain_mod.write_back(domain, P0 + (0.0, 0.0, 1.0))
    assert not np.allclose(local_co(a), snap)
    op = base.FalloffOpMixin()
    op._domain, op._P0 = domain, P0
    op._influence0 = None
    op._modal = lambda context, event: (_ for _ in ()).throw(RuntimeError("boom"))
    ctx = SimpleNamespace(workspace=None, scene=bpy.context.scene)
    try:
        op.modal(ctx, None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("exception swallowed")
    assert np.allclose(local_co(a), snap, atol=TOL), "mesh left half-moved"


def test_cancel_by_blender_reverts_and_stops_drawing():
    """`cancel()` (Blender removed the modal: file load, window close) does what Esc does: mesh and
    influence back, and the op no longer keeps the field drawing on."""
    import importlib
    base = importlib.import_module(ADDON + ".operators.falloff.base")
    draw = importlib.import_module(ADDON + ".operators.falloff.draw")
    domain_mod = importlib.import_module(ADDON + ".operators.falloff.domain")
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    set_linear()
    snap = local_co(a)
    op = base.FalloffOpMixin()
    op._influence0 = [(f.curve, f.invert) for f in s.fields]
    domain = domain_mod.collect_domain(bpy.context)
    op._domain, op._P0 = domain, domain.P.copy()
    domain_mod.write_back(domain, op._P0 + (0.0, 0.0, 1.0))
    s.fields[0].curve = "SHARP"
    draw.op_begin(op)
    assert draw.is_visible(bpy.context)
    op.cancel(bpy.context)
    assert not draw.is_visible(bpy.context), "drawing stuck on after cancel"
    assert np.allclose(local_co(a), snap, atol=TOL), "mesh not reverted"
    assert s.fields[0].curve == "LINEAR"
    assert op._domain is None
    op.cancel(bpy.context)                       # a second cancel (nothing left) is harmless
    base.FalloffOpMixin().cancel(bpy.context)    # never invoked: harmless too


TESTS = [
    test_draw_lists_fields,
    test_scene_stack_equals_explicit_stack,
    test_stack_length_mismatch_copies_nothing_back,
    test_cancel_restores_influence_and_mesh_on_error,
    test_cancel_by_blender_reverts_and_stops_drawing,
    test_modal_helpers_and_draw_fallback,
    test_idnames_resolve,
    test_move_ramp,
    test_no_compounding_and_redo_equivalence,
    test_rotate,
    test_scale,
    test_scale_execute_defaults_to_basis_axes,
    test_normal_offset,
    test_normal_offset_uses_current_normals,
    test_multi_object,
    test_weight_zero_verts_of_transformed_object_keep_their_bits,
    test_nothing_selected_moves_all_visible_and_skips_hidden,
    test_empty_object_cancels,
    test_empty_stack_is_weight_one_and_adds_no_field,
    test_disabled_stack_is_weight_one,
    test_active_index_out_of_range,
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
