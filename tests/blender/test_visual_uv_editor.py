"""Headless test of Visual UV's UV Editor mode and its pivot picked by a click
on a gizmo point. The real invoke() / modal() run on a stand-in operator
instance with a fake Image Editor context (area, main region with a View2D,
space, window manager): islands from the UV selection, picking in UV space,
the gizmo on the View2D mapping, G / R / S moving the islands with the mouse,
click versus drag on a gizmo point, P cycling, Esc putting everything back.
Drawing is not exercised (no GPU in the background). Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_visual_uv_editor.py

(with every BLENDER_USER_* variable pointed at scratch directories).

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import inspect
import math
import os
import sys
import traceback
from types import SimpleNamespace

import bmesh
import bpy
from mathutils import Matrix, Vector

ADDON = "InteractionOps"
HERE = os.path.dirname(os.path.abspath(__file__))

mod = None          # operators.mesh_visual_uv
CLS = None

# UV rectangles of the three quads (each its own island): u0, v0, u1, v1
RECTS = [(0.1, 0.1, 0.3, 0.3), (0.5, 0.5, 0.7, 0.9), (0.8, 0.1, 0.9, 0.2)]
ZOOM = 500.0
OX, OY = 100.0, 50.0             # region pixel of UV (0, 0)


def enable_addon():
    global mod, CLS
    repo_root = os.path.dirname(os.path.dirname(HERE))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.operators import mesh_visual_uv
    mod = mesh_visual_uv
    CLS = mesh_visual_uv.IOPS_OT_MeshVisualUV
    # The operator reaches bpy.context.window (cursor), which a background
    # session does not have: give the module a bpy whose context has one.
    mod.bpy = _BpyProxy()


# --- fakes -------------------------------------------------------------------------------------------------------

class FakeWindow:
    def cursor_modal_set(self, _c):
        pass

    def cursor_modal_restore(self):
        pass

    def cursor_warp(self, _x, _y):
        pass


WINDOW = FakeWindow()


class _CtxProxy:
    def __getattr__(self, name):
        if name == "window":
            return WINDOW
        return getattr(bpy.context, name)


class _BpyProxy:
    context = _CtxProxy()

    def __getattr__(self, name):
        return getattr(bpy, name)


class FakeView2D:
    def __init__(self, ox, oy, zoom):
        self.ox, self.oy, self.zoom = ox, oy, zoom

    def region_to_view(self, x, y):
        return ((x - self.ox) / self.zoom, (y - self.oy) / self.zoom)

    def view_to_region(self, u, v, clip=True):
        return (int(round(self.ox + u * self.zoom)), int(round(self.oy + v * self.zoom)))


class FakeRegion:
    type = "WINDOW"

    def __init__(self):
        self.x, self.y, self.width, self.height = 300, 200, 800, 600
        self.view2d = FakeView2D(OX, OY, ZOOM)

    def as_pointer(self):
        return id(self)

    def tag_redraw(self):
        pass


class FakeArea:
    def __init__(self, region, type_="IMAGE_EDITOR"):
        self.type = type_
        self.regions = [SimpleNamespace(type="HEADER"), region]

    def tag_redraw(self):
        pass


class FakeWM:
    def __init__(self):
        self.modal = None
        self.windows = []

    def modal_handler_add(self, op):
        self.modal = op

    def event_timer_add(self, _t, window=None):
        return object()

    def event_timer_remove(self, _t):
        pass


class FakeWorkspace:
    def status_text_set(self, _t):
        pass


class FakeRV3D:
    """Orthographic top view of the z = 0 plane: world (x, y) -> region pixel
    (160 + 160 x, 320 + 160 y) in an 800 x 800 region."""

    def __init__(self):
        near, far = 0.1, 100.0
        self.view_matrix = Matrix.Translation((0.0, 0.0, -10.0))
        proj = Matrix(((0.4, 0.0, 0.0, -0.6),
                       (0.0, 0.4, 0.0, -0.2),
                       (0.0, 0.0, -2.0 / (far - near), -(far + near) / (far - near)),
                       (0.0, 0.0, 0.0, 1.0)))
        self.perspective_matrix = proj @ self.view_matrix
        self.is_perspective = False
        self.view_perspective = "ORTHO"
        self.view_distance = 10.0


def wpx(x, y):
    """Region pixel of world point (x, y, 0) in the fake viewport."""
    return (160.0 + 160.0 * x, 320.0 + 160.0 * y)


def make_viewport_context(obj):
    region = FakeRegion()
    region.x = region.y = 0
    region.width = region.height = 800
    return SimpleNamespace(
        active_object=obj, area=FakeArea(region, "VIEW_3D"), region=region, region_data=FakeRV3D(),
        scene=bpy.context.scene,
        space_data=SimpleNamespace(type="VIEW_3D", overlay=SimpleNamespace(show_overlays=True)),
        window_manager=FakeWM(), workspace=FakeWorkspace(), window=WINDOW,
        preferences=bpy.context.preferences)


def start_viewport(obj):
    ctx = make_viewport_context(obj)
    op = StandIn()
    assert CLS.poll(ctx)
    result = CLS.invoke(op, ctx, ev(ctx, "NONE", "NOTHING", 0, 0))
    assert result == {"RUNNING_MODAL"}, (result, op.reports)
    return op, ctx


def make_context(obj):
    region = FakeRegion()
    return SimpleNamespace(
        active_object=obj, area=FakeArea(region), region=region, region_data=None,
        scene=bpy.context.scene,
        space_data=SimpleNamespace(type="IMAGE_EDITOR", show_uvedit=True, cursor_location=[0.25, 0.75]),
        window_manager=FakeWM(), workspace=FakeWorkspace(), window=WINDOW,
        preferences=bpy.context.preferences)


def ev(ctx, type_, value="PRESS", x=0.0, y=0.0, shift=False, ctrl=False, alt=False):
    r = ctx.region
    return SimpleNamespace(type=type_, value=value, mouse_x=r.x + x, mouse_y=r.y + y,
                           mouse_region_x=x, mouse_region_y=y,
                           shift=shift, ctrl=ctrl, alt=alt, oskey=False)


class StandIn:
    """An operator instance stand-in: RNA defaults, the class's methods."""

    def __init__(self):
        rna = bpy.ops.iops.mesh_visual_uv.get_rna_type()
        self.__dict__["properties"] = SimpleNamespace(bl_rna=rna)
        for prop in rna.properties:
            if prop.identifier == "rna_type" or prop.type in {"POINTER", "COLLECTION"}:
                continue
            self.__dict__[prop.identifier] = prop.default
        self.__dict__["reports"] = []
        self.__dict__["_handle_3d"] = self.__dict__["_handle_pixel"] = None
        self.__dict__["_handle_shortcuts"] = self.__dict__["_timer"] = None

    def report(self, _kinds, message):
        self.reports.append(message)

    def __getattr__(self, name):
        try:
            attr = inspect.getattr_static(CLS, name)
        except AttributeError:
            raise AttributeError(name) from None
        if hasattr(attr, "__get__"):
            return attr.__get__(self, CLS)
        return attr


