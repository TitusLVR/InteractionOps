import bpy
import blf


def draw_iops_text(self, context, _uidpi, _uifactor):
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    tColor = prefs.text_color
    tKColor = prefs.text_color_key
    tCSize = prefs.text_size
    tCPosX = prefs.text_pos_x
    tCPosY = prefs.text_pos_y
    tShadow = prefs.text_shadow_toggle
    tSColor = prefs.text_shadow_color
    tSBlur = prefs.text_shadow_blur
    tSPosX = prefs.text_shadow_pos_x
    tSPosY = prefs.text_shadow_pos_y

    iops_text = (
        ("Press and Hold", "Q"),
        ("Pick snapping points", "Left Mouse Button Click"),
    )

    # FontID
    font = 0
    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
    blf.size(font, tCSize)
    if tShadow:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
        blf.shadow_offset(font, tSPosX, tSPosY)
    else:
        blf.disable(0, blf.SHADOW)

    textsize = tCSize
    # get leftbottom corner
    offset = tCPosY
    columnoffs = (textsize * 21) * _uifactor
    for line in reversed(iops_text):
        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
        blf.position(font, tCPosX * _uifactor, offset, 0)
        blf.draw(font, line[0])

        blf.color(font, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
        textdim = blf.dimensions(0, line[1])
        coloffset = columnoffs - textdim[0] + tCPosX
        blf.position(0, coloffset, offset, 0)
        blf.draw(font, line[1])
        offset += (tCSize + 5) * _uifactor


class IOPS_OT_DragSnapCursor(bpy.types.Operator):
    """Quick drag & snap using 3D Cursor"""

    bl_idname = "iops.object_drag_snap_cursor"
    bl_label = "IOPS Drag Snap Cursor"
    bl_description = (
        "Hold Q and LMB Click to quickly snap point to point using 3D Cursor"
    )
    bl_options = {"REGISTER", "UNDO"}

    step = 1
    count = 0
    old_type = None
    old_value = None

    def clear_draw_handlers(self):
        for handler in self.vp_handlers:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
        )

    def modal(self, context, event):
        context.area.tag_redraw()
        # prevent spamming
        # new_type = event.type
        # new_value = event.value
        # if new_type != self.old_type and new_value != self.old_value:
        #     print(event.type, event.value)
        #     self.old_type = new_type
        #     self.old_value = new_value

        if (
            event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
            and event.value == "PRESS"
        ):
            return {"PASS_THROUGH"}
        elif event.type in {"ESC", "RIGHMOUSE"} and event.value == "PRESS":
            try:
                self.clear_draw_handlers()
            except ValueError:
                pass
            return {"CANCELLED"}

        elif event.type == "Q" and event.value == "PRESS":
            print("Count:", self.count)
            bpy.ops.transform.translate(
                "INVOKE_DEFAULT",
                cursor_transform=True,
                use_snap_self=True,
                snap_target="CLOSEST",
                use_snap_nonedit=True,
                snap_elements={"VERTEX"},
                snap=True,
                release_confirm=True,
            )
            self.count += 1
            if self.count == 1:
                # print("Count:", 1)
                self.report({"INFO"}, "Step 2: Q to place cursor at point B")
            elif self.count == 2:
                bpy.context.scene.IOPS.dragsnap_point_a = (
                    bpy.context.scene.cursor.location
                )
                # print("Count:", 2)
                self.report({"INFO"}, "Step 3: press Q")
            elif self.count == 3:
                # print("Count:", 3)
                bpy.context.scene.IOPS.dragsnap_point_b = (
                    bpy.context.scene.cursor.location
                )
                vector = (
                    bpy.context.scene.IOPS.dragsnap_point_b
                    - bpy.context.scene.IOPS.dragsnap_point_a
                )
                bpy.ops.transform.translate(value=vector, orient_type="GLOBAL")
                try:
                    self.clear_draw_handlers()
                except ValueError:
                    pass
                return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        preferences = context.preferences
        if context.space_data.type == "VIEW_3D":
            uidpi = int((72 * preferences.system.ui_scale))
            args_text = (self, context, uidpi, preferences.system.ui_scale)
            # Add draw handlers
            self._handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(
                draw_iops_text, args_text, "WINDOW", "POST_PIXEL"
            )
            self.report({"INFO"}, "Step 1: Q to place cursor at point A")
            self.vp_handlers = [self._handle_iops_text]
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "Active space must be a View3d")
            return {"CANCELLED"}
