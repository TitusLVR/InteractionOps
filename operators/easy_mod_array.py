import bpy
import blf

from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty
)


def draw_iops_array_text(self, context, _uidpi, _uifactor):
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
        ("Flip Start/End", "F"),
        ("X-Axis", "X"),
        ("Y-Axis", "Y"),
        ("Z-Axis", "Z"),
        ("Add Array modifier", "A"),
        ("Array duplicates count", "+/-"),
        ("Add Curve modifier", "C"),
        ("Apply", "LMB, Enter, Space"),
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


class IOPS_OT_Easy_Mod_Array_Caps(bpy.types.Operator):
    """Auto setup for array modifier"""

    bl_idname = "iops.modifier_easy_array_caps"
    bl_label = "OBJECT: Array mod and caps setup"
    bl_options = {"REGISTER", "UNDO"}

    def modal(self, context, event):
        context.area.tag_redraw()
        cursor = self.cursor
        mid_obj = self.mid_obj
        mid_obj_loc = self.mid_obj_loc
        mid_obj_dim = self.mid_obj_dim
        curve = self.curve
        cap_objs = self.cap_objs
        if len(cap_objs) == 1:
            end_obj = self.cap_objs[0]
            end_obj.name = mid_obj.name + "_END_CAP"
        else:
            start_obj = self.cap_objs[0]
            end_obj = self.cap_objs[1]
            start_obj.name = mid_obj.name + "_START_CAP"
            end_obj.name = mid_obj.name + "_END_CAP"

        # bpy.ops.object.select_all(action='DESELECT')
        # bpy.data.objects[start_obj.name].select_set(True)
        # bpy.context.view_layer.objects.active = start_obj

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            # allow navigation
            return {"PASS_THROUGH"}
        # Pick up in Local space

        elif event.type in {"F"} and event.value == "PRESS":
            if len(cap_objs) != 1:
                cap_objs[0], cap_objs[1] = cap_objs[1], cap_objs[0]
                start_obj = cap_objs[0]
                end_obj = cap_objs[1]
                start_obj.name = mid_obj.name + "_START_CAP"
                end_obj.name = mid_obj.name + "_END_CAP"

                bpy.ops.object.select_all(action="DESELECT")
                bpy.data.objects[start_obj.name].select_set(True)
                bpy.context.view_layer.objects.active = start_obj

                arr_mod = mid_obj.modifiers.get("CappedArray")
                if arr_mod:
                    arr_mod.start_cap = start_obj
                    arr_mod.end_cap = end_obj

        elif event.type in {"X"} and event.value == "PRESS":

            # Set X start
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
            cursor.location = mid_obj_loc
            cursor.location[0] -= mid_obj_dim[0]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            # Set X end
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[end_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = end_obj
            cursor.location = mid_obj_loc
            cursor.location[0] += mid_obj_dim[0]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj

        elif event.type in {"Y"} and event.value == "PRESS":
            # Set Y Start
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
            cursor.location = mid_obj_loc
            cursor.location[1] -= mid_obj_dim[1]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            # Set Y end
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[end_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = end_obj
            cursor.location = mid_obj_loc
            cursor.location[1] += mid_obj_dim[1]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj

        elif event.type in {"Z"} and event.value == "PRESS":
            # Set Z start
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
            cursor.location = mid_obj_loc
            cursor.location[2] += mid_obj_dim[2]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            # Set Z end
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[end_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = end_obj
            cursor.location = mid_obj_loc
            cursor.location[2] -= mid_obj_dim[2]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj

        elif event.type in {"A"} and event.value == "PRESS":
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj

            arr_mod = mid_obj.modifiers.get("CappedArray")
            if arr_mod:
                mid_obj.modifiers.remove(arr_mod)
            else:
                arr_mod = mid_obj.modifiers.new("CappedArray", type="ARRAY")
                if len(cap_objs) == 1:
                    arr_mod.end_cap = end_obj
                else:
                    arr_mod.start_cap = start_obj
                    arr_mod.end_cap = end_obj

        elif event.type in {"NUMPAD_MINUS"} and event.value == "PRESS":
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            arr_mod = mid_obj.modifiers.get("CappedArray")
            if arr_mod.count > 1:
                arr_mod.count -= 1
            self.report({"INFO"}, event.type)

        elif event.type in {"NUMPAD_PLUS"} and event.value == "PRESS":
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            arr_mod = mid_obj.modifiers.get("CappedArray")
            arr_mod.count += 1
            self.report({"INFO"}, event.type)

        elif event.type in {"C"} and event.value == "PRESS":
            if curve:
                if curve.location != mid_obj_loc:
                    bpy.ops.object.select_all(action="DESELECT")
                    bpy.data.objects[curve.name].select_set(True)
                    bpy.context.view_layer.objects.active = curve
                    cursor.location = mid_obj_loc
                    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

                bpy.ops.object.select_all(action="DESELECT")
                bpy.data.objects[mid_obj.name].select_set(True)
                bpy.context.view_layer.objects.active = mid_obj

                curve_mod = mid_obj.modifiers.get("CappedArrayCurve")
                arr_mod = mid_obj.modifiers.get("CappedArray")
                if curve_mod:
                    mid_obj.modifiers.remove(curve_mod)
                else:
                    curve_mod = mid_obj.modifiers.new("CappedArrayCurve", type="CURVE")
                    curve_mod.object = curve

                if arr_mod and curve_mod:
                    arr_mod.fit_type = "FIT_CURVE"
                    arr_mod.curve = curve

        elif event.type in {"LEFTMOUSE", "SPACE", "ENTER"}:
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_iops_text, "WINDOW")
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_iops_text, "WINDOW")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":
            objs = bpy.context.selected_objects
            if len(objs) == 3 or len(objs) == 4:
                preferences = context.preferences
                self.mid_obj = bpy.context.active_object
                self.mid_obj_dim = self.mid_obj.dimensions
                self.mid_obj_loc = self.mid_obj.location
                self.cursor = context.scene.cursor
                self.cap_objs = []
                self.curve_obj = []
                # get caps amd curve
                for ob in objs:
                    if ob.name != bpy.context.active_object.name:
                        if ob.type == "MESH":
                            self.cap_objs.append(ob)
                        if ob.type == "CURVE":
                            self.curve_obj.append(ob)

                print("ActiveObj: ", self.mid_obj)
                print("CapsObjs: ", self.cap_objs)
                print("CurveOBJ: ", self.curve_obj)

                if self.curve_obj:
                    self.curve = self.curve_obj[0]
                    self.curve.name = self.mid_obj.name + "_CURVE"
                    self.curve.data.use_stretch = True
                    self.curve.data.use_deform_bounds = True
                else:
                    self.curve = None

                uidpi = int((72 * preferences.system.ui_scale))
                args_text = (self, context, uidpi, preferences.system.ui_scale)
                # Add draw handlers
                self._handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(
                    draw_iops_array_text, args_text, "WINDOW", "POST_PIXEL"
                )
                # Add modal handler to enter modal mode
                context.window_manager.modal_handler_add(self)
                return {"RUNNING_MODAL"}
            else:
                self.report({"WARNING"}, "Tree objects needed, start, middle and end")
                return {"CANCELLED"}


class IOPS_OT_Easy_Mod_Array_Curve(bpy.types.Operator):
    """Auto setup for array modifier"""

    bl_idname = "iops.modifier_easy_array_curve"
    bl_label = "OBJECT: Array mod and caps setup"
    bl_options = {"REGISTER", "UNDO"}

    use_array_fit_curve: BoolProperty(
        name="Array Fit Curve Type",
        description="Switches Array Fit Type to Fit Curve otherwise keep current",
        default=True,
    )
    use_array_merge: BoolProperty(
        name="Array Merge", description="Merge verts", default=True
    )
    array_merge_distance: FloatProperty(
        name="Distance",
        description="Distance between verts for merge",
        default=0.001,
        soft_min=0.0,
        soft_max=1000000.0,
    )

    add_curve_mod: BoolProperty(
        name="Add Curve modifier",
        description="Add Curve modifier after Array modifier.",
        default=True,
    )

    use_curve_radius: BoolProperty(
        name="Use Curve Radius",
        description="Causes the deformed object to be scaled by the set curve radius.",
        default=True,
    )
    use_curve_stretch: BoolProperty(
        name="Use Curve Length",
        description="The Stretch curve option allows you to let the mesh object stretch, or squeeze, over the entire curve.",
        default=True,
    )
    use_curve_bounds_clamp: BoolProperty(
        name="Use Curve Bounds",
        description="When this option is enabled, the object and mesh offset along the deformation axis is ignored.",
        default=True,
    )
    curve_modifier_axis: EnumProperty(
        name="Deformation Axis",
        description="Deformation along selected axis",
        items=[
            ("POS_X", "X", "", "", 0),
            ("POS_Y", "Y", "", "", 1),
            ("POS_Z", "Z", "", "", 2),
            ("NEG_X", "-X", "", "", 3),
            ("NEG_Y", "-Y", "", "", 4),
            ("NEG_Z", "-Z", "", "", 5),
        ],
        default="POS_X",
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.area.type == "VIEW_3D"

    def execute(self, context):
        if (
            len(context.view_layer.objects.selected) == 1
            and context.active_object.type == "MESH"
        ):
            for mod in reversed(bpy.context.active_object.modifiers):
                if mod.type == "ARRAY" and mod.fit_type == "FIT_CURVE":
                    if mod.curve:
                        bpy.ops.object.select_all(action="DESELECT")
                        mod.curve.select_set(True)
                        context.view_layer.objects.active = mod.curve
                        self.report({"INFO"}, "Array Modifier - Curve Selected")
                        return {"FINISHED"}

        if len(context.view_layer.objects.selected) == 2:
            obj = None
            curve = None

            for ob in context.view_layer.objects.selected:
                if ob.type == "MESH":
                    obj = ob
                if ob.type == "CURVE":
                    curve = ob

            if obj and curve:
                cur = context.scene.cursor
                curve.data.use_radius = self.use_curve_radius
                curve.data.use_stretch = self.use_curve_stretch
                curve.data.use_deform_bounds = self.use_curve_bounds_clamp

                if obj.location != curve.location:
                    bpy.ops.object.select_all(action="DESELECT")
                    curve.select_set(True)
                    context.view_layer.objects.active = curve

                    if curve.data.splines.active.type == "POLY":
                        cur.location = (
                            curve.data.splines.active.points[0].co.xyz
                            @ curve.matrix_world.transposed()
                        )
                        bpy.ops.object.origin_set(type="ORIGIN_CURSOR", center="MEDIAN")

                    if curve.data.splines.active.type == "BEZIER":
                        cur.location = (
                            curve.data.splines.active.bezier_points[0].co
                            @ curve.matrix_world.transposed()
                        )
                        bpy.ops.object.origin_set(type="ORIGIN_CURSOR", center="MEDIAN")

                    if curve.data.splines.active.type == "NURBS":
                        cur.location = (
                            curve.data.splines.active.points[0].co.xyz
                            @ curve.matrix_world.transposed()
                        )
                        bpy.ops.object.origin_set(type="ORIGIN_CURSOR", center="MEDIAN")

                    bpy.ops.object.select_all(action="DESELECT")
                    obj.location = curve.location

            if obj.modifiers:
                for mod in reversed(obj.modifiers):
                    if mod.type == "ARRAY" and self.use_array_fit_curve:
                        mod.fit_type = "FIT_CURVE"
                        mod.curve = curve
                        self.report({"INFO"}, "Array Modifier - Curve picked.")

            else:
                mod = obj.modifiers.new("iOps Array", type="ARRAY")
                if self.use_array_fit_curve:
                    mod.fit_type = "FIT_CURVE"
                    mod.curve = curve
                if self.use_array_merge:
                    mod.use_merge_vertices = True
                    mod.merge_threshold = self.array_merge_distance
                    self.report({"INFO"}, "iOps Array - Merge enabled.")
                else:
                    mod.use_merge_vertices = False
                    self.report({"INFO"}, "iOps Array - Merge disabled.")

                if self.add_curve_mod:
                    mod_curve = obj.modifiers.new("iOps Curve", type="CURVE")
                    mod_curve.object = curve
                    mod_curve.deform_axis = self.curve_modifier_axis
                    mod_curve.show_in_editmode = True
                    mod_curve.show_on_cage = True

                    self.report(
                        {"INFO"}, "Curve Modifier added and curve object picked."
                    )
                self.report({"INFO"}, "Array Modifier added and wired.")

            obj.select_set(True)
            curve.select_set(True)
            context.view_layer.objects.active = obj

        return {"FINISHED"}
