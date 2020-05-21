import bpy
import bmesh
import addon_utils


def ContextOverride(area):
    for window in bpy.context.window_manager.windows:      
        screen = window.screen
        for screen_area in screen.areas:
            if screen_area.ui_type == area.ui_type:            
                for region in screen_area.regions:
                    if region.type == 'WINDOW':               
                        context_override = {'window': window, 
                                            'screen': screen, 
                                            'area': screen_area, 
                                            'region': region, 
                                            'scene': bpy.context.scene, 
                                            'edit_object': bpy.context.edit_object, 
                                            'active_object': bpy.context.active_object, 
                                            'selected_objects': bpy.context.selected_objects
                                            } 
                        return context_override
    raise Exception("ERROR: Override failed!")

def view_selected_uv():
    selected_verts = []
    selected_faces = set()

    view_3d = [area for area in bpy.context.screen.areas if area.type == 'VIEW_3D']
    view_3d = view_3d[0]
    if bpy.context.tool_settings.use_uv_select_sync == False:
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

        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.uv.select_all(action='DESELECT')

        for v in selected_verts:
            v.select = True
        for f in selected_faces:
            f.select = True
    
        bm.select_flush(True)
        bmesh.update_edit_mesh(mesh)

        context_override = ContextOverride(view_3d)
        bpy.ops.view3d.view_selected(context_override)
        bpy.ops.mesh.select_all(action='SELECT')
        
    else:
        context_override = ContextOverride(view_3d)
        bpy.ops.view3d.view_selected(context_override)



def get_iop(dictionary, query):
    uv_flag = bpy.context.tool_settings.use_uv_select_sync
    debug = bpy.context.preferences.addons['InteractionOps'].preferences.IOPS_DEBUG
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
    return (lambda: print("No entry in the dictionary for ", [q for q in query]))


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


def object_mode_switch(mode):
    bpy.ops.object.mode_set(mode=mode)


def align_to_face():
    bpy.ops.iops.align_object_to_face("INVOKE_DEFAULT")


def curve_subdivide():
    bpy.ops.iops.curve_subdivide("INVOKE_DEFAULT")


def curve_spline_type():
    bpy.ops.iops.curve_spline_type("INVOKE_DEFAULT")


def cursor_origin_mesh():
    bpy.ops.iops.cursor_origin_mesh("INVOKE_DEFAULT")


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
    r1 = bmesh.ops.bisect_edges(bm, edges=list(es), cuts=1)['geom_split']
    vs = [a for a in r1 if type(a) == bmesh.types.BMVert]
    r2 = bmesh.ops.connect_verts(bm, verts=vs, check_degenerate=True)['edges']
    for e in r2:
        e.select = True
    bmesh.update_edit_mesh(mesh)


# WarningMessage
def ShowMessageBox(text="", title="WARNING", icon="ERROR"):
    def draw(self, context):
        self.layout.label(text=text)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)



############################## Keymaps ##############################

def register_keymaps(keys): 
    keyconfigs = bpy.context.window_manager.keyconfigs

    keymapItems = bpy.context.window_manager.keyconfigs.addon.keymaps.new("Window").keymap_items
    for k in reversed(keys):
        if str(k[0]).startswith('iops.split_area'):
            continue
        found = False
        for kc in keyconfigs:
            keymap = kc.keymaps.get("Window")
            if keymap:
                kmi = keymap.keymap_items
                for item in kmi:
                    if item.idname.startswith('iops.') and item.idname == str(k[0]):
                        found = True
                    else:
                        found = False
        if not found:
            kmi = keymapItems.new(k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6])
            kmi.active = True
    
    keymapItems = bpy.context.window_manager.keyconfigs.addon.keymaps.new("Screen Editing").keymap_items
    for k in reversed(keys):
        if str(k[0]).startswith('iops.split_area'):
            found = False
            for kc in keyconfigs:
                keymap = kc.keymaps.get("Screen Editing")
                if keymap:
                    kmi = keymap.keymap_items
                    for item in kmi:
                        if item.idname == str(k[0]):
                            found = True
                        else:
                            found = False  
            if not found:
                kmi = keymapItems.new(k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5], oskey=k[6])
                kmi.active = True

def unregister_keymaps():
    keyconfigs = bpy.context.window_manager.keyconfigs
    for kc in keyconfigs:
        for keymap in kc.keymaps:
            if keymap:
                keymapItems = keymap.keymap_items
                toDelete = tuple(
                    item for item in keymapItems if item.idname.startswith('iops.'))
                for item in toDelete:
                    keymapItems.remove(item)