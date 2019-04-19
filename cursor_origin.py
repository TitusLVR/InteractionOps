class IOPS_CursorOrigin (bpy.types.Operator):
    bl_idname = "iops.cursor_origin"
    bl_label = "iOps Cursor to Selected/Origin to Cursor"
    bl_options = {"REGISTER","UNDO"}

    @classmethod 
    def poll (self, context):
        return context.area.type == "VIEW_3D"

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

