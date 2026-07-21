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


def active_uvmap_by_name(obj, name):
    obj_uvmaps = obj.data.uv_layers
    if obj_uvmaps and name in obj_uvmaps:
        obj_uvmaps.active = obj_uvmaps[name]
        return True
    return False


def _swap_uv_layers(me, i, j):
    # uv_layers has no reorder API; swap the layers' contents in place
    uvs = me.uv_layers
    n = len(uvs[i].uv)

    # pin storage is a lazily-created attribute (.pn.<name>); if either side
    # has pins, create the missing one FIRST — attributes.new() invalidates
    # existing layer references, so all handles are grabbed after this block
    swap_pins = len(uvs[i].pin) == n or len(uvs[j].pin) == n
    if swap_pins:
        for k in (i, j):
            if len(me.uv_layers[k].pin) != n:
                me.attributes.new(".pn." + me.uv_layers[k].name, "BOOLEAN", "CORNER")

    a, b = me.uv_layers[i], me.uv_layers[j]
    buf_a = [0.0] * (n * 2)
    buf_b = [0.0] * (n * 2)
    a.uv.foreach_get("vector", buf_a)
    b.uv.foreach_get("vector", buf_b)
    a.uv.foreach_set("vector", buf_b)
    b.uv.foreach_set("vector", buf_a)

    if swap_pins:
        pin_a = [False] * n
        pin_b = [False] * n
        a.pin.foreach_get("value", pin_a)
        b.pin.foreach_get("value", pin_b)
        a.pin.foreach_set("value", pin_b)
        b.pin.foreach_set("value", pin_a)

    name_a, name_b = a.name, b.name
    a.name = name_a + ".iops_tmp"
    b.name = name_a
    a.name = name_b


def uvmaps_sort_by_name(obj):
    me = obj.data
    uvs = me.uv_layers
    count = len(uvs)
    if count < 2:
        return False
    if [l.name for l in uvs] == sorted((l.name for l in uvs), key=str.lower):
        return False
    active_name = uvs.active.name if uvs.active else None
    render_name = next((l.name for l in uvs if l.active_render), None)
    clone_name = next((l.name for l in uvs if l.active_clone), None)
    # selection sort: put the alphabetically next layer into each slot;
    # re-fetch uv_layers every pass — swaps may create attributes, which
    # invalidates existing layer references
    for slot in range(count):
        uvs = me.uv_layers
        src = min(range(slot, count), key=lambda i: uvs[i].name.lower())
        if src != slot:
            _swap_uv_layers(me, slot, src)
    uvs = me.uv_layers
    if active_name:
        uvs.active = uvs[active_name]
    if render_name:
        uvs[render_name].active_render = True
    if clone_name:
        uvs[clone_name].active_clone = True
    me.update()
    return True



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


class IOPS_OT_Active_UVMap_by_Active_Name(bpy.types.Operator):
    """Set active UVMap on selected objects by name of the active object's active UVMap.
Ctrl+Click: also set it as the render UVMap"""

    bl_idname = "iops.uv_active_uvmap_by_active_name"
    bl_label = "Set Active UVMap by Name on selected objects"
    bl_options = {"REGISTER", "UNDO"}

    set_render: bpy.props.BoolProperty(
        name="Set Render UVMap",
        description="Also set the UVMap as active for rendering",
        default=False,
        options={"SKIP_SAVE"},
    )

    def invoke(self, context, event):
        self.set_render = event.ctrl
        return self.execute(context)

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs and context.active_object in selected_objs:
            if context.active_object.data.uv_layers:
                uvmap_name = context.active_object.data.uv_layers.active.name
                count = 0
                missing = []
                for ob in selected_objs:
                    if active_uvmap_by_name(ob, uvmap_name):
                        if self.set_render:
                            ob.data.uv_layers[uvmap_name].active_render = True
                        count += 1
                    else:
                        missing.append(ob.name)
                tag_redraw(context)
                self.report(
                    {"INFO"},
                    (
                        "UVMap %s set Active%s on %d object(s)"
                        % (uvmap_name, " + Render" if self.set_render else "", count)
                    ),
                )
                if missing:

                    def draw_missing(menu, _context):
                        col = menu.layout.column(align=True)
                        col.label(
                            text="UVMap '%s' not found on:" % uvmap_name,
                            icon="ERROR",
                        )
                        for name in missing:
                            col.label(text=name, icon="OBJECT_DATA")

                    context.window_manager.popup_menu(
                        draw_missing, title="Missing UVMap", icon="UV_DATA"
                    )
        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Sort_UVMaps_by_Name(bpy.types.Operator):
    """Sort UVMaps alphabetically by name on selected objects"""

    bl_idname = "iops.uv_sort_uvmaps_by_name"
    bl_label = "Sort UVMaps by Name on selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if not selected_objs:
            self.report({"ERROR"}, "Select MESH objects.")
            return {"FINISHED"}
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Works in Object Mode only.")
            return {"CANCELLED"}
        # skip instances (linked data) so each mesh is sorted once
        unique_data = set()
        count = 0
        for ob in selected_objs:
            if ob.data in unique_data:
                continue
            unique_data.add(ob.data)
            if uvmaps_sort_by_name(ob):
                count += 1
        tag_redraw(context)
        self.report({"INFO"}, "UVMaps sorted on %d object(s)" % count)
        return {"FINISHED"}
