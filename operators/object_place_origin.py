import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import region_2d_to_vector_3d, region_2d_to_origin_3d, location_3d_to_region_2d
from bpy_extras import view3d_utils
import bmesh
import math
from math import radians, degrees
from mathutils import Vector, Matrix, Euler
from math import sin, cos, pi


# get circle vertices on pos 2D by segments
def GenerateCircleVerts(position, radius, segments):    
    coords = []
    coords.append(position)
    mul = (1.0 / segments) * (pi * 2)
    for i in range(segments):
        coord = (sin(i * mul) * radius + position[0], cos(i * mul) * radius + position[1])
        coords.append(coord)
    return coords


## get circle triangles by segments
def GenerateCircleTris(segments, startID):
    triangles = []
    tri = startID
    for i in range(segments-1):
        tricomp = (startID, tri + 1, tri + 2)
        triangles.append(tricomp)
        tri += 1
    tricomp = (startID, tri, startID+1)
    triangles.append(tricomp)
    return triangles

## draw multiple circle in one batch on screen
def draw_multicircles_fill_2d_Face(self, context):    
    positions = (self.ObjectBBox(context))[0]
    if positions != None: 
        color = (0.973, 0.723, 0.15, 0.1)
        radius = 5
        segments= 12
        coords = []
        triangles = []  
        # create vertices
        for center in positions:
            actCoords = GenerateCircleVerts(center, radius, segments)
            coords.extend(actCoords)
        # create triangles
        for tris in range(len(positions)):
            actTris = GenerateCircleTris(segments, tris*(segments+1))
            triangles.extend(actTris)
        # set shader and draw
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=triangles)
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

## draw multiple circle in one batch on screen
def draw_multicircles_fill_2d_BBOX(self, context):    
    positions = (self.ObjectBBox(context))[2]
    if positions != None: 
        color = (0.973, 0.723, 0.15, 0.1)
        radius = 5
        segments= 16
        coords = []
        triangles = []  
        # create vertices
        for center in positions:
            actCoords = GenerateCircleVerts(center, radius, segments)
            coords.extend(actCoords)
        # create triangles
        for tris in range(len(positions)):
            actTris = GenerateCircleTris(segments, tris*(segments+1))
            triangles.extend(actTris)
        # set shader and draw
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=triangles)
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

def draw_bbox_lines(self,context):
    coords = (self.ObjectBBox(context))[3]
    if len(coords) != 0:    
        if len(coords) == 8:
            indices = (
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)
            )
        elif len(coords) > 8:  
            indices = (
                        #Bbox
                        (0, 1), (1, 2), (2, 3), (3, 0),
                        (4, 5), (5, 6), (6, 7), (7, 4),
                        (0, 4), (1, 5), (2, 6), (3, 7),
                        #SUBD
                        #(8, 10), (9, 11), (12, 14), (13,15),
                        #(16,17), (17, 18),(19,16),(11,15),
                        #(12,8)                        
                        )
        else:
            indices = ()
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords}, indices=indices)    
        shader.bind()
        shader.uniform_float("color", (0.873, 0.623, 0.15, 1))
        batch.draw(shader)

#Calculate distance between raycasts
def calc_distance(step,old_loc,new_loc):
        distance = math.sqrt(((old_loc[0]-new_loc[0])**2)+((old_loc[1]-new_loc[1])**2))
        if step <= distance:
            return True
        else:
            return False

#def draw_face_pts(self,context):
#    print ("CALLBACK POS",self.getFaceVertPos(context))    
#    coords = self.getFaceVertPos(context) # <- sequence    
#    print ("!!!!!!:", coords)
#    shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
#    batch = batch_for_shader(shader, "POINTS", {"pos": coords})
#    shader.bind()
#    shader.uniform_float("color", (1, 0, 0, 1))
#    batch.draw(shader)
#    # pass  


