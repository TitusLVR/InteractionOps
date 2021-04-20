import bpy

iops_spc = ['TOOL', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'OBJECT', 'MODIFIER', 'PARTICLES', 'PHYSICS', 'CONSTRAINT', 'DATA', 'MATERIAL', 'TEXTURE']
iops_axis_types = ['GLOBAL', 'LOCAL', 'NORMAL', 'GIMBAL', 'VIEW', 'CURSOR']
iops_ppoint_types =['BOUNDING_BOX_CENTER','CURSOR','INDIVIDUAL_ORIGINS','MEDIAN_POINT','ACTIVE_ELEMENT'] 
iops_snap_types = ['CLOSEST','CENTER','MEDIAN','ACTIVE']

def set_space_context(idx):
    areas = [a.type for a in bpy.context.screen.areas]
    area_index = areas.index("PROPERTIES")
    if "PROPERTIES" in areas:   
        bpy.context.screen.areas[area_index].spaces.active.context = iops_spc[idx]

def set_axis_type(idx):
    bpy.context.scene.transform_orientation_slots[0].type = iops_axis_types[idx]

def set_ppoint_type(idx):
    bpy.context.scene.tool_settings.transform_pivot_point = iops_ppoint_types[idx]  

def set_snap_type(idx):
    bpy.context.scene.tool_settings.snap_target = iops_snap_types[idx] 


def try_next(dict,idx):    
    if idx <= len(dict):
        idx += 1 
        try:
            if dict == iops_spc:
                set_space_context(idx)
            
            if dict == iops_axis_types:
                set_axis_type(idx)
            
            if dict == iops_ppoint_types:
                set_ppoint_type(idx)
            
            if dict == iops_snap_types:
                set_snap_type(idx)
        
        except TypeError:
            try_next(dict, idx)
        except IndexError:
            idx = 0
            if dict == iops_spc:
                set_space_context(idx)

            if dict == iops_axis_types:
                set_axis_type(idx)
           
            if dict == iops_ppoint_types:
                set_ppoint_type(idx)
            
            if dict == iops_snap_types:
                set_snap_type(idx)
    else:
        idx = 0
        if dict == iops_spc:
            set_space_context(idx)
        
        if dict == iops_axis_types:
            set_axis_type(idx)
        
        if dict == iops_ppoint_types:
            set_ppoint_type(idx)
        
        if dict == iops_snap_types:
            set_snap_type(idx)

def try_prev(dict, idx):    
    if idx > 0 and idx <= len(dict):
        idx -= 1
        try:
            if dict == iops_spc:
                set_space_context(idx)

            if dict == iops_axis_types:
                set_axis_type(idx)
           
            if dict == iops_ppoint_types:
                set_ppoint_type(idx)
            
            if dict == iops_snap_types:
                set_snap_type(idx)
        except TypeError:
            try_prev(dict, idx)
        except IndexError:
            idx = 0
            if dict == iops_spc:
                set_space_context(idx)

            if dict == iops_axis_types:
                set_axis_type(idx)
           
            if dict == iops_ppoint_types:
                set_ppoint_type(idx)
            
            if dict == iops_snap_types:
                set_snap_type(idx)
    else:
        idx = len(dict) - 1
        try:
            if dict == iops_spc:
                set_space_context(idx)

            if dict == iops_axis_types:
                set_axis_type(idx)
           
            if dict == iops_ppoint_types:
                set_ppoint_type(idx)
            
            if dict == iops_snap_types:
                set_snap_type(idx)
        except TypeError:
            try_prev(dict, idx - 1)

class IOPS_OT_PropScroll_UP(bpy.types.Operator):
    """Cyclic switching properties types UP"""
    bl_idname = "iops.prop_scroll_up"
    bl_label = "Cyclic switching properties types UP"

    def execute(self, context):
        areas = [a.type for a in context.screen.areas]        
        if "PROPERTIES" in areas:
            area_index = areas.index("PROPERTIES")                                                 
            idx = iops_spc.index(bpy.context.screen.areas[area_index].spaces.active.context) 
            try:
                try_prev(iops_spc, idx)
            except TypeError:
                try_prev(iops_spc, idx)
        return {'FINISHED'}   


