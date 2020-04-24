import bpy
import copy

def ContextOverride(area_type):
    for window in bpy.context.window_manager.windows:      
        screen = window.screen
        for area in screen.areas:
            if area.type == area_type:            
                for region in area.regions:
                    if region.type == 'WINDOW':               
                        context_override = {'window': window, 
                                            'screen': screen, 
                                            'area': area, 
                                            'region': region, 
                                            'scene': bpy.context.scene, 
                                            'edit_object': bpy.context.edit_object, 
                                            'active_object': bpy.context.active_object, 
                                            'selected_objects': bpy.context.selected_objects
                                            } 
                        return context_override
    raise Exception("ERROR: Override failed!")


def get_neighbour_right(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x == current_area.width + current_area.x + 1 and 
              area.y == current_area.y):
            return area.type

def get_neighbour_left(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x + area.width + 1 == current_area.x and 
              area.y == current_area.y):
            return area.type

def get_neighbour_top(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x == current_area.x and 
              area.y + area.height + 1 == current_area.y):
            return area.type

def get_neighbour_bottom(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x == current_area.x and 
              area.y + area.height + 1 == current_area.y):
            return area.type
    

def join_area_right(join_x, join_y, area_type):
    bpy.ops.screen.area_swap(cursor=(join_x, join_y))
    bpy.ops.screen.area_join(cursor=(join_x, join_y))
    # Refresh UI
    context_override = ContextOverride(area_type)   
    bpy.ops.screen.screen_full_area(context_override)
    bpy.ops.screen.back_to_previous()

def join_area_left(join_x, join_y, area_type):
    bpy.ops.screen.area_join(cursor=(join_x, join_y))
    # Refresh UI
    context_override = ContextOverride(area_type)   
    bpy.ops.screen.screen_full_area(context_override)
    bpy.ops.screen.back_to_previous()


class IOPS_OT_SplitAreaUV(bpy.types.Operator):
    bl_idname = "iops.split_area_uv"
    bl_label = "IOPS Split Area UV"

    # @classmethod 
    # def poll(self, context):
    #     return context.area.type in ["VIEW_3D","IMAGE_EDITOR"]

    def execute(self,context):
        current_area = context.area
        override = current_area.type
        current_screen =  bpy.context.screen
        side_area = None
        join_x = current_area.x + current_area.width + 1
        join_y = int(current_area.y + current_area.height/2)
        current_type = context.area.type # VIEW_3D
        areas = list(context.screen.areas)

        # Check if toggle fullscreen was activated
        if "nonnormal" in current_screen.name: 
            # bpy.ops.screen.back_to_previous()
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return {"FINISHED"}

        for area in context.screen.areas:
            if area == current_area:
                continue
            elif area.x == join_x and area.y == current_area.y:
                side_area = area
                break

        if side_area and side_area.type == 'IMAGE_EDITOR':
            join_area_right(join_x, join_y, override)
            return {"FINISHED"}
        
        if current_area.type == 'IMAGE_EDITOR':
            override = get_neighbour_left(current_area)
            join_area_right(current_area.x, join_y, override)
            return {"FINISHED"}
        
        else:
            context.area.type = "IMAGE_EDITOR"
            context.area.ui_type = 'UV'
            new_area = None
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.5)
            for area in context.screen.areas:
                if area not in areas:
                    new_area = area
                    break
            if new_area:
                new_area.type = current_type # VIEW_3D
                return {"FINISHED"}
        
        return {"CANCELLED"}


class IOPS_OT_SplitAreaOutliner(bpy.types.Operator):
    bl_idname = "iops.split_area_outliner"
    bl_label = "IOPS Split Area Outliner"

    # @classmethod 
    # def poll(self, context):
    #     return context.area.type in ["VIEW_3D","OUTLINER"]

    def execute(self,context):
        current_area = context.area
        override = current_area.type
        current_screen =  bpy.context.screen
        side_area = None
        join_x = current_area.x
        join_y = int(current_area.y + current_area.height/2)
        current_type = context.area.type # VIEW_3D
        areas = list(context.screen.areas)

        # Check if toggle fullscreen was activated
        if "nonnormal" in current_screen.name: 
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return {"FINISHED"}

        for area in context.screen.areas:
            if area == current_area:
                continue
            elif area.width + area.x + 1 == join_x and area.y == current_area.y:
                side_area = area
                break

        if side_area and side_area.type == 'OUTLINER':
            join_area_left(join_x, join_y, override)
            return {"FINISHED"}
        
        if current_area.type == 'OUTLINER':
            join_x = current_area.width + current_area.x + 1
            override = get_neighbour_right(current_area)
            join_area_left(join_x, join_y, override)
            return {"FINISHED"}
        
        else:
            context.area.type = current_type
            new_area = None
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.15)

            for area in context.screen.areas:
                if area not in areas:
                    new_area = area
                    break
            if new_area:
                new_area.type = "OUTLINER" # VIEW_3D
                return {"FINISHED"}
        
        return {"CANCELLED"}

