import bpy
from ..operators.iops import IOPS


class IOPS_OT_CursorOrigin_Mesh(IOPS):
    bl_idname = "iops.cursor_origin_mesh"
    bl_lable ="IOPS_OT_CursorOrigin_Mesh"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects

    @classmethod 
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and 
                context.mode == "OBJECT" and
                context.active_object.type == "MESH")


class IOPS_OT_CursorOrigin_Mesh_Edit(IOPS):
    bl_idname = "iops.cursor_origin_mesh_edit"
    bl_lable ="IOPS_OT_CursorOrigin_EditMesh"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects

    @classmethod 
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and 
                context.mode == "EDIT_MESH")


class IOPS_OT_CursorOrigin_Curve(IOPS):
    bl_idname = "iops.cursor_origin_curve"
    bl_lable ="IOPS_OT_CursorOrigin_Curve"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects

    @classmethod 
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and 
                context.mode == "OBJECT" and
                context.active_object.type == "CURVE")


class IOPS_OT_CursorOrigin_Curve_Edit(IOPS):
    bl_idname = "iops.cursor_origin_curve_edit"
    bl_lable ="IOPS_OT_CursorOrigin_Curve_Edit"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects

    @classmethod 
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and 
                context.mode == "EDIT_CURVE")"


class IOPS_OT_CursorOrigin_Empty(IOPS):
    bl_idname = "iops.cursor_origin_empty"
    bl_lable ="IOPS_OT_CursorOrigin_Empty"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects

    @classmethod 
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and 
                context.active_object.type == "EMPTY")


class IOPS_OT_CursorOrigin_Gpen(IOPS):
    bl_idname = "iops.cursor_origin_gpen"
    bl_lable ="IOPS_OT_CursorOrigin_Gpen"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects

    @classmethod 
        return (context.area.type == "VIEW_3D" and 
                context.mode == "OBJECT" and
                context.active_object.type == "GPENCIL")


class IOPS_OT_CursorOrigin_Gpen_Edit(IOPS):
    bl_idname = "iops.cursor_origin_gpen_edit"
    bl_lable ="IOPS_OT_CursorOrigin_Gpen_Edit"
    scene = bpy.context.scene
    objs = bpy.context.selected_objects
    
    @classmethod 
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and 
                context.mode == "EDIT_GPENCIL" and
                context.active_object.type == "GPENCIL")


class CursorOrigin(IOPS):
    bl_idname = "iops.cursor_origin"
    bl_label = "iOps Cursor to Selected/Origin to Cursor"

    @classmethod 
    def poll (self, context):
        return context.area.type == "VIEW_3D"

################################################################################

    def execute(self, context):
        # MESH
        scene = bpy.context.scene
        objs = bpy.context.selected_objects
        if bpy.context.active_object.type == "MESH":
            if bpy.context.mode == "OBJECT":
                if len(objs) != 0:
                    for ob in objs:
                        ob.location = scene.cursor.location
                        ob.rotation_euler = scene.cursor.rotation_euler
                    return{"FINISHED"}

            else:
                bpy.ops.view3d.snap_cursor_to_selected()
                bpy.ops.object.editmode_toggle()
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                return{"FINISHED"}

        # CURVE
        if bpy.context.active_object.type == "CURVE":
            if bpy.context.mode != "EDIT_CURVE":
                if len(objs) != 0:
                    for ob in objs:
                        ob.location = scene.cursor.location
                        ob.rotation_euler = scene.cursor.rotation_euler
                    return{"FINISHED"}
            else:
                bpy.ops.view3d.snap_cursor_to_selected()
                bpy.ops.object.editmode_toggle()
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                return{"FINISHED"}

        # EMPTY    
        if bpy.context.active_object.type == "EMPTY":
            if len(objs) != 0:
                for ob in objs:
                    ob.location = scene.cursor.location
                    ob.rotation_euler = scene.cursor.rotation_euler
                return{"FINISHED"}

        # GPENCIL
        if bpy.context.active_object.type == "GPENCIL":
            if bpy.context.mode!= "EDIT_GPENCIL":
                if len(objs) != 0:
                    for ob in objs:
                        ob.location = scene.cursor.location
                        ob.rotation_euler = scene.cursor.rotation_euler
                    return{"FINISHED"}
            else:
                bpy.ops.gpencil.snap_cursor_to_selected()                
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                bpy.ops.object.mode_set(mode="OBJECT")
                return{"FINISHED"}     
                
        if bpy.context.active_object.type not in IOPS.supported_types:
            return{"FINISHED"}

