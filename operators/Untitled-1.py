import bpy
from bpy_extras import view3d_utils


         



def draw_face_pts(self, context):
    coords = self.getFaceVertPos() # <- sequence
    shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "POINTS", {"pos": coords})
    shader.bind()
    shader.uniform_float("color", (1, 0, 0, 1))
    batch.draw(shader)
    # pass  

class ViewOperatorRayCast(bpy.types.Operator):
    """Modal object selection with a ray cast"""
    bl_idname = "view3d.modal_operator_raycast"
    bl_label = "RayCast View Operator"   
    
    
    def getFaceVertPos(context, event):
    """Run this function on left mouse, execute the ray cast"""
        # get the context arguments
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y
        view_layer = context.view_layer

        # get the ray from the viewport and mouse
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        ray_target = ray_origin + view_vector
        
        result,location,normal,index,object,matrix = scene.ray_cast(view_layer,ray_origin,view_vector,distance=1.70141e+38)
        print (index,object)    
        vertsPos = []
        mesh = object.data
        verts = mesh.polygons[index].vertices   
        for v in verts:
            vertsPos.append(mesh.vertices[v.real].co)
        return vertsPos

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'LEFTMOUSE':
            getFaceVertPos(context, event)
            return {'RUNNING_MODAL'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_points, "WINDOW")
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            args = (self, context)
            self._handle_points = bpy.types.SpaceView3D.draw_handler_add(draw_face_pts,args,'WINDOW','POST_VIEW')
            self.pairs = self.getFaceVertPos(context,event)
            print("----------------------------------------")
            print(self.pairs)
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

def register():
    bpy.utils.register_class(ViewOperatorRayCast)


def unregister():
    bpy.utils.unregister_class(ViewOperatorRayCast)


if __name__ == "__main__":
    register()