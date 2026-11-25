"""Falloff toolbar tool: registration, draw-handler hygiene, the weight-preview cache, the type-change refit
and the pure geometry behind the field drawing and the gizmo handles. No GPU drawing runs here
(``--background`` has no GPU context); the interactive parts are checked live.

Run with an isolated user resource folder (the script refuses the real one, see ``_isolation.py``):
``BLENDER_USER_RESOURCES="$TEMP/iops_blender_res" blender --background --factory-startup --python-exit-code 1
--python <this>``.
"""

import importlib
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
TOOL_IDNAME = "iops.falloff_tool"


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


def _mod(name):
    return importlib.import_module(f"{ADDON}.{name}")


def draw_mod():
    return _mod("operators.falloff.draw")


def tool_mod():
    return _mod("operators.falloff.tool")


def fc():
    return _mod("utils.falloff_core")


# --- fixture (as test_falloff_fields.py) --------------------------------------------------------------------------

def _grid_object(name):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1.0)
    co = np.array([v.co[:] for v in bm.verts])
    span = co.max(axis=0) - co.min(axis=0)
    if abs(span[0] - 2.0) > 1e-5:
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
    s.last_type = "LINEAR"
    return a, b


def bm_of(obj):
    return bmesh.from_edit_mesh(obj.data)


def select_where(obj, pred):
    bm = bm_of(obj)
    for v in bm.verts:
        v.select = bool(pred(v.co))
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def world_co(obj, mask=None):
    mw = np.array(obj.matrix_world)
    co = np.array([v.co[:] for v in bm_of(obj).verts], dtype=np.float64)
    if mask is not None:
        co = co[mask]
    return co @ mw[:3, :3].T + mw[:3, 3]


def set_linear(start=(-1.0, 0.0, 0.0), end=(1.0, 0.0, 0.0)):
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()
    f = s.fields.add()
    f.name = "Falloff 1"
    f.type = "LINEAR"
    f.start = start
    f.end = end
    s.active_index = 0
    return f


def field_dict(**over):
    d = dict(type="LINEAR", start=(-1.0, 0.0, 0.0), end=(1.0, 0.0, 0.0), radii=(1.0, 1.0), roll=0.0,
             curve="LINEAR", invert=False, strength=1.0, blend="REPLACE", enabled=True)
    d.update(over)
    return d


# --- registration -------------------------------------------------------------------------------------------------

def _edit_mesh_tool_ids():
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    cls = ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D")
    return {t.idname for t in cls._tools_flatten(cls._tools["EDIT_MESH"]) if t is not None}


def _registered(base, name):
    """Gizmo / GizmoGroup types are not exposed on bpy.types by name: look for a registered subclass
    (registration adds ``bl_rna`` to the class itself, unregistration removes it)."""
    return any("bl_rna" in c.__dict__ for c in base.__subclasses__() if c.__name__ == name)


def _view3d_override():
    scr = bpy.context.window.screen
    area = next(a for a in scr.areas if a.type == "VIEW_3D")
    return bpy.context.temp_override(area=area, screen=scr)


def set_tool(idname):
    with _view3d_override():
        assert bpy.ops.wm.tool_set_by_id(name=idname, space_type="VIEW_3D") == {"FINISHED"}


def active_tool_id():
    t = bpy.context.workspace.tools.from_space_view3d_mode(bpy.context.mode, create=False)
    return t.idname if t else None


def _falloff_handlers(kind):
    return [h for h in getattr(bpy.app.handlers, kind)
            if getattr(h, "__module__", "").endswith("operators.falloff.draw")]


def _falloff_depsgraph_handlers():
    return _falloff_handlers("depsgraph_update_post")


def _falloff_load_handlers():
    return _falloff_handlers("load_post")


