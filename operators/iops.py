import bpy
from ..utils.iops_dict import IOPS_Dict
from ..utils.functions import get_iop


class IOPS_OT_Main(bpy.types.Operator):
    bl_idname = "iops.main"
    bl_label = "IOPS"
    bl_options = {"REGISTER"}

    # modes_3d = {0: "VERT", 1: "EDGE", 2: "FACE"}
    # modes_uv = {0: "VERTEX", 1: "EDGE", 2: "FACE", 3: "ISLAND"}
    # modes_gpen = {0: "EDIT_GPENCIL", 1: "PAINT_GPENCIL", 2: "SCULPT_GPENCIL"}
    # modes_curve = {0: "EDIT_CURVE"}
    # modes_text = {0: "EDIT_TEXT"}
    # modes_meta = {0: "EDIT_META"}
    # modes_lattice = {0: "EDIT_LATTICE"}
    # modes_armature = {0: "EDIT", 1: "POSE"}
    # supported_types = {"MESH", "CURVE", "GPENCIL", "EMPTY", "TEXT", "META", "ARMATURE", "LATTICE"}

    # @classmethod
    # def poll(cls, context):
    # return (bpy.context.object is not None and
    # bpy.context.active_object is not None)

    alt = False
    ctrl = False
    shift = False

    def get_mode_3d(self, tool_mesh):
        mode = ""
        if tool_mesh[0]:
            mode = "VERT"
        elif tool_mesh[1]:
            mode = "EDGE"
        elif tool_mesh[2]:
            mode = "FACE"
        return mode
    
    def get_modifier_state(self):
        modifiers = []
        if self.alt:
            modifiers.append("ALT")
        if self.ctrl:
            modifiers.append("CTRL")
        if self.shift:
            modifiers.append("SHIFT")
        return "_".join(modifiers) if modifiers else "NONE"

    def invoke(self, context, event):
        # Set modifier flags
        self.alt = event.alt
        self.ctrl = event.ctrl
        self.shift = event.shift
        return self.execute(context)

    def execute(self, context):
        op = self.operator
        event = self.get_modifier_state()
        if bpy.context.area:
            type_area = bpy.context.area.type
            if bpy.context.view_layer.objects.active:
                tool_mesh = bpy.context.scene.tool_settings.mesh_select_mode
                type_object = bpy.context.view_layer.objects.active.type
                mode_object = bpy.context.view_layer.objects.active.mode
                mode_mesh = self.get_mode_3d(tool_mesh)
                mode_uv = 'UV_' + bpy.context.tool_settings.uv_select_mode
                flag_uv = bpy.context.tool_settings.use_uv_select_sync
                if flag_uv:
                    mode_uv = mode_mesh

                # Build query with current state
                query = (
                    type_area,
                    flag_uv,
                    type_object,
                    mode_object,
                    mode_uv,
                    mode_mesh,
                    op,
                    event,
                )
            else:
                query = (type_area, None, None, None, None, None, op, event)

            # Get and execute the function
            function = get_iop(IOPS_Dict.iops_dict, query)
            if function:
                function()
            else:
                self.report({"WARNING"}, "No operation defined for this context")
        else:
            self.report({"INFO"}, "Focus your mouse pointer on corresponding window.")
        return {"FINISHED"}
