import blf
import bpy


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
        ("Reset object's transforms", "0"),
        ("Toggle lock", "1"),
        ("Toggle 2 point", "2"),
        ("Toggle 3 point", "3"),
        ("Select all dummies", "A"),
        ("Flip Y and Z", "F"),
        ("Toggle snaps", "S"),
        ("Translate/Rotate", "G/R"),
        ("Select dummy O,Y,Z", "F1, F2, F3"),
        ("Scale dummies", "=/-"),
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


class IOPS_OT_ThreePointRotation(bpy.types.Operator):
    """Three point rotation"""

    bl_idname = "iops.object_modal_three_point_rotation"
    bl_label = "Complex Modal Rotation"
    bl_options = {"REGISTER", "UNDO"}
    obj = None
    dummy_size = None
    O_Dummy = None
    Z_Dummy = None
    Y_Dummy = None
    snaps = {}
    mx = None

    # UI
    ui_handlers = []

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
            and context.view_layer.objects.active.type == "MESH"
        )

    def clear_draw_handlers(self):
        for handler in self.ui_handlers:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")

    def store_snaps(self, context):
        self.snaps = {
            "transform_pivot_point": bpy.context.scene.tool_settings.transform_pivot_point,
            "snap_target": bpy.context.scene.tool_settings.snap_target,
            "use_snap_self": bpy.context.scene.tool_settings.use_snap_self,
            "snap_elements": bpy.context.scene.tool_settings.snap_elements,
            "use_snap_align_rotation": bpy.context.scene.tool_settings.use_snap_align_rotation,
            "use_snap_translate": bpy.context.scene.tool_settings.use_snap_translate,
            "use_snap_rotate": bpy.context.scene.tool_settings.use_snap_rotate,
            "use_snap_scale": bpy.context.scene.tool_settings.use_snap_scale,
            # "use_snap_grid_absolute": bpy.context.scene.tool_settings.use_snap_grid_absolute,
        }

    def set_snaps(self, context):
        bpy.context.scene.tool_settings.transform_pivot_point = "ACTIVE_ELEMENT"
        bpy.context.scene.tool_settings.snap_target = "ACTIVE"
        bpy.context.scene.tool_settings.use_snap_self = True
        bpy.context.scene.tool_settings.snap_elements = {"VERTEX", "EDGE_MIDPOINT"}
        bpy.context.scene.tool_settings.use_snap_align_rotation = False
        bpy.context.scene.tool_settings.use_snap_translate = True
        bpy.context.scene.tool_settings.use_snap_rotate = False
        bpy.context.scene.tool_settings.use_snap_scale = False
        # bpy.context.scene.tool_settings.use_snap_grid_absolute = False
        bpy.context.scene.tool_settings.use_snap = False

    def restore_snaps(self, context):
        bpy.context.scene.tool_settings.transform_pivot_point = self.snaps[
            "transform_pivot_point"
        ]
        bpy.context.scene.tool_settings.snap_target = self.snaps["snap_target"]
        bpy.context.scene.tool_settings.use_snap_self = self.snaps["use_snap_self"]
        bpy.context.scene.tool_settings.snap_elements = self.snaps["snap_elements"]
        bpy.context.scene.tool_settings.use_snap_align_rotation = self.snaps[
            "use_snap_align_rotation"
        ]
        bpy.context.scene.tool_settings.use_snap_translate = self.snaps[
            "use_snap_translate"
        ]
        bpy.context.scene.tool_settings.use_snap_rotate = self.snaps["use_snap_rotate"]
        bpy.context.scene.tool_settings.use_snap_scale = self.snaps["use_snap_scale"]
        # bpy.context.scene.tool_settings.use_snap_grid_absolute = self.snaps[
        #     "use_snap_grid_absolute"
        # ]

    def snap_dummy(self, context, dummy):
        if dummy == "O_Dummy":
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.objects.active = bpy.data.objects["O_Dummy"]
            bpy.data.objects["O_Dummy"].select_set(True)
            bpy.ops.transform.translate("INVOKE_DEFAULT")
        if dummy == "Y_Dummy":
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.objects.active = bpy.data.objects["Z_Dummy"]
            bpy.data.objects["Z_Dummy"].select_set(True)
            bpy.ops.transform.translate("INVOKE_DEFAULT")
        if dummy == "Z_Dummy":
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.objects.active = bpy.data.objects["Y_Dummy"]
            bpy.data.objects["Y_Dummy"].select_set(True)
            bpy.ops.transform.translate("INVOKE_DEFAULT")

    def select_target(self, context, target, active, deselect):
        if target == "O_Dummy":
            if deselect:
                bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects["O_Dummy"].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects["O_Dummy"]

        elif target == "Y_Dummy":
            if deselect:
                bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects["Z_Dummy"].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects["Z_Dummy"]

        elif target == "Z_Dummy":
            if deselect:
                bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects["Y_Dummy"].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects["Y_Dummy"]

        elif target == "PROXY":
            if deselect:
                bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects["Proxy_Dummy"].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects["Proxy_Dummy"]

        elif target == "ALL":
            if deselect:
                bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects["O_Dummy"].select_set(True)
            bpy.data.objects["Z_Dummy"].select_set(True)
            bpy.data.objects["Y_Dummy"].select_set(True)

        elif target == "OBJECT":
            if deselect:
                bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[self.obj.name].select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[self.obj.name]

    def clean_up_cancel(self, context):
        bpy.data.objects.remove(
            bpy.data.objects["O_Dummy"],
            do_unlink=True,
            do_id_user=True,
            do_ui_user=True,
        )
        bpy.data.objects.data.objects.remove(
            bpy.data.objects["Z_Dummy"],
            do_unlink=True,
            do_id_user=True,
            do_ui_user=True,
        )
        bpy.data.objects.data.objects.remove(
            bpy.data.objects["Y_Dummy"],
            do_unlink=True,
            do_id_user=True,
            do_ui_user=True,
        )
        self.remove_proxy(context)

    def clean_up_confirm(self, context):
        # Keep transforms on object
        self.select_target(context, "OBJECT", active=True, deselect=True)
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
        # Dummies kill
        bpy.data.objects.remove(
            bpy.data.objects["O_Dummy"],
            do_unlink=True,
            do_id_user=True,
            do_ui_user=True,
        )
        bpy.data.objects.data.objects.remove(
            bpy.data.objects["Z_Dummy"],
            do_unlink=True,
            do_id_user=True,
            do_ui_user=True,
        )
        bpy.data.objects.data.objects.remove(
            bpy.data.objects["Y_Dummy"],
            do_unlink=True,
            do_id_user=True,
            do_ui_user=True,
        )
        self.remove_proxy(context)

    def add_proxy(self, context, target):
        size = (
            (self.obj.dimensions[0] + self.obj.dimensions[1] + self.obj.dimensions[2])
            / 3
        ) * 0.05
        bpy.ops.object.empty_add(type="CUBE", location=target.location, radius=size)
        proxy = bpy.context.view_layer.objects.active
        proxy.name = "Proxy_Dummy"
        proxy.parent = target
        proxy.matrix_parent_inverse = target.matrix_world.inverted()

    def remove_proxy(self, context):
        if "Proxy_Dummy" in bpy.data.objects:
            bpy.data.objects.remove(
                bpy.data.objects["Proxy_Dummy"],
                do_unlink=True,
                do_id_user=True,
                do_ui_user=True,
            )

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Allow only dummies selection
            ao = bpy.context.view_layer.objects.active
            dummies = ["O_Dummy", "Y_Dummy", "Z_Dummy"]
            bpy.ops.view3d.select("INVOKE_DEFAULT")
            if bpy.context.view_layer.objects.active.name not in dummies:
                bpy.data.objects[bpy.context.view_layer.objects.active.name].select_set(
                    False
                )
                bpy.context.view_layer.objects.active = ao
                bpy.data.objects[ao.name].select_set(True)

        elif event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            # Allow navigation
            return {"PASS_THROUGH"}

        elif event.type == "F1" and event.value == "PRESS":
            self.select_target(context, "O_Dummy", active=True, deselect=True)
            bpy.ops.transform.translate("INVOKE_DEFAULT")
            # self.snap_dummy(context, 'O_Dummy')

        elif event.type == "EQUAL" and event.value == "PRESS":
            bpy.data.objects["O_Dummy"].scale *= 1.5
            bpy.data.objects["Z_Dummy"].scale *= 1.5
            bpy.data.objects["Y_Dummy"].scale *= 1.5

        elif event.type == "MINUS" and event.value == "PRESS":
            bpy.data.objects["O_Dummy"].scale *= 0.75
            bpy.data.objects["Z_Dummy"].scale *= 0.75
            bpy.data.objects["Y_Dummy"].scale *= 0.75

        elif event.type == "F2" and event.value == "PRESS":
            self.select_target(context, "Y_Dummy", active=True, deselect=True)
            bpy.ops.transform.translate("INVOKE_DEFAULT")
            # self.snap_dummy(context, 'Y_Dummy')

        elif event.type == "F3" and event.value == "PRESS":
            self.select_target(context, "Z_Dummy", active=True, deselect=True)
            bpy.ops.transform.translate("INVOKE_DEFAULT")
            # self.snap_dummy(context, 'Y_Dummy')

        elif event.type == "A" and event.value == "PRESS":
            self.select_target(context, "ALL", active=True, deselect=True)

        # Link Object -> Dummy #1
        elif event.type == "ONE" and event.value == "PRESS":
            if self.obj.parent == bpy.data.objects["O_Dummy"]:
                # Clear parent if already parented
                self.select_target(context, "OBJECT", active=True, deselect=True)
                bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

                self.select_target(context, "O_Dummy", active=True, deselect=True)
                bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

                self.select_target(context, "Y_Dummy", active=True, deselect=True)
                bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

                self.select_target(context, "Z_Dummy", active=True, deselect=True)
                bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

                self.remove_proxy(context)
                self.select_target(context, "O_Dummy", active=True, deselect=True)

            else:
                # Set parent
                self.select_target(context, "OBJECT", active=False, deselect=True)
                self.select_target(context, "O_Dummy", active=True, deselect=False)
                bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
                self.add_proxy(context, self.O_Dummy)
                self.select_target(context, "Y_Dummy", active=False, deselect=True)
                self.select_target(context, "Z_Dummy", active=False, deselect=False)
                self.select_target(context, "O_Dummy", active=True, deselect=False)

        # Constrain Dummy #1 ->  Dummy #2, Link -> Object
        elif event.type == "TWO" and event.value == "PRESS":
            if "IOPS_DT_Z_Dummy" in bpy.data.objects["O_Dummy"].constraints:
                # Remove constraint if exists
                self.select_target(context, "O_Dummy", active=True, deselect=True)
                self.O_Dummy.empty_display_type = "ARROWS"
                bpy.ops.object.constraints_clear()
            else:
                # Add Constraint
                self.select_target(context, "O_Dummy", active=True, deselect=True)
                bpy.ops.object.constraint_add(type="DAMPED_TRACK")
                self.O_Dummy.empty_display_type = "SINGLE_ARROW"
                bpy.data.objects["O_Dummy"].constraints[
                    "Damped Track"
                ].name = "IOPS_DT_Z_Dummy"
                bpy.data.objects["O_Dummy"].constraints["IOPS_DT_Z_Dummy"].target = (
                    bpy.data.objects["Z_Dummy"]
                )
                bpy.data.objects["O_Dummy"].constraints[
                    "IOPS_DT_Z_Dummy"
                ].track_axis = "TRACK_Z"

        # Constrain Dummy #1 -> Dummy #3
        elif event.type == "THREE" and event.value == "PRESS":
            if (
                "IOPS_DT_Y_Dummy" in bpy.data.objects["O_Dummy"].constraints
                or "IOPS_DT_Z_Dummy" in bpy.data.objects["O_Dummy"].constraints
            ):
                # Remove constraint if exists
                self.select_target(context, "O_Dummy", active=True, deselect=True)
                bpy.ops.object.constraints_clear()

                self.O_Dummy.empty_display_type = "ARROWS"
            else:
                # Add Constraint
                self.select_target(context, "O_Dummy", active=True, deselect=True)
                bpy.ops.object.constraint_add(type="DAMPED_TRACK")
                # To Y_Dummy
                bpy.data.objects["O_Dummy"].constraints[
                    "Damped Track"
                ].name = "IOPS_DT_Y_Dummy"
                bpy.data.objects["O_Dummy"].constraints["IOPS_DT_Y_Dummy"].target = (
                    bpy.data.objects["Y_Dummy"]
                )
                bpy.data.objects["O_Dummy"].constraints[
                    "IOPS_DT_Y_Dummy"
                ].track_axis = "TRACK_Y"
                # To Z_Dummy
                bpy.ops.object.constraint_add(type="DAMPED_TRACK")
                bpy.data.objects["O_Dummy"].constraints[
                    "Damped Track"
                ].name = "IOPS_DT_Z_Dummy"
                bpy.data.objects["O_Dummy"].constraints["IOPS_DT_Z_Dummy"].target = (
                    bpy.data.objects["Z_Dummy"]
                )
                bpy.data.objects["O_Dummy"].constraints[
                    "IOPS_DT_Z_Dummy"
                ].track_axis = "TRACK_Z"
                # Display change
                self.O_Dummy.empty_display_type = "SINGLE_ARROW"

        # Reset all (restore object matrix, break link and constraint)
        elif event.type == "ZERO" and event.value == "PRESS":
            if self.obj.parent == bpy.data.objects["O_Dummy"]:
                self.select_target(context, "OBJECT", active=True, deselect=True)
                bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
            if (
                "IOPS_DT_Z_Dummy" in bpy.data.objects["O_Dummy"].constraints
                or "IOPS_DT_Y_Dummy" in bpy.data.objects["O_Dummy"].constraints
            ):
                self.select_target(context, "O_Dummy", active=True, deselect=True)
                bpy.ops.object.constraints_clear()
            self.remove_proxy(context)
            self.obj.matrix_world = self.mx

        elif event.type == "F" and event.value == "PRESS":
            z_loc = bpy.data.objects["Z_Dummy"].location.copy()
            y_loc = bpy.data.objects["Y_Dummy"].location.copy()
            bpy.data.objects["Z_Dummy"].location = y_loc
            bpy.data.objects["Y_Dummy"].location = z_loc

        elif event.type == "G" and event.value == "PRESS":
            bpy.ops.transform.translate("INVOKE_DEFAULT")
        elif event.type == "R" and event.value == "PRESS":
            bpy.ops.transform.rotate("INVOKE_DEFAULT")
        elif event.type == "S" and event.value == "PRESS":
            # Snap toggle
            bpy.context.scene.tool_settings.use_snap = (
                not bpy.context.scene.tool_settings.use_snap
            )

        elif event.type == "SPACE":
            self.restore_snaps(context)
            self.clean_up_confirm(context)
            self.clear_draw_handlers()
            self.report({"INFO"}, "3 Point Align finished")
            return {"FINISHED"}

        elif event.type in {"ESC"}:
            self.restore_snaps(context)
            self.clean_up_cancel(context)
            self.obj.matrix_world = self.mx
            self.clear_draw_handlers()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        preferences = context.preferences
        self.store_snaps(context)
        self.set_snaps(context)
        self.obj = bpy.context.view_layer.objects.active
        self.mx = bpy.context.view_layer.objects.active.matrix_world.copy()
        self.dummy_size = (
            (self.obj.dimensions[0] + self.obj.dimensions[1] + self.obj.dimensions[2])
            / 3
        ) * 0.1

        bpy.ops.object.select_all(action="DESELECT")

        # Create dummies
        # O_Dummy
        self.O_Dummy = bpy.ops.object.empty_add(
            type="SINGLE_ARROW", location=self.obj.location, radius=self.dummy_size * 3
        )
        bpy.context.view_layer.objects.active.name = "O_Dummy"
        bpy.context.view_layer.objects.active.show_in_front = True
        bpy.context.view_layer.objects.active.show_name = True
        # Z_Dummy
        self.Z_Dummy = bpy.ops.object.empty_add(
            type="SPHERE",
            location=(
                self.obj.location[0],
                self.obj.location[1],
                self.obj.location[2] + self.obj.dimensions[2] / 2,
            ),
            radius=self.dummy_size,
        )
        bpy.context.view_layer.objects.active.name = "Z_Dummy"
        bpy.context.view_layer.objects.active.show_in_front = True
        bpy.context.view_layer.objects.active.show_name = True
        # Y_Dummy
        self.Y_Dummy = bpy.ops.object.empty_add(
            type="SPHERE",
            location=(
                self.obj.location[0],
                self.obj.location[1] + self.obj.dimensions[2] / 2,
                self.obj.location[2],
            ),
            radius=self.dummy_size,
        )
        bpy.context.view_layer.objects.active.name = "Y_Dummy"
        bpy.context.view_layer.objects.active.show_in_front = True
        bpy.context.view_layer.objects.active.show_name = True

        # NAMING
        self.O_Dummy = bpy.data.objects["O_Dummy"]
        self.Z_Dummy = bpy.data.objects["Z_Dummy"]
        self.Z_Dummy = bpy.data.objects["Y_Dummy"]

        self.select_target(context, "O_Dummy", active=True, deselect=True)
        bpy.ops.object.constraint_add(type="DAMPED_TRACK")
        bpy.data.objects["O_Dummy"].constraints["Damped Track"].name = "IOPS_DT_Z_Dummy"
        bpy.data.objects["O_Dummy"].constraints["IOPS_DT_Z_Dummy"].target = (
            bpy.data.objects["Z_Dummy"]
        )
        bpy.data.objects["O_Dummy"].constraints[
            "IOPS_DT_Z_Dummy"
        ].track_axis = "TRACK_Z"

        bpy.ops.object.constraint_add(type="DAMPED_TRACK")
        bpy.data.objects["O_Dummy"].constraints["Damped Track"].name = "IOPS_DT_Y_Dummy"
        bpy.data.objects["O_Dummy"].constraints["IOPS_DT_Y_Dummy"].target = (
            bpy.data.objects["Y_Dummy"]
        )
        bpy.data.objects["O_Dummy"].constraints[
            "IOPS_DT_Y_Dummy"
        ].track_axis = "TRACK_Y"

        self.select_target(context, "O_Dummy", active=True, deselect=True)

        if context.object and context.space_data.type == "VIEW_3D":
            uidpi = int((72 * preferences.system.ui_scale))
            args_text = (self, context, uidpi, preferences.system.ui_scale)
            # Add draw handlers
            self._handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(
                draw_iops_text, args_text, "WINDOW", "POST_PIXEL"
            )
            self.ui_handlers = [self._handle_iops_text]
            # Modal handler
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}