def test_tool_and_gizmo_group_registered():
    assert _registered(bpy.types.GizmoGroup, "IOPS_GGT_falloff")
    assert _registered(bpy.types.Gizmo, "IOPS_GT_falloff_handle")
    assert hasattr(bpy.types, "IOPS_PT_falloff_stack")
    assert hasattr(bpy.types, "IOPS_UL_falloff_fields")
    assert TOOL_IDNAME in _edit_mesh_tool_ids()
    assert draw_mod().TOOL_IDNAME == TOOL_IDNAME
    wt = tool_mod().IOPS_WT_falloff
    assert wt.bl_label == "Falloff" and wt.bl_widget == "IOPS_GGT_falloff"
    assert wt.bl_context_mode == "EDIT_MESH" and wt.bl_space_type == "VIEW_3D"
    binds = {(kmi[1]["type"], bool(kmi[1].get("alt")), bool(kmi[1].get("shift"))): kmi[0]
             for kmi in wt.bl_keymap}
    assert binds == {("G", False, False): "iops.mesh_falloff_move",
                     ("R", False, False): "iops.mesh_falloff_rotate",
                     ("S", False, False): "iops.mesh_falloff_scale",
                     ("S", True, False): "iops.mesh_falloff_normal_offset",
                     ("F", False, True): "iops.mesh_falloff_fit"}, binds
    assert all(kmi[1]["value"] == "PRESS" for kmi in wt.bl_keymap)
    assert len(_falloff_depsgraph_handlers()) == 1, _falloff_depsgraph_handlers()
    assert len(_falloff_load_handlers()) == 1, _falloff_load_handlers()


def test_type_icons_exist():
    icons = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys())
    for t, icon in tool_mod().TYPE_ICONS.items():
        assert icon in icons, (t, icon)
    assert set(tool_mod().TYPE_ICONS) == set(fc().FALLOFF_TYPES)


class _Recorder:
    def __init__(self, module):
        self.module = module
        self.added, self.removed = [], []
        self._real = module.safe_handler_add, module.safe_handler_remove

        def add(space, callback, args, region, draw_type, **kwargs):
            handle = self._real[0](space, callback, args, region, draw_type, **kwargs)
            self.added.append((handle, draw_type, kwargs.get("tick", False)))
            return handle

        def remove(handle, space, region):
            self.removed.append(handle)
            self._real[1](handle, space, region)

        module.safe_handler_add, module.safe_handler_remove = add, remove

    def undo(self):
        self.module.safe_handler_add, self.module.safe_handler_remove = self._real


def test_install_twice_uninstall_once():
    draw = draw_mod()
    draw.uninstall()
    rec = _Recorder(draw)
    try:
        draw.install()
        draw.install()
        assert len(_falloff_depsgraph_handlers()) == 1
        assert len(_falloff_load_handlers()) == 1
        draw.uninstall()
    finally:
        rec.undo()
    assert sorted(k for _, k, _ in rec.added) == ["POST_PIXEL", "POST_VIEW"], rec.added
    assert not any(tick for _, _, tick in rec.added)
    assert {h for h, _, _ in rec.added} == set(rec.removed), (rec.added, rec.removed)
    assert _falloff_depsgraph_handlers() == [] and _falloff_load_handlers() == []
    draw.install()
    assert len(_falloff_depsgraph_handlers()) == 1 and len(_falloff_load_handlers()) == 1


def test_op_begin_end_visibility():
    draw = draw_mod()
    setup_scene()
    op = object()
    assert not draw.is_visible(bpy.context)          # tool not active, no op
    draw.op_begin(op)
    try:
        assert draw.is_visible(bpy.context)
    finally:
        draw.op_end(op)
    assert not draw.is_visible(bpy.context)
    draw.op_end(op)                                   # twice is harmless
    bpy.ops.object.mode_set(mode="OBJECT")
    draw.op_begin(op)
    try:
        assert not draw.is_visible(bpy.context)      # Object Mode never draws
    finally:
        draw.op_end(op)


def test_tool_activation_visibility_and_gizmo_poll():
    draw = draw_mod()
    setup_scene()
    ggt = tool_mod().IOPS_GGT_falloff
    set_tool("builtin.select_box")
    assert not draw.is_visible(bpy.context) and not ggt.poll(bpy.context)
    with _view3d_override():
        _mod("operators.falloff.fields")._activate_tool(bpy.context)
    assert active_tool_id() == TOOL_IDNAME
    assert draw.is_visible(bpy.context) and ggt.poll(bpy.context)
    bpy.ops.object.mode_set(mode="OBJECT")
    assert not draw.is_visible(bpy.context) and not ggt.poll(bpy.context)
    bpy.ops.object.mode_set(mode="EDIT")
    set_tool("builtin.select_box")


