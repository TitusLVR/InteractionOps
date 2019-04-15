bl_info = {
	"name": "iOps",
	"author": "Titus, Cyrill",
	"version": (1, 5, 1),
	"blender": (2, 80, 0),
	"location": "View3D > Toolbar and View3D",
	"description": "Interaction operators (iOps) - for workflow speedup",
	"warning": "",
	"wiki_url": "email: Titus.mailbox@gmail.com",
	"tracker_url": "",
	"category": 'Mesh'}

import bpy
from bpy.props import *
import math
from mathutils import Vector, Matrix, Euler
import bmesh

from bpy.types import (        
        Operator,
        Menu,
        Panel,
        PropertyGroup,
        AddonPreferences,
        )
from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
        PointerProperty,
        StringProperty,
        )

IOPS_KEYMAP_NAME = '3D View Generic' # Name of the user keymap (like a group) where the hotkey entries will be added.
IOPS_KEYMAP_ITEMS = { } # Used for caching keymap items only once.

#WarningMessage
def ShowMessageBox(text = "", title = "WARNING", icon = 'ERROR'):
    def draw(self, context):
        self.layout.label(text = text)        
    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)  

def edgeNum_update(self,context):
    IOPS_OT_AlignObjectToFace.AlignObjectToFace(self.EdgeNum) 

class IOPS_OT_AlignObjectToFace(bpy.types.Operator):
    ''' Align object to selected face '''
    bl_idname = "iops.align_object_to_face"
    bl_label = "iOps Align object to face"
    bl_options = {'REGISTER','UNDO'}
    
    def execute(self, context):
        self.AlignObjectToFace()
        self.report ({'INFO'}, 'Object aligned')
        return{'FINISHED'}
    
    #AlignObjToFace    
    @classmethod   
    def AlignObjectToFace(cls,edgeNum):
                
        obj = bpy.context.active_object
        me = obj.data 
        fEdges = (me.total_edge_sel)
        if edgeNum != 0 :
            if edgeNum <= fEdges:          
                mx = obj.matrix_world
                loc = mx.to_translation()      
                bm = bmesh.from_edit_mesh(me)    
                face = []
                loops = []
                edges = []
                bm.faces.ensure_lookup_table()
                for f in bm.faces:
                    if f.select == True:            
                        print ("Selected = ",f)
                        face = f
                        loops = f.loops
                        edges = f.edges  
                                
                n = face.normal                # Z
                print ("Z(n)=",n)
                #t = face.calc_tangent_edge()   # Y
                bm.edges.ensure_lookup_table()
                t = bm.edges[edgeNum-1].calc_tangent(loops[edgeNum-1])
                print ("Y(t)=",t) 
                c = t.cross(n)                 # X
                print ("X(c)=",c)
                    
                mx_rot = Matrix((c, t, n)).transposed().to_4x4() 
                obj.matrix_world = mx_rot.inverted()
                obj.location = loc
            else:
                ShowMessageBox("Face has only " + str(fEdges) + " edges")
        else:
           ShowMessageBox("Select face please")

