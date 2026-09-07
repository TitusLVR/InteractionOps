"""Modifier panel core: type registry and batch helpers.

Each operators/modifiers/iops_<type>.py file registers a ModDescriptor
here. The panel and all tool operators are driven by this registry, so
adding a new modifier type to the grid = adding one descriptor file.
"""

import bpy
from dataclasses import dataclass, field

GROUP_ORDER = ("GENERATE", "DEFORM", "UTILITY")

REGISTRY = {}  # mod_type -> ModDescriptor, insertion order = grid order

# Types enabled in the grid by default (the curated 6x3 set)
CURATED_TYPES = (
    "BEVEL", "BOOLEAN", "MIRROR", "ARRAY", "SOLIDIFY", "SUBSURF",
    "SCREW", "WELD", "TRIANGULATE", "DECIMATE", "REMESH", "WIREFRAME",
    "CURVE", "LATTICE", "SIMPLE_DEFORM", "DISPLACE", "SHRINKWRAP",
    "WEIGHTED_NORMAL",
)


@dataclass
class ModDescriptor:
    mod_type: str                 # bpy Modifier.type enum id
    icon: str                     # UI icon name
    group: str                    # GENERATE | DEFORM | UTILITY
    defaults: dict = field(default_factory=dict)   # smart defaults
    object_fields: tuple = ()     # pointer props referencing Objects
    requires_target: bool = False # empty object_fields[0] == dead modifier
    scale_props: tuple = ()       # distance props Safe Apply rescales
    is_noop: object = None        # callable(md) -> bool for Cleanup


def register_descriptor(desc):
    REGISTRY[desc.mod_type] = desc
    return desc


# --- RNA-derived data (cached) ---------------------------------------

_TYPE_ITEMS = None   # [(identifier, name, icon), ...] for all modifier types
_FIELDS_CACHE = {}   # mod_type -> tuple of object-pointer prop names


def all_mod_type_items():
    """(identifier, name, icon) for every Object modifier type."""
    global _TYPE_ITEMS
    if _TYPE_ITEMS is None:
        enum = bpy.types.Modifier.bl_rna.properties["type"].enum_items
        _TYPE_ITEMS = [(it.identifier, it.name, it.icon) for it in enum]
    return _TYPE_ITEMS


def enabled_grid_slots(prefs):
    """Grid content = the user's list in prefs, in list order, filtered
    to types this Blender build actually has. [(index, item)] — the
    index addresses the slot (and its own defaults) in prefs."""
    valid = {ident for ident, _name, _icon in all_mod_type_items()}
    return [(i, it) for i, it in enumerate(prefs.modifiers_grid_items)
            if it.mod_type in valid]


def enabled_grid_types(prefs):
    """Types in the grid, in list order (duplicates kept)."""
    return [it.mod_type for _i, it in enabled_grid_slots(prefs)]


def type_icon(mod_type):
    desc = REGISTRY.get(mod_type)
    if desc is not None:
        return desc.icon
    for ident, _name, icon in all_mod_type_items():
        if ident == mod_type:
            return icon if icon != "NONE" else "MODIFIER"
    return "MODIFIER"


def object_fields(md):
    """Names of md's props that point at Objects. Registry fast path,
    one-time RNA introspection fallback for unknown types."""
    desc = REGISTRY.get(md.type)
    if desc is not None:
        return desc.object_fields
    fields = _FIELDS_CACHE.get(md.type)
    if fields is None:
        fields = tuple(
            p.identifier for p in md.bl_rna.properties
            if p.type == "POINTER" and not p.is_readonly
            and getattr(p.fixed_type, "identifier", "") in {"Object"}
        )
        _FIELDS_CACHE[md.type] = fields
    return fields


# --- batch helpers ----------------------------------------------------

def add_with_defaults(obj, mod_type, slot=None):
    """Add a modifier with the grid slot's saved defaults (slot = grid
    item; None = first slot of that type) or the descriptor's smart
    defaults. A labelled slot names the modifier after its label.
    Returns the modifier or None (incompatible object)."""
    from . import iops_mod_presets as presets
    if slot is not None and slot.mod_type != mod_type:
        slot = None
    name = (slot.label if slot is not None and slot.label
            else mod_type.title().replace("_", " "))
    try:
        md = obj.modifiers.new(name=name, type=mod_type)
    except (TypeError, RuntimeError):
        return None
    if md is None:
        return None
    settings = (presets.slot_settings(slot) if slot is not None
                else presets.load_default(mod_type))
    if settings is None:
        desc = REGISTRY.get(mod_type)
        settings = desc.defaults if desc else {}
    apply_settings(md, settings)
    return md


def apply_settings(md, settings):
    """Apply a settings dict to a modifier. Enums go first: mode-like
    switches (e.g. Bevel's offset_type) convert dependent values on set
    and would mangle numbers applied before them."""
    def _set(key, value):
        try:
            prop = md.bl_rna.properties.get(key)
            if prop is not None and prop.type == "ENUM" and prop.is_enum_flag:
                value = set(value)
            setattr(md, key, value)
        except Exception:
            pass  # renamed/removed prop from an old preset — skip

    enum_keys = {key for key in settings
                 if (p := md.bl_rna.properties.get(key)) is not None
                 and p.type == "ENUM"}
    for key in settings:
        if key in enum_keys:
            _set(key, settings[key])
    for key in settings:
        if key not in enum_keys:
            _set(key, settings[key])


