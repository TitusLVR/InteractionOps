"""Select objects linked through Boolean / Mirror modifiers.

Three Object-mode selectors that walk modifier pointers instead of the
outliner: the operands (cutters) of the selection's Boolean modifiers,
the objects whose Boolean modifiers use the selection as an operand,
and the mirror objects of the selection's Mirror modifiers. Hidden,
viewport-disabled and unselectable results are revealed first (each
toggleable in the redo panel), and when the 3D View is in local view
the results are added to that local view so they actually show up.
"""

import bpy

from ..utils.boolean_links_core import (
    boolean_operands, boolean_users, mirror_objects, local_view_of,
)


def _sources(context):
    """Selected objects, or the active one when nothing is selected."""
    objs = list(context.selected_objects)
    active = context.active_object
    if active is not None and active not in objs:
        objs.append(active)
    return objs


def _has_modifier(objs, mod_type):
    return any(md.type == mod_type
               for obj in objs for md in getattr(obj, "modifiers", ()))


class _SelectLinkedBase:
    """Shared props / apply step. Subclasses implement `_find(sources,
    context) -> list[Object]`."""

    extend: bpy.props.BoolProperty(
        name="Extend",
        description="Keep the current selection instead of replacing it",
        default=False,
    )
    select_hidden: bpy.props.BoolProperty(
        name="Reveal Hidden",
        description="Unhide results hidden with H / the eye icon",
        default=True,
    )
    select_disabled: bpy.props.BoolProperty(
        name="Reveal Disabled",
        description="Enable results disabled in viewports (the monitor icon)",
        default=True,
    )
    select_unselectable: bpy.props.BoolProperty(
        name="Make Selectable",
        description="Clear the selectability lock on results",
        default=True,
    )
    add_to_local_view: bpy.props.BoolProperty(
        name="Add to Local View",
        description="When the 3D View is in local view, bring the results "
                    "into it as well",
        default=True,
    )

    _mod_type = "BOOLEAN"
    _noun = "object"

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            return False
        return _has_modifier(_sources(context), cls._mod_type)

    def _find(self, sources, context):
        raise NotImplementedError

    def _reveal(self, obj):
        if self.select_hidden and obj.hide_get():
            obj.hide_set(False)
        if self.select_disabled and obj.hide_viewport:
            obj.hide_viewport = False
        if self.select_unselectable and obj.hide_select:
            obj.hide_select = False

    def execute(self, context):
        sources = _sources(context)
        found = self._find(sources, context)
        if not found:
            self.report({"INFO"}, f"No linked {self._noun}s found")
            return {"CANCELLED"}

        space = local_view_of(context.space_data) if self.add_to_local_view else None

        if not self.extend:
            for obj in context.selected_objects:
                obj.select_set(False)

        selected = 0
        skipped = []
        for obj in found:
            self._reveal(obj)
            if space is not None:
                try:
                    obj.local_view_set(space, True)
                except RuntimeError:
                    pass
            try:
                obj.select_set(True)
            except RuntimeError:  # not in this view layer
                skipped.append(obj.name)
                continue
            selected += 1

        first = next((o for o in found if o.select_get()), None)
        if first is not None:
            context.view_layer.objects.active = first

        msg = f"Selected {selected} {self._noun}(s)"
        if skipped:
            msg += f"; {len(skipped)} not in view layer: " + ", ".join(skipped[:3])
            self.report({"WARNING"}, msg)
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class IOPS_OT_SelectBooleanOperands(_SelectLinkedBase, bpy.types.Operator):
    """Select the cutter objects (and operand-collection members) used by
    the Boolean modifiers of the selected objects"""

    bl_idname = "iops.object_select_boolean_operands"
    bl_label = "Select Boolean Operands"
    bl_options = {"REGISTER", "UNDO"}

    _mod_type = "BOOLEAN"
    _noun = "operand"

    def _find(self, sources, context):
        return boolean_operands(sources)


class IOPS_OT_SelectBooleanTargets(_SelectLinkedBase, bpy.types.Operator):
    """Select the objects whose Boolean modifiers cut with the selected
    objects (directly or through an operand collection)"""

    bl_idname = "iops.object_select_boolean_targets"
    bl_label = "Select Boolean Targets"
    bl_options = {"REGISTER", "UNDO"}

    _noun = "target"

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(_sources(context))

    def _find(self, sources, context):
        return boolean_users(bpy.data.objects, sources)


class IOPS_OT_SelectMirrorObjects(_SelectLinkedBase, bpy.types.Operator):
    """Select the mirror objects used by the Mirror modifiers of the
    selected objects"""

    bl_idname = "iops.object_select_mirror_objects"
    bl_label = "Select Mirror Objects"
    bl_options = {"REGISTER", "UNDO"}

    _mod_type = "MIRROR"
    _noun = "mirror object"

    def _find(self, sources, context):
        return mirror_objects(sources)


classes = (
    IOPS_OT_SelectBooleanOperands,
    IOPS_OT_SelectBooleanTargets,
    IOPS_OT_SelectMirrorObjects,
)


def draw_select_menu(self, context):
    """Appended to the 3D View › Select menu (and HOPS Select Grouped)."""
    layout = self.layout
    layout.separator()
    layout.operator(IOPS_OT_SelectBooleanOperands.bl_idname)
    layout.operator(IOPS_OT_SelectBooleanTargets.bl_idname)
    layout.operator(IOPS_OT_SelectMirrorObjects.bl_idname)
