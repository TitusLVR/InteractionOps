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
	"category": "Meshimport bfrom bpy.props import *
import math
from mathutils import Vector, Matrix, Euler
import bmesh
import iops

# WarningMessage
def ShowMessageBox(text = "", title = "WARNING", icon = "ERROR"):
    def draw(self, context):
        self.layout.label(text = text)        
    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)
                  	
#KeyMaps          
addon_keymaps = []

def register_keymaps():
    # pass
    wm1 = bpy.context.window_manager
    km1 = wm1.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi1 = km1.keymap_items.new("iops.mode_f1", "F1", "PRESS", alt=False, shift=False)        
    addon_keymaps.append(km1)
    
    wm2 = bpy.context.window_manager
    km2 = wm2.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi2 = km2.keymap_items.new("iops.mode_f2", "F2", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km2)
    
    wm3 = bpy.context.window_manager
    km3 = wm3.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi3 = km3.keymap_items.new("iops.mode_f3", "F3", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km3)
    
    wm4 = bpy.context.window_manager
    km4 = wm4.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi4 = km4.keymap_items.new("iops.mode_f4", "F4", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km4)
    
    wm5 = bpy.context.window_manager
    km5 = wm5.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi5 = km5.keymap_items.new("iops.cursor_origin", "F4", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km5)
    
    wm6 = bpy.context.window_manager
    km6 = wm6.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY",  region_type="WINDOW")
    kmi6 = km6.keymap_items.new("iops.align_object_to_face", "F6", "PRESS", alt=False, shift=False)     
    addon_keymaps.append(km6)
    
def unregister_keymaps():
    wm = bpy.context.window_manager
    for km in addon_keymaps:
        for kmi in km.keymap_items:
            km.keymap_items.remove(kmi)
        wm.keyconfigs.addon.keymaps.remove(km)
    addon_keymaps.clear()

#Classes for reg and unreg
classes = (
            IOPS_MODE_F1,
            IOPS_MODE_F2,
            IOPS_MODE_F3,             
            IOPS_MODE_F4,
            IOPS_CursorOrigin,
            IOPS_AlignObjectToFace
            )

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps() 
    print ("iOps Registred!")

def unregister(): 
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_keymaps()
    print ("iOps UnRegistred!") 
    
if __name__ == "__main__":
    register()