class IOPS_OP_PlaceOrigin(bpy.types.Operator):
    """Place origin operator"""
    bl_idname = "iops.place_origin"
    bl_label = "Place origin"   


    mouse_pos = [0,0]
    result = False
    result_obj = None   
       
        
    def getClosestPoint(self,context):
        coord = self.mouse_pos        
        
    def SceneRayCast(self,context):
        # get the context arguments        
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = self.mouse_pos
        view_layer = context.view_layer

        # get the ray from the viewport and mouse
        view_vector = region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = region_2d_to_origin_3d(region, rv3d, coord)

        ray_target = ray_origin + view_vector
        
        result,location,normal,index,object,matrix = scene.ray_cast(view_layer,ray_origin,view_vector,distance=1.70141e+38)        
        
        if result:
            self.result = result
            self.result_obj = object
            return result,object
        else:
            if self.result_obj != None:
                pass
            else:
                object = None            
            return result, object
    
    def ObjectBBox(self, context):
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = self.mouse_pos
        view_layer = context.view_layer
        
        res = self.result
        object = self.result_obj 
        vertsPos = []
        bboxBatch =[]
        bboxBatch3D = []       
        faceBatch = []
        faceBatch3D = []
        if object != None:                        
            #verts = mesh.polygons[index].vertices            
            matrix = object.matrix_world 
            matrix_trans = matrix.transposed()
            
            bbox = object.bound_box
            bbox_Verts3D =[]
            if len(bbox) != 0:         
                bbox_Edges = ((0, 1), (1, 2), (2, 3), (3, 0),
                              (4, 5), (5, 6), (6, 7), (7, 4),
                              (0, 4), (1, 5), (2, 6), (3, 7))
                #BBox
                for v in bbox:                
                    pos = Vector(v) @  matrix_trans               
                    bbox_Verts3D.append(pos)
                #BBox Edge subD
                for e in bbox_Edges:                    
                    vert1 = Vector(bbox[(e[0])])
                    vert2 = Vector(bbox[(e[1])])
                    vertmid = (vert1+vert2)/2
                    pos = Vector(vertmid) @  matrix_trans
                    bbox_Verts3D.append(pos)                                 
                #BBOX COLLECT
                for v in bbox_Verts3D:                
                    pos3D = v            
                    pos2D = location_3d_to_region_2d(region, rv3d, pos3D, default=None)
                    bboxBatch3D.append(pos3D)
                    bboxBatch.append(pos2D)                
                #print (len(bboxBatch))            
            
            #bpy.data.meshes.remove(bbox_mesh, do_unlink=True,do_id_user=True, do_ui_user=True)                
            #FACE COLLECT          
#            for v in verts:
#                pos3D = (mesh.vertices[v.real].co @ matrix + object.location)
#                pos2D = location_3d_to_region_2d(region, rv3d, pos3D, default=None)
#                faceBatch3D.append(pos3D)
#                faceBatch.append(pos2D)
            #return vertsPos            
            return [faceBatch,faceBatch3D, bboxBatch, bboxBatch3D]
        else:
            return [None,None, bboxBatch, bboxBatch3D]
        

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:           
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'MOUSEMOVE':
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            self.SceneRayCast(context)
            self.ObjectBBox(context)          
#            print ("VERT POS",self.getFaceVertPos(context))
#            print ("MOUSE POS",self.mouse_pos)
            
            
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.mouse_pos = [0,0]
            self.result = False
            self.result_obj = None
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_points, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_lines, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_points,'WINDOW')
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            args = (self, context)
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            #self.vertPos = self.getFaceVertPos(event)
            self.result,self.result_obj = self.SceneRayCast(context)
            self._handle_points = bpy.types.SpaceView3D.draw_handler_add(draw_multicircles_fill_2d_Face,args,'WINDOW','POST_PIXEL')
            self._handle_bbox_lines = bpy.types.SpaceView3D.draw_handler_add(draw_bbox_lines,args,'WINDOW','POST_VIEW')
            self._handle_bbox_points = bpy.types.SpaceView3D.draw_handler_add(draw_multicircles_fill_2d_BBOX,args,'WINDOW','POST_PIXEL')
            
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
