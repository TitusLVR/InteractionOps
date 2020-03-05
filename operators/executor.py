import bpy
import copy

class IOPS_OT_EXECUTOR(bpy.types.Operator):
    """ Execute info operators from buffer """
    bl_idname = "iops.executor"
    bl_label = "IOPS Executor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selection = context.view_layer.objects.selected        
        buf = ""
        buf = copy.deepcopy(bpy.context.window_manager.clipboard.splitlines())
        if len(selection) != 0: 
            for window in bpy.context.window_manager.windows:
                screen = window.screen
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        override = {'window': window, 'screen': screen, 'area': area}
            for ob in selection:
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ob
                ob.select_set(True)
                for line in buf:
                    cmd = line.split('()')
                    cmd = str(cmd[0]) + "(override)"                     
                    try:
                        exec(cmd)
                        print(cmd)                                   
                    except:
                        continue

        return {"FINISHED"}
