"""Panel state of the iOps Materials panel (WindowManager, UI only) and the
cached material sets of the Scene / Selected source filters."""
import bpy
from bpy.app.handlers import persistent

from . import common

_VIEW_ITEMS = (
    ("LIST", "List", "Show materials as a list", "LONGDISPLAY", 0),
    ("GALLERY", "Gallery", "Show materials as a grid of previews",
     "IMGDISPLAY", 1),
)
_VIEW_IDS = tuple(item[0] for item in _VIEW_ITEMS)


def _redraw(_self, context):
    common.tag_redraw(context)


def _get_active_index(self):
    mat = common.find_material(self.active_name, self.active_library)
    if mat is None:
        return -1
    for i, m in enumerate(bpy.data.materials):
        if m == mat:
            return i
    return -1


def _set_active_index(self, value):
    mats = bpy.data.materials
    if 0 <= value < len(mats):
        set_active(mats[value])


def _get_view(self):
    stored = self.get("_view", -1)
    if stored in (0, 1):
        return stored
    try:
        default = common.addon_prefs().materials_default_view
    except (KeyError, AttributeError):
        default = "LIST"
    return _VIEW_IDS.index(default) if default in _VIEW_IDS else 0


def _set_view(self, value):
    self["_view"] = value


class IOPS_MaterialsRemapRow(bpy.types.PropertyGroup):
    """One row of the Remap Materials table: the source by name + library
    path (no ID pointer, see the panel state), the target as a pointer,
    empty = unchanged. Rows only live while the dialog is open."""
    source_name: bpy.props.StringProperty(name="Material")
    source_library: bpy.props.StringProperty(name="Library")
    target: bpy.props.PointerProperty(
        name="Change To", type=bpy.types.Material,
        description="Material this one changes to (empty: unchanged)")


class IOPS_MaterialsState(bpy.types.PropertyGroup):
    remap_rows: bpy.props.CollectionProperty(type=IOPS_MaterialsRemapRow)
    remap_view: bpy.props.EnumProperty(
        name="View",
        items=(
            ("LIST", "List", "Names and pickers", "LONGDISPLAY", 0),
            ("THUMBNAILS", "Thumbnails", "Previews of both columns",
             "IMGDISPLAY", 1),
        ),
        default="LIST")
    remap_page: bpy.props.IntProperty(name="Page", default=1, min=1)
    remap_scope: bpy.props.StringProperty(name="Built For")
    active_name: bpy.props.StringProperty(name="Active Material")
    active_library: bpy.props.StringProperty(name="Active Material Library")
    active_index: bpy.props.IntProperty(
        name="Active Material", get=_get_active_index, set=_set_active_index)
    view: bpy.props.EnumProperty(
        name="View", items=_VIEW_ITEMS, get=_get_view, set=_set_view,
        update=_redraw)
    search: bpy.props.StringProperty(
        name="Search", description="Show only materials whose name contains "
        "these words", options={"TEXTEDIT_UPDATE"}, update=_redraw)
    source: bpy.props.EnumProperty(
        name="Source",
        items=(
            ("SCENE", "Scene", "Materials used by objects in the scene"),
            ("SELECTED", "Selected", "Materials used by the selected objects"),
            ("FILE", "File", "All materials in the file"),
        ),
        default="SCENE", update=_redraw)
    gallery_page: bpy.props.IntProperty(name="Gallery Page", default=0, min=0)


def get_state(context=None):
    context = context or bpy.context
    return context.window_manager.iops_materials


def set_active(mat, context=None):
    state = get_state(context)
    name, lib = common.material_key(mat)
    state.active_name = name
    state.active_library = lib


def active_material(context=None):
    state = get_state(context)
    return common.find_material(state.active_name, state.active_library)


# ----------------------------------------------------------------------
# Source sets: recomputed only after a depsgraph update / undo / load, so a
# panel redraw does not walk every object's slots.
# ----------------------------------------------------------------------
_CACHE = {"generation": 0, "entries": {}}


def _objects_materials(objects):
    keys = set()
    for obj in objects:
        for slot in getattr(obj, "material_slots", ()):
            mat = slot.material
            if mat is not None:
                keys.add(common.material_key(mat))
    return keys


def source_keys(context, source):
    """Set of material keys in the source, or None for File (all)."""
    if source == "FILE":
        return None
    scene = context.scene
    cache_key = (source, scene.name, context.view_layer.name)
    hit = _CACHE["entries"].get(cache_key)
    if hit is not None and hit[0] == _CACHE["generation"]:
        return hit[1]
    if source == "SCENE":
        keys = _objects_materials(scene.objects)
    else:
        keys = _objects_materials(common.selected_objects(context))
    _CACHE["entries"][cache_key] = (_CACHE["generation"], keys)
    return keys


def empty_slot_count(context):
    """Empty slots on the assignment targets (shared data once), cached
    like the source sets: recomputed only after a depsgraph update / undo /
    load or an iOps material operator."""
    cache_key = ("EMPTY_SLOTS", context.mode, context.scene.name,
                 context.view_layer.name)
    hit = _CACHE["entries"].get(cache_key)
    if hit is not None and hit[0] == _CACHE["generation"]:
        return hit[1]
    good, _skipped = common.split_compatible(common.target_objects(context))
    seen, count = set(), 0
    for obj in good:
        key = obj.data.as_pointer()
        if key not in seen:
            seen.add(key)
            count += sum(1 for m in obj.data.materials if m is None)
    _CACHE["entries"][cache_key] = (_CACHE["generation"], count)
    return count


def generation():
    """Bumped on every depsgraph update / undo / load and by the iOps
    material operators; memo keys include it."""
    return _CACHE["generation"]


def invalidate_sources():
    _CACHE["generation"] += 1


@persistent
def _on_change(*_args):
    invalidate_sources()


@persistent
def _on_load(*_args):
    # remap rows hold Material pointers: never carry them across files
    wm = bpy.context.window_manager
    if wm is not None and hasattr(wm, "iops_materials"):
        wm.iops_materials.remap_rows.clear()


_HANDLERS = (
    bpy.app.handlers.depsgraph_update_post,
    bpy.app.handlers.undo_post,
    bpy.app.handlers.redo_post,
    bpy.app.handlers.load_post,
)


def register_props():
    bpy.types.WindowManager.iops_materials = bpy.props.PointerProperty(
        type=IOPS_MaterialsState)
    for handlers in _HANDLERS:
        if _on_change not in handlers:
            handlers.append(_on_change)
    for handlers in _CLEAR_HANDLERS:
        if _on_load not in handlers:
            handlers.append(_on_load)


# undo / redo / load may free materials the remap rows point at
_CLEAR_HANDLERS = (
    bpy.app.handlers.undo_post,
    bpy.app.handlers.redo_post,
    bpy.app.handlers.load_post,
)


def unregister_props():
    for handlers in _HANDLERS:
        if _on_change in handlers:
            handlers.remove(_on_change)
    for handlers in _CLEAR_HANDLERS:
        if _on_load in handlers:
            handlers.remove(_on_load)
    _CACHE["entries"].clear()
    try:
        del bpy.types.WindowManager.iops_materials
    except AttributeError:
        pass