# --- scene -------------------------------------------------------------------------------------------------------

def make_mesh(uv_selected=(0, 1), sync=False):
    """Three quads in a row, each its own UV island (RECTS), all faces
    selected, in Edit Mode; faces in `uv_selected` are UV-selected."""
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    verts = [(x, y, 0.0) for y in (0, 1) for x in range(4)]
    faces = [(i, i + 1, i + 5, i + 4) for i in range(3)]
    me = bpy.data.meshes.new("vuv")
    me.from_pydata(verts, [], faces)
    me.uv_layers.new(name="UVMap")
    obj = bpy.data.objects.new("vuv", me)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # Before the flags: setting UV sync re-derives the whole UV selection.
    bpy.context.scene.tool_settings.use_uv_select_sync = sync
    bm = bmesh.from_edit_mesh(me)
    uv = bm.loops.layers.uv.verify()
    bm.faces.ensure_lookup_table()
    for f, (u0, v0, u1, v1) in zip(bm.faces, RECTS):
        for lp, co in zip(f.loops, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))):
            lp[uv].uv = co
        state = f.index in uv_selected
        f.uv_select = state
        for lp in f.loops:
            lp.uv_select_vert = state
            lp.uv_select_edge = state
    bmesh.update_edit_mesh(me)
    return obj


