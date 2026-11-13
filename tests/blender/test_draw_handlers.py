"""Draw handlers of the tools whose preview lines lie on the mesh: Inset, Straight Bevel, Quick Connect, Shear and
Hinge (Edge Slide, UV Pipe and UV Stripe are covered in their own files).

Each tool's ``invoke`` runs on a stand-in operator with a stand-in context (no region, no window: the modal
handler is kept by a stand-in window manager), its module's ``safe_handler_add`` / ``safe_handler_remove`` are
recorded, and every way out of the modal is taken: the lines on the mesh must be drawn by a POST_VIEW handler,
the HUD by a POST_PIXEL one, both tracked for the purge on reload and both gone after each exit.

Run: ``blender --background --factory-startup --python-exit-code 1 --python <this>``.
"""

import os
import sys
import traceback
from types import SimpleNamespace

import bmesh
import bpy

ADDON = "InteractionOps"


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


# --- stand-ins ----------------------------------------------------------------------------------------------------

class _OperatorStandIn:
    """Stands in for an instance of ``cls``: its properties at their defaults, its methods bound here."""

    def __init__(self, cls, idname, **props):
        object.__setattr__(self, "_cls", cls)
        group, name = idname.split(".")
        for prop in getattr(getattr(bpy.ops, group), name).get_rna_type().properties:
            if prop.identifier == "rna_type":
                continue
            value = prop.default_array if getattr(prop, "is_array", False) else prop.default
            self.__dict__[prop.identifier] = tuple(value) if getattr(prop, "is_array", False) else value
        self.__dict__.update(props)
        self.reports = []

    def report(self, kinds, message):
        self.reports.append((set(kinds), message))

    def __getattr__(self, name):
        attr = getattr(self._cls, name)
        return attr.__get__(self) if callable(attr) and hasattr(attr, "__get__") else attr


class _WindowManager:
    def __init__(self):
        self.modal = []

    def modal_handler_add(self, op):
        self.modal.append(op)
        return True


class _Context:
    """``bpy.context`` with no region and a stand-in area and window manager."""

    region = None
    region_data = None

    def __init__(self):
        self.window_manager = _WindowManager()
        self.area = SimpleNamespace(tag_redraw=lambda: None)

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def _event(kind, value="PRESS"):
    return SimpleNamespace(type=kind, value=value, shift=False, ctrl=False, alt=False, oskey=False,
                           mouse_x=0, mouse_y=0, mouse_region_x=0, mouse_region_y=0)


class _Recorder:
    """Records ``module``'s draw handlers (the calls still go through)."""

    def __init__(self, module):
        self.module = module
        self.added, self.removed = [], []
        self._real = module.safe_handler_add, module.safe_handler_remove

        def add(space, callback, args, region, draw_type, **kwargs):
            handle = self._real[0](space, callback, args, region, draw_type, **kwargs)
            self.added.append((handle, callback.__name__, draw_type))
            return handle

        def remove(handle, space, region):
            self.removed.append(handle)
            self._real[1](handle, space, region)

        module.safe_handler_add, module.safe_handler_remove = add, remove

    def undo(self):
        self.module.safe_handler_add, self.module.safe_handler_remove = self._real
        self.module._purge_handles()

    def handles(self):
        return {h for h, _name, _kind in self.added}


# --- scenes -------------------------------------------------------------------------------------------------------

def _cube(select):
    """A fresh 2 x 2 x 2 cube in Edit Mode with ``select`` ("face": its top face, "edge": one top edge,
    "none": nothing) selected."""
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    me = bpy.data.meshes.new("cube")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("cube", me)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(me)
    for elem in (*bm.verts, *bm.edges, *bm.faces):
        elem.select_set(False)
    top = max(bm.faces, key=lambda f: f.calc_center_median().z)
    if select == "face":
        top.select_set(True)
    elif select == "edge":
        top.edges[0].select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(me)
    return obj


def _module(name):
    import importlib
    return importlib.import_module(f"InteractionOps.operators.{name}")


