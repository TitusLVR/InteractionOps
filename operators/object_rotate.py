import bpy
import math
import bmesh
from mathutils import Matrix, Vector

from bpy.props import (
        BoolProperty,       
        IntProperty,
        FloatProperty        
        )

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
        return {"FINISHED"}
    
    
class IOPS_OT_object_rotate_Y (bpy.types.Operator):
    """ Rotate object local Y-axis 45 degrees """
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
        return {"FINISHED"}


class IOPS_OT_object_normalize (bpy.types.Operator):
    """ Normalize location,Rotation,Scale,Dimensions values """
    bl_idname = "iops.object_normalize"
    bl_label = "IOPS object normalize"
    bl_options = {"REGISTER", "UNDO"}

    precision: IntProperty(
        name="Precision",
        description="Digits after point",
        default=2,
        soft_min=0,
        soft_max=10
    )
    location: BoolProperty(
        name="Trim location",
        description="Trim location values",
        default=True
    )
    rotation: BoolProperty(
        name="Trim rotation",
        description="Trim rotation values",
        default=True
    )
    
    dimensions: BoolProperty(
        name="Trim dimentsion",
        description="Trim dimentsion values",
        default=True
    )                

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                (context.view_layer.objects.active.type == "MESH" or context.view_layer.objects.active.type == "EMPTY"))
    
    def execute(self, context):
        selection = context.view_layer.objects.selected
        dg = bpy.context.evaluated_depsgraph_get()        
        for ob in selection:
            if self.location:            
                pos_x = round(ob.location.x, self.precision)
                pos_y = round(ob.location.y, self.precision)
                pos_z = round(ob.location.z, self.precision)
                ob.location.x = pos_x
                ob.location.y = pos_y
                ob.location.z = pos_z
            
            if self.rotation:
                rot_x = round(math.degrees(ob.rotation_euler.x), self.precision)
                rot_y = round(math.degrees(ob.rotation_euler.y), self.precision)
                rot_z = round(math.degrees(ob.rotation_euler.z), self.precision)
                ob.rotation_euler.x = math.radians(rot_x)
                ob.rotation_euler.y = math.radians(rot_y)
                ob.rotation_euler.z = math.radians(rot_z)
            
            if self.dimensions:
                dim_x = round(ob.dimensions.x, self.precision)
                dim_y = round(ob.dimensions.y, self.precision)
                dim_z = round(ob.dimensions.z, self.precision)
                ob.dimensions = Vector((dim_x, dim_y, dim_z))                
        dg.update() 
        return {"FINISHED"}           

class IOPS_OT_mesh_to_grid (bpy.types.Operator):
    """ Gridify vertex position """
    bl_idname = "iops.mesh_to_grid"
    bl_label = "IOPS mesh_to_grid"
    bl_options = {"REGISTER", "UNDO"}

    base: FloatProperty(
        name="Base",
        description="Nearest grid number in scene units (0.01 = 1cm, 10 = 10m)",
        default=0.01,
        soft_min=0.01,
        soft_max=10
    )        

    @classmethod 
    def poll(self, context):
        return context.mode == "EDIT_MESH"
    
    def round_to_base(self, coord, base):
        return base * round(coord/base)

    def execute(self, context):
        dg = bpy.context.evaluated_depsgraph_get()   
        ob = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(ob.data)

        for v in bm.verts:            
            pos_x = self.round_to_base(v.co[0], self.base)
            pos_y = self.round_to_base(v.co[1], self.base)
            pos_z = self.round_to_base(v.co[2], self.base)

            v.co = (pos_x, pos_y, pos_z)

        bmesh.update_edit_mesh(bm)
        dg.update()
                
        return {"FINISHED"}           
    

classes = (IOPS_OT_object_rotate_Z,
           IOPS_OT_object_rotate_MZ,
           IOPS_OT_object_rotate_Y,
           IOPS_OT_object_rotate_MY,
           IOPS_OT_object_rotate_X,
           IOPS_OT_object_rotate_MX,
           IOPS_OT_object_normalize,
           IOPS_OT_mesh_to_grid,
           )

reg_cls, unreg_cls = bpy.utils.register_classes_factory(classes)

def register():
    reg_cls()


def unregister():
    unreg_cls()


if __name__ == "__main__":
    register()

   

