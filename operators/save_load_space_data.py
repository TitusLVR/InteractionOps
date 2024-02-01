import bpy


def save_space_data(context):
    area_type = context.area.type
    sd = context.space_data

    if "IOPS" not in context.scene:
        context.scene["IOPS"] = {}

    if area_type not in context.scene["IOPS"]:
        context.scene["IOPS"][area_type] = {}

    if area_type == "OUTLINER":
        outliner = context.scene["IOPS"]["OUTLINER"]
        display_mode = context.space_data.display_mode
        outliner["display_mode"] = display_mode

        outliner["show_header"] = sd.show_region_header
        outliner["show_menus"] = context.area.show_menus

        if display_mode == "VIEW_LAYER":
            outliner["show_restrict_column_enable"] = sd.show_restrict_column_enable
            outliner["show_restrict_column_select"] = sd.show_restrict_column_select
            outliner["show_restrict_column_hide"] = sd.show_restrict_column_hide
            outliner["show_restrict_column_viewport"] = sd.show_restrict_column_viewport
            outliner["show_restrict_column_render"] = sd.show_restrict_column_render
            outliner["show_restrict_column_holdout"] = sd.show_restrict_column_holdout

        elif display_mode == "SCENES":
            outliner["show_restrict_column_select"] = sd.show_restrict_column_select
            outliner["show_restrict_column_hide"] = sd.show_restrict_column_hide
            outliner["show_restrict_column_viewport"] = sd.show_restrict_column_viewport
            outliner["show_restrict_column_render"] = sd.show_restrict_column_render

        if display_mode != "DATA_API":
            outliner["use_sort_alpha"] = sd.use_sort_alpha
    else:
        context.scene["IOPS"][area_type]["show_header"] = sd.show_region_header
        context.scene["IOPS"][area_type]["show_menus"] = context.area.show_menus


def load_space_data(context):
    area_type = context.area.type
    sd = context.space_data

    if "IOPS" not in context.scene:
        context.scene["IOPS"] = {}

    if context.scene["IOPS"].values() != []:
        if area_type in context.scene["IOPS"] and area_type == "OUTLINER":
            outliner = context.scene["IOPS"]["OUTLINER"]
            display_mode = context.space_data.display_mode
            sd.display_mode = outliner["display_mode"]
            context.area.show_menus = outliner["show_menus"]
            sd.show_region_header = outliner["show_header"]

            if display_mode == "VIEW_LAYER":
                sd.show_restrict_column_enable = outliner["show_restrict_column_enable"]
                sd.show_restrict_column_select = outliner["show_restrict_column_select"]
                sd.show_restrict_column_hide = outliner["show_restrict_column_hide"]
                sd.show_restrict_column_viewport = outliner[
                    "show_restrict_column_viewport"
                ]
                sd.show_restrict_column_render = outliner["show_restrict_column_render"]
                sd.show_restrict_column_holdout = outliner[
                    "show_restrict_column_holdout"
                ]

            elif display_mode == "SCENES":
                sd.show_restrict_column_select = outliner["show_restrict_column_select"]
                sd.show_restrict_column_hide = outliner["show_restrict_column_hide"]
                sd.show_restrict_column_viewport = outliner[
                    "show_restrict_column_viewport"
                ]
                sd.show_restrict_column_render = outliner["show_restrict_column_render"]

            if display_mode != "DATA_API":
                sd.use_sort_alpha = outliner["use_sort_alpha"]

            return f"{area_type} space data loaded"

        elif area_type in context.scene["IOPS"]:
            sd.show_region_header = context.scene["IOPS"][area_type]["show_header"]
            context.area.show_menus = context.scene["IOPS"][area_type]["show_menus"]
            return f"{area_type} space data loaded"
        else:
            return f"No space data for {area_type}"
    else:
        return "No space data to load!"


class IOPS_OT_SaveSpaceData(bpy.types.Operator):
    """Save Space Data"""

    bl_idname = "iops.space_data_save"
    bl_label = "Save space_data"

    # @classmethod
    # def poll(cls, context):
    #     return context.area.type == 'OUTLINER'

    def execute(self, context):
        save_space_data(context)
        self.report({"INFO"}, f"{bpy.context.area.type} Space Data Saved")
        return {"FINISHED"}


class IOPS_OT_LoadSpaceData(bpy.types.Operator):
    """Save Space Data"""

    bl_idname = "iops.space_data_load"
    bl_label = "Load space_data"

    # @classmethod
    # def poll(cls, context):
    #     return context.area.type == 'OUTLINER'

    def execute(self, context):
        event = load_space_data(context)
        if event:
            self.report({"INFO"}, event)
        else:
            self.report({"INFO"}, "load_space_data failed")
        return {"FINISHED"}