def _open(module, cls, idname, select, expect, **props):
    """invoke() on a fresh scene; checks the handlers it registered against ``expect`` [(callback name, draw
    type)] and returns (op, context, recorder)."""
    _cube(select)
    rec = _Recorder(module)
    op = _OperatorStandIn(cls, idname, **props)
    ctx = _Context()
    try:
        result = op.invoke(ctx, _event("MOUSEMOVE", "NOTHING"))
        assert result == {"RUNNING_MODAL"}, (result, op.reports)
        assert ctx.window_manager.modal == [op]
        assert [(name, kind) for _h, name, kind in rec.added] == expect, rec.added
        assert rec.handles() <= module._ACTIVE_HANDLES
    except Exception:
        rec.undo()
        raise
    return op, ctx, rec


def _closed(op, rec, names=("_handle_view", "_handle")):
    """Every handler the run added is removed and out of the registry, and the operator holds none."""
    try:
        assert rec.handles() <= set(rec.removed), (rec.added, rec.removed)
        assert not rec.handles() & rec.module._ACTIVE_HANDLES
        for name in names:
            assert getattr(op, name, None) is None, name
    finally:
        rec.undo()


def _raising(op):
    """Make the operator's event handling fail, as a bug inside it would."""
    def fail(_context, _event):
        raise RuntimeError("a bug inside the modal")
    op.__dict__["_modal"] = fail


def _modal_raises(op, ctx):
    try:
        op.modal(ctx, _event("MOUSEMOVE", "NOTHING"))
    except RuntimeError:
        return
    raise AssertionError("the modal swallowed the error")


VIEW_PIXEL = [("_draw_view_callback", "POST_VIEW"), ("_draw_callback", "POST_PIXEL")]


# --- tests --------------------------------------------------------------------------------------------------------

def _inset():
    module = _module("mesh_inset")
    return module, module.IOPS_OT_inset, "iops.mesh_inset"


def test_inset_handlers_go_on_every_exit():
    module, cls, idname = _inset()
    for exit_key, expected in (("ESC", {"CANCELLED"}), ("RIGHTMOUSE", {"CANCELLED"}), ("RET", {"FINISHED"})):
        op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
        assert op.modal(ctx, _event(exit_key)) == expected, (exit_key, op.reports)
        _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    _raising(op)
    _modal_raises(op, ctx)
    _closed(op, rec)


def test_inset_purge_removes_both():
    module, cls, idname = _inset()
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    module._purge_handles()
    assert rec.handles() <= set(rec.removed) and not module._ACTIVE_HANDLES
    op._finish(ctx)
    rec.undo()


def _bevel():
    module = _module("mesh_straight_bevel")
    return module, module.IOPS_OT_straight_bevel, "iops.mesh_straight_bevel"


def test_straight_bevel_handlers_go_on_every_exit():
    module, cls, idname = _bevel()
    for exit_key, expected in (("ESC", {"CANCELLED"}), ("RIGHTMOUSE", {"CANCELLED"}), ("RET", {"FINISHED"})):
        op, ctx, rec = _open(module, cls, idname, "edge", VIEW_PIXEL)
        assert op.modal(ctx, _event(exit_key)) == expected, (exit_key, op.reports)
        _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "edge", VIEW_PIXEL)
    module._purge_handles()
    assert rec.handles() <= set(rec.removed)
    op._finish(ctx)
    rec.undo()


QC_HANDLERS = [("draw_callback_view", "POST_VIEW"), ("draw_callback_px", "POST_PIXEL"),
               ("draw_shortcuts_callback", "POST_PIXEL")]
QC_NAMES = ("_handle_view", "_handle", "_handle_text")


def _quick_connect():
    module = _module("mesh_quick_connect")
    return module, module.IOPS_OT_Mesh_Quick_Connect, "iops.mesh_quick_connect"