class IOPS_OT_PropScroll_DOWN(bpy.types.Operator):
    """Cyclic switching properties types DOWN"""
    bl_idname = "iops.prop_scroll_down"
    bl_label = "Cyclic switching properties types Down"

    def execute(self, context):
        areas = [a.type for a in context.screen.areas]
        if "PROPERTIES" in areas:
            area_index = areas.index("PROPERTIES")
            idx = iops_spc.index(bpy.context.screen.areas[area_index].spaces.active.context)
            try:
                try_next(iops_spc, idx)
            except TypeError:
                try_next(iops_spc, idx)            
        return {'FINISHED'}


class IOPS_OT_Axis_Scroll_UP(bpy.types.Operator):
    """Cyclic switching axis types UP"""
    bl_idname = "iops.axis_scroll_up"
    bl_label = "Cyclic switching axis types UP"

    def execute(self, context):
        idx = iops_axis_types.index(context.scene.transform_orientation_slots[0].type)
        try:
            try_prev(iops_axis_types, idx)
        except TypeError:
            try_prev(iops_axis_types, idx)
        self.report ({'INFO'}, "Axis Type: " + context.scene.transform_orientation_slots[0].type)
        return {'FINISHED'} 

class IOPS_OT_Axis_Scroll_DOWN(bpy.types.Operator):
    """Cyclic switching axis types UP"""
    bl_idname = "iops.axis_scroll_down"
    bl_label = "Cyclic switching axis types DOWN"

    def execute(self, context):             
        idx = iops_axis_types.index(context.scene.transform_orientation_slots[0].type) 
        try:
            try_next(iops_axis_types, idx)
        except TypeError:
            try_next(iops_axis_types, idx)        
        self.report ({'INFO'}, "Axis Type: " + context.scene.transform_orientation_slots[0].type)
        return {'FINISHED'} 


class IOPS_OT_PPoint_Scroll_UP(bpy.types.Operator):
    """Cyclic switching pivot point types UP"""
    bl_idname = "iops.ppoint_scroll_up"
    bl_label = "Cyclic switching pivot point types UP"

    def execute(self, context):
        idx = iops_ppoint_types.index(context.scene.tool_settings.transform_pivot_point)
        try:
            try_prev(iops_ppoint_types, idx)
        except TypeError:
            try_prev(iops_ppoint_types, idx)
        
        self.report ({'INFO'}, "Pivot Point Type: " + context.scene.tool_settings.transform_pivot_point)
        return {'FINISHED'} 

class IOPS_OT_PPoint_Scroll_DOWN(bpy.types.Operator):
    """Cyclic switching pivot point types UP"""
    bl_idname = "iops.ppoint_scroll_down"
    bl_label = "Cyclic switching pivot point types DOWN"

    def execute(self, context):             
        idx = iops_ppoint_types.index(context.scene.tool_settings.transform_pivot_point) 
        try:
            try_next(iops_ppoint_types, idx)
        except TypeError:
            try_next(iops_ppoint_types, idx)
        self.report ({'INFO'}, "Pivot Point Type: " + context.scene.tool_settings.transform_pivot_point)
        return {'FINISHED'} 

class IOPS_OT_Snap_Scroll_UP(bpy.types.Operator):
    """Cyclic switching properties types UP"""
    bl_idname = "iops.snap_scroll_up"
    bl_label = "Cyclic switching snap with types UP"

    def execute(self, context):
        idx = iops_snap_types.index(context.scene.tool_settings.snap_target)
        try:
            try_prev(iops_snap_types, idx)
        except TypeError:
            try_prev(iops_snap_types, idx)
        self.report ({'INFO'}, "Snap With: " + context.scene.tool_settings.snap_target)
        return {'FINISHED'} 

class IOPS_OT_Snap_Scroll_DOWN(bpy.types.Operator):
    """Cyclic switching snap with types UP"""
    bl_idname = "iops.snap_scroll_down"
    bl_label = "Cyclic switching snap with types DOWN"

    def execute(self, context):             
        idx = iops_snap_types.index(context.scene.tool_settings.snap_target) 
        try:
            try_next(iops_snap_types, idx)
        except TypeError:
            try_next(iops_snap_types, idx)
        self.report ({'INFO'}, "Snap With: " + context.scene.tool_settings.snap_target)
        return {'FINISHED'}   
    
  
    

    

    
