"""Stack and fit operators of the falloff fields (scene data, no undo steps)."""
from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from ...utils import falloff_core as fc
from .domain import collect_domain, finish_domain, selection_signature
from .draw import TOOL_IDNAME, active_tool_id
from .props import active_field, enum_items, no_type_refit


def _activate_tool(context):
    """Make the Falloff tool the 3D view's active tool. Without a 3D view
    (headless, scripts) there is nothing to activate: swallowed."""
    if active_tool_id(context) == TOOL_IDNAME:
        return
    try:
        bpy.ops.wm.tool_set_by_id(name=TOOL_IDNAME, space_type="VIEW_3D")
    except (RuntimeError, AttributeError, TypeError):
        pass


def edit_mesh_poll(context):
    """An active mesh object in Edit Mode."""
    ob = context.active_object
    return ob is not None and ob.type == "MESH" and ob.mode == "EDIT"


def fit_active(settings, domain, mode) -> None:
    """Write fc.fit_field of the domain into the active field."""
    fit_into(active_field(settings), domain, mode)


def fit_into(f, domain, mode) -> None:
    """Write fc.fit_field of the domain into field `f`."""
    if f is None or domain is None or len(domain.P) == 0:
        return
    fit = fc.fit_field(domain.P, f.type, mode)
    f.start = tuple(float(x) for x in fit["start"])
    f.end = tuple(float(x) for x in fit["end"])
    f.radii = tuple(float(x) for x in fit["radii"])
    f.roll = float(fit["roll"])


def refit_field(context, settings, f) -> None:
    """Fit `f` to the current domain with PCA (a type change). The next Fit
    on an unchanged selection then cycles on to X. Outside Edit Mesh mode
    (a script setting `type`) there is nothing to fit: the field is kept."""
    if getattr(context, "mode", None) != "EDIT_MESH":
        return
    domain = collect_domain(context, normals=False)
    if domain is None:
        return
    try:
        fit_into(f, domain, "PCA")
        settings.fit_mode = "PCA"
        settings.fit_signature = selection_signature(domain)
    finally:
        finish_domain(domain, update=False)


def new_field_name(fields) -> str:
    """"Falloff N" for a new field (the last one of `fields`), unique among
    the others: N starts at the stack length."""
    taken = {f.name for f in fields[:-1]} if len(fields) else set()
    n = max(len(fields), 1)
    while f"Falloff {n}" in taken:
        n += 1
    return f"Falloff {n}"


def _add_fitted(context, ftype, domain, *, remember=False):
    settings = context.scene.IOPS.falloff
    f = settings.fields.add()
    with no_type_refit():
        f.type = ftype
    f.name = new_field_name(settings.fields)
    settings.active_index = len(settings.fields) - 1
    settings.last_type = ftype
    fit_active(settings, domain, "PCA")
    settings.fit_mode = "PCA"
    # `remember`: the next Fit on this selection cycles to X; otherwise it
    # starts over at PCA
    settings.fit_signature = selection_signature(domain) if remember else ""


def ensure_field(context) -> bool:
    """Empty stack -> add a field of settings.last_type fitted with PCA.
    False when there is no domain to fit."""
    settings = context.scene.IOPS.falloff
    if len(settings.fields):
        return True
    domain = collect_domain(context, normals=False)
    if domain is None:
        return False
    try:
        _add_fitted(context, settings.last_type, domain, remember=True)
    finally:
        finish_domain(domain, update=False)
    return True


class _FalloffOp:
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return edit_mesh_poll(context)


class IOPS_OT_mesh_falloff_field_add(_FalloffOp, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_field_add"
    bl_label = "Add Falloff Field"
    bl_description = "Add a falloff field fitted to the selection"

    type: EnumProperty(name="Type",
                       items=enum_items(fc.FALLOFF_TYPES),
                       default="LINEAR")

    def execute(self, context):
        domain = collect_domain(context, normals=False)
        if domain is None:
            self.report({"WARNING"}, "No visible vertices")
            return {"CANCELLED"}
        try:
            _add_fitted(context, self.type, domain)
        finally:
            finish_domain(domain, update=False)
        return {"FINISHED"}


class IOPS_OT_mesh_falloff_field_remove(_FalloffOp, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_field_remove"
    bl_label = "Remove Falloff Field"
    bl_description = "Remove the active falloff field"

    def execute(self, context):
        settings = context.scene.IOPS.falloff
        if active_field(settings) is None:
            return {"CANCELLED"}
        settings.fields.remove(settings.active_index)
        settings.active_index = max(0, min(settings.active_index,
                                           len(settings.fields) - 1))
        return {"FINISHED"}


class IOPS_OT_mesh_falloff_field_move(_FalloffOp, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_field_move"
    bl_label = "Move Falloff Field"
    bl_description = "Move the active falloff field up or down the stack"

    direction: EnumProperty(name="Direction",
                            items=[("UP", "Up", ""), ("DOWN", "Down", "")],
                            default="UP")

    def execute(self, context):
        settings = context.scene.IOPS.falloff
        i = settings.active_index
        j = i - 1 if self.direction == "UP" else i + 1
        if active_field(settings) is None or not (0 <= j < len(settings.fields)):
            return {"CANCELLED"}
        settings.fields.move(i, j)
        settings.active_index = j
        return {"FINISHED"}


class IOPS_OT_mesh_falloff_clear(_FalloffOp, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_clear"
    bl_label = "Clear Falloff"
    bl_description = "Remove all falloff fields"

    def execute(self, context):
        settings = context.scene.IOPS.falloff
        settings.fields.clear()
        settings.active_index = 0
        settings.use_custom_pivot = False
        return {"FINISHED"}


class IOPS_OT_mesh_falloff_fit(_FalloffOp, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_fit"
    bl_label = "Fit Falloff"
    bl_description = ("Fit the active falloff field to the selection; repeat on "
                      "an unchanged selection to cycle PCA, X, Y, Z")
    is_bindable = True

    def execute(self, context):
        settings = context.scene.IOPS.falloff
        if not len(settings.fields):
            settings.use_custom_pivot = False
            if not ensure_field(context):
                self.report({"WARNING"}, "No visible vertices")
                return {"CANCELLED"}
            _activate_tool(context)
            return {"FINISHED"}
        domain = collect_domain(context, normals=False)
        if domain is None:
            self.report({"WARNING"}, "No visible vertices")
            return {"CANCELLED"}
        try:
            sig = selection_signature(domain)
            if sig == settings.fit_signature:
                modes = fc.FIT_MODES
                settings.fit_mode = modes[(modes.index(settings.fit_mode) + 1)
                                          % len(modes)]
            else:
                settings.fit_mode = "PCA"
            fit_active(settings, domain, settings.fit_mode)
            settings.fit_signature = sig
            settings.use_custom_pivot = False
        finally:
            finish_domain(domain, update=False)
        _activate_tool(context)
        return {"FINISHED"}


class IOPS_OT_mesh_falloff_pivot_reset(_FalloffOp, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_pivot_reset"
    bl_label = "Reset Falloff Pivot"
    bl_description = "Go back to the automatic pivot"

    def execute(self, context):
        context.scene.IOPS.falloff.use_custom_pivot = False
        return {"FINISHED"}
