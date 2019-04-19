class AlignObjectToFace(bpy.types.Operator):
    """ Align object to selected face """
    bl_idname = "iops.align_object_to_face"
    bl_label = "iOps Align object to face"
    bl_options = {"REGISTER","UNDO"}

    AlignObjToFace: BoolProperty(
    name = "Align object to selected face",
    description = "Align object to selected face",        
    default = False    
    )
    
    def execute(self, context):
        self.AlignObjectToFace()
        self.report ({"INFO"}, "Object aligned")
        return{"FINISHED"}
       
    @classmethod   
    def AlignObjectToFace(cls):   
        """ Takes face normal and aligns it to global axis.
            Uses one of the face edges to further align it to another axis.
            
            TODO: Convert to MODAL
        """     
        obj = bpy.context.active_object
        mx = obj.matrix_world
        loc = mx.to_translation()           #  Store location   
        polymesh = obj.data            
        bm = bmesh.from_edit_mesh(polmesh)    
        face = []

        # Get active face
        for f in bm.faces:
            if f.select == True:            
                print ("Selected = ",f)
                face = f

        # Build vectors for new matrix               
        n = face.normal                # Z
        t = face.calc_tangent_edge()   # Y
        c = t.cross(n)                 # X

        # Assemble new matrix    
        mx_rot = Matrix((c, t, n)).transposed().to_4x4() 
        obj.matrix_world = mx_rot.inverted()
        obj.location = loc    
