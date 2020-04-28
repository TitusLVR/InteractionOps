import bpy

iops_spc = ['TOOL', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'OBJECT', 'MODIFIER', 'PARTICLES', 'PHYSICS', 'CONSTRAINT', 'DATA', 'MATERIAL', 'TEXTURE']


def set_space_context(idx):
    areas = [a.type for a in bpy.context.screen.areas]
    area_index = areas.index("PROPERTIES")
    if "PROPERTIES" in areas:   
        bpy.context.screen.areas[area_index].spaces.active.context = iops_spc[idx]

def try_next(idx):    
    if idx <= len(iops_spc):
        idx += 1 
        try:
            set_space_context(idx)
        except TypeError:
            try_next(idx)
        except IndexError:
            idx = 0
            set_space_context(idx)
    else:
        idx = 0
        set_space_context(idx)

def try_prev(idx):    
    if idx > 0 and idx <= len(iops_spc):
        idx -= 1
        try:
            set_space_context(idx)
        except TypeError:
            try_prev(idx)
        except IndexError:
            idx = 0
            set_space_context(idx)
    else:
        idx = len(iops_spc) - 1
        try:
            set_space_context(idx)
        except TypeError:
            try_prev(idx - 1)

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
                try_prev(idx)
            except TypeError:
                try_prev(idx)
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
                try_next(idx)
            except TypeError:
                try_next(idx)
        return {'FINISHED'}
    
