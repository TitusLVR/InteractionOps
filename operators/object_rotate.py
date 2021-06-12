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

def iops_rotate(angle, object, axis, axis_x, axis_y, axis_z):
    cursor = bpy.context.scene.cursor
    cursor.location = object.location
    cursor.rotation_euler = object.rotation_euler    
    bpy.ops.transform.rotate(value=math.radians(angle),
                                        center_override=(cursor.location),
                                        orient_axis=axis,
                                        orient_type='CURSOR',
                                        constraint_axis=(axis_x,axis_y,axis_z),
                                        use_accurate=True,                                     
                                        orient_matrix_type='CURSOR'                                     
                            )
def iops_per_obj(name):
    ob = bpy.data.objects[name]
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    return ob

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
                ob = iops_per_obj(name)
                iops_rotate(rotation, ob, "Z", False, False, True)
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
            obj = bpy.context.view_layer.objects.active
            iops_rotate(rotation, obj, "Z", False, False, True)
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
                ob = iops_per_obj(name)
                iops_rotate(rotation, ob, "Z", False, False, True)
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
            obj = bpy.context.view_layer.objects.active
            iops_rotate(rotation, obj, "Z", False, False, True)
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
                ob = iops_per_obj(name)              
                iops_rotate(rotation, ob, "Y", False, True, False)
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
            obj = bpy.context.view_layer.objects.active
            iops_rotate(rotation, obj, "Y", False, True, False)
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
                ob = iops_per_obj(name)
                iops_rotate(rotation, ob, "Y", False, True, False)
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
            obj = bpy.context.view_layer.objects.active
            iops_rotate(rotation, obj, "Y", False, True, False)
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
                ob = iops_per_obj(name)
                iops_rotate(rotation, ob, "X", True, False, False)
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
            obj = bpy.context.view_layer.objects.active
            iops_rotate(rotation, obj, "X", True, False, False)
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
                ob = iops_per_obj(name)
                iops_rotate(rotation, ob, "X", True, False, False)
            for name in selection:
                bpy.data.objects[name].select_set(True)
             
        else:
            obj = bpy.context.view_layer.objects.active
            iops_rotate(rotation, obj, "X", True, False, False)
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