class IOPS_OT_Vert(bpy.types.Operator):
    bl_idname = "iops.vertex"
    bl_label = "iOps Vertex"
    bl_options = {'REGISTER','UNDO'}
    
    @classmethod
    def poll(cls, context):                  
        return context.object is not None        
    
    def execute(self, context):
        print (bpy.context.area.type)
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'VIEW_3D':           
            if bpy.context.mode != 'EDIT_MESH':                       
                bpy.ops.object.mode_set(mode='EDIT')            
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
                self.report ({'INFO'}, 'Edit mode - Vertex')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_MESH':                
                if bpy.context.tool_settings.mesh_select_mode[1] == True or bpy.context.tool_settings.mesh_select_mode[2] == True:
                    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
                    self.report ({'INFO'}, 'Vertex select')
                    return{'FINISHED'} 
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'}        
        
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'IMAGE_EDITOR':
            if bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.context.tool_settings.uv_select_mode = 'VERTEX'
                self.report ({'INFO'}, 'UV selection - Vertex')
                return{'FINISHED'}
            elif bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')                
                self.report ({'INFO'}, 'Vertex select')
                return{'FINISHED'}
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                if bpy.context.tool_settings.uv_select_mode == 'EDGE' or bpy.context.tool_settings.uv_select_mode == 'FACE' or bpy.context.tool_settings.uv_select_mode == 'ISLAND':
                    bpy.context.tool_settings.uv_select_mode = 'VERTEX'
                    self.report ({'INFO'}, 'UV selection - Vertex')
                    return{'FINISHED'}
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'} 
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                if bpy.context.tool_settings.mesh_select_mode[1] == True or bpy.context.tool_settings.mesh_select_mode[2] == True:
                    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
                    self.report ({'INFO'}, 'Vertex select')
                    return{'FINISHED'}              
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'}
            
        if bpy.context.active_object.type == 'CURVE' and bpy.context.area.type == 'VIEW_3D':                              
            if bpy.context.mode != 'EDIT_CURVE':                       
                bpy.ops.object.mode_set(mode='EDIT')                
                self.report ({'INFO'}, 'Edit mode - Curve')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_CURVE':
                bpy.ops.object.mode_set(mode='OBJECT')
                self.report ({'INFO'}, 'Object mode')
                return{'FINISHED'} 
        
        if bpy.context.active_object.type == 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':                              
            if bpy.context.mode != 'EDIT_GPENCIL':                       
                bpy.ops.object.mode_set(mode='EDIT_GPENCIL')                
                self.report ({'INFO'}, 'Edit mode - GPencil')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_GPENCIL':
                
                bpy.ops.object.mode_set(mode='OBJECT')
                self.report ({'INFO'}, 'Object mode')
                return{'FINISHED'}                                         
                
        if bpy.context.active_object.type != 'MESH' or bpy.context.active_object.type != 'CURVE' or bpy.context.active_object.type != 'GPENCIL'  and bpy.context.area.type == 'VIEW_3D':
            self.report ({'INFO'}, 'Object type not supported yet!')
            return{'FINISHED'} 

class IOPS_OT_Edge (bpy.types.Operator):
    bl_idname = "iops.edge"
    bl_label = "iOps Edge"
    bl_options = {'REGISTER','UNDO'}
    
    @classmethod
    def poll(cls, context):                  
        return context.object is not None 
    
    def execute(self, context):        
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'VIEW_3D':                              
            if bpy.context.mode != 'EDIT_MESH':                       
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='EDGE')
                self.report ({'INFO'}, 'Edit mode - Edge')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_MESH':                        
                if bpy.context.tool_settings.mesh_select_mode[0] == True or bpy.context.tool_settings.mesh_select_mode[2] == True:
                    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='EDGE')
                    self.report ({'INFO'}, 'Edge select')
                    return{'FINISHED'}                     
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'}
         
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'IMAGE_EDITOR':
            if bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.context.tool_settings.uv_select_mode = 'EDGE'
                self.report ({'INFO'}, 'UV selection - Edge')
                return{'FINISHED'}
            elif bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='EDGE')                
                self.report ({'INFO'}, 'Edge select')
                return{'FINISHED'}
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                if bpy.context.tool_settings.uv_select_mode == 'VERTEX' or bpy.context.tool_settings.uv_select_mode == 'FACE' or bpy.context.tool_settings.uv_select_mode == 'ISLAND':
                    bpy.context.tool_settings.uv_select_mode = 'EDGE'
                    self.report ({'INFO'}, 'UV selection - Edge')
                    return{'FINISHED'}
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'} 
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                if bpy.context.tool_settings.mesh_select_mode[0] == True or bpy.context.tool_settings.mesh_select_mode[2] == True:
                    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='EDGE')
                    self.report ({'INFO'}, 'Edge select')
                    return{'FINISHED'}              
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'}
            
        if bpy.context.active_object.type == 'CURVE' and bpy.context.area.type == 'VIEW_3D':                              
            if bpy.context.mode != 'EDIT_CURVE':
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_CURVE':                                         
                    obj = bpy.context.active_object
                    spline = obj.data.splines.active
                    active_points = []

                    for pt in spline.bezier_points:
                        if pt.select_control_point == True:
                            active_points.append(pt)
     
                    if (len(active_points)) >= 2:
                        bpy.ops.curve.subdivide()               
                        self.report ({'INFO'}, 'Curve divided')
                        return{'FINISHED'}
                    else:
                        bpy.ops.object.mode_set(mode='OBJECT')
                        self.report ({'INFO'}, 'Object mode')
                        return{'FINISHED'}
        
        if bpy.context.active_object.type == 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':                              
            if bpy.context.mode != 'PAINT_GPENCIL':                       
                bpy.ops.object.mode_set(mode='PAINT_GPENCIL')                
                self.report ({'INFO'}, 'Paint mode - GPencil')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_GPENCIL' or bpy.context.mode == 'SCULPT_GPENCIL':                
                    bpy.ops.object.mode_set(mode='PAINT_GPENCIL')
                    self.report ({'INFO'}, 'Paint mode - GPencil')
                    return{'FINISHED'}                               
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
                self.report ({'INFO'}, 'Object mode')
                return{'FINISHED'}                  
                    
        if bpy.context.active_object.type != 'MESH' or bpy.context.active_object.type != 'CURVE' or bpy.context.active_object.type != 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':
            self.report ({'INFO'}, 'Object type not supported!')
            return{'FINISHED'}

