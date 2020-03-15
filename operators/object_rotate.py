import bpy
import math
import bmesh
from mathutils import Matrix, Vector


class IOPS_OT_object_rotate_Z (bpy.types.Operator):
    """ Rotate object local Z-axis 90 degrees """
    bl_idname = "iops.object_rotate_z"
    bl_label = "IOPS rotate Z-axis: 90d"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        if len(selection) == 1:
            for ob in selection:
                ob.rotation_euler = (ob.rotation_euler.to_matrix() @ Matrix.Rotation(math.pi/2, 3, 'Z')).to_euler()
                x = round(math.degrees(ob.rotation_euler.x),2)
                y = round(math.degrees(ob.rotation_euler.y),2)
                z = round(math.degrees(ob.rotation_euler.z),2)
                ob.rotation_euler.x = math.radians(x)
                ob.rotation_euler.y = math.radians(y)
                ob.rotation_euler.z = math.radians(z)

        else:            
            bpy.ops.transform.rotate(value=math.radians(-90),
                                     center_override=(cursor),
                                     orient_axis='Z',
                                     orient_type='GLOBAL',
                                     constraint_axis=(False,False,True),
                                     use_accurate=True,                                     
                                     orient_matrix_type='GLOBAL'                                     
                                    )
        self.report({"INFO"}, "IOPS Rotate +Z")
        return {"FINISHED"}

class IOPS_OT_object_rotate_MZ (bpy.types.Operator):
    """ Rotate object local Z-axis -90 degrees """
    bl_idname = "iops.object_rotate_mz"
    bl_label = "IOPS rotate Z-axis: -90d"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        if len(selection) == 1:
            for ob in selection:            
                ob.rotation_euler = (ob.rotation_euler.to_matrix() @ Matrix.Rotation(math.pi/-2, 3, 'Z')).to_euler()
                x = round(math.degrees(ob.rotation_euler.x),2)
                y = round(math.degrees(ob.rotation_euler.y),2)
                z = round(math.degrees(ob.rotation_euler.z),2)
                ob.rotation_euler.x = math.radians(x)
                ob.rotation_euler.y = math.radians(y)
                ob.rotation_euler.z = math.radians(z)
        else:            
            bpy.ops.transform.rotate(value=math.radians(90),
                                     center_override=(cursor),
                                     orient_axis='Z',
                                     orient_type='GLOBAL',
                                     constraint_axis=(False,False,True),
                                     use_accurate=True,
                                     orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                                     orient_matrix_type='GLOBAL'                                   
                                    )
        self.report({"INFO"}, "IOPS Rotate -Z")                                    
        return {"FINISHED"}
    
    
class IOPS_OT_object_rotate_Y (bpy.types.Operator):
    """ Rotate object local Y-axis 90 degrees """
    bl_idname = "iops.object_rotate_y"
    bl_label = "IOPS rotate Y-axis: 90d"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        if len(selection) == 1:
            for ob in selection:            
                ob.rotation_euler = (ob.rotation_euler.to_matrix() @ Matrix.Rotation(math.pi/2, 3, 'Y')).to_euler()
                x = round(math.degrees(ob.rotation_euler.x),2)
                y = round(math.degrees(ob.rotation_euler.y),2)
                z = round(math.degrees(ob.rotation_euler.z),2)
                ob.rotation_euler.x = math.radians(x)
                ob.rotation_euler.y = math.radians(y)
                ob.rotation_euler.z = math.radians(z)            
        else:            
            bpy.ops.transform.rotate(value=math.radians(-90),
                                     center_override=(cursor),
                                     orient_axis='Y',
                                     orient_type='GLOBAL',
                                     constraint_axis=(False,True,False),
                                     use_accurate=True,
                                     #orient_matrix=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
                                     orient_matrix_type='GLOBAL'
                                    )
        self.report({"INFO"}, "IOPS Rotate +Y")
        return {"FINISHED"}

class IOPS_OT_object_rotate_MY (bpy.types.Operator):
    """ Rotate object local Y-axis -90 degrees """
    bl_idname = "iops.object_rotate_my"
    bl_label = "IOPS rotate Y-axis: -90d"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        if len(selection) == 1:
            for ob in selection:            
                ob.rotation_euler = (ob.rotation_euler.to_matrix() @ Matrix.Rotation(math.pi/-2, 3, 'Y')).to_euler()                
                x = round(math.degrees(ob.rotation_euler.x),2)
                y = round(math.degrees(ob.rotation_euler.y),2)
                z = round(math.degrees(ob.rotation_euler.z),2)
                ob.rotation_euler.x = math.radians(x)
                ob.rotation_euler.y = math.radians(y)
                ob.rotation_euler.z = math.radians(z)                
        else:            
            bpy.ops.transform.rotate(value=math.radians(90),
                                     center_override=(cursor),
                                     orient_axis='Y',
                                     orient_type='GLOBAL',
                                     constraint_axis=(False,True,False),
                                     use_accurate=True,
                                     #orient_matrix=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
                                     orient_matrix_type='GLOBAL'
                                    )
        self.report({"INFO"}, "IOPS Rotate -Y")
        return {"FINISHED"}
    
class IOPS_OT_object_rotate_X (bpy.types.Operator):
    """ Rotate object local X-axis 90 degrees """
    bl_idname = "iops.object_rotate_x"
    bl_label = "IOPS rotate X-axis: 90d"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location        

        if len(selection) == 1:
            for ob in selection:            
                ob.rotation_euler = (ob.rotation_euler.to_matrix() @ Matrix.Rotation(math.pi/2, 3, 'X')).to_euler()
                x = round(math.degrees(ob.rotation_euler.x),2)
                y = round(math.degrees(ob.rotation_euler.y),2)
                z = round(math.degrees(ob.rotation_euler.z),2)
                ob.rotation_euler.x = math.radians(x)
                ob.rotation_euler.y = math.radians(y)
                ob.rotation_euler.z = math.radians(z)
                              
        else:            
            bpy.ops.transform.rotate(value=math.radians(-90),
                                     center_override=(cursor),
                                     orient_axis='X',
                                     orient_type='GLOBAL',
                                     constraint_axis=(True,False,False),
                                     use_accurate=True,
                                     #orient_matrix=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
                                     orient_matrix_type='GLOBAL'
                                    )
        self.report({"INFO"}, "IOPS Rotate +X")
        return {"FINISHED"}

class IOPS_OT_object_rotate_MX (bpy.types.Operator):
    """ Rotate object local X-axis -90 degrees """
    bl_idname = "iops.object_rotate_mx"
    bl_label = "IOPS rotate X-axis: -90d"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        if len(selection) == 1:
            for ob in selection:            
                ob.rotation_euler = (ob.rotation_euler.to_matrix() @ Matrix.Rotation(math.pi/-2, 3, 'X')).to_euler()
                x = round(math.degrees(ob.rotation_euler.x),2)
                y = round(math.degrees(ob.rotation_euler.y),2)
                z = round(math.degrees(ob.rotation_euler.z),2)
                ob.rotation_euler.x = math.radians(x)
                ob.rotation_euler.y = math.radians(y)
                ob.rotation_euler.z = math.radians(z)                
        else:            
            bpy.ops.transform.rotate(value=math.radians(90),
                                     center_override=(cursor),
                                     orient_axis='X',
                                     orient_type='GLOBAL',
                                     constraint_axis=(True,False,False),
                                     use_accurate=True,
                                     #orient_matrix=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
                                     orient_matrix_type='GLOBAL'
                                    )
        self.report({"INFO"}, "IOPS Rotate -X")
        return {"FINISHED"}
