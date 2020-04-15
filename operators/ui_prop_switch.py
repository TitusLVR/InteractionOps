import bpy

iops_spc = ['TOOL', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'OBJECT', 'MODIFIER', 'PARTICLES', 'PHYSICS', 'CONSTRAINT', 'DATA', 'MATERIAL', 'TEXTURE']


def set_space_context(idx):
    bpy.context.screen.areas[0].spaces.active.context = iops_spc[idx]


def poll_check():
    for area in bpy.context.screen.areas:
        if area.type == 'PROPERTIES':
            return True
        else:
            return False


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

    
    @classmethod
    def poll(cls, context):
        return (poll_check())

    def execute(self, context):
        idx = iops_spc.index(bpy.context.screen.areas[0].spaces.active.context)        
        try:
            try_prev(idx)
        except TypeError:
            try_prev(idx)
        return {'FINISHED'}   


class IOPS_OT_PropScroll_DOWN(bpy.types.Operator):
    """Cyclic switching properties types DOWN"""
    bl_idname = "iops.prop_scroll_down"
    bl_label = "Cyclic switching properties types Down"

    @classmethod
    def poll(cls, context):
        return (poll_check())

    def execute(self, context):
        idx = iops_spc.index(bpy.context.screen.areas[0].spaces.active.context)        
        try:
            try_next(idx)
        except TypeError:
            try_next(idx)
        return {'FINISHED'}
    
