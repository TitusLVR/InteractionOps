import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
)


class IOPS_OT_Easy_Mod_Shwarp(bpy.types.Operator):
    """Select picked curve in curve modifier"""

    bl_idname = "iops.modifier_easy_shwarp"
    bl_label = "Easy Modifier - Shrinkwarp"
    bl_options = {"REGISTER", "UNDO"}

    shwarp_offset: FloatProperty(
        name="Offset",
        description="Offset factor",
        default=0.0,
        min=0.00,
        max=9999.0,
    )
    shwarp_method: EnumProperty(
        name="Mode",
        description="Mod",
        items=[
            ("NEAREST_SURFACEPOINT", "NEAREST_SURFACEPOINT", "", "", 0),
            ("PROJECT", "PROJECT", "", "", 1),
            ("NEAREST_VERTEX", "NEAREST_VERTEX", "", "", 2),
            ("TARGET_PROJECT", "TARGET_PROJECT", "", "", 3),
        ],
        default="PROJECT",
    )
    shwarp_use_vg: BoolProperty(
        name="Use vertex groups", description="Takes last one", default=False
    )

    transfer_normals: BoolProperty(
        name="Transfer Normals",
        description="Add mod to transfer normals from target object",
        default=False,
    )

    stack_location: EnumProperty(
        name="Mod location in stack",
        description="Where to put SWARP modifier?",
        items=[
            ("First", "First", "", "", 0),
            ("Last", "Last", "", "", 1),
            ("Before Active", "Before Active", "", "", 2),
            ("After Active", "After Active", "", "", 3),
        ],
        default="Last",
    )

    @classmethod
    def poll(cls, context):
        return (
            context.object
            and context.object.type == "MESH"
            and context.area.type == "VIEW_3D"
            and len(context.view_layer.objects.selected) >= 2
        )

    def execute(self, context):
        target = context.active_object
        ctx = bpy.context.copy()
        objs = []

        for ob in context.view_layer.objects.selected:
            if ob.name != target.name and ob.type == "MESH":
                objs.append(ob)

        if objs and target:
            # print(objs)
            for ob in objs:
                if self.shwarp_use_vg and ob.vertex_groups[:] == []:
                    self.shwarp_use_vg = False
                    self.transfer_normals = False

                if ob.modifiers:
                    mod_list = ob.modifiers.keys()
                    active_idx = mod_list.index(ob.modifiers.active.name)
                    print("Active mod:", ob.modifiers.active.name)

                # Context copy
                ctx["object"] = ob
                ctx["active_object"] = ob
                ctx["selected_objects"] = [ob]
                ctx["selected_editable_objects"] = [ob]

                if "iOps Shwarp" in ob.modifiers.keys():
                    continue
                    # mod = ob.modifiers['iOps Shwarp']
                    # mod.show_in_editmode = True
                    # mod.show_on_cage = True
                    # mod.target = target
                    # mod.offset = self.shwarp_offset
                    # mod.wrap_method = self.shwarp_method
                    # if self.shwarp_use_vg:
                    #     mod.vertex_group = ob.vertex_groups[0].name
                else:
                    mod = ob.modifiers.new("iOps Shwarp", type="SHRINKWRAP")
                    mod.show_in_editmode = True
                    mod.show_on_cage = True
                    mod.target = target
                    mod.offset = self.shwarp_offset
                    mod.wrap_method = self.shwarp_method
                    if self.shwarp_use_vg and ob.vertex_groups:
                        mod.vertex_group = ob.vertex_groups[0].name

                    # Logic to move modifier around
                    if self.stack_location in {"First", "Last"}:
                        count = len(ob.modifiers) - 1
                    elif self.stack_location == "Before Active":
                        count = len(ob.modifiers) - 1 - active_idx
                    elif self.stack_location == "After Active":
                        count = len(ob.modifiers) - 2 - active_idx

                    print("Starting moves:", count)

                    while count > 0:
                        if self.stack_location in {
                            "First",
                            "Before Active",
                            "After Active",
                        }:
                            with context.temp_override(**ctx):
                                bpy.ops.object.modifier_move_down(
                                    modifier="iOps Shwarp"
                                )
                        else:
                            break
                        count -= 1
                        print("Active mod:", ob.modifiers.active.name, count)

                # Best settings for default Z projection, will use first group for snapping
                if self.shwarp_method == "PROJECT":
                    mod.use_project_z = True
                    mod.use_negative_direction = True
                    mod.use_positive_direction = True
                    if self.shwarp_use_vg and ob.vertex_groups:
                        mod.vertex_group = ob.vertex_groups[0].name

                if self.transfer_normals:
                    if "iOps Transfer Normals" not in ob.modifiers.keys():
                        mod = ob.modifiers.new(
                            "iOps Transfer Normals", type="DATA_TRANSFER"
                        )
                        mod.object = target
                        mod.use_loop_data = True
                        mod.data_types_loops = {"CUSTOM_NORMAL"}
                        mod.loop_mapping = "POLYINTERP_NEAREST"
                        if self.shwarp_use_vg and ob.vertex_groups:
                            mod.vertex_group = ob.vertex_groups[0].name
                    else:
                        continue

        return {"FINISHED"}
