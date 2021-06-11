import bpy
import math
# import bmesh
# from mathutils import Matrix, Vector
import copy
from bpy.props import (BoolProperty)

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
    
    per_object: BoolProperty(
        name="Per Object",
        description="Apply Per Object",
        default=False
        )
    reset_cursor: BoolProperty(
        name="Reset Cursor",
        description="Reset Cursor",
        default=True
        )
    

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle
        if self.reset_cursor:            
            bpy.context.scene.cursor.rotation_euler = (0,0,0)
        if self.per_object:
            selection = [o.name for o in context.view_layer.objects.selected]            
            for name in selection:
                ob = bpy.data.objects[name]
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                cursor = ob.location 
                bpy.context.scene.cursor.location =  ob.location
                bpy.context.scene.cursor.rotation_euler = ob.rotation_euler 
                bpy.ops.transform.rotate(value=math.radians(rotation),
                                        center_override=(cursor),
                                        orient_axis='Z',
                                        orient_type='CURSOR',
                                        constraint_axis=(False,False,True),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                                        )
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
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
        self.report({"INFO"}, "IOPS Rotate +Z")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)        
        row.prop(self,"reset_cursor")
        row.prop(self,"per_object")
        col.prop(props,"iops_rotation_angle")


class IOPS_OT_object_rotate_MZ (bpy.types.Operator):
    """ Rotate object local Z-axis -90 degrees """
    bl_idname = "iops.object_rotate_mz"
    bl_label = "IOPS rotate Z-axis - Negative"
    bl_options = {"REGISTER", "UNDO"}

    per_object: BoolProperty(
        name="Per Object",
        description="Apply Per Object",
        default=False
        )
    reset_cursor: BoolProperty(
        name="Reset Cursor",
        description="Reset Cursor",
        default=True
        )

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle * -1
        if self.reset_cursor:            
            bpy.context.scene.cursor.rotation_euler = (0,0,0)
        if self.per_object:
            selection = [o.name for o in context.view_layer.objects.selected]            
            for name in selection:
                ob = bpy.data.objects[name]
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                cursor = ob.location 
                bpy.context.scene.cursor.location =  ob.location
                bpy.context.scene.cursor.rotation_euler = ob.rotation_euler 
                bpy.ops.transform.rotate(value=math.radians(rotation),
                                        center_override=(cursor),
                                        orient_axis='Z',
                                        orient_type='CURSOR',
                                        constraint_axis=(False,False,True),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                                        )
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
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
        self.report({"INFO"}, "IOPS Rotate -Z")                                    
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)        
        row.prop(self,"reset_cursor")
        row.prop(self,"per_object")
        col.prop(props,"iops_rotation_angle")
    
    
class IOPS_OT_object_rotate_Y (bpy.types.Operator):
    """ Rotate object local Y-axis 90 degrees """
    bl_idname = "iops.object_rotate_y"
    bl_label = "IOPS rotate Y-axis - Positive"
    bl_options = {"REGISTER", "UNDO"}

    per_object: BoolProperty(
        name="Per Object",
        description="Apply Per Object",
        default=False
        )
    reset_cursor: BoolProperty(
        name="Reset Cursor",
        description="Reset Cursor",
        default=True
        )

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle
        if self.reset_cursor:            
            bpy.context.scene.cursor.rotation_euler = (0,0,0)
        if self.per_object:
            selection = [o.name for o in context.view_layer.objects.selected]            
            for name in selection:
                ob = bpy.data.objects[name]
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                cursor = ob.location 
                bpy.context.scene.cursor.location =  ob.location
                bpy.context.scene.cursor.rotation_euler = ob.rotation_euler 
                bpy.ops.transform.rotate(value=math.radians(rotation),
                                        center_override=(cursor),
                                        orient_axis='Y',
                                        orient_type='CURSOR',
                                        constraint_axis=(False,True,False),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                                        )
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
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
        self.report({"INFO"}, "IOPS Rotate +Y")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)        
        row.prop(self,"reset_cursor")
        row.prop(self,"per_object")
        col.prop(props,"iops_rotation_angle")