def bm_of(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    return bm, bm.loops.layers.uv.verify()


def face_uvs(obj, fi):
    bm, uv = bm_of(obj)
    return [lp[uv].uv.copy() for lp in bm.faces[fi].loops]


def bbox(uvs):
    return (min(p.x for p in uvs), min(p.y for p in uvs), max(p.x for p in uvs), max(p.y for p in uvs))


def px(u, v):
    return (OX + u * ZOOM, OY + v * ZOOM)


def start(obj):
    ctx = make_context(obj)
    op = StandIn()
    assert CLS.poll(ctx), "poll refuses an Image Editor showing UVs"
    result = CLS.invoke(op, ctx, ev(ctx, "NONE", "NOTHING", 0, 0))
    assert result == {"RUNNING_MODAL"}, (result, op.reports)
    return op, ctx


def send(op, ctx, *events):
    out = None
    for e in events:
        out = CLS.modal(op, ctx, e)
    return out


def island_of_face(op, fi):
    return next(i for i, isl in enumerate(op.islands) if fi in isl)


def close(a, b, tol=1e-5):
    return all(abs(x - y) < tol for x, y in zip(a, b))


# --- tests -------------------------------------------------------------------------------------------------------

def test_poll():
    obj = make_mesh()
    ctx = make_context(obj)
    assert CLS.poll(ctx)
    ctx.space_data.show_uvedit = False
    assert not CLS.poll(ctx), "an Image Editor without UVs is refused"
    ctx.area.type = "VIEW_3D"
    assert CLS.poll(ctx), "the 3D viewport still works"
    ctx.area.type = "NODE_EDITOR"
    assert not CLS.poll(ctx)


def test_session_is_the_uv_selection():
    obj = make_mesh(uv_selected=(0, 1))
    op, ctx = start(obj)
    try:
        assert op._uv_mode and op._space_type is bpy.types.SpaceImageEditor
        assert sorted(min(isl) for isl in op.islands) == [0, 1], op.islands
        bm, _uv = bm_of(obj)
        # Sync off: the mesh selection is what the editor shows, untouched.
        assert all(f.select for f in bm.faces)
        assert [f.uv_select for f in bm.faces] == [True, True, False]
        assert op.uv_cursor.to_tuple() == (0.25, 0.75), "the UV cursor is the editor's 2D cursor"
        assert op._pick_bvh is None
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_nothing_selected_cancels():
    obj = make_mesh(uv_selected=())
    ctx = make_context(obj)
    op = StandIn()
    assert CLS.invoke(op, ctx, ev(ctx, "NONE", "NOTHING")) == {"CANCELLED"}
    assert "No UV islands selected" in op.reports, op.reports


def test_gizmo_follows_pan_and_zoom():
    obj = make_mesh()
    op, ctx = start(obj)
    try:
        op.active_island_idx = island_of_face(op, 0)
        h = mod._compute_screen_handles(op, ctx)
        assert close(h["BL"], (px(0.1, 0.1)[0] - 14, px(0.1, 0.1)[1] - 14))
        assert close(h["TR"], (px(0.3, 0.3)[0] + 14, px(0.3, 0.3)[1] + 14))
        assert close(h["_u_dir"], (0.2 * ZOOM, 0.0)) and close(h["_v_dir"], (0.0, 0.2 * ZOOM))
        ctx.region.view2d.ox += 37.0          # pan
        ctx.region.view2d.zoom = 800.0        # zoom
        h2 = mod._compute_screen_handles(op, ctx)
        assert close(h2["BL"], (OX + 37.0 + 0.1 * 800.0 - 14, OY + 0.1 * 800.0 - 14))
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_hover_and_click_pick_islands_in_uv_space():
    obj = make_mesh(uv_selected=(0, 1))
    op, ctx = start(obj)
    try:
        # Hover over island 1's interior (not on a handle of the active one).
        x, y = px(0.6, 0.6)
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y))
        assert op.hover_island_idx == island_of_face(op, 1)
        # Plain click on the unselected island 2: it becomes the only one.
        op.active_island_idx = island_of_face(op, 1)
        x, y = px(0.85, 0.15)
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y))
        assert op.hover_pick is None, "clean view (the default) draws no preview"
        send(op, ctx, ev(ctx, "Q", "PRESS", x, y), ev(ctx, "MOUSEMOVE", "NOTHING", x, y))
        assert op.hover_pick is not None, "the island under the mouse is previewed"
        send(op, ctx, ev(ctx, "LEFTMOUSE", "PRESS", x, y))
        assert [min(i) for i in op.islands] == [2], op.islands
        bm, _uv = bm_of(obj)
        assert [f.uv_select for f in bm.faces] == [False, False, True]
        assert all(f.select for f in bm.faces), "sync off: the shown faces stay selected"
        # Shift + click adds island 0, Shift + click again removes it
        # (off its centre: the active island's centre is a gizmo point).
        x, y = px(0.13, 0.14)
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "LEFTMOUSE", "PRESS", x, y, shift=True))
        assert sorted(min(i) for i in op.islands) == [0, 2]
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "LEFTMOUSE", "PRESS", x, y, shift=True))
        assert [min(i) for i in op.islands] == [2]
        # Empty space: nothing changes.
        x, y = px(0.45, 0.05)
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "LEFTMOUSE", "PRESS", x, y))
        assert [min(i) for i in op.islands] == [2]
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_grab_moves_islands_with_the_mouse():
    obj = make_mesh(uv_selected=(0, 1))
    op, ctx = start(obj)
    before0, before1 = face_uvs(obj, 0), face_uvs(obj, 1)
    x, y = 400.0, 300.0
    send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "G", "PRESS", x, y))
    assert op.state == "GRAB"
    send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x + 50, y - 25))
    d = Vector((50 / ZOOM, -25 / ZOOM))
    for before, fi in ((before0, 0), (before1, 1)):
        for a, b in zip(before, face_uvs(obj, fi)):
            assert close(b, a + d), (fi, a, b)
    # X lock keeps only the u part.
    send(op, ctx, ev(ctx, "X", "PRESS", x + 50, y - 25), ev(ctx, "MOUSEMOVE", "NOTHING", x + 50, y - 25))
    for a, b in zip(before0, face_uvs(obj, 0)):
        assert close(b, (a.x + 50 / ZOOM, a.y)), (a, b)
    send(op, ctx, ev(ctx, "LEFTMOUSE", "PRESS", x + 50, y - 25))
    assert op.state == "IDLE" and len(op.undo_stack) == 1
    send(op, ctx, ev(ctx, "Z", "PRESS", x, y, ctrl=True))
    assert all(close(a, b) for a, b in zip(before0, face_uvs(obj, 0))), "Ctrl+Z undoes the move"
    send(op, ctx, ev(ctx, "RET"))


