bl_info = {
	"name": "iOps",
	"author": "Titus, Cyrill",
	"version": (1, 4, 1),
	"blender": (2, 80, 0),
	"location": "View3D > Toolbar and View3D",
	"description": "Interaction operators (iOps) - for workflow speedup",
	"warning": "",
	"wiki_url": "email: Titus.mailbox@gmail.com",
	"tracker_url": "",
	"category": "Mesh"}

import bpy
from bpy.props import *
import math
from mathutils import Vector, Matrix, Euler
import bmesh

#WarningMessage
def ShowMessageBox(text = "", title = "WARNING", icon = "ERROR"):
    def draw(self, context):
        self.layout.label(text = text)        
    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)

#AlignObjToFace
class IOPS_OT_AlignObjectToFace(bpy.types.Operator):
    """ Align object to selected face """
    bl_idname = "iops.align_object_to_face"
    bl_label = "iOps Align object to face"
    bl_options = {"REGISTER","UNDO"}
    
    def execute(self, context):
        self.AlignObjectToFace()
        self.report ({"INFO"}, "Object aligned")
        return{"FINISHED"}
       
    @classmethod   
    def AlignObjectToFace(cls):        
        obj = bpy.context.active_object
        me = obj.data            
        mx = obj.matrix_world
        loc = mx.to_translation()      
        bm = bmesh.from_edit_mesh(me)    
        face = []
        for f in bm.faces:
            if f.select == True:            
                print ("Selected = ",f)
                face = f
                        
        n = face.normal                # Z
        t = face.calc_tangent_edge()   # Y
        c = t.cross(n)                 # X
            
        mx_rot = Matrix((c, t, n)).transposed().to_4x4() 
        obj.matrix_world = mx_rot.inverted()
        obj.location = loc    

class IOPS(bpy.types.Operator):
    bl_idname = "IOPS"
    bl_label = "iOps"
    bl_options = {"REGISTER","UNDO"}

    modes_3d = {0:"VERT", 1:"EDGE", 2:"FACE"}
    modes_uv = {0:"VERTEX", 1:"EDGE", 2:"FACE", 3:"ISLAND"}
    modes_gpen = {0:"EDIT_GPENCIL", 1:"PAINT_GPENCIL", 2:"SCULPT_GPENCIL"}
    modes_curve = {0:"EDIT_CURVE"}
    supported_types = ["MESH", "CURVE", "GPENCIL", "EMPTY"]

    mode_3d = ""
    mode_uv = ""
    mode_gpen = ""
    mode_curve = ""
       
    @classmethod
    def poll(cls, context):                  
        return context.object is not None
      
    def execute(self, context):

        scene = bpy.context.scene

        #Object <-> Mesh
        if bpy.context.active_object.type == "MESH": 
            mode_3d = "VERT" if scene.tool_settings.mesh_select_mode[0] else ""
            mode_3d = "EDGE" if scene.tool_settings.mesh_select_mode[1] else ""
            mode_3d = "FACE" if scene.tool_settings.mesh_select_mode[2] else ""
            # Same modes for active sync in UV 
            if (bpy.context.area.type == "VIEW_3D" or 
               (bpy.context.area.type == "IMAGE_EDITOR" and bpy.context.tool_settings.use_uv_select_sync == True)):
                # Go to Edit Mode       
                if bpy.context.mode == "OBJECT": 
                    bpy.ops.object.mode_set(mode="EDIT")            
                    bpy.ops.mesh.select_mode(type=self.mode_3d)
                    IOPS.mode_3d = self.mode_3d
                    return{"FINISHED"}
                    
                # Switch selection modes
                # If activated same selection mode again switch to Object Mode   
                if bpy.context.mode == "EDIT_MESH" and self.mode_3d != IOPS.mode_3d:                
                    bpy.ops.mesh.select_mode(type=self.mode_3d)
                    IOPS.mode_3d = self.mode_3d
                    return{"FINISHED"}
                else:
                    bpy.ops.object.mode_set(mode="OBJECT")
                    return{"FINISHED"}   

            # UV <-> Mesh 
            if bpy.context.area.type == "IMAGE_EDITOR": 
                # Go to Edit Mode and Select All
                if bpy.context.mode == "OBJECT":
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.context.tool_settings.uv_select_mode = self.mode_uv
                    IOPS.mode_uv = self.mode_uv
                    return{"FINISHED"}

                elif self.mode_uv != IOPS.mode_uv:
                        bpy.context.tool_settings.uv_select_mode = self.mode_uv
                        IOPS.mode_uv = self.mode_uv
                        return{"FINISHED"}
                else:
                        bpy.ops.object.mode_set(mode="OBJECT")
                        return{"FINISHED"} 

        # Object <-> Curve    
        if bpy.context.active_object.type == "CURVE":  
            mode_curve = "EDIT" if bpy.context.mode != "EDIT_CURVE" else "OBJECT" 
            bpy.ops.object.mode_set(mode=mode_curve)                             
            return{"FINISHED"}

        # Object <-> GPencil  
        if bpy.context.active_object.type == "GPENCIL":
            mode_gpen = "EDIT_GPENCIL" if bpy.context.mode != "EDIT_GPENCIL" else "OBJECT" 
            bpy.ops.object.mode_set(mode=mode_gpen)
            return{"FINISHED"} 

        #Unsupported Types      
        if bpy.context.active_object.type not in IOPS.supported_types:
            print(bpy.context.active_object.type,"not supported yet!")
            return{"FINISHED"} 
        return{"FINISHED"}
  