class IOPS_OT_object_rotate_MY (bpy.types.Operator):
    """ Rotate object local Y-axis -90 degrees """
    bl_idname = "iops.object_rotate_my"
    bl_label = "IOPS rotate Y-axis - Negative"
    bl_options = {"REGISTER", "UNDO"}

    per_object: BoolProperty(
        name="Per Object",
        description="Apply Per Object",
        default=False
        )
    reset_cursor: BoolProperty(
        name="Reset Cursor",
        description="Reset Cursor",
        default=True
        )

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle * -1
        if self.reset_cursor:            
            bpy.context.scene.cursor.rotation_euler = (0,0,0)
        if self.per_object:
            selection = [o.name for o in context.view_layer.objects.selected]            
            for name in selection:
                ob = bpy.data.objects[name]
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                cursor = ob.location 
                bpy.context.scene.cursor.location =  ob.location
                bpy.context.scene.cursor.rotation_euler = ob.rotation_euler 
                bpy.ops.transform.rotate(value=math.radians(rotation),
                                        center_override=(cursor),
                                        orient_axis='Y',
                                        orient_type='CURSOR',
                                        constraint_axis=(False,True,False),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                                        )
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
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
        self.report({"INFO"}, "IOPS Rotate -Y")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)        
        row.prop(self,"reset_cursor")
        row.prop(self,"per_object")
        col.prop(props,"iops_rotation_angle")
    
class IOPS_OT_object_rotate_X (bpy.types.Operator):
    """ Rotate object local X-axis 90 degrees """
    bl_idname = "iops.object_rotate_x"
    bl_label = "IOPS rotate X-axis - Positive"
    bl_options = {"REGISTER", "UNDO"}

    per_object: BoolProperty(
        name="Per Object",
        description="Apply Per Object",
        default=False
        )
    reset_cursor: BoolProperty(
        name="Reset Cursor",
        description="Reset Cursor",
        default=True
        )

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle
        if self.reset_cursor:            
            bpy.context.scene.cursor.rotation_euler = (0,0,0)
        if self.per_object:
            selection = [o.name for o in context.view_layer.objects.selected]            
            for name in selection:
                ob = bpy.data.objects[name]
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                cursor = ob.location 
                bpy.context.scene.cursor.location =  ob.location
                bpy.context.scene.cursor.rotation_euler = ob.rotation_euler 
                bpy.ops.transform.rotate(value=math.radians(rotation),
                                        center_override=(cursor),
                                        orient_axis='X',
                                        orient_type='CURSOR',
                                        constraint_axis=(True,False,False),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                                        )
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
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
        self.report({"INFO"}, "IOPS Rotate +X")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)        
        row.prop(self,"reset_cursor")
        row.prop(self,"per_object")
        col.prop(props,"iops_rotation_angle")

class IOPS_OT_object_rotate_MX (bpy.types.Operator):
    """ Rotate object local X-axis -90 degrees """
    bl_idname = "iops.object_rotate_mx"
    bl_label = "IOPS rotate X-axis - Negative"
    bl_options = {"REGISTER", "UNDO"}

    per_object: BoolProperty(
        name="Per Object",
        description="Apply Per Object",
        default=False
        )
    reset_cursor: BoolProperty(
        name="Reset Cursor",
        description="Reset Cursor",
        default=True
        )

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)
    
    def execute(self, context):
        rotation = context.window_manager.IOPS_AddonProperties.iops_rotation_angle * -1
        if self.reset_cursor:            
            bpy.context.scene.cursor.rotation_euler = (0,0,0)
        if self.per_object:
            selection = [o.name for o in context.view_layer.objects.selected]            
            for name in selection:
                ob = bpy.data.objects[name]
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                cursor = ob.location 
                bpy.context.scene.cursor.location =  ob.location
                bpy.context.scene.cursor.rotation_euler = ob.rotation_euler 
                bpy.ops.transform.rotate(value=math.radians(rotation),
                                        center_override=(cursor),
                                        orient_axis='X',
                                        orient_type='CURSOR',
                                        constraint_axis=(True,False,False),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                                        )
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
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
        self.report({"INFO"}, "IOPS Rotate -X")
        return {"FINISHED"}
    
    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)        
        row.prop(self,"reset_cursor")
        row.prop(self,"per_object")
        col.prop(props,"iops_rotation_angle")
