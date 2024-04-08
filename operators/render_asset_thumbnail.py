import bpy
from bpy.props import FloatProperty, BoolProperty, EnumProperty
import os


def get_path():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class IOPS_OT_RenderAssetThumbnail(bpy.types.Operator):
    bl_idname = "iops.assets_render_asset_thumbnail"
    bl_label = "Render Active Asset Thumbnail"
    bl_description = "Render Active Asset Thumbnail: Collection, Object, Material, Geometry Nodes"
    bl_options = {"REGISTER", "UNDO"}

    thumbnail_lens: FloatProperty(name="Thumbnail Lens", default=100)
    toggle_overlays: BoolProperty(name="Toggle Overlays", default=True)

    render_for: EnumProperty(
        name="Render for:",
        items=[
            ("OBJECT", "Object", "Render the selected object"),
            ("COLLECTION", "Collection", "Render the selected collection"),
            ("MATERIAL", "Material", "Render the selected material"),
            ("GEOMETRY", "Geometry Nodes", "Render the selected geometry node"),

        ],
        default="COLLECTION",
    )

    def render_viewport(self, context, filepath):
        resolution = (
            context.scene.render.resolution_x,
            context.scene.render.resolution_y,
        )
        file_format = context.scene.render.image_settings.file_format
        lens = context.space_data.lens
        show_overlays = context.space_data.overlay.show_overlays

        context.scene.render.resolution_x = 500
        context.scene.render.resolution_y = 500
        context.scene.render.image_settings.file_format = "JPEG"

        context.space_data.lens = self.thumbnail_lens

        if show_overlays and self.toggle_overlays:
            context.space_data.overlay.show_overlays = False

        bpy.ops.render.opengl()

        thumb = bpy.data.images.get("Render Result")

        if thumb:
            thumb.save_render(filepath=filepath)

        context.scene.render.resolution_x = resolution[0]
        context.scene.render.resolution_y = resolution[1]
        context.space_data.lens = lens

        context.scene.render.image_settings.file_format = file_format

        if show_overlays and self.toggle_overlays:
            context.space_data.overlay.show_overlays = True

    def execute(self, context):
        if self.render_for == "COLLECTION":
            active_collection = bpy.context.collection

            thumbpath = os.path.join(get_path(), "resources", "thumb.png")
            self.render_viewport(context, thumbpath)
            if os.path.exists(thumbpath):
                with context.temp_override(id=active_collection):
                    bpy.ops.ed.lib_id_load_custom_preview(filepath=thumbpath)
                os.unlink(thumbpath)
        elif self.render_for == "OBJECT":
            active_object = bpy.context.object

            thumbpath = os.path.join(get_path(), "resources", "thumb.png")
            self.render_viewport(context, thumbpath)
            if os.path.exists(thumbpath):
                with context.temp_override(id=active_object):
                    bpy.ops.ed.lib_id_load_custom_preview(filepath=thumbpath)
                os.unlink(thumbpath)
        elif self.render_for == "MATERIAL":
            active_object = bpy.context.object
            if active_object.type == "MESH":
                active_material = active_object.active_material

                thumbpath = os.path.join(get_path(), "resources", "thumb.png")
                self.render_viewport(context, thumbpath)
                if os.path.exists(thumbpath):
                    try:
                        with context.temp_override(id=active_material):
                            bpy.ops.ed.lib_id_load_custom_preview(filepath=thumbpath)
                        os.unlink(thumbpath)
                    except RuntimeError:
                        self.report({"ERROR"}, "Current object does not have a material marked as asset")
        elif self.render_for == "GEOMETRY":
            active_object = bpy.context.object
            if active_object.type == "MESH" and active_object.modifiers.active.type == "NODES":
                active_node = active_object.modifiers.active.node_group

                thumbpath = os.path.join(get_path(), "resources", "thumb.png")
                self.render_viewport(context, thumbpath)
                if os.path.exists(thumbpath):
                    try:
                        with context.temp_override(id=active_node):
                            bpy.ops.ed.lib_id_load_custom_preview(filepath=thumbpath)
                        os.unlink(thumbpath)
                    except RuntimeError:
                        self.report({"ERROR"}, "Current object does not have a node groups marked as asset")
            else:
                self.report({"ERROR"}, "Active object is not a mesh")

        return {"FINISHED"}
