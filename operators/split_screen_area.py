import bpy
from bpy.props import StringProperty, FloatProperty
import copy


def ContextOverride(area):
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for screen_area in screen.areas:
            if screen_area.ui_type == area.ui_type:
                for region in screen_area.regions:
                    if region.type == "WINDOW":
                        context_override = {
                            "window": window,
                            "screen": screen,
                            "area": screen_area,
                            "region": region,
                            # 'scene': bpy.context.scene,
                            # 'edit_object': bpy.context.edit_object,
                            # 'active_object': bpy.context.active_object,
                            # 'selected_objects': bpy.context.selected_objects
                        }
                        return context_override
    raise Exception("ERROR: Override failed!")


class IOPS_OT_SplitScreenArea(bpy.types.Operator):
    bl_idname = "iops.split_screen_area"
    bl_label = "IOPS Split Screen Area"

    area_type: StringProperty(
        name="Area Type", description="Which area to create", default=""
    )

    ui: StringProperty(
        name="Area UI Type", description="Which UI to enable", default=""
    )

    pos: StringProperty(
        name="Position", description="Where to create new area", default=""
    )

    factor: FloatProperty(
        name="Factor",
        description="Area split factor",
        default=0.01,
        soft_min=0.01,
        soft_max=1,
        step=0.01,
        precision=2,
    )

    def refresh_ui(self, area):
        context_override = ContextOverride(area)
        with bpy.context.temp_override(**context_override):
            bpy.ops.screen.screen_full_area()
            bpy.ops.screen.back_to_previous()

    def get_join_xy(self, context, ui, pos):
        x, y = 0, 0
        if ui == context.area.ui_type:
            if pos == "TOP":
                x = int(context.area.width / 2 + context.area.x)
                y = context.area.y - 1

            elif pos == "RIGHT":
                x = context.area.x - 1
                y = int(context.area.height / 2 + context.area.y)

            elif pos == "BOTTOM":
                x = int(context.area.width / 2 + context.area.x)
                y = context.area.height + context.area.y + 1

            elif pos == "LEFT":
                x = context.area.width + context.area.x + 1
                y = int(context.area.y + context.area.height / 2)

        else:
            if pos == "TOP":
                x = int(context.area.x + context.area.width / 2)
                y = context.area.height + context.area.y + 1

            elif pos == "RIGHT":
                x = context.area.x + context.area.width + 1
                y = int(context.area.y + context.area.height / 2)

            elif pos == "BOTTOM":
                x = int(context.area.x + context.area.width / 2)
                y = context.area.y

            elif pos == "LEFT":
                x = context.area.x
                y = int(context.area.y + context.area.height / 2)

        return (x, y)

    def get_side_area(self, context, area, pos):

        side_area = None

        for screen_area in context.screen.areas:
            if (
                pos == "TOP"
                and screen_area.x == area.x
                and screen_area.width == area.width
                and screen_area.y == area.height + area.y + 1
            ):
                side_area = screen_area
                break

            elif (
                pos == "RIGHT"
                and screen_area.x == area.x + area.width + 1
                and screen_area.height == area.height
                and screen_area.y == area.y
            ):
                side_area = screen_area
                break

            elif (
                pos == "BOTTOM"
                and screen_area.width == area.width
                and screen_area.x == area.x
                and screen_area.height + screen_area.y + 1 == area.y
            ):
                side_area = screen_area
                break

            elif (
                pos == "LEFT"
                and screen_area.width + screen_area.x + 1 == area.x
                and screen_area.y == area.y
                and screen_area.height == area.height
            ):
                side_area = screen_area
                break

        return side_area

    def join_areas(self, context, current_area, side_area, pos, swap):
        join_x, join_y = self.get_join_xy(context, side_area.ui_type, pos)
        context_override = ContextOverride(side_area)
        with context.temp_override(**context_override):
            bpy.ops.iops.space_data_save()
        refresh_area = side_area if current_area.ui_type == self.ui else current_area

        if swap:
            bpy.ops.screen.area_swap(cursor=(join_x, join_y))
            refresh_area = (
                side_area if current_area.ui_type == self.ui else current_area
            )
            bpy.ops.screen.area_join(cursor=(join_x, join_y))
            self.refresh_ui(refresh_area)
        else:
            bpy.ops.screen.area_join(cursor=(join_x, join_y))
            self.refresh_ui(refresh_area)

        return side_area

    def execute(self, context):
        areas = list(context.screen.areas)
        current_area = context.area
        side_area = None

        # Fix stupid Blender's behaviour
        if self.factor == 0.5:
            self.factor = 0.499

        # Check if toggle fullscreen was activated
        if "nonnormal" in context.screen.name:
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return {"FINISHED"}

        for area in context.screen.areas:
            if area == current_area:
                continue
            else:
                side_area = self.get_side_area(context, current_area, self.pos)
                if side_area and side_area.ui_type == self.ui:
                    swap = True if self.pos in {"TOP", "RIGHT"} else False
                    self.join_areas(context, current_area, side_area, self.pos, swap)
                    self.report({"INFO"}, "Joined Areas")

                    return {"FINISHED"}
                else:
                    continue

        if current_area.ui_type == self.ui:
            if self.pos == "LEFT":
                mirror_pos = "RIGHT"
            elif self.pos == "RIGHT":
                mirror_pos = "LEFT"
            elif self.pos == "TOP":
                mirror_pos = "BOTTOM"
            elif self.pos == "BOTTOM":
                mirror_pos = "TOP"

            swap = False if mirror_pos in {"TOP", "RIGHT"} else True
            side_area = self.get_side_area(context, current_area, mirror_pos)
            if side_area:
                self.join_areas(context, current_area, side_area, mirror_pos, swap)
                self.report({"INFO"}, "Joined Areas")
                return {"FINISHED"}
            else:
                self.report({"INFO"}, "No side area to join")
                return {"FINISHED"}

        else:
            new_area = None
            swap = True if self.factor >= 0.5 else False

            direction = "VERTICAL" if self.pos in {"LEFT", "RIGHT"} else "HORIZONTAL"
            factor = (1 - self.factor) if self.pos in {"RIGHT", "TOP"} else self.factor
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
                    if direction == "VERTICAL":
                        if self.pos == "LEFT":
                            bpy.ops.screen.area_swap(
                                cursor=(new_area.x, int(new_area.height / 2))
                            )
                        if self.pos == "RIGHT":
                            bpy.ops.screen.area_swap(
                                cursor=(context.area.x, int(new_area.height / 2))
                            )
                    if direction == "HORIZONTAL":
                        if self.pos == "TOP":
                            bpy.ops.screen.area_swap(
                                cursor=(int(new_area.width / 2), context.area.y)
                            )
                        if self.pos == "BOTTOM":
                            bpy.ops.screen.area_swap(
                                cursor=(int(new_area.height / 2), new_area.y)
                            )

                context_override = ContextOverride(new_area)
                with context.temp_override(**context_override):
                    bpy.ops.iops.space_data_load()
                return {"FINISHED"}

        return {"FINISHED"}


class IOPS_OT_SwitchScreenArea(bpy.types.Operator):
    bl_idname = "iops.switch_screen_area"
    bl_label = "IOPS Switch Screen Area"

    area_type: StringProperty(
        name="Area Type", description="Which area to create", default=""
    )

    ui: StringProperty(
        name="Area UI Type", description="Which UI to enable", default=""
    )

    def refresh_ui(self, area):
        context_override = ContextOverride(area)
        with bpy.context.temp_override(**context_override):
            bpy.ops.screen.screen_full_area()
            bpy.ops.screen.back_to_previous()

    def execute(self, context):

        if "nonnormal" in context.screen.name:
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return {"FINISHED"}

        if (context.area.type == self.area_type) and (context.area.ui_type == self.ui):
            context_override = ContextOverride(context.area)
            with context.temp_override(**context_override):
                bpy.ops.screen.area_close()

        else:
            bpy.context.area.type = self.area_type
            bpy.context.area.ui_type = self.ui
            context_override = ContextOverride(context.area)
            try:
                with context.temp_override(**context_override):
                    bpy.ops.iops.space_data_load()
            except TypeError:
                pass

        return {"FINISHED"}