def test_click_on_gizmo_point_picks_the_pivot():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        before = face_uvs(obj, 0)
        h = mod._compute_screen_handles(op, ctx)
        tl = h["TL"]
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", tl.x, tl.y), ev(ctx, "LEFTMOUSE", "PRESS", tl.x, tl.y))
        assert op._press is not None and op.state == "IDLE", "a press on a point waits for click or drag"
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", tl.x + 1, tl.y + 1),
             ev(ctx, "LEFTMOUSE", "RELEASE", tl.x + 1, tl.y + 1))
        assert op.pivot_mode == "ANCHOR" and op.pivot_anchor == "TL"
        assert op._hud is not None
        row = next(p for s in op._hud.param_sections for p in s.params if p.name == "Pivot (P)")
        assert row.value_text() == "Top Left Corner", row.value_text()
        assert all(close(a, b) for a, b in zip(before, face_uvs(obj, 0))), "a click moves nothing"
        assert mod._pivot_anchor_screen(op, h) == tl, "the picked point is drawn on its handle"
        # P: Center -> Cursor -> Anchor -> Center
        seq = []
        for _ in range(3):
            send(op, ctx, ev(ctx, "P", "PRESS", 10, 10))
            seq.append(op.pivot_mode)
        assert seq == ["CENTER", "CURSOR", "ANCHOR"], seq
        # The centre point returns to the Center pivot.
        c = h["_C"]
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", c.x, c.y), ev(ctx, "LEFTMOUSE", "PRESS", c.x, c.y),
             ev(ctx, "LEFTMOUSE", "RELEASE", c.x, c.y))
        assert op.pivot_mode == "CENTER" and op.pivot_anchor == "TL"
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_rotate_spins_around_the_picked_point():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        op.pivot_mode, op.pivot_anchor = "ANCHOR", "BR"
        before = face_uvs(obj, 0)
        pivot = Vector((0.3, 0.1))                      # BR of island 0
        cx, cy = px(*pivot)
        r = 120.0
        x0, y0 = cx + r, cy                            # angle 0 around the pivot
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x0, y0), ev(ctx, "R", "PRESS", x0, y0))
        assert op.state == "ROTATE"
        assert close(op.drag_center_screen, (cx, cy)), "angles are measured around the picked point"
        x1, y1 = cx, cy + r                            # +90 degrees, counter-clockwise
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x1, y1))
        ang = math.radians(90.0)
        for a, b in zip(before, face_uvs(obj, 0)):
            d = a - pivot
            exp = pivot + Vector((d.x * math.cos(ang) - d.y * math.sin(ang),
                                  d.x * math.sin(ang) + d.y * math.cos(ang)))
            assert close(b, exp), (a, b, exp)
        send(op, ctx, ev(ctx, "RIGHTMOUSE", "PRESS", x1, y1))
        assert all(close(a, b) for a, b in zip(before, face_uvs(obj, 0))), "RMB cancels the rotation"
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_anchor_follows_the_island():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        op.pivot_mode, op.pivot_anchor = "ANCHOR", "TL"
        idata = op.islands_data[op.active_island_idx]
        assert close(mod._get_pivot_uv(op, idata), (0.1, 0.3))
        x, y = 400.0, 300.0
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "G", "PRESS", x, y),
             ev(ctx, "MOUSEMOVE", "NOTHING", x + 100, y), ev(ctx, "LEFTMOUSE", "PRESS", x + 100, y))
        idata = op.islands_data[op.active_island_idx]
        assert close(mod._get_pivot_uv(op, idata), (0.1 + 100 / ZOOM, 0.3)), mod._get_pivot_uv(op, idata)
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_drag_on_side_handle_scales_and_tracks_the_mouse():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        h = mod._compute_screen_handles(op, ctx)
        rh = h["R"]
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", rh.x, rh.y), ev(ctx, "LEFTMOUSE", "PRESS", rh.x, rh.y))
        threshold = bpy.context.preferences.inputs.drag_threshold_mouse
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", rh.x + threshold, rh.y))
        assert op._press is not None and op.state == "IDLE", "within the threshold it is still a click"
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", rh.x + 50, rh.y))
        assert op.state == "HANDLE_SCALE" and op._press is None
        u0, v0, u1, v1 = bbox(face_uvs(obj, 0))
        assert close((u0, v0, v1), (0.1, 0.1, 0.3)), "the left side is the pivot"
        assert abs(u1 - (0.3 + 50 / ZOOM)) < 1e-5, ("the right side follows the mouse", u1)
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", rh.x + 80, rh.y))
        u1 = bbox(face_uvs(obj, 0))[2]
        assert abs(u1 - (0.3 + 80 / ZOOM)) < 1e-5, u1
        send(op, ctx, ev(ctx, "LEFTMOUSE", "RELEASE", rh.x + 80, rh.y))
        assert op.state == "IDLE" and len(op.undo_stack) == 1
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_drag_on_centre_moves_without_a_jump():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        before = face_uvs(obj, 0)
        c = mod._compute_screen_handles(op, ctx)["_C"]
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", c.x, c.y), ev(ctx, "LEFTMOUSE", "PRESS", c.x, c.y),
             ev(ctx, "MOUSEMOVE", "NOTHING", c.x + 30, c.y + 20))
        assert op.state == "GRAB"
        for a, b in zip(before, face_uvs(obj, 0)):
            assert close(b, (a.x + 30 / ZOOM, a.y + 20 / ZOOM)), (a, b)
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_scale_key_grows_the_island():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        cx, cy = px(0.2, 0.2)                          # island centre
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", cx + 100, cy), ev(ctx, "S", "PRESS", cx + 100, cy),
             ev(ctx, "MOUSEMOVE", "NOTHING", cx + 200, cy))
        u0, v0, u1, v1 = bbox(face_uvs(obj, 0))
        assert close((u1 - u0, v1 - v0), (0.4, 0.4)), "S scales the island up as the mouse moves out"
        assert close(((u0 + u1) / 2, (v0 + v1) / 2), (0.2, 0.2))
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_c_snaps_the_editor_cursor_and_esc_restores_everything():
    obj = make_mesh(uv_selected=(0, 1))
    op, ctx = start(obj)
    before = [face_uvs(obj, i) for i in range(3)]
    h = mod._compute_screen_handles(op, ctx)
    tr = h["TR"]
    ai = op.active_island_idx
    send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", tr.x + 3, tr.y + 3), ev(ctx, "C", "PRESS", tr.x + 3, tr.y + 3))
    rect = RECTS[min(op.islands[ai])]
    assert op.pivot_mode == "CURSOR"
    assert close(ctx.space_data.cursor_location, (rect[2], rect[3])), ctx.space_data.cursor_location
    # Change the selection, move an island, then cancel.
    x, y = px(0.85, 0.15)
    send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "LEFTMOUSE", "PRESS", x, y),
         ev(ctx, "G", "PRESS", x, y), ev(ctx, "MOUSEMOVE", "NOTHING", x + 40, y),
         ev(ctx, "LEFTMOUSE", "PRESS", x + 40, y))
    assert send(op, ctx, ev(ctx, "ESC")) == {"CANCELLED"}
    for fi in range(3):
        assert all(close(a, b) for a, b in zip(before[fi], face_uvs(obj, fi))), fi
    bm, _uv = bm_of(obj)
    assert [f.uv_select for f in bm.faces] == [True, True, False]
    assert [lp.uv_select_vert for lp in bm.faces[2].loops] == [False] * 4
    assert all(f.select for f in bm.faces)
    assert close(ctx.space_data.cursor_location, (0.25, 0.75)), "Esc puts the 2D cursor back"