def test_disable_enable_leaves_nothing_behind():
    setup_scene()
    set_tool(TOOL_IDNAME)                             # disable while the tool is the active one
    assert active_tool_id() == TOOL_IDNAME
    # addon_utils with refresh_handled: the preferences operator also re-syncs the extension wheels of
    # the user resource dir for the (empty) set of extensions a factory session has enabled, which
    # deletes the wheels a real session uses
    import addon_utils
    addon_utils.disable(ADDON, default_set=True, refresh_handled=True)
    assert TOOL_IDNAME not in _edit_mesh_tool_ids()
    assert not _registered(bpy.types.GizmoGroup, "IOPS_GGT_falloff")
    assert not _registered(bpy.types.Gizmo, "IOPS_GT_falloff_handle")
    assert not hasattr(bpy.types, "IOPS_PT_falloff_stack")
    assert _falloff_depsgraph_handlers() == []
    assert _falloff_load_handlers() == []
    km = bpy.context.window_manager.keyconfigs.default.keymaps
    assert not any("Falloff" in k.name for k in km), [k.name for k in km if "Falloff" in k.name]
    enable_addon()
    assert TOOL_IDNAME in _edit_mesh_tool_ids()
    assert _registered(bpy.types.GizmoGroup, "IOPS_GGT_falloff")
    assert _registered(bpy.types.Gizmo, "IOPS_GT_falloff_handle")
    assert len(_falloff_depsgraph_handlers()) == 1 and len(_falloff_load_handlers()) == 1
    set_tool(TOOL_IDNAME)                             # the re-registered tool activates again
    assert draw_mod().is_visible(bpy.context)
    set_tool("builtin.select_box")


