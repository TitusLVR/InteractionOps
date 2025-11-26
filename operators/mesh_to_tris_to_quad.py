import bpy


class IOPS_OT_MeshToTrisToQuads(bpy.types.Operator):
    bl_idname = "iops.mesh_to_tris_to_quads"
    bl_label = "Mesh To Tris To Quads"
    bl_options = {"REGISTER", "UNDO"}

    # Properties for quads_convert_to_tris
    quad_method: bpy.props.EnumProperty(
        name="Quad Method",
        items=[
            ("BEAUTY", "Beauty", "Split the quads in the nicest way"),
            ("FIXED", "Fixed", "Split the quads on the 1st and 3rd vertices"),
            (
                "FIXED_ALTERNATE",
                "Fixed Alternate",
                "Split the quads on the 2nd and 4th vertices",
            ),
            (
                "SHORTEST_DIAGONAL",
                "Shortest Diagonal",
                "Split the quads based on the distance between the vertices",
            ),
        ],
        default="BEAUTY",
    )
    ngon_method: bpy.props.EnumProperty(
        name="N-gon Method",
        items=[
            ("BEAUTY", "Beauty", "Arrange the new triangles nicely"),
            ("CLIP", "Clip", "Split the n-gons using the ear clipping algorithm"),
        ],
        default="BEAUTY",
    )

    # Properties for tris_convert_to_quads
    face_threshold: bpy.props.FloatProperty(
        name="Max Face Angle",
        default=0.698132,
        min=0.0,
        max=3.14159,
        subtype="ANGLE",
    )
    shape_threshold: bpy.props.FloatProperty(
        name="Max Shape Angle",
        default=1.5708,
        min=0.0,
        max=3.14159,
        subtype="ANGLE",
    )
    topology_influence: bpy.props.FloatProperty(
        name="Topology Influence",
        default=2.0,
        min=0.0,
        max=2.0,
    )
    uvs: bpy.props.BoolProperty(name="Compare UVs", default=False)
    vcols: bpy.props.BoolProperty(name="Compare Color Attributes", default=False)
    seam: bpy.props.BoolProperty(name="Compare Seam", default=False)
    sharp: bpy.props.BoolProperty(name="Compare Sharp", default=False)
    materials: bpy.props.BoolProperty(name="Compare Materials", default=False)
    deselect_joined: bpy.props.BoolProperty(name="Deselect Joined", default=False)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Triangulate")
        box.prop(self, "quad_method")
        box.prop(self, "ngon_method")

        box = layout.box()
        box.label(text="Tris to Quads")
        box.prop(self, "face_threshold")
        box.prop(self, "shape_threshold")
        box.prop(self, "topology_influence")

        col = box.column(align=True)
        col.prop(self, "uvs")
        col.prop(self, "vcols")
        col.prop(self, "seam")
        col.prop(self, "sharp")
        col.prop(self, "materials")
        col.prop(self, "deselect_joined")

    def execute(self, context):
        bpy.ops.mesh.quads_convert_to_tris(
            quad_method=self.quad_method, ngon_method=self.ngon_method
        )
        bpy.ops.mesh.tris_convert_to_quads(
            face_threshold=self.face_threshold,
            shape_threshold=self.shape_threshold,
            topology_influence=self.topology_influence,
            uvs=self.uvs,
            vcols=self.vcols,
            seam=self.seam,
            sharp=self.sharp,
            materials=self.materials,
            deselect_joined=self.deselect_joined,
        )
        return {"FINISHED"}
