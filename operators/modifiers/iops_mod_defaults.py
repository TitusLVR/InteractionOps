"""Editable per-type default settings for the modifiers grid.

For every modifier type Blender knows, a PropertyGroup is generated at
import time by mirroring the type's editable RNA props (pointers,
collections and base Modifier props excluded). The groups live on the
addon preferences (one PointerProperty per type, injected into the
prefs class annotations) so the user edits defaults right in the addon
settings; Blender persists them in userpref.blend.

Descriptor smart defaults (REGISTRY[type].defaults) are baked into the
generated property definitions, so an untouched group already carries
the curated values and property_unset() returns to them.
"""

import bpy

# Descriptor modules must be imported before the groups are built so
# REGISTRY is populated (this module is imported from prefs, which the
# root __init__ imports before the operators). Idempotent.
from . import (  # noqa: F401  (imported for their REGISTRY side effect)
    iops_mod_bevel, iops_mod_boolean, iops_mod_mirror, iops_mod_array,
    iops_mod_solidify, iops_mod_subsurf, iops_mod_screw, iops_mod_weld,
    iops_mod_triangulate, iops_mod_decimate, iops_mod_remesh,
    iops_mod_wireframe, iops_mod_curve, iops_mod_lattice,
    iops_mod_simple_deform, iops_mod_displace, iops_mod_shrinkwrap,
    iops_mod_weighted_normal,
)
from .iops_mod_registry import REGISTRY
from .iops_mod_presets import _SKIP_PROPS, _TYPE_SKIP_PROPS

_MAX_VECTOR = 32  # bpy vector property size limit

# RNA properties may carry subtypes/units bpy.props can't take (the
# mismatch only explodes at class registration, not at definition
# time) — anything outside these allowlists degrades to 'NONE'.
_FLOAT_SUBTYPES = {
    "PIXEL", "PIXEL_DIAMETER", "UNSIGNED", "PERCENTAGE", "FACTOR",
    "MASS", "ANGLE", "TIME", "TIME_ABSOLUTE", "DISTANCE",
    "DISTANCE_DIAMETER", "DISTANCE_CAMERA", "POWER", "TEMPERATURE",
    "WAVELENGTH", "COLOR_TEMPERATURE", "FREQUENCY", "NONE",
}
_VECTOR_SUBTYPES = {
    "COLOR", "TRANSLATION", "DIRECTION", "VELOCITY", "ACCELERATION",
    "MATRIX", "EULER", "QUATERNION", "AXISANGLE", "XYZ", "XYZ_LENGTH",
    "COLOR_GAMMA", "COORDINATES", "LAYER", "LAYER_MEMBER", "NONE",
}
_UNITS = {
    "NONE", "LENGTH", "AREA", "VOLUME", "ROTATION", "TIME",
    "TIME_ABSOLUTE", "VELOCITY", "ACCELERATION", "MASS", "CAMERA",
    "POWER", "TEMPERATURE", "WAVELENGTH", "COLOR_TEMPERATURE",
    "FREQUENCY",
}


def _modifier_rna_structs():
    """{enum identifier: bl_rna} for every Object modifier subclass.

    Class names match enum identifiers with underscores removed
    (SIMPLE_DEFORM -> SimpleDeformModifier), compared case-insensitively.
    """
    enum = bpy.types.Modifier.bl_rna.properties["type"].enum_items
    idents = {it.identifier.replace("_", ""): it.identifier for it in enum}
    out = {}
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        if (not isinstance(cls, type)
                or not issubclass(cls, bpy.types.Modifier)
                or cls is bpy.types.Modifier
                or not name.endswith("Modifier")):
            continue
        ident = idents.get(name[:-len("Modifier")].upper())
        if ident is not None:
            out[ident] = cls.bl_rna
    return out


