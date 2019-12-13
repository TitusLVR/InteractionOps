import bpy
import copy
from mathutils import Matrix
from bpy.props import IntProperty, FloatProperty


class IOPS_OT_ThreePointRotation(bpy.types.Operator):
    """Three point rotation"""
    bl_idname = "iops.modal_three_point_rotation"
    bl_label = "Complex Modal Rotation"
    bl_options = {"REGISTER", "UNDO"}
    obj = None
    dummy_size = None
    O_Dummy = None
    Z_Dummy = None
    Y_Dummy = None
    snaps = {}
    mx = None

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")

    def store_snaps(self, context):
        self.snaps = {
                'transform_pivot_point':   bpy.context.scene.tool_settings.transform_pivot_point, 
                'snap_target':             bpy.context.scene.tool_settings.snap_target,
                'use_snap_self':           bpy.context.scene.tool_settings.use_snap_self,
                'snap_elements':           bpy.context.scene.tool_settings.snap_elements,
                'use_snap_align_rotation': bpy.context.scene.tool_settings.use_snap_align_rotation,
                'use_snap_translate':      bpy.context.scene.tool_settings.use_snap_translate,
                'use_snap_rotate':         bpy.context.scene.tool_settings.use_snap_rotate,
                'use_snap_scale':          bpy.context.scene.tool_settings.use_snap_scale,
                'use_snap_grid_absolute':  bpy.context.scene.tool_settings.use_snap_grid_absolute
                }

    def set_snaps(self, context):
        bpy.context.scene.tool_settings.transform_pivot_point   = 'ACTIVE_ELEMENT'
        bpy.context.scene.tool_settings.snap_target             = 'ACTIVE'
        bpy.context.scene.tool_settings.use_snap_self           = True
        bpy.context.scene.tool_settings.snap_elements           = {'VERTEX', 'EDGE_MIDPOINT'}
        bpy.context.scene.tool_settings.use_snap_align_rotation = False
        bpy.context.scene.tool_settings.use_snap_translate      = True
        bpy.context.scene.tool_settings.use_snap_rotate         = False
        bpy.context.scene.tool_settings.use_snap_scale          = False
        bpy.context.scene.tool_settings.use_snap_grid_absolute  = False
        bpy.context.scene.tool_settings.use_snap                = False

    def restore_snaps(self, context):
        bpy.context.scene.tool_settings.transform_pivot_point   = self.snaps['transform_pivot_point']
        bpy.context.scene.tool_settings.snap_target             = self.snaps['snap_target']
        bpy.context.scene.tool_settings.use_snap_self           = self.snaps['use_snap_self']
        bpy.context.scene.tool_settings.snap_elements           = self.snaps['snap_elements']
        bpy.context.scene.tool_settings.use_snap_align_rotation = self.snaps['use_snap_align_rotation']
        bpy.context.scene.tool_settings.use_snap_translate      = self.snaps['use_snap_translate']
        bpy.context.scene.tool_settings.use_snap_rotate         = self.snaps['use_snap_rotate']
        bpy.context.scene.tool_settings.use_snap_scale          = self.snaps['use_snap_scale']
        bpy.context.scene.tool_settings.use_snap_grid_absolute  = self.snaps['use_snap_grid_absolute']

    def snap_dummy(self, context, dummy):
        if dummy == 'FIRST':
            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.view_layer.objects.active = bpy.data.objects['O_Dummy']
            bpy.data.objects['O_Dummy'].select_set(True)
            bpy.ops.transform.translate('INVOKE_DEFAULT')
        if dummy == 'SECOND':
            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.view_layer.objects.active = bpy.data.objects['Z_Dummy']
            bpy.data.objects['Z_Dummy'].select_set(True)
            bpy.ops.transform.translate('INVOKE_DEFAULT')
        if dummy == 'THIRD':
            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.view_layer.objects.active = bpy.data.objects['Y_Dummy']
            bpy.data.objects['Y_Dummy'].select_set(True)
            bpy.ops.transform.translate('INVOKE_DEFAULT')

    def select_target(self, context, target, active, deselect):
        if target == 'FIRST':
            if deselect:
                bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects['O_Dummy'].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects['O_Dummy']

        elif target == 'SECOND':
            if deselect:
                bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects['Z_Dummy'].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects['Z_Dummy']

        elif target == 'THIRD':
            if deselect:
                bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects['Y_Dummy'].select_set(True)
            if active:
                bpy.context.view_layer.objects.active = bpy.data.objects['Y_Dummy']

        elif target == 'BOTH':
            if deselect:
                bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects['O_Dummy'].select_set(True)
            bpy.data.objects['Z_Dummy'].select_set(True)
            bpy.data.objects['Y_Dummy'].select_set(True)
        
        elif target == 'OBJECT':
            if deselect:
                bpy.ops.object.select_all(action='DESELECT')
            bpy.data.objects[self.obj.name].select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[self.obj.name]

    def clean_up_cancel(self, context):
        bpy.data.objects.remove(bpy.data.objects['O_Dummy'], do_unlink=True, do_id_user=True, do_ui_user=True)
        bpy.data.objects.data.objects.remove(bpy.data.objects['Z_Dummy'], do_unlink=True, do_id_user=True, do_ui_user=True)
        bpy.data.objects.data.objects.remove(bpy.data.objects['Y_Dummy'], do_unlink=True, do_id_user=True, do_ui_user=True)
        self.remove_proxy(context)
    
    def clean_up_confirm(self, context):
        # Keep transforms on object
        self.select_target(context, 'OBJECT', active=True, deselect=True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        # Dummies kill
        bpy.data.objects.remove(bpy.data.objects['O_Dummy'], do_unlink=True, do_id_user=True, do_ui_user=True)
        bpy.data.objects.data.objects.remove(bpy.data.objects['Z_Dummy'], do_unlink=True, do_id_user=True, do_ui_user=True)
        bpy.data.objects.data.objects.remove(bpy.data.objects['Y_Dummy'], do_unlink=True, do_id_user=True, do_ui_user=True)
        self.remove_proxy(context)

    def add_proxy(self, context, target):
        size = ((self.obj.dimensions[0] + self.obj.dimensions[1] + self.obj.dimensions[2]) / 3) * 0.05
        bpy.ops.object.empty_add(type='CUBE', location=target.location, radius=size)
        proxy = bpy.context.view_layer.objects.active
        proxy.name = "IOPS_Proxy"
        proxy.parent = target
        proxy.matrix_parent_inverse = target.matrix_world.inverted()
        
    
    def remove_proxy(self, context):
        if 'IOPS_Proxy' in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects['IOPS_Proxy'], do_unlink=True, do_id_user=True, do_ui_user=True)


    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":            
            bpy.ops.view3d.select('INVOKE_DEFAULT')       

        elif event.type in {'MIDDLEMOUSE','WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # Allow navigation
            return {'PASS_THROUGH'}
        
        elif event.type == 'F1' and event.value == "PRESS":
            self.select_target(context, 'FIRST', active=True, deselect=True)
            bpy.ops.transform.translate('INVOKE_DEFAULT')
            # self.snap_dummy(context, 'FIRST')

        elif event.type == 'F2' and event.value == "PRESS":
            self.select_target(context, 'SECOND', active=True, deselect=True)
            bpy.ops.transform.translate('INVOKE_DEFAULT')
            # self.snap_dummy(context, 'SECOND')

        # Link Object -> Dummy #1
        elif event.type == 'ONE' and event.value == "PRESS":
            if self.obj.parent == bpy.data.objects['O_Dummy']:
                # Clear parent if already parented
                self.select_target(context, 'OBJECT', active=True, deselect=True)
                bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
                self.remove_proxy(context)
                self.select_target(context, 'FIRST', active=True, deselect=True)

            else:
                # Set parent
                self.select_target(context, 'OBJECT', active=False, deselect=True)
                self.select_target(context, 'FIRST', active=True, deselect=False)
                bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
                self.add_proxy(context, self.O_Dummy)
                self.select_target(context, 'FIRST', active=True, deselect=True)

        #Constrain Dummy #1 ->  Dummy #2, Link -> Object
        elif event.type == 'TWO' and event.value == "PRESS":
            if "IOPS_DT_Z_Dummy" in bpy.data.objects['O_Dummy'].constraints:
                # Remove constraint if exists
                self.select_target(context, 'FIRST', active=True, deselect=True)
                self.O_Dummy.empty_display_type = 'ARROWS'
                bpy.ops.object.constraints_clear()
            else:
                # Add Constraint
                self.select_target(context, 'FIRST', active=True, deselect=True)
                bpy.ops.object.constraint_add(type='DAMPED_TRACK')
                self.O_Dummy.empty_display_type = 'SINGLE_ARROW'
                bpy.data.objects['O_Dummy'].constraints['Damped Track'].name = "IOPS_DT_Z_Dummy"
                bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Z_Dummy'].target = bpy.data.objects['Z_Dummy']
                bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Z_Dummy'].track_axis = 'TRACK_Z'

        # #Constrain Dummy #1 -> Dummy #3
        # elif event.type == 'THREE' and event.value == "PRESS":
        #     if "Damped Track" in bpy.data.objects['O_Dummy'].constraints:
        #         # Remove constraint if exists
        #         self.select_target(context, 'FIRST', active=True, deselect=True)
        #         self.O_Dummy.empty_display_type = 'ARROWS'
        #         bpy.ops.object.constraints_clear()
        #     else:
        #         # Add Constraint
        #         self.select_target(context, 'FIRST', active=True, deselect=True)
        #         bpy.ops.object.constraint_add(type='DAMPED_TRACK')
        #         self.O_Dummy.empty_display_type = 'SINGLE_ARROW'
        #         bpy.data.objects['O_Dummy'].constraints['Damped Track'].name = "IOPS_DT_Y_Dummy"
        #         bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Y_Dummy'].target = bpy.data.objects['Y_Dummy']
        #         bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Y_Dummy'].track_axis = 'TRACK_Y'
                
        # Reset all (restore object matrix, break link and constraint)
        elif event.type == 'ZERO' and event.value == "PRESS":
            if self.obj.parent == bpy.data.objects['O_Dummy']:
                self.select_target(context, 'OBJECT', active=True, deselect=True)
                bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            if "IOPS_DT_Z_Dummy" in bpy.data.objects['O_Dummy'].constraints:
                self.select_target(context, 'FIRST', active=True, deselect=True)
                bpy.ops.object.constraints_clear()
            self.obj.matrix_world = self.mx
        
        elif event.type == 'G' and event.value == "PRESS":
            bpy.ops.transform.translate('INVOKE_DEFAULT')
        elif event.type == 'R' and event.value == "PRESS":
            bpy.ops.transform.rotate('INVOKE_DEFAULT')
        elif event.type == 'S' and event.value == "PRESS":
            #Snap toggle
            bpy.context.scene.tool_settings.use_snap = not bpy.context.scene.tool_settings.use_snap
        
        elif event.type == 'SPACE':
            self.restore_snaps(context)
            self.clean_up_confirm(context)
            return {'FINISHED'}

        elif event.type in {'ESC'}:
            self.restore_snaps(context)
            self.clean_up_cancel(context)
            self.obj.matrix_world = self.mx
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        self.store_snaps(context)
        self.set_snaps(context)
        self.obj = bpy.context.view_layer.objects.active
        self.mx = bpy.context.view_layer.objects.active.matrix_world.copy()
        self.dummy_size = ((self.obj.dimensions[0] + self.obj.dimensions[1] + self.obj.dimensions[2]) / 3) * 0.1

        bpy.ops.object.select_all(action='DESELECT')

        #Create dummies
        # FIRST
        self.O_Dummy = bpy.ops.object.empty_add(type='SINGLE_ARROW', location=(self.obj.location[0], 
                                                                                   self.obj.location[1], 
                                                                                   self.obj.location[2] - self.obj.dimensions[2]/2), 
                                                    radius=self.dummy_size*3)
        bpy.context.view_layer.objects.active.name = "O_Dummy"
        bpy.context.view_layer.objects.active.show_in_front = True
        bpy.context.view_layer.objects.active.show_name = True
        # SECOND
        self.Z_Dummy = bpy.ops.object.empty_add(type='SPHERE', 
                                                     location=(self.obj.location[0],
                                                               self.obj.location[1],
                                                               self.obj.location[2] + self.obj.dimensions[2]/2), 
                                                     radius=self.dummy_size)
        bpy.context.view_layer.objects.active.name = "Z_Dummy"
        bpy.context.view_layer.objects.active.show_in_front = True
        bpy.context.view_layer.objects.active.show_name = True
        # THIRD
        self.Y_Dummy = bpy.ops.object.empty_add(type='SPHERE', 
                                                     location=(self.obj.location[0],
                                                               self.obj.location[1],
                                                               self.obj.location[2]), 
                                                     radius=self.dummy_size)
        bpy.context.view_layer.objects.active.name = "Y_Dummy"
        bpy.context.view_layer.objects.active.show_in_front = True
        bpy.context.view_layer.objects.active.show_name = True

        # NAMING
        self.O_Dummy  = bpy.data.objects['O_Dummy']
        self.Z_Dummy = bpy.data.objects['Z_Dummy']
        self.Z_Dummy = bpy.data.objects['Y_Dummy']

        self.select_target(context, 'FIRST', active=True, deselect=True)
        bpy.ops.object.constraint_add(type='DAMPED_TRACK')
        bpy.data.objects['O_Dummy'].constraints['Damped Track'].name = "IOPS_DT_Z_Dummy"
        bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Z_Dummy'].target = bpy.data.objects['Z_Dummy']
        bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Z_Dummy'].track_axis = 'TRACK_Z'

        bpy.ops.object.constraint_add(type='DAMPED_TRACK')
        bpy.data.objects['O_Dummy'].constraints['Damped Track'].name = "IOPS_DT_Y_Dummy"
        bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Y_Dummy'].target = bpy.data.objects['Y_Dummy']
        bpy.data.objects['O_Dummy'].constraints['IOPS_DT_Y_Dummy'].track_axis = 'TRACK_Y'

        self.select_target(context, 'FIRST', active=True, deselect=True)

        if context.object:
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "No active object, could not finish")
            return {'CANCELLED'}