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
import numpy


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

# draw a circle on scene
def draw_circle_fill_2d(self,context):
    point = self.target
    if point != (0,0):
        position = point    
        color = (1, 0, 0, 1)
        radius = 6
        segments= 12
        # create vertices
        coords = GenerateCircleVerts(position, radius, segments)
        # create triangles
        triangles = GenerateCircleTris(segments, 0)
        # set shader and draw
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=triangles)
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

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
        color = (0.873, 0.623, 0.15, 0.1)         
        radius = 3
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
                        #X-
                        (0, 1), (1, 2), (2, 3), (0,3),
                        #X+
                        (4, 5), (5, 6), (6, 7), (4,7),
                        #Y- BTM
                        (0, 4),
                        #Y- UP
                        (1, 5),
                        #Y-BTM
                        (3, 7),
                        #Y+UP
                        (2, 6),
                        
                        #SUBD
                        #X-
                        (8, 10), (9, 11),
                        #X+
                        (12, 14), (13, 15),
                        #Y-
                        (16, 17), (8, 12), 
                        #Y+
                        (10, 14), (18, 19),                        
                        #Z-
                        (11, 15), (16, 19),
                        #Z+
                        (17, 18),(9,13),
                        
                        #Center
                        #+X
                        (20,23),
                        #-X
                        (20,21),
                        #+Y
                        (20,27),
                        #-Y
                        (20,25),
                        #+Z
                        (20,31),                        
                        #-Z
                        (20,29),
                        )
        else:
            indices = ()
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords}, indices=indices)    
        shader.bind()
        shader.uniform_float("color", (0.573, 0.323, 0.15, 1))
        batch.draw(shader)



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


    mouse_pos = (0,0)
    result = False
    result_obj = None
    posBatch = []
    posBatch3D = []
    BatchIDX = None 
    target = (0,0)
     
    
    def PlaceOrigin(self, context):
        pos = self.posBatch3D[self.BatchIDX]
        context.scene.cursor.location = pos       
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR") 
           
    #Calculate distance between raycasts
    def calc_distance(self,context):        
        mouse_pos = self.mouse_pos
        posBatch = self.posBatch        
        if len(posBatch) != 0:            
            actDist = numpy.linalg.norm(posBatch[0]-Vector(mouse_pos))
            actID = 0
            counter = 1
            itertargets = iter(self.posBatch)
            next(itertargets)
            for pos in itertargets:
                dist = numpy.linalg.norm(pos-Vector(mouse_pos))
                if dist < actDist:
                    actID = counter
                    actDist = dist
                counter += 1
            self.BatchIDX = actID 
            self.target = posBatch[actID]
        
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
                SubD_Vert_POS = []         
                bbox_Edges = ((0, 1), (1, 2), (2, 3), (0, 3),
                              (4, 5), (5, 6), (6, 7), (4, 7),
                              (0, 4), (1, 5), (2, 6), (3, 7),(0,6))
                bbox_SubD_Edges =((8, 10), (9, 11),(12, 14), (13, 15),
                                  (16, 17), (8, 12), (10, 14), (18, 19),
                                  (11, 15), (16, 19),(17, 18), (9,13))
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
                for e in bbox_SubD_Edges:
                    vert1 = Vector(bbox_Verts3D[(e[0])])
                    vert2 = Vector(bbox_Verts3D[(e[1])])
                    vertmid = (vert1+vert2)/2                    
                    pos = Vector(vertmid) 
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
            self.posBatch = bboxBatch
            self.posBatch3D = bboxBatch3D  
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
            self.calc_distance(context)          
#            print ("VERT POS",self.getFaceVertPos(context))
#            print ("MOUSE POS",self.mouse_pos)
        elif event.type in {"LEFTMOUSE", "SPACE"}:
            self.PlaceOrigin(context)
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_points, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_lines, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_points,'WINDOW')
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_act_point,'WINDOW')
            return {"FINISHED"}
            
            
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.mouse_pos = [0,0]
            self.result = False
            self.result_obj = None
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_points, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_lines, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_points,'WINDOW')
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_act_point,'WINDOW')
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
            self._handle_bbox_act_point = bpy.types.SpaceView3D.draw_handler_add(draw_circle_fill_2d,args,'WINDOW','POST_PIXEL')
            
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
