import bpy
import bmesh
from bpy.props import FloatProperty, BoolProperty

class IOPS_OT_VertexColorAssign(bpy.types.Operator):
    """Assign Vertex color in editr mode to selected vertecies"""

    bl_idname = "iops.mesh_assign_vertex_color"
    bl_label = "Assign Vertex color in editr mode to selected vertecies"
    bl_options = {"REGISTER", "UNDO"}

    col_attr_name: bpy.props.StringProperty(
        name="Color Attribute Name",
        default="Color"
    )
    fill_color_black: BoolProperty(
        name="Fill Black",
        #description="Fill selected vertecies with black color",
        default=False
    )
    fill_color_white: BoolProperty(
        name="Fill White",
        #descritpion="Fill selected vertecies with white color",
        default=False
    )
    fill_color_grey: BoolProperty(
        name="Fill Grey",
        #description="Fill selected vertecies with grey color",
        default=False
    )

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == "MESH"

    def execute(self, context):
        color_black = (0.0, 0.0, 0.0, 1.0)
        color_white = (1.0, 1.0, 1.0, 1.0)
        color_picker = context.scene.IOPS.iops_vertex_color

        color = color_picker

        if self.fill_color_black:
            self.fill_color_black = False
            color = color_black
        
        if self.fill_color_grey:
            self.fill_color_grey = False
            color = (0.5, 0.5, 0.5, 1.0)

        if self.fill_color_white:
            self.fill_color_white = False
            color = color_white


        sel = [obj for obj in context.selected_objects]
        # Create color attribute if not exists
        for obj in sel:
            if self.col_attr_name not in obj.data.color_attributes:
                obj.data.color_attributes.new(
                    self.col_attr_name, "FLOAT_COLOR", "POINT"
                )
            # Set color attribute as active
            color_attr = obj.data.color_attributes[self.col_attr_name]
            obj.data.color_attributes.active_color = color_attr

        if sel and context.mode == "EDIT_MESH":
            # IF EDIT MODE
            for obj in sel:
                bm = bmesh.new()
                bm = bmesh.from_edit_mesh(obj.data)
                col_layer = bm.verts.layers.float_color[self.col_attr_name]
                verts = [v for v in bm.verts if v.select]
                for v in verts:
                    v[col_layer] = color

                bmesh.update_edit_mesh(context.object.data)
                bm.free()

        elif context.mode == "OBJECT":
            self.report(
                {"WARNING"}, "OBJECT MODE. Will be implemented soon. Crashing for now."
            )
            pass
            # IF OBJECT MODE
            # # BOTH ARE CRASHING ON POST OPERATOR COLOR CHANGE
            # for obj in sel:
            #     # NON-Bmesh way
            #     for poly in obj.data.polygons:
            #         for i in poly.loop_indices:
            #             obj.data.color_attributes[self.col_attr_name].data[i].color = color

            #     # Bmesh way
            #     bm = bmesh.new()
            #     bm.from_mesh(obj.data)
            #     verts = [v for v in bm.verts]
            #     col_layer = bm.verts.layers.float_color[self.col_attr_name]
            #     for v in verts:
            #         v[col_layer] = color

            #     bm.to_mesh(obj.data)
            #     bm.free()
        else:
            self.report({"WARNING"}, obj.name + " is not a MESH.")

        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(
            context.scene.IOPS,
            "iops_vertex_color",
            text="",
        )
        col.prop(self, "col_attr_name", text="Color Attribute Name")
        col.prop(self, "fill_color_black", text="Fill Black")
        col.prop(self, "fill_color_grey", text="Fill Grey")
        col.prop(self, "fill_color_white", text="Fill White")


class IOPS_OT_VertexColorAlphaAssign(bpy.types.Operator):
    """Assign Vertex Color Alpha to selected vertecies"""

    bl_idname = "iops.mesh_assign_vertex_color_alpha"
    bl_label = "Assign Vertex Color Alpha to selected vertecies"
    bl_options = {"REGISTER", "UNDO"}

    vertex_color_alpha: FloatProperty(
        name="Alpha",
        description="Alpha channel value. 0 - Transparent, 1 - Solid",
        default=1.0,
        min=0.0,
        max=1.0,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.object
            and context.object.type == "MESH"
            and context.object.mode == "EDIT"
        )

    def execute(self, context):
        if context.object.mode == "EDIT":
            bpy.ops.object.editmode_toggle()

            mesh = bpy.context.active_object.data
            if mesh.vertex_colors[:] == []:
                mesh.vertex_colors.new()
            vertices = mesh.vertices
            vcol = mesh.vertex_colors.active

            for loop_index, loop in enumerate(mesh.loops):
                # If vertex selected
                if vertices[loop.vertex_index].select:
                    vertex_color = vcol.data[loop_index].color
                    vertex_color[3] = self.vertex_color_alpha
            mesh.update()
            bpy.ops.object.editmode_toggle()
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(self, "vertex_color_alpha", slider=True, text="Alpha value")