def test_file_load_clears_running_ops():
    """A modal Blender drops on file load must not leave the field drawing on: load_post forgets every
    running op."""
    import tempfile
    draw = draw_mod()
    setup_scene()
    bpy.ops.object.mode_set(mode="OBJECT")
    path = os.path.join(tempfile.mkdtemp(prefix="iops_falloff_"), "load_post.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    op = object()
    draw.op_begin(op)
    assert draw._ops
    bpy.ops.wm.open_mainfile(filepath=path)
    assert not draw._ops, draw._ops
    assert len(_falloff_load_handlers()) == 1 and len(_falloff_depsgraph_handlers()) == 1
    setup_scene()
    assert not draw.is_visible(bpy.context)


# --- preview cache ------------------------------------------------------------------------------------------------

def test_preview_cache_matches_stack_weights_and_refreshes():
    draw = draw_mod()
    props = _mod("operators.falloff.props")
    domain_mod = _mod("operators.falloff.domain")
    a, b = setup_scene()
    select_where(a, lambda co: co.x > -0.5)
    set_linear()
    draw.invalidate()
    cache = draw.compute_preview(bpy.context)
    d = domain_mod.collect_domain(bpy.context)
    try:
        P = d.P.copy()
    finally:
        domain_mod.finish_domain(d, normals=False)
    s = bpy.context.scene.IOPS.falloff
    expect = fc().stack_weights(P, props.stack_to_list(s.fields))
    assert len(cache.W) == len(P) == 88, (len(cache.W), len(P))
    assert np.allclose(cache.P, P) and np.allclose(cache.W, expect)
    assert np.allclose(cache.pivot, fc().bbox_center(P))
    assert draw.compute_preview(bpy.context) is cache        # clean and unchanged: same cache
    w_before = cache.W.copy()

    s.fields[0].end = (0.0, 0.0, 0.0)                       # signature change alone refreshes
    cache = draw.compute_preview(bpy.context)
    expect = fc().stack_weights(P, props.stack_to_list(s.fields))
    assert np.allclose(cache.W, expect) and not np.allclose(cache.W, w_before)

    s.fields[0].curve = "SMOOTH"
    draw.invalidate()
    cache = draw.compute_preview(bpy.context)
    assert np.allclose(cache.W, fc().stack_weights(P, props.stack_to_list(s.fields)))

    select_where(a, lambda co: co.x > 0.5)                   # selection change + invalidate (depsgraph)
    draw.invalidate()
    cache = draw.compute_preview(bpy.context)
    assert len(cache.P) == 33, len(cache.P)

    bad = (bmesh.types.BMesh, bmesh.types.BMVert)
    for name in dir(cache):
        if name.startswith("__"):
            continue
        val = getattr(cache, name)
        assert not isinstance(val, bad), name
        if isinstance(val, (list, tuple)):
            assert not any(isinstance(x, bad) for x in val), name


def test_preview_without_weights_keeps_pivot_and_points():
    draw = draw_mod()
    a, b = setup_scene()
    select_where(a, lambda co: True)
    set_linear()
    s = bpy.context.scene.IOPS.falloff
    s.show_weights = False
    try:
        draw.invalidate()
        cache = draw.compute_preview(bpy.context)
        assert len(cache.W) == 0, "weights computed with Show Weights off"
        assert len(cache.P) == 121 and cache.pivot is not None
        s.show_weights = True
        cache = draw.compute_preview(bpy.context)
        assert len(cache.W) == 121
    finally:
        s.show_weights = True


def test_field_edit_alone_does_not_recollect_the_domain():
    """A handle drag only changes scene properties: the weights follow (signature), the domain is not
    collected again; a mesh change still marks it dirty."""
    draw = draw_mod()
    a, _ = setup_scene()
    select_where(a, lambda co: True)
    f = set_linear()
    bpy.context.view_layer.update()
    draw.invalidate()
    cache = draw.compute_preview(bpy.context)
    v0, P0 = cache.version, cache.P
    f.end = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    assert not draw.preview_dirty(), "scene-only update re-dirtied the domain"
    cache = draw.compute_preview(bpy.context)
    assert cache.P is P0 and cache.version == v0 + 1
    assert draw.compute_preview(bpy.context).version == v0 + 1      # unchanged: no new version
    assert draw.touches_geometry([]) is True


def test_weight_batches_rebuild_only_on_key_change():
    draw = draw_mod()
    built = []
    slot = draw.BatchSlot()

    def build():
        built.append(1)
        return object()

    cache = draw.PreviewCache()
    k = draw.weight_batch_key(cache, C0, C100, [1.0, 0.5])
    first = slot.get(k, build)
    assert slot.get(draw.weight_batch_key(cache, C0, C100, [1.0, 0.5]), build) is first and len(built) == 1
    slot.get(draw.weight_batch_key(cache, C100, C100, [1.0, 0.5]), build)           # theme colour
    slot.get(draw.weight_batch_key(cache, C100, C100, [1.0]), build)                # dimming
    cache.version += 1
    slot.get(draw.weight_batch_key(cache, C100, C100, [1.0]), build)                # preview changed
    assert len(built) == 4
    slot.clear()
    assert slot.value is None and slot.key is None


def test_uninstall_drops_the_cached_batches():
    draw = draw_mod()
    draw._weight_batches.get(("probe",), lambda: object())
    assert draw._weight_batches.value is not None
    draw.uninstall()
    try:
        assert draw._weight_batches.value is None
    finally:
        draw.install()


def test_preview_cache_empty_without_edit_mode():
    draw = draw_mod()
    setup_scene()
    bpy.ops.object.mode_set(mode="OBJECT")
    draw.invalidate()
    cache = draw.compute_preview(bpy.context)
    assert len(cache.P) == 0 and len(cache.W) == 0 and cache.pivot is None


def test_depsgraph_update_marks_dirty():
    draw = draw_mod()
    a, _ = setup_scene()
    set_linear()
    draw.invalidate()
    draw.compute_preview(bpy.context)
    assert not draw.preview_dirty()
    select_where(a, lambda co: co.x > 0.0)
    bpy.context.view_layer.update()                        # runs depsgraph_update_post
    assert draw.preview_dirty()


def test_preview_read_does_not_tag_the_mesh():
    """Reading the preview must not call update_edit_mesh (it would re-dirty itself every frame)."""
    draw = draw_mod()
    setup_scene()
    set_linear()
    bpy.context.view_layer.update()
    draw.invalidate()
    draw.compute_preview(bpy.context)
    bpy.context.view_layer.update()
    assert not draw.preview_dirty()


# --- type change refit, fit, tool activation ----------------------------------------------------------------------

def test_type_change_refits_to_selection():
    a, _ = setup_scene()
    mask_fn = lambda co: co.x > 0.1 and co.y < 0.5           # noqa: E731
    select_where(a, mask_fn)
    assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}
    s = bpy.context.scene.IOPS.falloff
    f = s.fields[0]
    f.type = "RADIAL"
    mask = np.array([mask_fn(v.co) for v in bm_of(a).verts])
    P = world_co(a, mask)
    centre = 0.5 * (P.min(axis=0) + P.max(axis=0))
    assert np.allclose(f.start[:], centre, atol=1e-5), (f.start[:], centre)
    assert s.last_type == "RADIAL"