class IOPS_OT_SplitAreaProperties(bpy.types.Operator):
    bl_idname = "iops.split_area_properties"
    bl_label = "IOPS Split Area Properties"

   
    # @classmethod 
    # def poll(self, context):
    #     return context.area.type in ["VIEW_3D","PROPERTIES"]

    def execute(self,context):
        current_area = context.area
        override = current_area.type
        current_screen =  bpy.context.screen
        side_area = None
        join_x = current_area.x + current_area.width + 1
        join_y = int(current_area.y + current_area.height/2)
        current_type = context.area.type # VIEW_3D
        areas = list(context.screen.areas)

        # Check if toggle fullscreen was activated
        if "nonnormal" in current_screen.name: 
            # bpy.ops.screen.back_to_previous()
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return {"FINISHED"}

        for area in context.screen.areas:
            if area == current_area:
                continue
            elif area.x == join_x and area.y == current_area.y:
                side_area = area
                break

        if side_area and side_area.type == 'PROPERTIES':
            join_area_right(join_x, join_y, override)
            return {"FINISHED"}
        
        if current_area.type == 'PROPERTIES':
            override = get_neighbour_left(current_area)
            join_area_right(current_area.x, join_y, override)
            return {"FINISHED"}
        
        else:
            context.area.type = "VIEW_3D"
            new_area = None
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.8)
            for area in context.screen.areas:
                if area not in areas:
                    new_area = area
                    break
            if new_area:
                new_area.type = 'PROPERTIES' 
                return {"FINISHED"}
        
        return {"CANCELLED"}


class IOPS_OT_SplitAreaText(bpy.types.Operator):
    bl_idname = "iops.split_area_text"
    bl_label = "IOPS Split Area Text"

   
    # @classmethod 
    # def poll(self, context):
    #     return context.area.type in ["VIEW_3D","TEXT_EDITOR"]

    def execute(self,context):
        current_area = context.area
        current_screen =  bpy.context.screen
        override = current_area.type
        side_area = None
        join_x = current_area.x + current_area.width + 1
        join_y = int(current_area.y + current_area.height/2)
        areas = list(context.screen.areas)

        # Check if toggle fullscreen was activated
        if "nonnormal" in current_screen.name: 
            # bpy.ops.screen.back_to_previous()
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return {"FINISHED"}

        for area in context.screen.areas:
            if area == current_area:
                continue
            elif area.x == join_x and area.y == current_area.y:
                side_area = area
                break

        if side_area and side_area.type == 'TEXT_EDITOR':
            join_area_right(join_x, join_y, override)
            return {"FINISHED"}
        
        if current_area.type == 'TEXT_EDITOR':
            override = get_neighbour_left(current_area)
            join_area_right(current_area.x, join_y, override)
            return {"FINISHED"}
        
        else:
            context.area.type = "VIEW_3D"
            new_area = None
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.8)
            for area in context.screen.areas:
                if area not in areas:
                    new_area = area
                    break
            if new_area:
                new_area.type = 'TEXT_EDITOR' 
                return {"FINISHED"}
        
        return {"CANCELLED"}


class IOPS_OT_SplitAreaConsole(bpy.types.Operator):
    bl_idname = "iops.split_area_console"
    bl_label = "IOPS Split Area Console"

   
    # @classmethod 
    # def poll(self, context):
    #     return context.area.type in ["VIEW_3D","CONSOLE"]

    def execute(self,context):
        current_area = context.area
        current_screen =  bpy.context.screen
        override = current_area.type
        current_area_top = current_area.height + current_area.y + 1
        side_area = None
        join_x = int(current_area.x + current_area.width / 2)
        join_y = current_area_top
        areas = list(context.screen.areas)

        # Check if toggle fullscreen was activated
        if "nonnormal" in current_screen.name: 
            bpy.ops.screen.screen_full_area(use_hide_panels=True)

            return {"FINISHED"}

        for area in context.screen.areas:
            if area == current_area:
                continue
            elif area.x == current_area.x and area.y == current_area_top:
                side_area = area
                break

        if side_area and side_area.type == 'CONSOLE':
            join_area_right(join_x, join_y, override)

            return {"FINISHED"}
        
        if current_area.type == 'CONSOLE':
            override = get_neighbour_top(current_area)
            join_area_right(join_x, current_area.y, override)

            return {"FINISHED"}
        
        else:
            context.area.type = "VIEW_3D"
            new_area = None
            bpy.ops.screen.area_split(direction="HORIZONTAL", factor=0.8)
            for area in context.screen.areas:
                if area not in areas:
                    new_area = area
                    break

            if new_area:
                new_area.type = 'CONSOLE' 
                return {"FINISHED"}

        return {"CANCELLED"}
