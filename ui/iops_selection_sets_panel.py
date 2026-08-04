"""iOps Selection Sets panel: UIList over a WindowManager mirror.

The mirror is UI-only state rebuilt from the source of truth (mesh
attributes / scene collection). Panel draw() callbacks may not write to
ID data, so rebuilds run from app handlers (depsgraph/undo/redo/load)
and from the operators via tag_mirror_dirty(); a cheap signature check
keeps the handler no-op on unrelated updates.
"""
import bpy
import bmesh
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..operators import mesh_selection_sets as ss
from .draw import Role, draw_scope, get_theme, safe_handler_add, \
    safe_handler_remove

_last_sig = None
_dirty = True
_syncing = False


def tag_mirror_dirty():
    global _dirty
    _dirty = True
    # every mutating set operator lands here — refresh the preview too.
    _PREVIEW["dirty"] = True
    # Rebuild synchronously: scene-collection edits (object-mode sets)
    # never fire a depsgraph update, so waiting for the resync handler
    # leaves the UIList stale until the next unrelated event.
    try:
        rebuild_mirror(bpy.context)
    except Exception as e:
        print(f"IOPS selection sets: mirror rebuild failed: {e}")
    # ...and wake the viewports so panel + preview redraw now.
    wm = bpy.context.window_manager
    if wm is not None:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


def _mirror_name_update(self, context):
    """Write-through rename from the UIList double-click editor."""
    if _syncing:
        return
    old = self.get("_prev_name", "")
    new = ss.sanitize_set_name(self.name)
    if not old or old == new:
        return
    if self.flags == "OBJ":
        taken = [s.name for s in context.scene.iops_selection_sets
                 if s.name != old]
        new = ss.unique_name(new, taken)
        ss.scene_rename_set(context.scene, old, new)
    else:
        taken = [n for n in ss.all_edit_set_names(context) if n != old]
        new = ss.unique_name(new, taken)
        for obj, bm in ss.edit_meshes(context):
            ss.bm_rename_set(bm, old, new)
            bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                                   destructive=False)
    if old in preview_names():
        _preview_renamed(old, new)
    self["name"] = new          # raw write: no update recursion
    self["_prev_name"] = new
    # self is the same PropertyGroup item being renamed, so `checked`
    # survives in place; rebuild_mirror() re-keys keep_checked by this
    # already-updated name, so the row's checked state carries over.
    tag_mirror_dirty()


class IOPS_SS_MirrorItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(update=_mirror_name_update)
    flags: bpy.props.StringProperty()   # subset of "VEF", or "OBJ"
    count: bpy.props.IntProperty()
    total: bpy.props.IntProperty()
    checked: bpy.props.BoolProperty(default=False)


def _signature(context):
    if context.mode == "EDIT_MESH":
        sig = ["EDIT"]
        for obj, bm in ss.edit_meshes(context):
            sig.append((obj.name, len(bm.verts), len(bm.edges),
                        len(bm.faces),
                        tuple(sorted(ss.bm_list_sets(bm).items()))))
        return tuple(sig)
    scene = context.scene
    return ("OBJECT", len(scene.objects),
            tuple((s.name, len(s.objects))
                  for s in scene.iops_selection_sets))


def rebuild_mirror(context, force=False):
    global _last_sig, _dirty, _syncing
    if context.mode not in {"EDIT_MESH", "OBJECT"}:
        return
    sig = _signature(context)
    if not force and not _dirty and sig == _last_sig:
        return
    _last_sig, _dirty = sig, False

    wm = context.window_manager
    keep_checked = {it.name: it.checked for it in wm.iops_ss_mirror}
    active_name = ""
    if 0 <= wm.iops_ss_index < len(wm.iops_ss_mirror):
        active_name = wm.iops_ss_mirror[wm.iops_ss_index].name

    rows = []
    if context.mode == "EDIT_MESH":
        merged = {}   # name -> [flags-set, count]
        for _obj, bm in ss.edit_meshes(context):
            for name, flags in ss.bm_list_sets(bm).items():
                entry = merged.setdefault(name, [set(), 0])
                entry[0].update(flags)
                entry[1] += ss.bm_set_count(bm, name)
        for name in sorted(merged):
            flags = "".join(d for d in "VEF" if d in merged[name][0])
            count = merged[name][1]
            rows.append((name, flags, count, count))
    else:
        for name, (alive, total) in sorted(
                ss.scene_list_sets(context.scene).items()):
            rows.append((name, "OBJ", alive, total))

    _syncing = True
    try:
        wm.iops_ss_mirror.clear()
        for name, flags, count, total in rows:
            it = wm.iops_ss_mirror.add()
            it["name"] = name           # raw: skip rename update
            it["_prev_name"] = name
            it.flags = flags
            it.count = count
            it.total = total
            it.checked = keep_checked.get(name, False)
            if name == active_name:
                wm.iops_ss_index = len(wm.iops_ss_mirror) - 1
        wm.iops_ss_index = min(wm.iops_ss_index,
                               max(0, len(wm.iops_ss_mirror) - 1))
    finally:
        _syncing = False


