import bpy
import math
import bmesh
from mathutils import Matrix, Vector
from bpy.props import FloatProperty


def round_rotation(obj):
        # x = round(math.degrees(obj.rotation_euler.x),2) 
        # y = round(math.degrees(obj.rotation_euler.y),2) 
        # z = round(math.degrees(obj.rotation_euler.z),2)
        # obj.rotation_euler.x = math.radians(x)
        # obj.rotation_euler.y = math.radians(y)
        # obj.rotation_euler.z = math.radians(z) 
        pass # WAS A BAD IDEA


class IOPS_OT_object_rotate_Z (bpy.types.Operator):
    """ Rotate object local Z-axis 90 degrees """
    bl_idname = "iops.object_rotate_z"
    bl_label = "IOPS rotate Z-axis - Positive"
    bl_options = {"REGISTER", "UNDO"}    

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location =  context.view_layer.objects.active.location
        bpy.context.scene.cursor.rotation_euler = context.view_layer.objects.active.rotation_euler 
        bpy.ops.transform.rotate(value=math.radians(rotation),
                                    center_override=(cursor),
                                    orient_axis='Z',
                                    orient_type='CURSOR',
                                    constraint_axis=(False,False,True),
                                    use_accurate=True,                                     
                                    orient_matrix_type='CURSOR'                                     
                                )
        # for obj in selection:
        #     round_rotation(obj)
        self.report({"INFO"}, "IOPS Rotate +Z")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout        
        row = layout.row(align=True)
        row.prop(props,"iops_rotation_angle")


class IOPS_OT_object_rotate_MZ (bpy.types.Operator):
    """ Rotate object local Z-axis -90 degrees """
    bl_idname = "iops.object_rotate_mz"
    bl_label = "IOPS rotate Z-axis - Negative"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle * -1
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location = context.view_layer.objects.active.location 
        bpy.context.scene.cursor.rotation_euler = context.view_layer.objects.active.rotation_euler
        bpy.ops.transform.rotate(value=math.radians(rotation),
                                    center_override=(cursor),
                                    orient_axis='Z',
                                    orient_type='CURSOR',
                                    constraint_axis=(False,False,True),
                                    use_accurate=True,
                                    orient_matrix_type='CURSOR'                                   
                                )
        # for obj in selection:
        #    round_rotation(obj)
        self.report({"INFO"}, "IOPS Rotate -Z")                                    
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout        
        row = layout.row(align=True)
        row.prop(props,"iops_rotation_angle")
    
    
class IOPS_OT_object_rotate_Y (bpy.types.Operator):
    """ Rotate object local Y-axis 90 degrees """
    bl_idname = "iops.object_rotate_y"
    bl_label = "IOPS rotate Y-axis - Positive"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location = context.view_layer.objects.active.location
        bpy.context.scene.cursor.rotation_euler = context.view_layer.objects.active.rotation_euler           
        bpy.ops.transform.rotate(value=math.radians(rotation),
                                    center_override=(cursor),
                                    orient_axis='Y',
                                    orient_type='CURSOR',
                                    constraint_axis=(False,True,False),
                                    use_accurate=True,
                                    orient_matrix_type='CURSOR'
                                )
        # for obj in selection:
        #     round_rotation(obj)
        self.report({"INFO"}, "IOPS Rotate +Y")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout        
        row = layout.row(align=True)
        row.prop(props,"iops_rotation_angle")

class IOPS_OT_object_rotate_MY (bpy.types.Operator):
    """ Rotate object local Y-axis -90 degrees """
    bl_idname = "iops.object_rotate_my"
    bl_label = "IOPS rotate Y-axis - Negative"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle * -1
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location =  context.view_layer.objects.active.location
        bpy.context.scene.cursor.rotation_euler = context.view_layer.objects.active.rotation_euler 
        bpy.ops.transform.rotate(value=math.radians(rotation),
                                    center_override=(cursor),
                                    orient_axis='Y',
                                    orient_type='CURSOR',
                                    constraint_axis=(False,True,False),
                                    use_accurate=True,
                                    orient_matrix_type='CURSOR'
                                )
        # for obj in selection:
        #     round_rotation(obj)
        self.report({"INFO"}, "IOPS Rotate -Y")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout        
        row = layout.row(align=True)
        row.prop(props,"iops_rotation_angle")
    
class IOPS_OT_object_rotate_X (bpy.types.Operator):
    """ Rotate object local X-axis 90 degrees """
    bl_idname = "iops.object_rotate_x"
    bl_label = "IOPS rotate X-axis - Positive"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location   
        bpy.context.scene.cursor.location =  context.view_layer.objects.active.location
        bpy.context.scene.cursor.rotation_euler = context.view_layer.objects.active.rotation_euler               
        bpy.ops.transform.rotate(value=math.radians(rotation),
                                    center_override=(cursor),
                                    orient_axis='X',
                                    orient_type='CURSOR',
                                    constraint_axis=(True,False,False),
                                    use_accurate=True,
                                    orient_matrix_type='CURSOR'
                                )
        # for obj in selection:
        #     round_rotation(obj)
        self.report({"INFO"}, "IOPS Rotate +X")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout        
        row = layout.row(align=True)
        row.prop(props,"iops_rotation_angle")

class IOPS_OT_object_rotate_MX (bpy.types.Operator):
    """ Rotate object local X-axis -90 degrees """
    bl_idname = "iops.object_rotate_mx"
    bl_label = "IOPS rotate X-axis - Negative"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle * -1
        selection = context.view_layer.objects.selected
        cursor = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location =  context.view_layer.objects.active.location
        bpy.context.scene.cursor.rotation_euler = context.view_layer.objects.active.rotation_euler 
        bpy.ops.transform.rotate(value=math.radians(rotation),
                                    center_override=(cursor),
                                    orient_axis='X',
                                    orient_type='CURSOR',
                                    constraint_axis=(True,False,False),
                                    use_accurate=True,
                                    orient_matrix_type='CURSOR'
                                )   
        # for obj in selection:
        #     round_rotation(obj)            
        self.report({"INFO"}, "IOPS Rotate -X")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout        
        row = layout.row(align=True)
        row.prop(props,"iops_rotation_angle")