class IOPS_OT_Vert(IOPS):
    bl_idname = "iops.vertex"
    bl_label = "iOps Vertex"
    mode_3d = IOPS.modes_3d[0]
    mode_uv = IOPS.modes_uv[0]
  
class IOPS_OT_Edge(IOPS):
    bl_idname = "iops.edge"
    bl_label = "iOps Edge"
    mode_3d = IOPS.modes_3d[1]
    mode_uv = IOPS.modes_uv[1]
  
class IOPS_OT_Face(IOPS):
    bl_idname = "iops.face"
    bl_label = "iOps Face"
    mode_3d= IOPS.modes_3d[2]
    mode_uv = IOPS.modes_uv[2]
    AlignObjToFace: BoolProperty(
        name = "Align object to selected face",
        description = "Align object to selected face",        
        default = False    
    )
   
class IOPS_OT_Island(IOPS):
    bl_idname = "iops.island"
    bl_label = "iOps Island"
    mode_uv = IOPS.modes_uv[3]

    @classmethod
    def poll(cls, context):
        return bpy.context.area.type == "IMAGE_EDITOR"


class IOPS_OT_CursorOrigin (IOPS):
    bl_idname = "iops.cursor_origin"
    bl_label = "iOps Cursor to Selected/Origin to Cursor"
    def execute(self, context):
        # MESH
        objs = bpy.context.selected_objects              
        if bpy.context.area.type == "VIEW_3D":
            if bpy.context.active_object.type == "MESH":
                if bpy.context.mode == "OBJECT":
                    if len(objs) != 0:
                        for ob in objs:
                            bpy.context.object.location = scene.cursor.location
                            bpy.context.object.rotation_euler = scene.cursor.rotation_euler
                        return{"FINISHED"}
                else:
                        bpy.ops.view3d.snap_cursor_to_selected()
                        bpy.ops.object.editmode_toggle()
                        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                        return{"FINISHED"}
            # CURVE
            if bpy.context.active_object.type == "CURVE":
                if bpy.context.mode != "EDIT_CURVE":
                    if len(objs) != 0:
                        for ob in objs:
                            bpy.context.location = scene.cursor.location
                            bpy.context.rotation_euler = scene.cursor.rotation_euler
                        return{"FINISHED"}
                else:
                    bpy.ops.view3d.snap_cursor_to_selected()
                    bpy.ops.object.editmode_toggle()
                    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                    return{"FINISHED"}
            # EMPTY    
            if bpy.context.active_object.type == "EMPTY":
                if len(objs) != 0:
                    for ob in objs:
                        bpy.context.location = scene.cursor.location
                        bpy.context.rotation_euler = scene.cursor.rotation_euler
                    return{"FINISHED"}
            # GPENCIL
            if bpy.context.active_object.type == "GPENCIL":
                if bpy.context.mode!= "EDIT_GPENCIL":
                    if len(objs) != 0:
                        for ob in objs:
                            bpy.context.location = scene.cursor.location
                            bpy.context.rotation_euler = scene.cursor.rotation_euler
                        return{"FINISHED"}
                else:
                    bpy.ops.gpencil.snap_cursor_to_selected()                
                    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                    bpy.ops.object.mode_set(mode="OBJECT")
                    return{"FINISHED"}     
            if bpy.context.active_object.type not in IOPS.supported_types:
                return{"FINISHED"}
        else:
            print("Not in 3d View!")
            return{"FINISHED"}

                       	
#KeyMaps          
addon_keymaps = []

def register_keymaps():
    # pass
    wm1 = bpy.context.window_manager
    km1 = wm1.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi1 = km1.keymap_items.new("iops.vertex", "F1", "PRESS", alt=False, shift=False)        
    addon_keymaps.append(km1)
    
    wm2 = bpy.context.window_manager
    km2 = wm2.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi2 = km2.keymap_items.new("iops.edge", "F2", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km2)
    
    wm3 = bpy.context.window_manager
    km3 = wm3.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi3 = km3.keymap_items.new("iops.face", "F3", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km3)
    
    wm4 = bpy.context.window_manager
    km4 = wm4.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi4 = km4.keymap_items.new("iops.island", "F4", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km4)
    
    wm5 = bpy.context.window_manager
    km5 = wm5.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi5 = km5.keymap_items.new("iops.cursor_origin", "F4", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km5)
    
def unregister_keymaps():
    wm = bpy.context.window_manager
    for km in addon_keymaps:
        for kmi in km.keymap_items:
            km.keymap_items.remove(kmi)
        wm.keyconfigs.addon.keymaps.remove(km)
    addon_keymaps.clear()

#Classes for reg and unreg
classes = (
            IOPS_OT_Vert,
            IOPS_OT_Edge,
            IOPS_OT_Face,             
            IOPS_OT_CursorOrigin,
            IOPS_OT_AlignObjectToFace,
            IOPS_OT_Island
            )

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps() 
    print ("iOps - Registred!")

def unregister(): 
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_keymaps()
    print ("iOps - UnRegistred!") 
    
if __name__ == "__main__":
    register()