def test_type_change_outside_edit_mode_keeps_geometry():
    setup_scene()
    f = set_linear(start=(5.0, 5.0, 5.0), end=(6.0, 5.0, 5.0))
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        f.type = "RADIAL"                                    # no exception from the update callback
        assert f.type == "RADIAL"
        assert tuple(f.start) == (5.0, 5.0, 5.0) and tuple(f.end) == (6.0, 5.0, 5.0), (f.start[:], f.end[:])
    finally:
        bpy.ops.object.mode_set(mode="EDIT")


def test_operator_stack_copy_does_not_refit():
    props = _mod("operators.falloff.props")
    a, _ = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    f = set_linear(start=(5.0, 5.0, 5.0), end=(6.0, 5.0, 5.0))
    props.dict_to_field(field_dict(type="RADIAL", start=(5.0, 5.0, 5.0), end=(6.0, 5.0, 5.0)), f)
    assert f.type == "RADIAL" and tuple(f.start) == (5.0, 5.0, 5.0), tuple(f.start)
    assert s.last_type == "LINEAR"


def test_fit_headless_finishes():
    a, _ = setup_scene()
    select_where(a, lambda co: True)
    assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}
    assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}


# --- pure geometry: field drawing ---------------------------------------------------------------------------------

C0 = (0.0, 0.5, 1.0, 1.0)
C100 = (1.0, 0.5, 0.0, 1.0)


def test_gradient_endpoints_carry_the_end_colours():
    draw = draw_mod()
    segs = draw.gradient_segments(field_dict(), C0, C100, steps=8)
    assert len(segs) == 8
    (a0, _), c_first = segs[0]
    (_, b_last), c_last = segs[-1]
    assert np.allclose(a0, (-1, 0, 0)) and np.allclose(b_last, (1, 0, 0))
    assert np.allclose(c_first, C0, atol=0.07) and np.allclose(c_last, C100, atol=0.07)
    inv = draw.gradient_segments(field_dict(invert=True), C0, C100, steps=8)
    assert np.allclose(inv[0][1], C100, atol=0.07) and np.allclose(inv[-1][1], C0, atol=0.07)
    bid = draw.gradient_segments(field_dict(type="BIDIRECTIONAL"), C0, C100, steps=8)
    assert np.allclose(bid[0][1], C0, atol=0.15) and np.allclose(bid[-1][1], C0, atol=0.15)
    assert np.allclose(bid[3][1], C100, atol=0.15) and np.allclose(bid[4][1], C100, atol=0.15)
    rad = draw.gradient_segments(field_dict(type="RADIAL"), C0, C100, steps=8)
    assert np.allclose(rad[0][1], C100, atol=0.07) and np.allclose(rad[-1][1], C0, atol=0.07)


