"""Scene-level falloff field stack: property groups and plain-data helpers.

`scene.IOPS.falloff` holds the field stack and the tool settings. The core
(utils/falloff_core.py) never sees bpy, so `field_to_dict` / `stack_to_list`
snapshot the groups into the dicts it consumes.
"""
from __future__ import annotations

from contextlib import contextmanager

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, FloatVectorProperty, IntProperty,
                       StringProperty)
from bpy.types import PropertyGroup

from ...utils.falloff_core import (BLEND_MODES, FALLOFF_TYPES, FIT_MODES,
                                   SHAPES)


def enum_items(values):
    """EnumProperty items: ("SOME_KEY", "Some Key", "")."""
    return [(v, v.replace("_", " ").title(), "") for v in values]


# ------------------------------------------------------------------ type refit

_FIELDS_PATH = "IOPS.falloff.fields["
_refit_suppressed = 0


@contextmanager
def no_type_refit():
    """Assign `type` without the refit (copying a stack, adding a field that
    is fitted right after)."""
    global _refit_suppressed
    _refit_suppressed += 1
    try:
        yield
    finally:
        _refit_suppressed -= 1


def _scene_field_owner(field):
    """The Scene whose `IOPS.falloff.fields` holds `field`, else None
    (operator-owned stack snapshots, unsaved copies)."""
    scene = field.id_data
    if not isinstance(scene, bpy.types.Scene):
        return None
    try:
        path = field.path_from_id()
    except (ValueError, RuntimeError):
        return None
    return scene if path.startswith(_FIELDS_PATH) else None


def _on_type_update(self, context):
    """Changing a scene field's type refits it to the current domain (PCA)."""
    if _refit_suppressed:
        return
    scene = _scene_field_owner(self)
    if scene is None:
        return
    from . import fields          # lazy: fields imports this module
    settings = scene.IOPS.falloff
    settings.last_type = self.type
    fields.refit_field(context, settings, self)


class IOPS_FalloffField(PropertyGroup):
    name: StringProperty(name="Name", default="Field")
    type: EnumProperty(name="Type", items=enum_items(FALLOFF_TYPES), default="LINEAR",
                      update=_on_type_update)
    start: FloatVectorProperty(
        name="Start", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0),
        description="Start point (world space); centre for Radial / Elliptical")
    end: FloatVectorProperty(
        name="End", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 1.0),
        description="End point (world space)")
    radii: FloatVectorProperty(
        name="Radii", size=2, min=0.0, default=(1.0, 1.0),
        description="Elliptical radii perpendicular to the axis")
    roll: FloatProperty(name="Roll", subtype="ANGLE", default=0.0,
                        description="Elliptical roll about the axis")
    curve: EnumProperty(name="Curve", items=enum_items(SHAPES), default="LINEAR")
    invert: BoolProperty(name="Invert", default=False)
    strength: FloatProperty(name="Strength", min=0.0, max=1.0, default=1.0)
    blend: EnumProperty(name="Blend", items=enum_items(BLEND_MODES), default="REPLACE")
    enabled: BoolProperty(name="Enabled", default=True)


class IOPS_FalloffSettings(PropertyGroup):
    fields: CollectionProperty(type=IOPS_FalloffField)
    active_index: IntProperty(name="Active Field", default=0, min=0)
    show_weights: BoolProperty(name="Show Weights", default=True)
    basis: EnumProperty(
        name="Falloff Basis",
        description="Pivot and axes the falloff transforms work in",
        items=[("LOCAL", "Local", "Selection centre, object axes"),
               ("CURSOR", "Cursor", "3D cursor location and rotation"),
               ("WORLD", "World", "World origin and axes"),
               ("NORMAL", "Normal", "Active element centre, Z along its normal")],
        default="LOCAL",
    )
    use_custom_pivot: BoolProperty(name="Custom Pivot", default=False)
    pivot: FloatVectorProperty(name="Pivot", size=3, subtype="TRANSLATION",
                               default=(0.0, 0.0, 0.0))
    last_type: EnumProperty(name="Last Type", items=enum_items(FALLOFF_TYPES),
                            default="LINEAR")
    fit_mode: EnumProperty(name="Fit Mode", items=enum_items(FIT_MODES), default="PCA")
    fit_signature: StringProperty(name="Fit Signature", default="")


# ------------------------------------------------------------------ helpers

_VEC_KEYS = ("start", "end", "radii")
_SCALAR_KEYS = ("type", "curve", "invert", "blend", "enabled")


def field_to_dict(field) -> dict:
    d = {k: tuple(float(x) for x in getattr(field, k)) for k in _VEC_KEYS}
    for k in _SCALAR_KEYS:
        d[k] = getattr(field, k)
    d["roll"] = float(field.roll)
    d["strength"] = float(field.strength)
    return d


def dict_to_field(d: dict, field) -> None:
    for k in _VEC_KEYS:
        setattr(field, k, tuple(float(x) for x in d[k]))
    with no_type_refit():
        for k in _SCALAR_KEYS:
            setattr(field, k, d[k])
    field.roll = float(d["roll"])
    field.strength = float(d["strength"])


def stack_to_list(fields) -> list:
    return [field_to_dict(f) for f in fields]


def copy_stack(src_fields, dst_fields) -> None:
    """Replace `dst_fields` with a copy of `src_fields` (names included)."""
    snapshot = [(f.name, field_to_dict(f)) for f in src_fields]
    dst_fields.clear()
    for name, d in snapshot:
        nf = dst_fields.add()
        nf.name = name
        dict_to_field(d, nf)


def active_field(settings):
    i = settings.active_index
    if 0 <= i < len(settings.fields):
        return settings.fields[i]
    return None