class IOPS_OT_Face (bpy.types.Operator):
    bl_idname = "iops.face"
    bl_label = "iOps Face"
    bl_options = {'REGISTER','UNDO'}
    
    AlignObjToFace: BoolProperty(
        name = "Align object to selected face",
        description = "Align object to selected face (Z-Axis)",        
        default = False,           
        )
    EdgeNum: IntProperty(
        name = "Edge tangent:",
        description = "Edge as Y-Axis",        
        default = 1,
        soft_min = 1,        
        update = edgeNum_update,       
        )
    
    @classmethod
    def poll(cls, context):                  
        return context.object is not None  
    
    def execute(self, context):
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'VIEW_3D':                           
            if bpy.context.mode != 'EDIT_MESH':                      
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='FACE')
                self.report ({'INFO'}, 'Edit mode - Face')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_MESH':
                if self.AlignObjToFace != True:                
                    if bpy.context.tool_settings.mesh_select_mode[0] == True or bpy.context.tool_settings.mesh_select_mode[1] == True:
                        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='FACE')                    
                        self.report ({'INFO'}, 'Face select')
                        return{'FINISHED'}
                    else:  
                        bpy.ops.object.mode_set(mode='OBJECT')
                        self.report ({'INFO'}, 'Object mode')
                        return{'FINISHED'}
                else: 
                    
                    IOPS_OT_AlignObjectToFace.AlignObjectToFace(self.EdgeNum)
                    print (self.EdgeNum)
                    self.report ({'INFO'}, 'Object aligned to face.')
                    return{'FINISHED'}
                
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'IMAGE_EDITOR':
            if bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.context.tool_settings.uv_select_mode = 'FACE'
                self.report ({'INFO'}, 'UV selection - Face')
                return{'FINISHED'}
            elif bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='FACE')                
                self.report ({'INFO'}, 'Face select')
                return{'FINISHED'}
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                if bpy.context.tool_settings.uv_select_mode == 'VERTEX' or bpy.context.tool_settings.uv_select_mode == 'EDGE' or bpy.context.tool_settings.uv_select_mode == 'ISLAND':
                    bpy.context.tool_settings.uv_select_mode = 'FACE'
                    self.report ({'INFO'}, 'UV selection - Face')
                    return{'FINISHED'}
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'} 
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                if bpy.context.tool_settings.mesh_select_mode[0] == True or bpy.context.tool_settings.mesh_select_mode[1] == True:
                    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='FACE')
                    self.report ({'INFO'}, 'Face select')
                    return{'FINISHED'}              
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'}
         
        if bpy.context.active_object.type == 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':                              
            if bpy.context.mode != 'SCULPT_GPENCIL':                       
                bpy.ops.object.mode_set(mode='SCULPT_GPENCIL')                
                self.report ({'INFO'}, 'Sculpt mode - GPencil')
                return{'FINISHED'}                           
            elif bpy.context.mode == 'EDIT_GPENCIL' or bpy.context.mode == 'PAINT_GPENCIL':                
                    bpy.ops.object.mode_set(mode='SCULPT_GPENCIL')
                    self.report ({'INFO'}, 'Sculpt mode - GPencil')
                    return{'FINISHED'}                               
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
                self.report ({'INFO'}, 'Object mode')
                return{'FINISHED'}                  
        
        if bpy.context.active_object.type != 'MESH' or bpy.context.active_object.type != 'CURVE' or bpy.context.active_object.type != 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':
            self.report ({'INFO'}, 'Object type not supported!')
            return{'FINISHED'}
                  