@persistent
def _iops_ss_resync(*_args):
    ctx = bpy.context
    if ctx.window_manager is None:
        return
    if _PREVIEW["handle"] is not None:
        _PREVIEW["dirty"] = True
    try:
        rebuild_mirror(ctx)
    except Exception as e:
        print(f"IOPS selection sets: mirror resync failed: {e}")


@persistent
def _iops_ss_force_resync(*_args):
    tag_mirror_dirty()
    _PREVIEW["dirty"] = True
    _iops_ss_resync()


# ----------------------------------------------------------------------
# Set preview overlay — POST_VIEW handler highlighting previewed sets.
# Any number of sets preview at once: the active list row draws in the
# theme's Active colors, the rest in Result Preview colors (same lazy-
# batch pattern as the non-planar overlay: handlers only mark dirty,
# draw rebuilds on demand).
# ----------------------------------------------------------------------
_PREVIEW = {"handle": None, "names": set(), "batches": {}, "dirty": True}

_BBOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7),
               (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
# bound_box corner quads per face (Blender's corner ordering)
_BBOX_QUADS = ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
               (3, 2, 6, 7), (0, 3, 7, 4), (1, 2, 6, 5))


def preview_names():
    return _PREVIEW["names"] if _PREVIEW["handle"] is not None else set()


def _preview_renamed(old, new):
    """Keep the overlay tracking sets through an operator rename."""
    if old in _PREVIEW["names"]:
        _PREVIEW["names"].discard(old)
        _PREVIEW["names"].add(new)
        _PREVIEW["dirty"] = True


def _preview_build_one(context, name, shader):
    """[(kind, batch)] for one set's members."""
    verts, edges, tris = [], [], []
    if context.mode == "EDIT_MESH":
        for obj, bm in ss.edit_meshes(context):
            member = ss.bm_set_membership(bm, name)
            if not member:
                continue
            mw = obj.matrix_world
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            for i in member.get("V", ()):
                verts.append(tuple(mw @ bm.verts[i].co))
            for i in member.get("E", ()):
                e = bm.edges[i]
                edges.append(tuple(mw @ e.verts[0].co))
                edges.append(tuple(mw @ e.verts[1].co))
            fset = member.get("F", set())
            if fset:
                for loops in bm.calc_loop_triangles():
                    if loops[0].face.index in fset:
                        tris.extend(tuple(mw @ lo.vert.co) for lo in loops)
                # outline member faces so the fill reads at low alpha
                bm.faces.ensure_lookup_table()
                seen = set()
                for i in fset:
                    for e in bm.faces[i].edges:
                        if e.index not in seen:
                            seen.add(e.index)
                            edges.append(tuple(mw @ e.verts[0].co))
                            edges.append(tuple(mw @ e.verts[1].co))
    elif context.mode == "OBJECT":
        for obj_name in ss.scene_membership(context.scene, name):
            obj = context.scene.objects.get(obj_name)
            if obj is None:
                continue
            mw = obj.matrix_world
            corners = [tuple(mw @ Vector(c)) for c in obj.bound_box]
            for a, b in _BBOX_EDGES:
                edges.append(corners[a])
                edges.append(corners[b])
            for a, b, c, d in _BBOX_QUADS:
                tris.extend((corners[a], corners[b], corners[c],
                             corners[a], corners[c], corners[d]))
    batches = []
    if tris:
        batches.append(
            ("TRIS", batch_for_shader(shader, 'TRIS', {"pos": tris})))
    if edges:
        batches.append(
            ("LINES", batch_for_shader(shader, 'LINES', {"pos": edges})))
    if verts:
        batches.append(
            ("POINTS", batch_for_shader(shader, 'POINTS', {"pos": verts})))
    return batches


def _preview_rebuild(context):
    _PREVIEW["dirty"] = False
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    _PREVIEW["batches"] = {
        name: _preview_build_one(context, name, shader)
        for name in _PREVIEW["names"]
    }


def _theme_colors(theme, active):
    """(point, line, fill) for an active or a background preview set."""
    if active:
        point = theme.color_for(Role.ACTIVE_POINT)
        line = theme.color_for(Role.ACTIVE_LINE)
        fill = theme.color_for(Role.GHOST_ACTIVE)
    else:
        point = theme.color_for(Role.PREVIEW_POINT)
        line = theme.color_for(Role.PREVIEW_LINE)
        fill = theme.color_for(Role.GHOST_PREVIEW)
    return point, line, fill