def smart_apply_object(context, obj, mod_type=None, up_to=None):
    """Apply obj's modifiers top-down (stack order respected).

    mod_type: only modifiers of this type (None = all).
    up_to: (type, name) — apply every enabled modifier from the top
      through the first modifier matching type and name, inclusive.
      If no match exists on obj, nothing is applied.
    Handles multi-user data (auto single-user copy). Objects with shape
    keys are skipped. Disabled (show_viewport off) modifiers are skipped.
    Returns (applied_count, skip_reason or None, failed_count) — a
    per-modifier RuntimeError from bpy.ops.object.modifier_apply is
    caught, printed with detail, and counted in failed_count; the batch
    never aborts.
    """
    if obj.data is not None and getattr(obj.data, "shape_keys", None):
        return 0, "shape keys", 0

    names = []
    if up_to is not None:
        found = False
        for md in obj.modifiers:
            if md.show_viewport:
                names.append(md.name)
            if md.type == up_to[0] and md.name == up_to[1]:
                found = True
                break
        if not found:
            return 0, "no matching modifier", 0
    else:
        names = [md.name for md in obj.modifiers
                 if md.show_viewport and (mod_type is None or md.type == mod_type)]

    if not names:
        return 0, None, 0
    if obj.data is not None and obj.data.users > 1:
        obj.data = obj.data.copy()

    applied = 0
    failed = 0
    for name in names:
        try:
            with context.temp_override(object=obj, active_object=obj,
                                       selected_editable_objects=[obj]):
                bpy.ops.object.modifier_apply(modifier=name)
            applied += 1
        except RuntimeError as e:
            print(f"IOPS modifiers: apply {name!r} on {obj.name!r} failed: {e}")
            failed += 1
    return applied, None, failed


# --- the grid click operator -----------------------------------------

class IOPS_OT_ModGridClick(bpy.types.Operator):
    """Modifier grid cell: add / apply / remove / toggle by type"""

    bl_idname = "iops.mod_grid_click"
    bl_label = "Modifier"
    bl_options = {"REGISTER", "UNDO"}

    mod_type: bpy.props.StringProperty(options={"SKIP_SAVE"})
    # grid slot index in prefs (-1 = none: first slot of the type)
    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})
    mode: bpy.props.EnumProperty(
        items=[
            ("ADD", "Add", "Add with smart defaults"),
            ("APPLY", "Apply", "Smart Apply all of this type"),
            ("REMOVE", "Remove", "Remove all of this type"),
            ("TOGGLE", "Toggle", "Toggle viewport visibility of this type"),
        ],
        default="ADD",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    @classmethod
    def description(cls, context, properties):
        name = properties.mod_type.title().replace("_", " ")
        try:
            items = context.preferences.addons[
                "InteractionOps"].preferences.modifiers_grid_items
            item = items[properties.index]
            if item.label and item.mod_type == properties.mod_type:
                name = f"{item.label} ({name})"
        except (KeyError, IndexError, AttributeError):
            pass
        return (f"{name}\n"
                "Click: add to selection (slot defaults)\n"
                "Ctrl: apply all of this type (Smart Apply)\n"
                "Alt: remove all of this type\n"
                "Shift: toggle viewport visibility of this type")

    def invoke(self, context, event):
        if event.ctrl:
            self.mode = "APPLY"
        elif event.alt:
            self.mode = "REMOVE"
        elif event.shift:
            self.mode = "TOGGLE"
        else:
            self.mode = "ADD"
        return self.execute(context)

    def execute(self, context):
        objects = list(context.selected_objects)
        mt = self.mod_type

        if self.mode == "ADD":
            items = context.preferences.addons[
                "InteractionOps"].preferences.modifiers_grid_items
            slot = (items[self.index]
                    if 0 <= self.index < len(items) else None)
            added = skipped = 0
            for obj in objects:
                if add_with_defaults(obj, mt, slot) is not None:
                    added += 1
                else:
                    skipped += 1
            msg = f"{mt}: added on {added} object(s)"
            if skipped:
                msg += f", {skipped} incompatible skipped"
            self.report({"INFO"}, msg)

        elif self.mode == "APPLY":
            if context.mode != "OBJECT":
                self.report({"ERROR"},
                            "Modifiers cannot be applied in edit mode")
                return {"CANCELLED"}
            applied = 0
            failed = 0
            skipped = {}
            for obj in objects:
                count, reason, fail_count = smart_apply_object(context, obj, mod_type=mt)
                applied += count
                failed += fail_count
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
            msg = f"{mt}: applied {applied} modifier(s)"
            if failed:
                msg += f", {failed} failed (see console)"
            for reason, n in skipped.items():
                msg += f", {n} object(s) skipped ({reason})"
            self.report({"INFO"}, msg)

        elif self.mode == "REMOVE":
            removed = 0
            for obj in objects:
                for md in [m for m in obj.modifiers if m.type == mt]:
                    obj.modifiers.remove(md)
                    removed += 1
            self.report({"INFO"}, f"{mt}: removed {removed} modifier(s)")

        elif self.mode == "TOGGLE":
            active = context.active_object
            src = active if active in objects else (objects[0] if objects else None)
            state = True
            if src is not None:
                mods = [m for m in src.modifiers if m.type == mt]
                if mods:
                    state = not mods[0].show_viewport
            toggled = 0
            for obj in objects:
                for md in obj.modifiers:
                    if md.type == mt:
                        md.show_viewport = state
                        toggled += 1
            self.report({"INFO"},
                        f"{mt}: viewport {'on' if state else 'off'} "
                        f"for {toggled} modifier(s)")

        return {"FINISHED"}