class IOPS_OT_CursorOrigin (bpy.types.Operator):
    bl_idname = "iops.cursor_origin"
    bl_label = "iOps Cursor to Selected/Origin to Cursor"
    bl_options = {'REGISTER','UNDO'}
    
    @classmethod
    def poll(cls, context):                  
        return context.object is not None
    
    def execute(self, context):        
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'VIEW_3D':
            scn = bpy.context.scene
            objs = bpy.context.selected_objects              
            if bpy.context.mode != 'EDIT_MESH':
                if len(objs) != 0:
                    for ob in objs:
                        ob.location = scn.cursor.location
                        ob.rotation_euler = scn.cursor.rotation_euler
                    self.report ({'INFO'}, 'Object aligned!')
                    return{'FINISHED'}
            else:                
                bpy.ops.view3d.snap_cursor_to_selected()
                bpy.ops.object.editmode_toggle()
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                self.report ({'INFO'}, 'Origin placed!')
                return{'FINISHED'}
        
        if bpy.context.active_object.type == 'MESH' and bpy.context.area.type == 'IMAGE_EDITOR':
            if bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.context.tool_settings.uv_select_mode = 'ISLAND'
                self.report ({'INFO'}, 'UV selection - Island')
                return{'FINISHED'}
            elif bpy.context.mode != 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.context.tool_settings.use_uv_select_sync = False               
                self.report ({'INFO'}, 'UV and Edit mode selection sync - Disabled')
                return{'FINISHED'}
            
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == False:
                if bpy.context.tool_settings.uv_select_mode == 'VERTEX' or bpy.context.tool_settings.uv_select_mode == 'EDGE' or bpy.context.tool_settings.uv_select_mode == 'FACE':
                    bpy.context.tool_settings.uv_select_mode = 'ISLAND'
                    self.report ({'INFO'}, 'UV selection - Island')
                    return{'FINISHED'}
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'} 
            elif bpy.context.mode == 'EDIT_MESH' and bpy.context.tool_settings.use_uv_select_sync == True:
                bpy.context.tool_settings.use_uv_select_sync = False 
                self.report ({'INFO'}, 'UV and Edit mode selection sync - Disabled')
                return{'FINISHED'}              
            else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    self.report ({'INFO'}, 'Object mode')
                    return{'FINISHED'}
        
        if bpy.context.active_object.type == 'CURVE' and bpy.context.area.type == 'VIEW_3D':
            scn = bpy.context.scene
            objs = bpy.context.selected_objects               
            if bpy.context.mode != 'EDIT_CURVE':
                if len(objs) != 0:
                    for ob in objs:
                        ob.location = scn.cursor.location
                        ob.rotation_euler = scn.cursor.rotation_euler
                    self.report ({'INFO'}, 'Object aligned!')
                    return{'FINISHED'}
            else:
                bpy.ops.view3d.snap_cursor_to_selected()
                bpy.ops.object.editmode_toggle()
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                self.report ({'INFO'}, 'Origin placed!')
                return{'FINISHED'}
            
        if bpy.context.active_object.type == 'EMPTY' and bpy.context.area.type == 'VIEW_3D':
            scn = bpy.context.scene
            objs = bpy.context.selected_objects
            if len(objs) != 0:
                for ob in objs:
                    ob.location = scn.cursor.location
                    ob.rotation_euler = scn.cursor.rotation_euler
                self.report ({'INFO'}, 'Object aligned!')
                return{'FINISHED'}
        
        if bpy.context.active_object.type == 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':
            scn = bpy.context.scene
            objs = bpy.context.selected_objects               
            if bpy.context.mode != 'EDIT_GPENCIL':
                if len(objs) != 0:
                    for ob in objs:
                        ob.location = scn.cursor.location
                        ob.rotation_euler = scn.cursor.rotation_euler
                    self.report ({'INFO'}, 'Object aligned!')
                    return{'FINISHED'}
            else:
                bpy.ops.gpencil.snap_cursor_to_selected()                
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                bpy.ops.object.mode_set(mode='OBJECT')
                self.report ({'INFO'}, 'Origin placed!')
                return{'FINISHED'}
        
        if bpy.context.active_object.type != 'MESH' or bpy.context.active_object.type != 'CURVE' or bpy.context.active_object.type != 'EMPTY' or bpy.context.active_object.type != 'GPENCIL' and bpy.context.area.type == 'VIEW_3D':
            self.report ({'INFO'}, 'Object type not supported!')
            return{'FINISHED'}

