"""Shared bpy helpers of the iOps Materials panel: material lookup by
(name, library), the compatibility rule, targets and skip labels."""
import bpy


def addon_prefs(context=None):
    context = context or bpy.context
    return context.preferences.addons["InteractionOps"].preferences


def popup_width_units(context=None):
    return getattr(addon_prefs(context), "materials_popup_width", 12)


def popup_width_px(context=None):
    context = context or bpy.context
    scale = context.preferences.system.ui_scale or 1.0
    return int(popup_width_units(context) * 20 * scale)


def material_key(mat):
    """(name, library filepath or "") — identifies a material even when a
    local and a linked one share a name."""
    lib = mat.library
    return (mat.name, lib.filepath if lib is not None else "")


def find_material(name, library=""):
    if not name:
        return None
    try:
        return bpy.data.materials.get((name, library or None))
    except (KeyError, TypeError, ValueError):
        return None


def is_linked(id_data):
    return id_data is not None and (
        id_data.library is not None
        or not getattr(id_data, "is_editable", True))


def real_users(mat):
    """Users not counting the fake user."""
    return mat.users - (1 if mat.use_fake_user else 0)


def type_label(obj):
    """Blender's display name of the object type (Empty, Camera, Light)."""
    try:
        return obj.bl_rna.properties["type"].enum_items[obj.type].name
    except (KeyError, AttributeError):
        return obj.type.title()


def skip_reason(obj):
    """None when `obj` can take materials, else the label it is counted
    under in reports. Compatible = has data with a `materials` collection
    and neither the object nor its data is linked library data."""
    data = getattr(obj, "data", None)
    if data is None or not hasattr(data, "materials"):
        return type_label(obj)
    if is_linked(obj) or is_linked(data):
        return "Linked"
    return None


def is_compatible(obj):
    return skip_reason(obj) is None


def in_edit_mode(context):
    return context.mode.startswith("EDIT")


def view_layer_objects(context):
    # an unsynced view layer yields None for objects removed a moment ago
    return [o for o in context.view_layer.objects if o is not None]


def selected_objects(context):
    return [o for o in view_layer_objects(context) if o.select_get()]


def edit_objects(context):
    return [o for o in view_layer_objects(context) if o.mode == "EDIT"]


def target_objects(context):
    """Edit Mode: every object in edit mode. Otherwise the selected objects,
    else the active object."""
    if in_edit_mode(context):
        objs = edit_objects(context)
        if objs:
            return objs
    objs = selected_objects(context)
    if objs:
        return objs
    active = context.view_layer.objects.active
    return [active] if active is not None else []


def split_compatible(objects):
    """(compatible objects, {skip label: count})."""
    good, skipped = [], {}
    for obj in objects:
        reason = skip_reason(obj)
        if reason is None:
            good.append(obj)
        else:
            skipped[reason] = skipped.get(reason, 0) + 1
    return good, skipped


def tag_redraw(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        area.tag_redraw()
