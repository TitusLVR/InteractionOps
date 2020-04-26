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


class IOPS_OT_SplitScreenArea(bpy.types.Operator):
    bl_idname = "iops.split_screen_area"
    bl_label = "IOPS Split Screen Area"

    area_type : StringProperty(
        name="Area Type",
        description="Which area to create",
        default=""
        )


    ui : StringProperty(
        name="Area UI Type",
        description="Which UI to enable",
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

    def refresh_ui(self, area):
        context_override = ContextOverride(area.type)   
        bpy.ops.screen.screen_full_area(context_override)
        bpy.ops.screen.back_to_previous()


    def get_join_xy(self, context, ui, pos):
        x, y = 0, 0
        if ui == context.area.ui_type:
            if pos == "TOP":
                print('Found TOP Area')
                x = int(context.area.width/2 + context.area.x)
                y = context.area.y - 1

            elif pos == "RIGHT":
                print('Found RIGHT Area')
                x = context.area.x - 1
                y = int(context.area.height/2 + context.area.y)

            elif pos == "BOTTOM":
                print('Found BOTTOM Area')
                x = int(context.area.width/2 + context.area.x)
                y = context.area.height + context.area.y + 1
                
            elif pos == "LEFT":
                print('Found LEFT Area')
                x = context.area.width + context.area.x + 1
                y = int(context.area.y + context.area.height/2)

        else:
            if pos == "TOP":
                x = int(context.area.x + context.area.width / 2)
                y = context.area.height + context.area.y + 1

            elif pos == "RIGHT":
                x = context.area.x + context.area.width + 1
                y = int(context.area.y + context.area.height/2)

            elif pos == "BOTTOM":
                x = int(context.area.x + context.area.width / 2)
                y = context.area.y

            elif pos == "LEFT":
                x = context.area.x
                y = int(context.area.y + context.area.height/2)

        return (x, y)


    def get_side_area(self, context, area, pos):

        side_area = None

        if pos == "TOP" and \
            area.x == context.area.x and \
            area.width == context.area.width and \
            area.y == context.area.height + context.area.y + 1:
                side_area = area
            
        elif pos == "RIGHT" and \
            area.x == context.area.x + context.area.width + 1 and \
            area.height == context.area.height and \
            area.y == context.area.y:
                side_area = area

        elif pos == "BOTTOM" and \
            area.width == context.area.width and \
            area.x == context.area.x and \
            area.height + area.y + 1 == context.area.y:
                side_area = area

        elif pos == "LEFT" and \
            area.width + area.x + 1 == context.area.x and \
            area.y == context.area.y and \
            area.height == context.area.height:
                side_area = area

        return side_area


    def join_areas(self, context, current_area, side_area, pos):
        join_x, join_y = self.get_join_xy(context, side_area.ui_type, pos)

        if pos == "TOP":
            bpy.ops.screen.area_swap(cursor=(join_x, join_y))
            bpy.ops.screen.area_join(cursor=(join_x, join_y))
            self.refresh_ui(side_area)

            
        elif pos == "RIGHT":
            bpy.ops.screen.area_swap(cursor=(join_x, join_y))
            bpy.ops.screen.area_join(cursor=(join_x, join_y))
            self.refresh_ui(side_area)

        elif pos == "BOTTOM":
            bpy.ops.screen.area_join(cursor=(join_x, join_y))
            self.refresh_ui(side_area)

        elif pos == "LEFT":
            bpy.ops.screen.area_join(cursor=(join_x, join_y))
            self.refresh_ui(side_area)

        return side_area


    def execute(self, context):
        areas = list(context.screen.areas)
        current_area = context.area
        side_area = None
        # Fix stupid Blender's behaviour
        if self.factor == 0.5:
            self.factor = 0.499
        # side_area = None
        # join_x, join_y = self.get_join_xy(context, area, direction)

        # Check if toggle fullscreen was activated
        if "nonnormal" in context.screen.name: 
            bpy.ops.screen.screen_full_area(use_hide_panels=True)

            return {"FINISHED"}


        for area in context.screen.areas:
            if area == current_area:
                continue
            else:
                side_area = self.get_side_area(context, area, self.pos)
                if side_area and side_area.ui_type == self.ui:
                    self.join_areas(context, current_area, side_area, self.pos)
                    self.report({'INFO'}, "Joined Areas")
                    return {'FINISHED'}
                else:
                    continue
        
        if current_area.ui_type == self.ui:
            self.join_areas(context, current_area, current_area, self.pos)
            self.report({'INFO'}, "Joined Areas")

        else:
            new_area = None
            swap = True if self.factor >= 0.5 else False

            direction = "VERTICAL" if self.pos in {'LEFT', 'RIGHT'} else "HORIZONTAL"
            factor = (1 - self.factor) if self.pos in {'RIGHT', 'TOP'} else self.factor
            bpy.ops.screen.area_split(direction=direction, factor=factor)

            for area in context.screen.areas:
                if area not in areas:
                    new_area = area
                    break
            
            if new_area:
                new_area.type = self.area_type
                new_area.ui_type = self.ui

                if swap:
                    self.refresh_ui(new_area)
                    if direction == 'VERTICAL':
                        if self.pos == 'LEFT':
                            bpy.ops.screen.area_swap(cursor=(new_area.x, int(new_area.height / 2)))
                        if self.pos == 'RIGHT':
                            bpy.ops.screen.area_swap(cursor=(context.area.x, int(new_area.height / 2)))
                    if direction == 'HORIZONTAL':
                        if self.pos == 'TOP':
                            bpy.ops.screen.area_swap(cursor=(int(new_area.width / 2), context.area.y))
                        if self.pos == 'BOTTOM':
                            bpy.ops.screen.area_swap(cursor=(int(new_area.height / 2), new_area.y))
                        
                return {"FINISHED"}

        return {"FINISHED"}