class IOPS_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    def draw(self, context):
        layout = self.layout      

        # Keymaps.
        box = layout.box()
        box.label(text='Keymaps:')
        try:
            mainRow = box.row(align=True)
            mainRow.alignment = 'LEFT'            

            colLabels = mainRow.column(align=True)
            colLabels.alignment = 'RIGHT'

            colKeys = mainRow.column(align=True)
            colKeys.alignment = 'EXPAND'

            keymap = context.window_manager.keyconfigs.user.keymaps[IOPS_KEYMAP_NAME]
            colKeys.context_pointer_set("keymap", keymap) # For the 'wm.keyitem_restore' operator.

            for item in keymap.keymap_items:
                if item.idname.startswith('iops.'):
                    colLabels.label(text = item.idname.split('.')[1] + ':')
                    subRow = colKeys.row()
                    subRow.alignment = 'LEFT'
                    subRow.prop(item, 'type', text='', full_event=True)
                    subRow.prop(item, 'shift')
                    subRow.prop(item, 'ctrl')
                    subRow.prop(item, 'alt')
                    if item.is_user_modified:
                        subRow.operator('preferences.keyitem_restore', text='', icon='BACK').item_id = item.id
        except:
            layout.label(text='No keymaps found.', icon='ERROR') 

classes = (
            IOPS_OT_Vert,
            IOPS_OT_Edge,
            IOPS_OT_Face,             
            IOPS_OT_CursorOrigin,
            IOPS_OT_AlignObjectToFace,
            IOPS_AddonPreferences,
            )

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
  
    keymapItems = bpy.context.window_manager.keyconfigs.addon.keymaps.new(IOPS_KEYMAP_NAME, space_type='VIEW_3D', region_type='WINDOW').keymap_items
    kmi = keymapItems.new('iops.cursor_origin', 'F4', 'PRESS')    
    kmi.active = True
    kmi = keymapItems.new('iops.face', 'F3', 'PRESS')    
    kmi.active = True
    kmi = keymapItems.new('iops.edge','F2', 'PRESS')    
    kmi.active = True
    kmi = keymapItems.new('iops.vertex', 'F1', 'PRESS')
    kmi.active = True     
    
    print ("iOps - Registred!")

def unregister():    
       
    allKeymaps = bpy.context.window_manager.keyconfigs.addon.keymaps
    keymap = allKeymaps.get(IOPS_KEYMAP_NAME)
    if keymap:
        keymapItems = keymap.keymap_items
        toDelete = tuple(
            item for item in keymapItems if item.properties.name.startswith('iops.')
        )
        for item in toDelete:
            keymapItems.remove(item)     
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
   
    print ("iOps - UnRegistred!") 
    
if __name__ == "__main__":
    register()