def _prop_def(p, smart_default):
    """bpy.props definition mirroring RNA property p, or None if the
    prop can't be represented (pointer/collection/oversized array)."""
    kw = {"name": p.name, "description": p.description}

    if p.type == "BOOLEAN":
        default = smart_default if smart_default is not None else (
            list(p.default_array) if p.is_array else p.default)
        if p.is_array:
            if p.array_length > _MAX_VECTOR:
                return None
            return bpy.props.BoolVectorProperty(
                size=p.array_length, default=default, **kw)
        return bpy.props.BoolProperty(default=default, **kw)

    if p.type == "INT":
        default = smart_default if smart_default is not None else (
            list(p.default_array) if p.is_array else p.default)
        if p.is_array:
            if p.array_length > _MAX_VECTOR:
                return None
            return bpy.props.IntVectorProperty(
                size=p.array_length, default=default,
                min=p.hard_min, max=p.hard_max,
                soft_min=p.soft_min, soft_max=p.soft_max, **kw)
        return bpy.props.IntProperty(
            default=default, min=p.hard_min, max=p.hard_max,
            soft_min=p.soft_min, soft_max=p.soft_max, **kw)

    if p.type == "FLOAT":
        default = smart_default if smart_default is not None else (
            list(p.default_array) if p.is_array else p.default)
        kw["unit"] = p.unit if p.unit in _UNITS else "NONE"
        if p.is_array:
            if p.array_length > _MAX_VECTOR:
                return None
            subtype = (p.subtype if p.subtype in _VECTOR_SUBTYPES
                       else "NONE")
            return bpy.props.FloatVectorProperty(
                size=p.array_length, default=default,
                subtype=subtype, min=p.hard_min, max=p.hard_max,
                soft_min=p.soft_min, soft_max=p.soft_max, **kw)
        subtype = p.subtype if p.subtype in _FLOAT_SUBTYPES else "NONE"
        return bpy.props.FloatProperty(
            default=default, subtype=subtype,
            min=p.hard_min, max=p.hard_max,
            soft_min=p.soft_min, soft_max=p.soft_max, **kw)

    if p.type == "ENUM":
        items = [(it.identifier, it.name, it.description)
                 for it in p.enum_items]
        if not items:
            return None
        if p.is_enum_flag:
            default = (set(smart_default) if smart_default is not None
                       else p.default_flag)
            return bpy.props.EnumProperty(
                items=items, default=default, options={"ENUM_FLAG"}, **kw)
        default = (smart_default if smart_default is not None
                   else p.default)
        valid = {it[0] for it in items}
        if default not in valid:
            default = items[0][0]
        return bpy.props.EnumProperty(items=items, default=default, **kw)

    if p.type == "STRING":
        default = smart_default if smart_default is not None else p.default
        return bpy.props.StringProperty(default=default, **kw)

    return None  # POINTER / COLLECTION


def _build_groups():
    """Generate one PropertyGroup class per modifier type. Returns
    (classes, {ident: class})."""
    base_props = {p.identifier
                  for p in bpy.types.Modifier.bl_rna.properties}
    skip = base_props | _SKIP_PROPS
    classes = []
    by_type = {}
    for ident, rna in sorted(_modifier_rna_structs().items()):
        desc = REGISTRY.get(ident)
        smart = desc.defaults if desc is not None else {}
        type_skip = _TYPE_SKIP_PROPS.get(ident, set())
        ann = {}
        for p in rna.properties:
            if (p.identifier in skip or p.identifier in type_skip
                    or p.is_readonly or p.is_hidden
                    or p.type in {"POINTER", "COLLECTION"}):
                continue
            try:
                definition = _prop_def(p, smart.get(p.identifier))
            except Exception as e:
                print(f"IOPS modifiers: defaults prop "
                      f"{ident}.{p.identifier} skipped: {e}")
                definition = None
            if definition is not None:
                ann[p.identifier] = definition
        if not ann:
            continue
        cls = type(f"IOPS_ModDefaults_{ident}",
                   (bpy.types.PropertyGroup,),
                   {"__annotations__": ann})
        classes.append(cls)
        by_type[ident] = cls
    return tuple(classes), by_type


DEFAULTS_CLASSES, GROUPS_BY_TYPE = _build_groups()


def group_prop_name(mod_type):
    return f"iops_mod_defaults_{mod_type.lower()}"


def inject_pointer_props(prefs_cls):
    """Add one PointerProperty per generated group to the prefs class
    annotations. Must run before the prefs class registers."""
    for ident, cls in GROUPS_BY_TYPE.items():
        prefs_cls.__annotations__[group_prop_name(ident)] = (
            bpy.props.PointerProperty(type=cls))


def get_group(prefs, mod_type):
    return getattr(prefs, group_prop_name(mod_type), None)


def group_values(group):
    """Group props as a plain dict (enum flags stay sets — the
    apply_settings consumer handles them)."""
    out = {}
    for key in type(group).__annotations__:
        value = getattr(group, key)
        if isinstance(value, (bpy.types.bpy_prop_array,)):
            value = list(value)
        out[key] = value
    return out


def set_group_values(group, settings):
    for key, value in settings.items():
        if key not in type(group).__annotations__:
            continue
        try:
            setattr(group, key, set(value) if isinstance(value, list)
                    and isinstance(getattr(group, key), set) else value)
        except Exception as e:
            print(f"IOPS modifiers: defaults {key}={value!r} skipped: {e}")


def reset_group(group):
    for key in type(group).__annotations__:
        group.property_unset(key)


_AXIS_LABELS = ("X", "Y", "Z", "W")


def draw_props(col, data, prop_ids):
    """Draw props on a property-split column; short boolean vectors
    (axes) become one row of labeled X/Y/Z toggles instead of an
    unlabeled checkbox column."""
    for key in prop_ids:
        p = data.bl_rna.properties.get(key)
        if p is None:
            continue
        if (p.type == "BOOLEAN" and p.is_array
                and 2 <= p.array_length <= 4):
            row = col.row(heading=p.name, align=True)
            for i in range(p.array_length):
                row.prop(data, key, index=i, text=_AXIS_LABELS[i],
                         toggle=True)
            continue
        col.prop(data, key)