def test_viewport_only_keys_are_ignored():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        before = face_uvs(obj, 0)
        x, y = px(0.2, 0.2)
        for key, mods in (("U", {}), ("U", {"ctrl": True}), ("M", {}), ("E", {}), ("A", {}), ("T", {}),
                          ("V", {}), ("Q", {"shift": True})):
            send(op, ctx, ev(ctx, key, "PRESS", x, y, **mods))
            assert op.state == "IDLE", (key, op.state)
        assert all(close(a, b) for a, b in zip(before, face_uvs(obj, 0)))
        assert not op._suspended_mods
        # Clean view: on by default, Q toggles the island fills. The fake
        # space has no overlay: touching it would raise.
        assert op._clean_view is True
        send(op, ctx, ev(ctx, "Q", "PRESS", x, y))
        assert op._clean_view is False and op.state == "IDLE"
        send(op, ctx, ev(ctx, "Q", "PRESS", x, y))
        assert op._clean_view is True
        help_keys = {it.key for s in op._help.sections for it in s.items}
        assert "Click Gizmo Point" in help_keys and "Q" in help_keys
        assert not ({"A", "E", "M", "T", "V"} & help_keys), help_keys
        names = {p.name for s in op._hud.param_sections for p in s.params}
        assert "Unwrap Method (Shift + U)" not in names and "Modifiers Paused (Shift + Q)" not in names
        # F flips, N randomizes, I toggles the scope: still there.
        send(op, ctx, ev(ctx, "F", "PRESS", x, y))
        assert len(op.undo_stack) == 1
        send(op, ctx, ev(ctx, "I", "PRESS", x, y))
        assert op.transform_scope == "ACTIVE"
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_fit_to_active():
    obj = make_mesh(uv_selected=(0, 1))
    op, ctx = start(obj)
    try:
        op.active_island_idx = island_of_face(op, 1)
        send(op, ctx, ev(ctx, "D", "PRESS", 10, 10))
        u0, v0, u1, v1 = bbox(face_uvs(obj, 0))
        assert close((u1 - u0, v1 - v0), (0.2, 0.4)), (u1 - u0, v1 - v0)
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_sync_on_mirrors_the_mesh_selection():
    obj = make_mesh(uv_selected=(0, 1), sync=True)
    bm, _uv = bm_of(obj)
    for f in bm.faces:
        f.select_set(f.index in (0, 1))
    bmesh.update_edit_mesh(obj.data)
    op, ctx = start(obj)
    try:
        assert sorted(min(isl) for isl in op.islands) == [0, 1]
        x, y = px(0.85, 0.15)                          # unselected, still shown with sync on
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "LEFTMOUSE", "PRESS", x, y, shift=True))
        assert sorted(min(isl) for isl in op.islands) == [0, 1, 2]
        bm, _uv = bm_of(obj)
        assert all(f.select for f in bm.faces)
        x, y = px(0.13, 0.14)                          # plain click: island 0 only
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "LEFTMOUSE", "PRESS", x, y))
        assert [min(isl) for isl in op.islands] == [0], op.islands
        bm, _uv = bm_of(obj)
        assert [f.select for f in bm.faces] == [True, False, False]
    finally:
        send(op, ctx, ev(ctx, "ESC"))
        bpy.context.scene.tool_settings.use_uv_select_sync = False
    bm, _uv = bm_of(obj)
    assert [f.select for f in bm.faces] == [True, True, False], "Esc puts the mesh selection back"