def test_labels():
    draw = draw_mod()
    lin = draw.field_labels(field_dict())
    assert [(t, tuple(np.round(p, 6))) for p, t, _ in lin] == [("0%", (-1, 0, 0)), ("100%", (1, 0, 0))], lin
    assert [w for _, _, w in lin] == [0.0, 1.0], lin
    bid = draw.field_labels(field_dict(type="BIDIRECTIONAL"))
    assert sorted(t for _, t, _ in bid) == ["0%", "0%", "100%"], bid
    mid = next(p for p, t, _ in bid if t == "100%")
    assert np.allclose(mid, (0, 0, 0))
    rad = draw.field_labels(field_dict(type="RADIAL"))
    assert dict((t, tuple(np.round(p, 6))) for p, t, _ in rad) == {"100%": (-1, 0, 0), "0%": (1, 0, 0)}, rad
    # the weight is the unrounded value the label text shows
    smooth = draw.field_labels(field_dict(start=(0.0, 0.0, 0.0), end=(2.0, 0.0, 0.0), curve="SMOOTH",
                                          strength=0.5))
    for _, t, w in smooth:
        assert isinstance(w, float) and t == "%d%%" % int(round(100.0 * w)), (t, w)


def test_ellipse_outlines_lie_on_the_ellipsoid():
    draw = draw_mod()
    f = field_dict(type="ELLIPTICAL", start=(1.0, 2.0, 3.0), end=(1.0, 4.0, 3.5), radii=(0.7, 0.3),
                   roll=0.4)
    loops = draw.volume_outlines(f, segments=24)
    assert len(loops) == 3 and all(len(lp) == 24 for lp in loops)
    axes, radii = fc().ellipsoid_frame(f["start"], f["end"], f["radii"], f["roll"])
    for lp in loops:
        local = (np.asarray(lp) - np.asarray(f["start"])) @ axes
        q = np.linalg.norm(local / radii, axis=1)
        assert np.allclose(q, 1.0, atol=1e-6), q
    pairs = draw.loops_to_segments(loops)
    assert len(pairs) == 2 * 3 * 24


def test_radial_rings_have_the_radius():
    draw = draw_mod()
    f = field_dict(type="RADIAL", start=(0.0, 0.0, 1.0), end=(0.0, 2.0, 1.0))
    loops = draw.volume_outlines(f, segments=16)
    assert len(loops) == 3
    for lp in loops:
        assert np.allclose(np.linalg.norm(np.asarray(lp) - (0, 0, 1), axis=1), 2.0, atol=1e-6)
    normals = []
    for lp in loops:
        p = np.asarray(lp) - (0, 0, 1)
        n = np.cross(p[0], p[4])
        normals.append(n / np.linalg.norm(n))
    N = np.abs(np.array(normals) @ np.array(normals).T)
    assert np.allclose(N, np.eye(3), atol=1e-6), N
    assert draw.volume_outlines(field_dict(), segments=16) == []
    assert draw.volume_outlines(field_dict(type="BIDIRECTIONAL"), segments=16) == []


def test_field_layers_draw_order_widths_and_alpha():
    draw = draw_mod()
    halo = (0.0, 0.0, 0.0, 1.0)
    lin = draw.field_layers(field_dict(), C0, C100, alpha=0.5, line_px=5.0, outline_px=2.5, halo_color=halo)
    # Linear: the halo under the whole line, then the whole gradient line as one layer with a colour per point
    assert len(lin) == 2
    pairs, col, px = lin[0]
    assert len(pairs) == 2 * draw.GRADIENT_STEPS and px == 5.0 + draw.HALO_PX
    assert np.allclose(col, (0, 0, 0, 0.5 * draw.HALO_ALPHA))
    segs = draw.gradient_segments(field_dict(), C0, C100)
    pairs, cols, px = lin[1]
    assert isinstance(cols, list) and len(cols) == len(pairs) == 2 * draw.GRADIENT_STEPS and px == 5.0
    for k, ((a, b), c) in enumerate(segs):
        assert np.allclose(pairs[2 * k], a) and np.allclose(pairs[2 * k + 1], b)
        for col in cols[2 * k:2 * k + 2]:
            assert np.allclose(col[:3], c[:3]) and col[3] == 0.5 * c[3]
    # Elliptical: outline halo, outline (full 0 % colour times alpha, as strong as the line), then the line
    f = field_dict(type="ELLIPTICAL", radii=(0.5, 0.25))
    ell = draw.field_layers(f, C0, C100, alpha=1.0, line_px=5.0, outline_px=2.5, halo_color=halo)
    outline = draw.loops_to_segments(draw.volume_outlines(f))
    assert len(ell) == 4
    assert np.allclose(ell[0][0], outline) and ell[0][2] == 2.5 + draw.HALO_PX
    assert np.allclose(ell[1][0], outline) and ell[1][2] == 2.5 and np.allclose(ell[1][1], C0)
    assert ell[2][2] == 5.0 + draw.HALO_PX and ell[3][2] == 5.0 and isinstance(ell[3][1], list)