def test_quick_connect_handlers_go_on_every_exit():
    module, cls, idname = _quick_connect()
    for exit_key, expected in (("SPACE", {"FINISHED"}), ("ESC", {"CANCELLED"}), ("RIGHTMOUSE", {"CANCELLED"})):
        op, ctx, rec = _open(module, cls, idname, "none", QC_HANDLERS)
        assert op.modal(ctx, _event(exit_key)) == expected, exit_key
        _closed(op, rec, QC_NAMES)
    op, ctx, rec = _open(module, cls, idname, "none", QC_HANDLERS)
    module._purge_handles()
    assert rec.handles() <= set(rec.removed)
    op.remove_handler(ctx)
    rec.undo()


def test_quick_connect_draws_a_connection_on_the_mesh_in_world_space():
    module, cls, idname = _quick_connect()
    op, ctx, rec = _open(module, cls, idname, "none", QC_HANDLERS)
    try:
        obj = bpy.context.active_object
        obj.matrix_world.translation = (5.0, 0.0, 0.0)
        bpy.context.view_layer.update()
        op.start_vert_index, op.end_vert_index = 0, 1
        # update_points projects too: with no region give it a stand-in projection
        from bpy_extras import view3d_utils
        real = view3d_utils.location_3d_to_region_2d
        view3d_utils.location_3d_to_region_2d = lambda _r, _v, co: (co.x * 100.0, co.y * 100.0)
        try:
            op.update_points(ctx)
        finally:
            view3d_utils.location_3d_to_region_2d = real
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        assert op.start_point_3d == obj.matrix_world @ bm.verts[0].co
        assert op.end_point_3d == obj.matrix_world @ bm.verts[1].co
        assert op._connecting_in_world()
        # the end still following the mouse: a screen-space guide, not drawn on the mesh
        op.end_vert_index = -1
        op.end_point_2d = op.end_point_3d = None
        assert not op._connecting_in_world()
        op.draw_callback_view(ctx)                   # no GPU in the background: fails inside, never raises
        op.draw_callback_px(ctx)
    finally:
        op.remove_handler(ctx)
        _closed(op, rec, QC_NAMES)


def _shear():
    module = _module("mesh_shear")
    return module, module.IOPS_OT_mesh_shear, "iops.mesh_shear"


def test_shear_handlers_go_on_every_exit():
    module, cls, idname = _shear()
    for exit_key, expected in (("ESC", {"CANCELLED"}), ("RIGHTMOUSE", {"CANCELLED"}), ("RET", {"FINISHED"})):
        op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
        assert op.modal(ctx, _event(exit_key)) == expected, (exit_key, op.reports)
        _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    _raising(op)
    _modal_raises(op, ctx)
    _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    module._purge_handles()
    assert rec.handles() <= set(rec.removed)
    op._finish(ctx)
    rec.undo()


def _hinge():
    module = _module("mesh_hinge")
    return module, module.IOPS_OT_mesh_hinge, "iops.mesh_hinge"


def test_hinge_handlers_go_on_every_exit():
    module, cls, idname = _hinge()
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    # Esc / RMB first release a locked axis or leave flush mode; with neither, it ends the run
    op.__dict__["_axis_locked"] = False
    op.__dict__["_flush_active"] = False
    assert op.modal(ctx, _event("ESC")) in ({"CANCELLED"}, {"FINISHED"}), op.reports
    _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    op.cancel(ctx)                                   # Blender cancelling the modal
    _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    _raising(op)
    _modal_raises(op, ctx)
    _closed(op, rec)
    op, ctx, rec = _open(module, cls, idname, "face", VIEW_PIXEL)
    module._purge_handles()
    assert rec.handles() <= set(rec.removed)
    op._finish(ctx)
    rec.undo()


TESTS = [
    test_inset_handlers_go_on_every_exit,
    test_inset_purge_removes_both,
    test_straight_bevel_handlers_go_on_every_exit,
    test_quick_connect_handlers_go_on_every_exit,
    test_quick_connect_draws_a_connection_on_the_mesh_in_world_space,
    test_shear_handlers_go_on_every_exit,
    test_hinge_handlers_go_on_every_exit,
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
