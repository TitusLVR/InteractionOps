import bpy
import blf

def draw_iops_array_text(self, context, _uidpi, _uifactor):
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
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
    blf.size(font, tCSize, _uidpi)
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
    """ Auto setup for array modifier """
    bl_idname = "iops.easy_mod_array_caps"
    bl_label = "OBJECT: Array mod and caps setup"
    bl_options = {"REGISTER", "UNDO"}

    def modal(self, context, event):
        context.area.tag_redraw()
        cap_objs = self.cap_objs
        start_obj = self.cap_objs[0]
        end_obj = self.cap_objs[1]
        cursor = self.cursor
        mid_obj = self.mid_obj
        mid_obj_loc = self.mid_obj_loc
        mid_obj_dim = self.mid_obj_dim
        curve = self.curve
        start_obj.name = mid_obj.name + "_START_CAP"
        end_obj.name = mid_obj.name + "_END_CAP"
        # bpy.ops.object.select_all(action='DESELECT')
        # bpy.data.objects[start_obj.name].select_set(True)
        # bpy.context.view_layer.objects.active = start_obj

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        # Pick up in Local space

        elif event.type in {'F'} and event.value == "PRESS":
            cap_objs[0], cap_objs[1] = cap_objs[1], cap_objs[0]
            start_obj = cap_objs[0]
            end_obj = cap_objs[1]
            start_obj.name = mid_obj.name + "_START_CAP"
            end_obj.name = mid_obj.name + "_END_CAP"
            
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj

        elif event.type in {'X'} and event.value == "PRESS":
            
            # Set X start
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
            cursor.location = mid_obj_loc
            cursor.location[0] -= mid_obj_dim[0]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            # Set X end
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[end_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = end_obj
            cursor.location = mid_obj_loc
            cursor.location[0] += mid_obj_dim[0]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj


        elif event.type in {'Y'} and event.value == "PRESS":            
            # Set Y Start
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
            cursor.location = mid_obj_loc
            cursor.location[1] -= mid_obj_dim[1]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            # Set Y end
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[end_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = end_obj
            cursor.location = mid_obj_loc
            cursor.location[1] += mid_obj_dim[1]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            
            bpy.ops.object.select_all(action='DESELECT')            
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj

        elif event.type in {'Z'} and event.value == "PRESS":
            # Set Z start
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
            cursor.location = mid_obj_loc
            cursor.location[2] += mid_obj_dim[2]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            # Set Z end
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[end_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = end_obj
            cursor.location = mid_obj_loc
            cursor.location[2] -= mid_obj_dim[2]
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[start_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = start_obj
        
        elif event.type in {'A'} and event.value == "PRESS":
            bpy.ops.object.select_all(action='DESELECT')            
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            
            arr_mod = mid_obj.modifiers.get("CappedArray")
            if arr_mod:
                mid_obj.modifiers.remove(arr_mod)
            else:
                arr_mod = mid_obj.modifiers.new("CappedArray", type='ARRAY')
                arr_mod.start_cap = start_obj
                arr_mod.end_cap = end_obj
        
        elif event.type in {'NUMPAD_MINUS'} and event.value == "PRESS":
            bpy.ops.object.select_all(action='DESELECT')            
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj            
            arr_mod = mid_obj.modifiers.get("CappedArray")
            if arr_mod.count > 1:
                arr_mod.count -= 1            
            self.report({"INFO"}, event.type)
        
        elif event.type in {'NUMPAD_PLUS'} and event.value == "PRESS":
            bpy.ops.object.select_all(action='DESELECT')            
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj            
            arr_mod = mid_obj.modifiers.get("CappedArray")        
            arr_mod.count += 1
            self.report({"INFO"}, event.type)            
        
        elif event.type in {'C'} and event.value == "PRESS":
            if curve:
                if curve.location != mid_obj_loc:
                    bpy.ops.object.select_all(action='DESELECT')
                    bpy.data.objects[curve.name].select_set(True)
                    bpy.context.view_layer.objects.active = curve
                    cursor.location = mid_obj_loc
                    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                    
                bpy.ops.object.select_all(action='DESELECT')
                bpy.data.objects[mid_obj.name].select_set(True)
                bpy.context.view_layer.objects.active = mid_obj

                curve_mod = mid_obj.modifiers.get("CappedArrayCurve")
                if curve_mod:
                    mid_obj.modifiers.remove(curve_mod)
                else:
                    curve_mod = mid_obj.modifiers.new("CappedArrayCurve", type='CURVE')
                    curve_mod.object = curve

        elif event.type in {'LEFTMOUSE', 'SPACE', 'ENTER'}:
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_iops_text, "WINDOW")
            return {'FINISHED'}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[mid_obj.name].select_set(True)
            bpy.context.view_layer.objects.active = mid_obj
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_iops_text, "WINDOW")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":
            objs = bpy.context.selected_objects
            if len(objs) == 3 or len(objs) == 4 :
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
                        if ob.type == 'MESH':                        
                            self.cap_objs.append(ob)
                        if ob.type == 'CURVE':                        
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
                self._handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(draw_iops_array_text, args_text, 'WINDOW', 'POST_PIXEL')
                # Add modal handler to enter modal mode
                context.window_manager.modal_handler_add(self)
                return {"RUNNING_MODAL"}
            else:
                self.report({'WARNING'}, "Tree objects needed, start, middle and end")
                return {'CANCELLED'}


class IOPS_OT_Easy_Mod_Array_Curve(bpy.types.Operator):
    """ Auto setup for array modifier """
    bl_idname = "iops.easy_mod_array_curve"
    bl_label = "OBJECT: Array mod and caps setup"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":
            objs = bpy.context.selected_objects
            # if len(objs) == 2:

            return {'FINISHED'}
               