def test_field_alpha_inactive_readable_but_distinct():
    draw = draw_mod()
    assert draw.field_alpha(True, True) == 1.0
    assert 0.6 <= draw.field_alpha(False, True) < 1.0
    assert draw.field_alpha(True, False) < draw.field_alpha(True, True)
    assert draw.field_alpha(False, False) < draw.field_alpha(False, True)


def test_weight_colours_and_dim():
    draw = draw_mod()
    cols = draw.weight_colors(np.array([0.0, 0.5, 1.0]), C0, C100)
    assert np.allclose(cols[0], C0) and np.allclose(cols[2], C100)
    assert np.allclose(cols[1], (0.5, 0.5, 0.5, 1.0))
    assert np.allclose(draw.dim(C100, 0.35), (1.0, 0.5, 0.0, 0.35))


# --- pure geometry: handles ---------------------------------------------------------------------------------------

def test_handle_points():
    tool = tool_mod()
    pts = tool.handle_points(field_dict())
    assert set(pts) == {"START", "END", "BODY"}
    assert np.allclose(pts["BODY"], (0, 0, 0))
    f = field_dict(type="ELLIPTICAL", start=(0.0, 0.0, 0.0), end=(0.0, 0.0, 2.0), radii=(0.5, 0.25))
    pts = tool.handle_points(f)
    assert set(pts) == {"START", "END", "BODY", "RADIUS_1", "RADIUS_2"}
    axes, _ = fc().ellipsoid_frame(f["start"], f["end"], f["radii"], f["roll"])
    assert np.allclose(pts["RADIUS_1"], axes[:, 1] * 0.5)
    assert np.allclose(pts["RADIUS_2"], axes[:, 2] * 0.25)


def test_handle_colors_follow_the_theme():
    tool = tool_mod()
    theme_mod = _mod("ui.draw.theme")
    Role = theme_mod.Role
    th = theme_mod.DEFAULT_THEME
    c = th.color_for(Role.HANDLE)
    h = th.color_for(Role.HANDLE_HOVER)
    got = tool.handle_colors(th, Role.HANDLE, 0.35)
    assert got == (tuple(c[:3]), float(c[3]) * 0.35, tuple(h[:3]), float(h[3])), got

    class _Edited:                                   # a theme whose handle colour the user changed
        def color_for(self, role):
            return (0.1, 0.2, 0.3, 0.8) if role == Role.HANDLE else th.color_for(role)
    assert tool.handle_colors(_Edited(), Role.HANDLE)[:2] == ((0.1, 0.2, 0.3), 0.8)


def test_drag_results():
    tool = tool_mod()
    f = field_dict()
    d = np.array([0.0, 1.0, 0.0])
    r = tool.drag_field(f, "START", d)
    assert np.allclose(r["start"], (-1, 1, 0)) and np.allclose(r["end"], (1, 0, 0))
    r = tool.drag_field(f, "END", d)
    assert np.allclose(r["end"], (1, 1, 0)) and np.allclose(r["start"], (-1, 0, 0))
    r = tool.drag_field(f, "BODY", d)
    assert np.allclose(r["start"], (-1, 1, 0)) and np.allclose(r["end"], (1, 1, 0))
    e = field_dict(type="ELLIPTICAL", start=(0.0, 0.0, 0.0), end=(0.0, 0.0, 2.0), radii=(0.5, 0.25))
    axes, _ = fc().ellipsoid_frame(e["start"], e["end"], e["radii"], e["roll"])
    # drag RADIUS_1 outward by 0.3 along its axis plus a sideways bit: radius follows the axis only
    r = tool.drag_field(e, "RADIUS_1", axes[:, 1] * 0.3 + axes[:, 0] * 0.4)
    assert np.allclose(r["radii"], (0.8, 0.25)), r["radii"]
    r = tool.drag_field(e, "RADIUS_2", -axes[:, 2] * 1.0)
    assert np.allclose(r["radii"], (0.5, 0.75)), r["radii"]
    assert np.allclose(r["start"], e["start"]) and np.allclose(r["end"], e["end"])