def test_cursor_pivot_measures_around_the_cursor():
    obj = make_mesh(uv_selected=(0,))
    op, ctx = start(obj)
    try:
        op.pivot_mode = "CURSOR"                      # 2D cursor at (0.25, 0.75)
        x, y = 600.0, 200.0
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "R", "PRESS", x, y))
        assert close(op.drag_center_screen, px(0.25, 0.75), 1e-3), (tuple(op.drag_center_screen), px(0.25, 0.75))
        assert close(op.transform_pivot_uv, (0.25, 0.75))
    finally:
        send(op, ctx, ev(ctx, "ESC"))


# --- the same pivot features in the 3D viewport ------------------------------------------------------------------

def test_viewport_click_on_corner_picks_the_pivot():
    obj = make_mesh()
    op, ctx = start_viewport(obj)
    try:
        assert not op._uv_mode and ctx.space_data.overlay.show_overlays is False
        op.active_island_idx = island_of_face(op, 0)
        before = face_uvs(obj, 0)
        tl = mod._compute_screen_handles(op, ctx)["TL"]
        assert close(tl, (wpx(0, 1)[0] - 14, wpx(0, 1)[1] + 14), 1e-3), tl
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", tl.x, tl.y), ev(ctx, "LEFTMOUSE", "PRESS", tl.x, tl.y),
             ev(ctx, "LEFTMOUSE", "RELEASE", tl.x, tl.y))
        assert (op.pivot_mode, op.pivot_anchor) == ("ANCHOR", "TL")
        assert all(close(a, b) for a, b in zip(before, face_uvs(obj, 0)))
        # A drag on the same point still scales from the opposite corner.
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", tl.x, tl.y), ev(ctx, "LEFTMOUSE", "PRESS", tl.x, tl.y),
             ev(ctx, "MOUSEMOVE", "NOTHING", tl.x - 40, tl.y + 40))
        assert op.state == "HANDLE_SCALE" and op.scale_handle_name == "TL"
        send(op, ctx, ev(ctx, "RIGHTMOUSE", "PRESS", tl.x - 40, tl.y + 40))
        assert all(close(a, b) for a, b in zip(before, face_uvs(obj, 0)))
    finally:
        send(op, ctx, ev(ctx, "ESC"))
    assert ctx.space_data.overlay.show_overlays is True