def _preview_draw():
    ctx = bpy.context
    if _PREVIEW["dirty"]:
        try:
            _preview_rebuild(ctx)
        except (ValueError, ReferenceError):
            _PREVIEW["batches"] = {}
    if not _PREVIEW["batches"]:
        return
    wm = ctx.window_manager
    mirror = getattr(wm, "iops_ss_mirror", None)
    active_name = ""
    if mirror is not None and 0 <= wm.iops_ss_index < len(mirror):
        active_name = mirror[wm.iops_ss_index].name
    theme = get_theme(ctx)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    with draw_scope(blend='ALPHA', depth='NONE', line_width=2.0,
                    point_size=6.0):
        # background sets first so the active one draws on top
        ordered = sorted(_PREVIEW["batches"].items(),
                         key=lambda kv: kv[0] == active_name)
        for name, batches in ordered:
            point, line, fill = _theme_colors(theme, name == active_name)
            colors = {"TRIS": fill, "LINES": line, "POINTS": point}
            for kind, batch in batches:
                shader.uniform_float("color", colors[kind])
                batch.draw(shader)


def _preview_disable():
    if _PREVIEW["handle"] is not None:
        safe_handler_remove(_PREVIEW["handle"], bpy.types.SpaceView3D,
                            "WINDOW")
    _PREVIEW.update(handle=None, names=set(), batches={}, dirty=True)


class IOPS_OT_SSPreview(bpy.types.Operator):
    """Highlight this set in the viewport — the active set in the
    theme's Active colors, others in Result Preview colors.
    Click again to hide. Alt: show/hide all sets"""
    bl_idname = "iops.ss_preview"
    bl_label = "Preview Selection Set"

    set_name: bpy.props.StringProperty(name="Set")

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def invoke(self, context, event):
        if event.alt:
            return bpy.ops.iops.ss_preview_all()
        return self.execute(context)

    def execute(self, context):
        names = _PREVIEW["names"]
        if self.set_name in names:
            names.discard(self.set_name)
            if not names:
                _preview_disable()
        else:
            names.add(self.set_name)
            if _PREVIEW["handle"] is None:
                _PREVIEW["handle"] = safe_handler_add(
                    bpy.types.SpaceView3D, _preview_draw, (), "WINDOW",
                    "POST_VIEW")
        _PREVIEW["dirty"] = True
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class IOPS_OT_SSPreviewAll(bpy.types.Operator):
    """Preview all selection sets; click again to hide them all"""
    bl_idname = "iops.ss_preview_all"
    bl_label = "Preview All Selection Sets"

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        if _PREVIEW["names"]:
            _preview_disable()
        else:
            names = {it.name for it in context.window_manager.iops_ss_mirror}
            if not names:
                return {"CANCELLED"}
            _PREVIEW["names"] = names
            _PREVIEW["dirty"] = True
            if _PREVIEW["handle"] is None:
                _PREVIEW["handle"] = safe_handler_add(
                    bpy.types.SpaceView3D, _preview_draw, (), "WINDOW",
                    "POST_VIEW")
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class IOPS_OT_SSRefresh(bpy.types.Operator):
    """Rebuild the selection sets list from mesh/scene data"""
    bl_idname = "iops.ss_refresh"
    bl_label = "Refresh Selection Sets"

    def execute(self, context):
        rebuild_mirror(context, force=True)
        return {"FINISHED"}


class IOPS_UL_SelectionSets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False)   # expands, left
        right = row.row(align=True)
        right.alignment = 'RIGHT'
        icons = {"V": "VERTEXSEL", "E": "EDGESEL", "F": "FACESEL",
                 "OBJ": "OBJECT_DATA"}
        flags = ["OBJ"] if item.flags == "OBJ" else list(item.flags)
        for f in flags:
            right.label(text="", icon=icons[f])
        stale = item.count == 0 or item.count < item.total
        text = (str(item.count) if item.flags != "OBJ"
                else f"{item.count}/{item.total}")
        right.label(text=text, icon="ERROR" if stale else "NONE")
        previewing = item.name in preview_names()
        op = right.operator("iops.ss_preview", text="", emboss=False,
                            icon="HIDE_OFF" if previewing else "HIDE_ON")
        op.set_name = item.name