def test_constrain_and_snap():
    tool = tool_mod()
    d = np.array([1.0, 2.0, 3.0])
    assert np.allclose(tool.constrain(d, None), d)
    assert np.allclose(tool.constrain(d, "Y"), (0, 2, 0))
    assert tool.toggle_constraint(None, "X") == "X"
    assert tool.toggle_constraint("X", "X") is None
    assert tool.toggle_constraint("X", "Z") == "Z"
    P2 = np.array([[10.0, 10.0], [100.0, 100.0], [30.0, 10.0]])
    vis = np.array([True, True, True])
    assert tool.nearest_within(P2, vis, (12.0, 11.0), 16.0) == 0
    assert tool.nearest_within(P2, vis, (60.0, 60.0), 16.0) is None
    assert tool.nearest_within(P2, np.array([False, True, True]), (12.0, 11.0), 16.0) is None
    # projection: identity perspective -> NDC == xy
    P = np.array([[0.0, 0.0, 0.0], [1.0, -1.0, 0.0], [0.0, 0.0, 0.0]])
    M = np.eye(4)
    xy, ok = tool.project_points(P, M, 200, 100)
    assert np.allclose(xy[0], (100, 50)) and np.allclose(xy[1], (200, 0)) and ok.all()


def test_builtin_widget_resolves():
    """Every op and scene property of the built-in Falloff Tools widget exists."""
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "presets", "widgets", "falloff_tools.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    ops, props = [], []

    def walk(node):
        if isinstance(node, dict):
            if "op" in node:
                ops.append(node["op"])
            if str(node.get("prop", "")).startswith("scene.IOPS."):
                props.append(node["prop"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    assert ops and props, (ops, props)
    for idname in ops:
        mod, name = idname.split(".", 1)
        getattr(getattr(bpy.ops, mod), name).get_rna_type()
    for path_ in props:
        bpy.context.scene.path_resolve(path_[len("scene."):])


TESTS = [
    test_tool_and_gizmo_group_registered,
    test_type_icons_exist,
    test_install_twice_uninstall_once,
    test_op_begin_end_visibility,
    test_file_load_clears_running_ops,
    test_preview_cache_matches_stack_weights_and_refreshes,
    test_preview_cache_empty_without_edit_mode,
    test_preview_without_weights_keeps_pivot_and_points,
    test_field_edit_alone_does_not_recollect_the_domain,
    test_weight_batches_rebuild_only_on_key_change,
    test_uninstall_drops_the_cached_batches,
    test_depsgraph_update_marks_dirty,
    test_preview_read_does_not_tag_the_mesh,
    test_type_change_refits_to_selection,
    test_type_change_outside_edit_mode_keeps_geometry,
    test_operator_stack_copy_does_not_refit,
    test_fit_headless_finishes,
    test_gradient_endpoints_carry_the_end_colours,
    test_labels,
    test_ellipse_outlines_lie_on_the_ellipsoid,
    test_radial_rings_have_the_radius,
    test_field_layers_draw_order_widths_and_alpha,
    test_field_alpha_inactive_readable_but_distinct,
    test_weight_colours_and_dim,
    test_handle_points,
    test_handle_colors_follow_the_theme,
    test_drag_results,
    test_constrain_and_snap,
    test_builtin_widget_resolves,
    test_tool_activation_visibility_and_gizmo_poll,
    test_disable_enable_leaves_nothing_behind,     # last: it re-enables the add-on
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
