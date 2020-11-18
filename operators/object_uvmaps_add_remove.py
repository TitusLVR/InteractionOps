import bpy

def uvmap_add(obj):
    obj_uvmaps = obj.data.uv_layers    
    ch_num_text = "ch" + str(len(obj_uvmaps)+1)    
    obj_uvmaps.new(name=ch_num_text, do_init=True)

def uvmap_clean_by_name(obj, name):
    obj_uvmaps = obj.data.uv_layers    
    if obj_uvmaps and name in obj_uvmaps:
        obj_uvmaps.remove(obj_uvmaps[name])

def active_uvmap_by_active(obj, index):    
    obj_uvmaps = obj.data.uv_layers
    if len(obj_uvmaps) >= index+1:    
        obj_uvmaps.active_index = index


class IOPS_OT_Add_UVMap(bpy.types.Operator):
    """Add UVMap to selected objects"""
    bl_idname = "iops.add_uvmap"
    bl_label = "Add UVMap to selected objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        selected_objs = [o for o in context.view_layer.objects.selected if o.type == 'MESH' and o.data.polygons[:] != [] and o.visible_get()]
        if selected_objs:
            for ob in selected_objs:
                uvmap_add(ob)
            self.report ({'INFO'}, "UVMaps Were Added")
        else:
            self.report ({'ERROR'}, "Select MESH objects.")
        return {'FINISHED'}

class IOPS_OT_Remove_UVMap_by_Active_Name(bpy.types.Operator):
    """Remove UVMap by Name of Active UVMap on selected objects"""
    bl_idname = "iops.remove_uvmap_by_active_name"
    bl_label = "Remove UVMap by Name of Active UVMap on selected objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene        
        selected_objs = [o for o in context.view_layer.objects.selected if o.type == 'MESH' and o.data.polygons[:] != [] and o.visible_get()]
        if selected_objs and context.active_object in selected_objs:
            uvmap_name = context.active_object.data.uv_layers.active.name           
            for ob in selected_objs:
                uvmap_clean_by_name(ob, uvmap_name)
            self.report ({'INFO'}, ("UVMap %s Was Deleted" % (uvmap_name)))
        else:
            self.report ({'ERROR'}, "Select MESH objects.")
        return {'FINISHED'}

class IOPS_OT_Active_UVMap_by_Active(bpy.types.Operator):
    """Remove UVMap by Name of Active UVMap on selected objects"""
    bl_idname = "iops.active_uvmap_by_active_object"
    bl_label = "Set Active UVMap as Active object active UVMap"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene        
        selected_objs = [o for o in context.view_layer.objects.selected if o.type == 'MESH' and o.data.polygons[:] != [] and o.visible_get()]
        if selected_objs and context.active_object in selected_objs:
            uvmap_name = context.active_object.data.uv_layers.active.name
            uvmap_index = context.active_object.data.uv_layers.active_index        
            for ob in selected_objs:
                active_uvmap_by_active(ob, uvmap_index)
            self.report ({'INFO'}, ("UVMap %s Active" % (uvmap_name)))
        else:
            self.report ({'ERROR'}, "Select MESH objects.")
        return {'FINISHED'}