def test_viewport_rotate_measures_around_the_picked_point():
    obj = make_mesh()
    op, ctx = start_viewport(obj)
    try:
        op.active_island_idx = island_of_face(op, 0)
        op.pivot_mode, op.pivot_anchor = "ANCHOR", "TL"
        x, y = 600.0, 700.0
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "R", "PRESS", x, y))
        assert op.state == "ROTATE"
        # The UV corner (0.1, 0.3) lies on world (0, 1): angles go around it.
        assert close(op.drag_center_screen, wpx(0, 1), 1e-3), tuple(op.drag_center_screen)
        assert close(op.transform_pivot_uv, (0.1, 0.3))
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x - 300, y + 100))
        tl = [p for p in face_uvs(obj, 0) if close(p, (0.1, 0.3), 1e-4)]
        assert tl, "the picked corner stays put while the island turns"
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_viewport_cursor_pivot_measures_around_the_cursor():
    obj = make_mesh()
    op, ctx = start_viewport(obj)
    try:
        op.active_island_idx = island_of_face(op, 0)
        tr = mod._compute_screen_handles(op, ctx)["TR"]
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", tr.x + 2, tr.y + 2), ev(ctx, "C", "PRESS", tr.x + 2, tr.y + 2))
        assert op.pivot_mode == "CURSOR" and close(op.uv_cursor, (0.3, 0.3))
        x, y = 700.0, 700.0
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "R", "PRESS", x, y))
        # Around the cursor's point on the mesh, not the island centre (240, 400).
        assert close(op.drag_center_screen, wpx(1, 1), 1e-3), tuple(op.drag_center_screen)
    finally:
        send(op, ctx, ev(ctx, "ESC"))


