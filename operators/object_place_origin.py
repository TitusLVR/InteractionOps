import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
import bmesh
import math
from math import radians, degrees
from mathutils import Vector, Matrix, Euler

# get circle vertices on pos 2D by segments
#def GenerateCircleVerts(position, radius, segments):
#    from math import sin, cos, pi
#    coords = []
#    coords.append(position)
#    mul = (1.0 / segments) * (pi * 2)
#    for i in range(segments):
#        coord = (sin(i * mul) * radius + position[0], cos(i * mul) * radius + position[1])
#        coords.append(coord)
#    return coords


## get circle triangles by segments
#def GenerateCircleTris(segments, startID):
#    triangles = []
#    tri = startID
#    for i in range(segments-1):
#        tricomp = (startID, tri + 1, tri + 2)
#        triangles.append(tricomp)
#        tri += 1
#    tricomp = (startID, tri, startID+1)
#    triangles.append(tricomp)
#    return triangles

## draw multiple circle in one batch on screen
#def draw_multicircles_fill_2d(self, context):    
#    
#    positions = self.getFaceVertPos(context)
#    color = (1, 0, 0, 1)
#    radius = 5
#    segments= 8   

#    coords = []
#    triangles = []  
#    
#    # create vertices
#    for center in positions:
#        actCoords = GenerateCircleVerts(center, radius, segments)
#        coords.extend(actCoords)
#    # create triangles
#    for tris in range(len(positions)):
#        actTris = GenerateCircleTris(segments, tris*(segments+1))
#        triangles.extend(actTris)
#    # set shader and draw
#    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
#    batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=triangles)
#    shader.bind()
#    shader.uniform_float("color", color)
#    batch.draw(shader)




def draw_face_pts(self,context):
    print ("CALLBACK POS",self.getFaceVertPos(context))    
    coords = self.getFaceVertPos(context) # <- sequence    
    print ("!!!!!!:", coords)
    shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "POINTS", {"pos": coords})
    shader.bind()
    shader.uniform_float("color", (1, 0, 0, 1))
    batch.draw(shader)
    # pass  

class IOPS_OP_PlaceOrigin(bpy.types.Operator):
    """Place origin operator"""
    bl_idname = "iops.place_origin"
    bl_label = "Place origin"   
    
    mouse_pos = [0,0]
    
    def getFaceVertPos(self,context):
        # get the context arguments        
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = self.mouse_pos
        view_layer = context.view_layer

        # get the ray from the viewport and mouse
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        ray_target = ray_origin + view_vector
        
        result,location,normal,index,object,matrix = scene.ray_cast(view_layer,ray_origin,view_vector,distance=1.70141e+38)
        #print (index,object)    
        vertsPos = []
        if object is not None:
            mesh = object.data
            verts = mesh.polygons[index].vertices   
            for v in verts:
                vertsPos.append(mesh.vertices[v.real].co @ object.matrix_world + object.location)
            return vertsPos

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:           
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'MOUSEMOVE':
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            self.getFaceVertPos(context)
            print ("VERT POS",self.getFaceVertPos(context))
            print ("MOUSE POS",self.mouse_pos)
            
            
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_points, "WINDOW")
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            args = (self, context)
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            #self.vertPos = self.getFaceVertPos(event)
            self._handle_points = bpy.types.SpaceView3D.draw_handler_add(draw_face_pts,args,'WINDOW','POST_VIEW')
            
            print("----------------------------------------")
            
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

def register():
    bpy.utils.register_class(IOPS_OP_PlaceOrigin)


def unregister():
    bpy.utils.unregister_class(IOPS_OP_PlaceOrigin)


if __name__ == "__main__":
    register()
