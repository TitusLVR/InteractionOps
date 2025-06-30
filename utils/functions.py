import bpy
import bmesh
import addon_utils
import os
import json
from statistics import median, StatisticsError
from mathutils import Vector


def ContextOverride(area):
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for screen_area in screen.areas:
            if screen_area.ui_type == area.ui_type:
                for region in screen_area.regions:
                    if region.type == "WINDOW":
                        context_override = {
                            "window": window,
                            "screen": screen,
                            "area": screen_area,
                            "region": region,
                            "scene": bpy.context.scene,
                            "edit_object": bpy.context.edit_object,
                            "active_object": bpy.context.active_object,
                            "selected_objects": bpy.context.selected_objects,
                        }
                        return context_override
    raise Exception("ERROR: Override failed!")

def get_object_col_names(object):
    found_cols = []
    for col in bpy.data.collections:
        if object.name in col.objects:
            found_cols.append(col.name)
    return '_'.join(found_cols) 

def view_selected_uv():
    active = bpy.context.view_layer.objects.active
    selected_verts = []
    selected_faces = set()

    view_3d = [area for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
    view_3d = view_3d[0]

    if not bpy.context.tool_settings.use_uv_select_sync:
        try:
            mesh = bpy.context.active_object.data
            bm = bmesh.from_edit_mesh(mesh)

            uvl = bm.loops.layers.uv[mesh.uv_layers.active_index]

            for face in bm.faces:
                if not face.select:
                    continue
                for loop in face.loops:
                    if not loop[uvl].select:
                        continue
                    selected_verts.append(loop.vert)
                    selected_faces.add(face)

            med_x = median([x.co[0] for x in selected_verts])
            med_y = median([y.co[1] for y in selected_verts])
            med_z = median([z.co[2] for z in selected_verts])

            # Put cursor to selected verts median
            bpy.context.scene.cursor.location = active.matrix_world @ Vector(
                (med_x, med_y, med_z)
            )

            bpy.ops.mesh.hide(unselected=True)
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.uv.select_all(action="DESELECT")

            for v in selected_verts:
                v.select = True
            for f in selected_faces:
                f.select = True

            bm.select_flush(True)
            bmesh.update_edit_mesh(mesh)

            context_override = ContextOverride(view_3d)
            with bpy.context.temp_override(**context_override):
                bpy.ops.view3d.view_selected()

            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.reveal(select=False)

        except StatisticsError:
            print("Empty selection!")
    else:
        context_override = ContextOverride(view_3d)
        with bpy.context.temp_override(**context_override):
            bpy.ops.view3d.view_selected()


def get_iop(dictionary, query):
    debug = bpy.context.preferences.addons["InteractionOps"].preferences.IOPS_DEBUG
    if debug:
        print("Query from Blender:", query)
    current = dictionary
    for key in query:
        next_ = current.get(key)
        if next_ is None:
            continue
        current = next_
        if not isinstance(current, dict):
            return current
    return lambda: print("No entry in the dictionary for ", [q for q in query])


def get_addon(addon, debug=False):

    # look for addon by name and find folder name and path
    # Note, this will also find addons that aren't registered!

    for mod in addon_utils.modules():
        name = mod.bl_info["name"]
        version = mod.bl_info.get("version", None)
        foldername = mod.__name__
        path = mod.__file__
        enabled = addon_utils.check(foldername)[1]

        if name == addon:
            return enabled, foldername, version, path

    return False, None, None, None


def no_operator():
    print("Operator not defined!")


def uv_select_mode(mode):
    bpy.context.tool_settings.uv_select_mode = mode


def uv_sync_toggle():
    flag = bpy.context.tool_settings.use_uv_select_sync
    bpy.context.tool_settings.use_uv_select_sync = not flag
    print("UV Sync:", flag)


def mesh_select_mode(type):
    if bpy.context.mode == "OBJECT":
        object_mode_switch("EDIT")
    bpy.ops.mesh.select_mode(type=type)

def mesh_selection_convert(type):
    print("Mesh selection convert:", type)
    match type:
        case "VERT":
            bpy.ops.iops.mesh_to_verts()
        case "EDGE":
            bpy.ops.iops.mesh_to_edges()
        case "FACE":
            bpy.ops.iops.mesh_to_faces()

def object_mode_switch(mode):
    bpy.ops.object.mode_set(mode=mode)


def align_to_face():
    bpy.ops.iops.mesh_align_object_to_face("INVOKE_DEFAULT")


def curve_subdivide():
    bpy.ops.iops.curve_subdivide("INVOKE_DEFAULT")


def curve_spline_type():
    bpy.ops.iops.curve_spline_type("INVOKE_DEFAULT")


def cursor_origin_mesh():
    if bpy.context.view_layer.objects.selected[
        :
    ] != [] and bpy.context.view_layer.objects.active.type in {"MESH", "LIGHT"}:
        bpy.ops.iops.cursor_origin_mesh("INVOKE_DEFAULT")
    else:
        print("VisualOrigin: Selection is empty!")


def cursor_origin_selected():
    bpy.ops.view3d.snap_cursor_to_selected()
    bpy.ops.object.editmode_toggle()
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")


def empty_to_cursor():
    scene = bpy.context.scene
    objs = bpy.context.selected_objects
    if len(objs) > 0:
        for ob in objs:
            if ob.type == "EMPTY":
                ob.location = scene.cursor.location
                ob.rotation_euler = scene.cursor.rotation_euler


def match_dimensions():
    selection = bpy.context.view_layer.objects.selected
    active = bpy.context.view_layer.objects.active

    if len(selection) > 0:
        for ob in selection:
            ob.dimensions = active.dimensions


def set_display_mode(mode):
    bpy.context.area.spaces.active.display_mode = mode


############################## ZALOOPOK ##############################
def z_connect():
    mesh = bpy.context.view_layer.objects.active.data
    bm = bmesh.from_edit_mesh(mesh)
    sel = set([a for a in bm.edges if a.select])
    es = set()
    for e in sel:
        e.select = False
        fs = set()
        for lf in e.link_faces:
            if len(set(lf.edges[:]).intersection(sel)) > 1:
                fs.add(lf)
        if fs:
            es.add(e)
    r1 = bmesh.ops.bisect_edges(bm, edges=list(es), cuts=1)["geom_split"]
    vs = [a for a in r1 if type(a) is bmesh.types.BMVert]
    r2 = bmesh.ops.connect_verts(bm, verts=vs, check_degenerate=True)["edges"]
    for e in r2:
        e.select = True
    bmesh.update_edit_mesh(mesh)


# WarningMessage
def ShowMessageBox(text="", title="WARNING", icon="ERROR"):
    def draw(self, context):
        self.layout.label(text=text)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def get_active_and_selected():
    active = bpy.context.view_layer.objects.active
    objects = []
    for ob in bpy.context.view_layer.objects.selected:
        if ob is not active:
            objects.append(ob)
    return active, objects


############################## Keymaps ##############################
old_new_km_map = {
    "iops.call_data_panel": "iops.call_panel_data",
    "iops.call_tm_panel": "iops.call_panel_tm",
    "iops.call_tps_panel": "iops.call_panel_tps",
    "iops.line_up_edges": "iops.z_line_up_edges",
    "iops.eq_edges": "iops.z_eq_edges",
    "iops.drag_snap": "iops.object_drag_snap",
    "iops.drag_snap_uv": "iops.uv_drag_snap_uv",
    "iops.drag_snap_cursor": "iops.object_drag_snap_cursor",
    "iops.f1": "iops.function_f1",
    "iops.f2": "iops.function_f2",
    "iops.f3": "iops.function_f3",
    "iops.f4": "iops.function_f4",
    "iops.f5": "iops.function_f5",
    "iops.esc": "iops.function_esc",
    "iops.to_verts": "iops.mesh_to_verts",
    "iops.to_edges": "iops.mesh_to_edges",
    "iops.to_faces": "iops.mesh_to_faces",
    "iops.align_origin_to_normal": "iops.mesh_align_origin_to_normal",
    "iops.mouseover_fill_select": "iops.mesh_mouseover_fill_select",
    "iops.run_text": "iops.scripts_run_text",
    "iops.call_mt_executor": "iops.scripts_call_mt_executor",
    "iops.to_grid_from_active": "iops.object_to_grid_from_active",
    "iops.modal_three_point_rotation": "iops.object_modal_three_point_rotation",
    "iops.active_object_scroll_up": "iops.object_active_object_scroll_up",
    "iops.active_object_scroll_down": "iops.object_active_object_scroll_down",
}

km_to_remove = ['iops.snap_scroll_down',
             'iops.snap_scroll_up',
             'iops.ppoint_scroll_down',
             'iops.ppoint_scroll_up',
             'iops.axis_scroll_down',
             'iops.axis_scroll_up',
             'iops.prop_scroll_down',
             'iops.prop_scroll_up',
             'iops.object_drag_snap_uv',]


def register_keymaps(keys):
    # keyconfigs = bpy.context.window_manager.keyconfigs
    keymapItems = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        "Window"
    ).keymap_items
    keymapItemsMesh = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        "Mesh"
    ).keymap_items
    keymapItemsObject = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        "Object Mode"
    ).keymap_items
    keymapItemsUV = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        "UV Editor"
    ).keymap_items
    for k in keys:
        # print ("init", k)
        if ".z_" in k[0]:  # Make z_ops in mesh keymaps
            keymapItemsMesh.new(
                k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6]
            )
        elif "iops.mesh" in k[0]:  # Make iops.mesh in mesh keymaps
            keymapItemsMesh.new(
                k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6]
            )
        elif "iops.object" in k[0]:  # Make iops.object in mesh keymaps
            keymapItemsObject.new(
                k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6]
            )
        elif "iops.uv" in k[0]:  # Make iops.object in mesh keymaps
            keymapItemsUV.new(
                k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6]
            )
        else:
            keymapItems.new(
                k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6]
            )
        # print("Registered:", k[0])
    print("IOPS Keymaps registered")


def unregister_keymaps():
    keyconfigs = bpy.context.window_manager.keyconfigs
    for kc in keyconfigs:
        for keymap in kc.keymaps:
            if keymap:
                keymapItems = keymap.keymap_items
                toDelete = tuple(
                    item for item in keymapItems if item.idname.startswith("iops.")
                )
                for item in toDelete:
                    keymapItems.remove(item)
    print("IOPS Keymaps unregistered")

def fix_old_keymaps():
    path = bpy.utils.script_path_user()
    user_hotkeys_file = os.path.join(
        path, "presets", "IOPS", "iops_hotkeys_user.py"
    )
    fixed_km = []

    if os.path.exists(user_hotkeys_file):
        with open(user_hotkeys_file, 'r') as f:
            keys_user_old = json.load(f)
        for km in keys_user_old:
            if km[0] not in km_to_remove:
                if km[0] in old_new_km_map.keys():
                    km[0] = old_new_km_map[km[0]]
                    fixed_km.append(km)
                else:
                    fixed_km.append(km)
        with open(user_hotkeys_file, "w") as f:
            f.write("[" + ",\n".join(json.dumps(i) for i in fixed_km) + "]\n")