def test_viewport_grab_keeps_its_direction():
    """In the viewport the texture follows the mouse, so the UVs move the
    other way (unchanged by the UV Editor mode)."""
    obj = make_mesh()
    op, ctx = start_viewport(obj)
    try:
        op.active_island_idx = island_of_face(op, 0)
        before = face_uvs(obj, 0)
        x, y = 700.0, 100.0
        send(op, ctx, ev(ctx, "MOUSEMOVE", "NOTHING", x, y), ev(ctx, "G", "PRESS", x, y),
             ev(ctx, "MOUSEMOVE", "NOTHING", x + 40, y))
        for a, b in zip(before, face_uvs(obj, 0)):
            assert close(b, (a.x - 0.05, a.y)), (a, b)
    finally:
        send(op, ctx, ev(ctx, "ESC"))


TESTS = [
    test_viewport_click_on_corner_picks_the_pivot,
    test_viewport_rotate_measures_around_the_picked_point,
    test_viewport_cursor_pivot_measures_around_the_cursor,
    test_viewport_grab_keeps_its_direction,
    test_poll,
    test_session_is_the_uv_selection,
    test_nothing_selected_cancels,
    test_gizmo_follows_pan_and_zoom,
    test_hover_and_click_pick_islands_in_uv_space,
    test_grab_moves_islands_with_the_mouse,
    test_click_on_gizmo_point_picks_the_pivot,
    test_rotate_spins_around_the_picked_point,
    test_anchor_follows_the_island,
    test_drag_on_side_handle_scales_and_tracks_the_mouse,
    test_drag_on_centre_moves_without_a_jump,
    test_scale_key_grows_the_island,
    test_c_snaps_the_editor_cursor_and_esc_restores_everything,
    test_viewport_only_keys_are_ignored,
    test_fit_to_active,
    test_sync_on_mirrors_the_mesh_selection,
    test_cursor_pivot_measures_around_the_cursor,
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