class IOPS_PT_SelectionSets_Panel(bpy.types.Panel):
    bl_label = "iOps Selection Sets"
    bl_idname = "IOPS_PT_selection_sets_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_ui_units_x = 14   # popover width when opened from the header

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"}

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        mirror = wm.iops_ss_mirror
        active = (mirror[wm.iops_ss_index].name
                  if 0 <= wm.iops_ss_index < len(mirror) else "")

        row = layout.row()
        row.template_list("IOPS_UL_SelectionSets", "", wm, "iops_ss_mirror",
                          wm, "iops_ss_index", rows=4)
        col = row.column(align=True)
        col.operator("iops.ss_new", text="", icon="ADD")
        sub = col.column(align=True)
        sub.enabled = bool(active)
        sub.operator("iops.ss_delete", text="",
                     icon="REMOVE").set_name = active
        sub.operator("iops.ss_rename", text="",
                     icon="OUTLINER_OB_FONT").set_name = active
        col.separator()
        col.operator("iops.ss_refresh", text="", icon="FILE_REFRESH")
        col.separator()
        col.operator("iops.ss_delete_all", text="", icon="TRASH")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.enabled = bool(active)
        op = row.operator("iops.ss_recall", text="Select Set")
        op.set_name = active
        row.operator("iops.ss_replace", text="Replace").set_name = active

        # Boolean modes: selection vs the active set (Shift: into the set).
        bcol = layout.column(align=True)
        bcol.enabled = bool(active)
        for mode, label, icon in (
                ("EXTEND", "Extend", "SELECT_EXTEND"),
                ("SUBTRACT", "Subtract", "SELECT_SUBTRACT"),
                ("INTERSECT", "Intersect", "SELECT_INTERSECT"),
                ("DIFFERENCE", "Difference", "SELECT_DIFFERENCE")):
            op = bcol.operator("iops.ss_bool", text=label, icon=icon)
            op.set_name, op.mode = active, mode


def draw_iops_ss_header(self, context):
    """Appended to VIEW3D_MT_editor_menus so the row sits mid-header
    (right after the View/Select/... menus), not at the far right edge
    where VIEW3D_HT_header appends land."""
    if context.mode not in {"OBJECT", "EDIT_MESH"}:
        return
    prefs = context.preferences.addons["InteractionOps"].preferences
    if not prefs.iops_ss_header:
        return
    layout = self.layout
    layout.separator()
    wm = context.window_manager
    mirror = wm.iops_ss_mirror
    active = (mirror[wm.iops_ss_index].name
              if 0 <= wm.iops_ss_index < len(mirror) else "")
    text = active or "Sets"
    # Header buttons truncate long labels; size the slot to the name so
    # the full set name is always visible (icon + ~0.55 units per char).
    row = layout.row()
    row.ui_units_x = max(4.0, 1.8 + 0.55 * len(text))
    row.popover(panel="IOPS_PT_selection_sets_panel", text=text,
                icon="SELECT_SET")
    sub = layout.row(align=True)
    sub.enabled = bool(active)
    sub.operator("iops.ss_recall", text="",
                 icon="RESTRICT_SELECT_OFF").set_name = active
    sub.operator("iops.ss_replace", text="",
                 icon="UV_SYNC_SELECT").set_name = active
    previewing = active and active in preview_names()
    sub.operator("iops.ss_preview", text="",
                 icon="HIDE_OFF" if previewing else "HIDE_ON",
                 depress=bool(previewing)).set_name = active
    sub2 = layout.row(align=True)
    sub2.operator("iops.ss_new", text="", icon="ADD")
    sub3 = sub2.row(align=True)
    sub3.enabled = bool(active)
    sub3.operator("iops.ss_delete", text="", icon="REMOVE").set_name = active


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _iops_ss_resync),
    (bpy.app.handlers.undo_post, _iops_ss_force_resync),
    (bpy.app.handlers.redo_post, _iops_ss_force_resync),
    (bpy.app.handlers.load_post, _iops_ss_force_resync),
)


def register_selection_sets_ui():
    bpy.types.WindowManager.iops_ss_mirror = bpy.props.CollectionProperty(
        type=IOPS_SS_MirrorItem)
    bpy.types.WindowManager.iops_ss_index = bpy.props.IntProperty(default=0)
    ss._tag_mirror_dirty = tag_mirror_dirty
    ss._rebuild_mirror_now = lambda context: rebuild_mirror(context,
                                                            force=True)
    ss._preview_renamed = _preview_renamed
    for handler_list, fn in _HANDLERS:
        if fn not in handler_list:
            handler_list.append(fn)


def unregister_selection_sets_ui():
    _preview_disable()
    for handler_list, fn in _HANDLERS:
        if fn in handler_list:
            handler_list.remove(fn)
    ss._tag_mirror_dirty = lambda: None
    ss._rebuild_mirror_now = lambda context: None
    ss._preview_renamed = lambda old, new: None
    for attr in ("iops_ss_mirror", "iops_ss_index"):
        try:
            delattr(bpy.types.WindowManager, attr)
        except AttributeError:
            pass
