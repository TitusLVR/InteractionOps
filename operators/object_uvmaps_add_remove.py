import bpy



def tag_redraw(context, space_type="VIEW_3D", region_type="WINDOW"):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.spaces[0].type == space_type:
                for region in area.regions:
                    if region.type == region_type:
                        region.tag_redraw()

def uvmap_add(obj):
    obj_uvmaps = obj.data.uv_layers
    ch_num_text = "ch" + str(len(obj_uvmaps) + 1)
    obj_uvmaps.new(name=ch_num_text, do_init=True)


def uvmap_clean_by_name(obj, name):
    obj_uvmaps = obj.data.uv_layers
    if obj_uvmaps and name in obj_uvmaps:
        obj_uvmaps.remove(obj_uvmaps[name])



def active_uvmap_by_active(obj, index):
    obj_uvmaps = obj.data.uv_layers
    if len(obj_uvmaps) >= index + 1:
        obj_uvmaps.active_index = index



class IOPS_OT_Add_UVMap(bpy.types.Operator):
    """Add UVMap to selected objects"""

    bl_idname = "iops.uv_add_uvmap"
    bl_label = "Add UVMap to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objs = [
            o for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            #check for instances
            unique_objects = {}
            filtered_list = []
            for ob in selected_objs:
            # Check if the object is an instance (linked data)
                ob_data= ob.data
                if ob_data not in unique_objects:
                    unique_objects[ob_data] = ob
                    filtered_list.append(ob)
            for ob in filtered_list:
                uvmap_add(ob)
            self.report({"INFO"}, "UVMaps Were Added")
        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Remove_UVMap_by_Active_Name(bpy.types.Operator):
    """Remove UVMap by Name of Active UVMap on selected objects"""

    bl_idname = "iops.uv_remove_uvmap_by_active_name"
    bl_label = "Remove UVMap by Name of Active UVMap on selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs and context.active_object in selected_objs:
            if context.active_object.data.uv_layers:
                uvmap_name = context.active_object.data.uv_layers.active.name
                for ob in selected_objs:
                    if ob.data.uv_layers:
                        uvmap_clean_by_name(ob, uvmap_name)
                        tag_redraw(context)
                self.report({"INFO"}, ("UVMap %s Was Deleted" % (uvmap_name)))
        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Active_UVMap_by_Active(bpy.types.Operator):
    """Remove UVMap by Name of Active UVMap on selected objects"""

    bl_idname = "iops.uv_active_uvmap_by_active_object"
    bl_label = "Set Active UVMap as Active object active UVMap"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs and context.active_object in selected_objs:
            if context.active_object.data.uv_layers:
                uvmap_name = context.active_object.data.uv_layers.active.name
                uvmap_index = context.active_object.data.uv_layers.active_index
                for ob in selected_objs:
                    if ob.data.uv_layers:
                        active_uvmap_by_active(ob, uvmap_index)
                        tag_redraw(context)
                self.report({"INFO"}, ("UVMap %s Active" % (uvmap_name)))
        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}
