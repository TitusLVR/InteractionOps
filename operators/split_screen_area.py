import bpy
from bpy.props import StringProperty, FloatProperty
import copy

def ContextOverride(area):
    for window in bpy.context.window_manager.windows:      
        screen = window.screen
        for area in screen.areas:
            if area.type == area.type:            
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
    if current_area:
        for area in bpy.context.screen.areas:
            if area == current_area:
                continue
            elif (area.x == current_area.width + current_area.x + 1 and 
                area.y == current_area.y):
                return area
    else:
        return None

def get_neighbour_left(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x + area.width + 1 == current_area.x and 
              area.y == current_area.y):
            return area

def get_neighbour_top(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x == current_area.x and 
              area.y  == current_area.height + current_area.y + 1):
            return area

def get_neighbour_bottom(current_area):
    for area in bpy.context.screen.areas:
        if area == current_area:
            continue
        elif (area.x == current_area.x and 
              area.y + area.height + 1 == current_area.y):
            return area
    

def join_area_right(join_x, join_y, area):
    if bpy.context.area.height == area.height:
        bpy.ops.screen.area_swap(cursor=(join_x, join_y))
        bpy.ops.screen.area_join(cursor=(join_x, join_y))
        # Refresh UI
        context_override = ContextOverride(area.type)   
        bpy.ops.screen.screen_full_area(context_override)
        bpy.ops.screen.back_to_previous()
        return "Joined areas"
    else:
        return "Cannot join area"

def join_area_left(join_x, join_y, area):
    if bpy.context.area.height == area.height:
        bpy.ops.screen.area_join(cursor=(join_x, join_y))
        # Refresh UI
        context_override = ContextOverride(area.type)   
        bpy.ops.screen.screen_full_area(context_override)
        bpy.ops.screen.back_to_previous()
        return "Joined areas"
    else:
        return "Cannot join area."


def join_area_top(join_x, join_y, area):
    if bpy.context.area.width == area.width:
        bpy.ops.screen.area_swap(cursor=(join_x, join_y))
        bpy.ops.screen.area_join(cursor=(join_x, join_y))
        # Refresh UI
        context_override = ContextOverride(area.type)   
        bpy.ops.screen.screen_full_area(context_override)
        bpy.ops.screen.back_to_previous()
        return "Joined areas"
    else:
        return "Cannot join area"

def join_area_bottom(join_x, join_y, area):
    if bpy.context.area.width == area.width:
        bpy.ops.screen.area_join(cursor=(join_x, join_y))
        # Refresh UI
        context_override = ContextOverride(area.type)   
        bpy.ops.screen.screen_full_area(context_override)
        bpy.ops.screen.back_to_previous()
        return "Joined areas"
    else:
        return "Cannot join area"


# ########################################################################################
#                                     REFACTORING
# ########################################################################################


class IOPS_OT_SplitScreenArea(bpy.types.Operator):
    bl_idname = "iops.split_screen_area"
    bl_label = "IOPS Split Screen Area"


    area : StringProperty(
        name="Area",
        description="Which area to create",
        default=""
    )

    pos : StringProperty(
        name="Position",
        description="Where to create new area",
        default=""
    )

    factor : FloatProperty(
        name="Factor",
        description="Area split factor",
        default=0.01,
        soft_min=0.01,
        soft_max=1,
        step=0.01,
        precision=2
    )        

    

    def get_join_xy(self, context, area, direction):
        if area == context.area:
            if direction == "TOP":
                x = int(area.width/2 + area.x)
                y = area.y - 1

            elif direction == "RIGHT":
                pass
            elif direction == "BOTTOM":
                pass
            elif direction == "LEFT":
                pass
        else:
            if direction == "TOP":
                pass
            elif direction == "RIGHT":
                pass
            elif direction == "BOTTOM":
                pass
            elif direction == "LEFT":
                pass

        return (x, y)


    def execute(self, context):
        # current_area = context.area
        # side_area = None
        # join_x, join_y = self.get_join_xy(context, area, direction)
        # areas = list(context.screen.areas)

        # # Check if toggle fullscreen was activated
        # if "nonnormal" in context.screen.name: 
        #     bpy.ops.screen.screen_full_area(use_hide_panels=True)

        #     return {"FINISHED"}

        # for area in context.screen.areas:
        #     if area == current_area:
        #         continue
        #     elif area.x == current_area.x and area.height + area.y + 1 == current_area.y:
        #         side_area = area
        #         break

        # if side_area and side_area.type == 'DOPESHEET_EDITOR':
        #     event = join_area_bottom(join_x, join_y, side_area)
        #     self.report({"INFO"}, event)

        #     return {"FINISHED"}
        
        # if current_area.type == 'DOPESHEET_EDITOR':
        #     join_x = int(current_area.width/2 + current_area.x)
        #     join_y = current_area.height + current_area.y + 1
        #     override = get_neighbour_top(current_area)
        #     event = join_area_bottom(join_x, join_y, override)
        #     self.report({"INFO"}, event)

        #     return {"FINISHED"}
        
        # else:
        #     context.area.type = current_area.type
        #     new_area = None
        #     bpy.ops.screen.area_split(direction="HORIZONTAL", factor=0.2)
        #     for area in context.screen.areas:
        #         if area not in areas:
        #             new_area = area
        #             break

        #     if new_area:
        #         new_area.type = 'DOPESHEET_EDITOR' 
        #         new_area.ui_type = 'TIMELINE'
        #         return {"FINISHED"}
        self.report({'INFO'},f'Area: {self.area}, Pos: {self.pos}, Factor: {self.factor}')
        return {"FINISHED"}
