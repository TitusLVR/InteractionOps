import bpy
from bpy.props import FloatProperty, BoolProperty, EnumProperty
import math
import os
import tempfile
import uuid
import array

from mathutils import Vector, Matrix


def get_path():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def get_view3d_context(context):
    """Return (area, region) for a VIEW_3D so we can override context, or (None, None)."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return area, region
    return None, None


def get_objects_to_frame(context, render_for):
    """Return list of objects to frame in the view based on render_for."""
    if render_for == "COLLECTION":
        coll = context.collection
        return [ob for ob in coll.all_objects if ob.type in ("MESH", "CURVE", "SURFACE", "META", "FONT")]
    if render_for == "OBJECT":
        ob = context.object
        return [ob] if ob else []
    if render_for in ("MATERIAL", "GEOMETRY"):
        ob = context.object
        return [ob] if ob and ob.type == "MESH" else []
    return []


def compute_combined_bound_box(objects):
    """World-space axis-aligned bounding box encompassing all objects. Returns (min, max) or None."""
    if not objects:
        return None
    inf = float("inf")
    bb_min = Vector((inf, inf, inf))
    bb_max = Vector((-inf, -inf, -inf))
    for ob in objects:
        for corner in ob.bound_box:
            wc = ob.matrix_world @ Vector(corner)
            bb_min.x = min(bb_min.x, wc.x)
            bb_min.y = min(bb_min.y, wc.y)
            bb_min.z = min(bb_min.z, wc.z)
            bb_max.x = max(bb_max.x, wc.x)
            bb_max.y = max(bb_max.y, wc.y)
            bb_max.z = max(bb_max.z, wc.z)
    return bb_min, bb_max


# ---------------------------------------------------------------------------
#   Camera geometry helpers (single source of truth)
# ---------------------------------------------------------------------------

_VIEW_DIRECTIONS = {
    "THREE_QUARTER_RIGHT": Vector((1, -1, 0.7)).normalized(),
    "THREE_QUARTER_LEFT":  Vector((-1, -1, 0.7)).normalized(),
    "FRONT":               Vector((0, -1, 0.3)).normalized(),
    "SIDE":                Vector((1, 0, 0.3)).normalized(),
}


def _get_view_direction(preset):
    """World-space direction from bbox center toward camera for a named preset."""
    return _VIEW_DIRECTIONS.get(preset, _VIEW_DIRECTIONS["THREE_QUARTER_RIGHT"]).copy()


def _view_dir_from_region(region_3d):
    """Target-to-camera direction extracted from a 3D viewport's region_3d."""
    d = region_3d.view_rotation @ Vector((0, 0, 1))
    d.normalize()
    return d


def _camera_basis(view_dir):
    """Orthonormal camera basis from a target-to-camera direction.
    Returns (forward, right, up) where forward = camera→target, +Z stays up."""
    forward = (-view_dir).normalized()
    up_world = Vector((0, 0, 1))
    right = forward.cross(up_world).normalized()
    if right.length < 1e-6:
        up_world = Vector((0, 1, 0))
        right = forward.cross(up_world).normalized()
    up = right.cross(forward).normalized()
    return forward, right, up


def _view_rotation(view_dir):
    """Quaternion orienting a camera/viewport to look from *view_dir* toward target."""
    fwd, r, u = _camera_basis(view_dir)
    return Matrix(((r.x, u.x, -fwd.x),
                   (r.y, u.y, -fwd.y),
                   (r.z, u.z, -fwd.z))).to_quaternion()


def _camera_world_matrix(center, view_dir, distance):
    """Full 4×4 world matrix for a camera placed at *distance* along *view_dir* from *center*."""
    fwd, r, u = _camera_basis(view_dir)
    rot = Matrix(((r.x, u.x, -fwd.x),
                  (r.y, u.y, -fwd.y),
                  (r.z, u.z, -fwd.z)))
    rot.resize_4x4()
    return Matrix.Translation(center + view_dir * distance) @ rot


# ---------------------------------------------------------------------------
#   Bbox projection
# ---------------------------------------------------------------------------

def _bbox_screen_extent(bbox, view_dir):
    """Half-extents of *bbox* projected onto the camera right / up axes.
    Returns (half_right, half_up)."""
    min_c, max_c = bbox
    center = (min_c + max_c) * 0.5
    _fwd, right, up = _camera_basis(view_dir)
    max_r = max_u = 0.0
    for x in (min_c.x, max_c.x):
        for y in (min_c.y, max_c.y):
            for z in (min_c.z, max_c.z):
                dx = x - center.x
                dy = y - center.y
                dz = z - center.z
                pr = abs(dx * right.x + dy * right.y + dz * right.z)
                pu = abs(dx * up.x + dy * up.y + dz * up.z)
                if pr > max_r:
                    max_r = pr
                if pu > max_u:
                    max_u = pu
    return max_r, max_u


# ---------------------------------------------------------------------------
#   Framing / fitting
# ---------------------------------------------------------------------------

def _lens_to_fov_rad(lens_mm, sensor=36.0):
    """Vertical FOV in radians from focal length (Blender default sensor = 36 mm)."""
    return 2.0 * math.atan(sensor / (2.0 * lens_mm))


def _get_framing_margin(style, custom):
    """Margin multiplier from a framing-style enum or custom float."""
    if style == "TIGHT":
        return 1.05
    if style == "BALANCED":
        return 1.16
    if style == "LOOSE":
        return 1.30
    return 1.0 + max(0.0, min(0.5, custom))


def _fit_persp(bbox, view_dir, fov_rad, margin):
    """Perspective camera distance that fits projected *bbox* inside *fov_rad* with *margin*."""
    if not bbox:
        return 2.0
    hr, hu = _bbox_screen_extent(bbox, view_dir)
    max_lateral = max(hr, hu, 0.001)
    tan_half = math.tan(fov_rad * 0.5)
    if tan_half <= 0:
        return max_lateral * 4.0
    min_c, max_c = bbox
    size = max_c - min_c
    depth = abs((size.x * view_dir.x) + (size.y * view_dir.y) + (size.z * view_dir.z))
    min_dist = depth * 0.5 + 0.001
    return max(max_lateral / tan_half * margin, min_dist)


# ---------------------------------------------------------------------------
#   Misc helpers
# ---------------------------------------------------------------------------

def _load_custom_preview(context, id_data, filepath):
    """Call ed.lib_id_load_custom_preview safely across Blender versions."""
    with context.temp_override(id=id_data):
        try:
            bpy.ops.ed.lib_id_load_custom_preview(filepath=filepath, hide_props_region=True)
        except TypeError:
            bpy.ops.ed.lib_id_load_custom_preview(filepath=filepath)


# ---------------------------------------------------------------------------
#   Operator
# ---------------------------------------------------------------------------

class IOPS_OT_RenderAssetThumbnail(bpy.types.Operator):
    bl_idname = "iops.assets_render_asset_thumbnail"
    bl_label = "Render Active Asset Thumbnail"
    bl_description = "Render Active Asset Thumbnail: Collection, Object, Material, Geometry Nodes"
    bl_options = {"REGISTER", "UNDO"}

    # --- What to render ---
    render_for: EnumProperty(
        name="Render For",
        items=[
            ("OBJECT", "Object", "Render the selected object"),
            ("COLLECTION", "Collection", "Render the selected collection"),
            ("MATERIAL", "Material", "Render the selected material"),
            ("GEOMETRY", "Geometry Nodes", "Render the selected geometry node"),
        ],
        default="COLLECTION",
    )

    # --- Camera ---
    camera_view: EnumProperty(
        name="Camera View",
        items=[
            ("CURRENT", "Current View", "Use the current 3D viewport angle"),
            ("THREE_QUARTER_RIGHT", "3/4 Right", "Three-quarter from the front-right"),
            ("THREE_QUARTER_LEFT", "3/4 Left", "Three-quarter from the front-left"),
            ("FRONT", "Front", "Front view (along Y)"),
            ("SIDE", "Side", "Side view (along X)"),
        ],
        default="CURRENT",
        description="Camera view direction for the thumbnail",
    )
    thumbnail_lens: FloatProperty(
        name="Lens (mm)",
        default=90.0,
        min=1.0,
        max=200.0,
        description="Focal length in millimetres — smaller = wider FOV",
    )
    persp_distance: FloatProperty(
        name="Distance",
        default=1.0,
        min=0.1,
        max=5.0,
        soft_min=0.5,
        soft_max=2.0,
        subtype="FACTOR",
        description="Camera distance multiplier — smaller = closer to object",
    )

    # --- Framing ---
    use_framing: BoolProperty(
        name="Frame Selection",
        default=True,
        description="Auto-frame the asset to fill the thumbnail",
    )
    framing_style: EnumProperty(
        name="Framing Style",
        items=[
            ("TIGHT", "Tight", "Minimal margin, fill frame (5% padding)"),
            ("BALANCED", "Balanced", "Recommended margin (16% padding, Blender asset style)"),
            ("LOOSE", "Loose", "More padding (30% padding)"),
            ("CUSTOM", "Custom", "Use Frame Margin value below"),
        ],
        default="TIGHT",
        description="How much padding around the subject",
    )
    frame_margin: FloatProperty(
        name="Frame Margin",
        default=0.16,
        min=0.0,
        max=0.5,
        soft_min=0.05,
        soft_max=0.35,
        subtype="FACTOR",
        description="Margin around framed content (only when Framing Style = Custom)",
    )

    # --- Misc ---
    use_alpha: BoolProperty(
        name="Transparent Background",
        default=True,
        description="Render with a transparent background (alpha channel). Disable for solid background",
    )
    toggle_overlays: BoolProperty(
        name="Toggle Overlays",
        default=True,
        description="Hide viewport overlays during thumbnail render",
    )

    # ------------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------------

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "render_for")
        layout.separator()

        col = layout.column(heading="Camera")
        col.prop(self, "camera_view")
        col.prop(self, "thumbnail_lens")
        col.prop(self, "persp_distance")
        layout.separator()

        col = layout.column(heading="Framing")
        col.prop(self, "use_framing")
        if self.use_framing:
            col.prop(self, "framing_style")
            if self.framing_style == "CUSTOM":
                col.prop(self, "frame_margin")

        layout.separator()
        layout.prop(self, "use_alpha")
        layout.prop(self, "toggle_overlays")

    # ------------------------------------------------------------------
    #  Shared helpers
    # ------------------------------------------------------------------

    def _margin(self):
        return _get_framing_margin(self.framing_style, self.frame_margin)

    def _resolve_view_dir(self, context):
        """Return the target-to-camera direction for the current settings."""
        if self.camera_view != "CURRENT":
            return _get_view_direction(self.camera_view)
        area, _ = get_view3d_context(context)
        if area and area.spaces.active and getattr(area.spaces.active, "region_3d", None):
            return _view_dir_from_region(area.spaces.active.region_3d)
        return _get_view_direction("THREE_QUARTER_RIGHT")

    # ------------------------------------------------------------------
    #  Temp-camera render path
    # ------------------------------------------------------------------

    def _setup_temp_camera(self, context, objects):
        """Create a temporary camera framing *objects*. Returns (cam_obj, orig_camera) or (None, None)."""
        scene = context.scene
        bbox = compute_combined_bound_box(objects) if objects else None
        if bbox:
            center = (bbox[0] + bbox[1]) * 0.5
        else:
            center = Vector((0, 0, 0))

        margin = self._margin()
        view_dir = self._resolve_view_dir(context)

        cam_data = bpy.data.cameras.new("IOPS_Thumbnail_Cam")
        cam_obj = bpy.data.objects.new("IOPS_Thumbnail_Cam", cam_data)
        scene.collection.objects.link(cam_obj)

        cam_data.type = "PERSP"
        cam_data.lens = self.thumbnail_lens
        fov = _lens_to_fov_rad(self.thumbnail_lens)
        distance = _fit_persp(bbox, view_dir, fov, margin) * self.persp_distance

        cam_obj.matrix_world = _camera_world_matrix(center, view_dir, distance)
        original_camera = scene.camera
        scene.camera = cam_obj
        return cam_obj, original_camera

    @staticmethod
    def _remove_temp_camera(scene, cam_obj, original_camera):
        scene.camera = original_camera
        if cam_obj:
            cam_data = cam_obj.data
            bpy.data.objects.remove(cam_obj, do_unlink=True)
            if cam_data and cam_data.name in bpy.data.cameras:
                bpy.data.cameras.remove(cam_data, do_unlink=True)

    def render_with_temp_camera(self, context):
        """Render via a temporary camera + render.opengl(CAMERA). Returns file path or None."""
        scene = context.scene
        objects = get_objects_to_frame(context, self.render_for)
        if self.use_framing and not objects:
            try:
                objects = [ob for ob in context.visible_objects if ob.type == "MESH"]
            except AttributeError:
                objects = [ob for ob in scene.objects if ob.type == "MESH" and ob.visible_get()]

        cam_obj, original_camera = self._setup_temp_camera(context, objects)
        if not cam_obj:
            self.report({"ERROR"}, "Thumbnail: could not create temp camera")
            return None

        area, region = get_view3d_context(context)
        if not area:
            self._remove_temp_camera(scene, cam_obj, original_camera)
            self.report({"ERROR"}, "Thumbnail: no 3D viewport found for render")
            return None

        rv3d = area.spaces.active.region_3d
        saved = self._apply_render_settings(scene)

        thumb_dir = os.path.join(tempfile.gettempdir(), "iops_thumb")
        os.makedirs(thumb_dir, exist_ok=True)
        filepath = os.path.normpath(os.path.join(thumb_dir, "thumb_%s.png" % uuid.uuid4().hex[:8]))

        old_persp = rv3d.view_perspective
        old_overlays = area.spaces.active.overlay.show_overlays
        old_lens = area.spaces.active.lens

        out_path = None
        try:
            rv3d.view_perspective = "CAMERA"
            if self.toggle_overlays:
                area.spaces.active.overlay.show_overlays = False
            rv3d.update()

            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.render.opengl(write_still=False)

            thumb = bpy.data.images.get("Render Result")
            if thumb and thumb.size[0] > 0:
                out_path = self._save_render_result(thumb, filepath)
        finally:
            rv3d.view_perspective = old_persp
            area.spaces.active.overlay.show_overlays = old_overlays
            area.spaces.active.lens = old_lens
            rv3d.update()
            self._remove_temp_camera(scene, cam_obj, original_camera)
            self._restore_render_settings(scene, saved)

        return out_path

    # ------------------------------------------------------------------
    #  Viewport render path
    # ------------------------------------------------------------------

    def _apply_viewport_framing(self, context, objects):
        """Orient and zoom the active 3D viewport to frame *objects*."""
        space = context.space_data
        if not objects or not space or not getattr(space, "region_3d", None):
            return
        rv3d = space.region_3d
        bbox = compute_combined_bound_box(objects)
        if not bbox:
            return
        center = (bbox[0] + bbox[1]) * 0.5
        margin = self._margin()
        view_dir = self._resolve_view_dir(context)

        rv3d.view_rotation = _view_rotation(view_dir)
        rv3d.view_location = center
        rv3d.view_perspective = "PERSP"
        fov = _lens_to_fov_rad(self.thumbnail_lens, sensor=72.0)
        rv3d.view_distance = _fit_persp(bbox, view_dir, fov, margin) * self.persp_distance
        rv3d.update()

    def render_viewport(self, context, filepath):
        """Viewport OpenGL render. Returns file path or None."""
        if getattr(context, "space_data", None) and context.space_data.type == "VIEW_3D":
            return self._render_viewport_impl(context, filepath)
        area, region = get_view3d_context(context)
        if not area:
            return None
        with bpy.context.temp_override(area=area, region=region):
            return self._render_viewport_impl(bpy.context, filepath)

    def _render_viewport_impl(self, context, filepath):
        space = context.space_data
        if not space or not getattr(space, "region_3d", None):
            return None
        rv3d = space.region_3d
        scene = context.scene
        img = scene.render.image_settings

        # Save
        saved_vp = {
            "perspective": rv3d.view_perspective,
            "distance": rv3d.view_distance,
            "location": rv3d.view_location.copy(),
            "rotation": rv3d.view_rotation.copy(),
            "lens": space.lens,
            "overlays": space.overlay.show_overlays,
            "background": getattr(space.shading, "show_background", True),
        }
        saved_render = {
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "file_format": img.file_format,
            "color_mode": img.color_mode,
            "media_type": getattr(img, "media_type", None),
            "film_transparent": scene.render.film_transparent,
        }

        # Apply thumbnail settings
        scene.render.resolution_x = 500
        scene.render.resolution_y = 500
        if hasattr(img, "media_type"):
            img.media_type = "IMAGE"
        img.file_format = "PNG"
        img.color_mode = "RGBA" if self.use_alpha else "RGB"
        scene.render.film_transparent = self.use_alpha
        if hasattr(space.shading, "show_background"):
            space.shading.show_background = False
        space.lens = self.thumbnail_lens
        if self.toggle_overlays:
            space.overlay.show_overlays = False

        objects = get_objects_to_frame(context, self.render_for)
        if self.use_framing and objects:
            self._apply_viewport_framing(context, objects)

        out_path = None
        try:
            bpy.ops.render.opengl()
            # Save while PNG/RGBA settings are still active
            thumb = bpy.data.images.get("Render Result")
            if thumb:
                out_path = self._save_render_result(thumb, bpy.path.abspath(filepath), scene)
        finally:
            rv3d.view_perspective = saved_vp["perspective"]
            rv3d.view_distance = saved_vp["distance"]
            rv3d.view_location = saved_vp["location"]
            rv3d.view_rotation = saved_vp["rotation"]
            rv3d.update()
            space.lens = saved_vp["lens"]
            space.overlay.show_overlays = saved_vp["overlays"]
            if hasattr(space.shading, "show_background"):
                space.shading.show_background = saved_vp["background"]
            scene.render.resolution_x = saved_render["resolution_x"]
            scene.render.resolution_y = saved_render["resolution_y"]
            if saved_render["media_type"] is not None and hasattr(img, "media_type"):
                img.media_type = saved_render["media_type"]
            img.file_format = saved_render["file_format"]
            img.color_mode = saved_render["color_mode"]
            scene.render.film_transparent = saved_render["film_transparent"]

        return out_path

    # ------------------------------------------------------------------
    #  Render-settings save/restore (temp-camera path)
    # ------------------------------------------------------------------

    def _apply_render_settings(self, scene):
        img = scene.render.image_settings
        saved = {
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "resolution_percentage": scene.render.resolution_percentage,
            "file_format": img.file_format,
            "color_mode": img.color_mode,
            "media_type": getattr(img, "media_type", None),
            "film_transparent": scene.render.film_transparent,
        }
        scene.render.resolution_x = 500
        scene.render.resolution_y = 500
        scene.render.resolution_percentage = 100
        if hasattr(img, "media_type"):
            img.media_type = "IMAGE"
        img.file_format = "PNG"
        img.color_mode = "RGBA" if self.use_alpha else "RGB"
        scene.render.film_transparent = self.use_alpha
        return saved

    @staticmethod
    def _restore_render_settings(scene, saved):
        img = scene.render.image_settings
        scene.render.resolution_x = saved["resolution_x"]
        scene.render.resolution_y = saved["resolution_y"]
        scene.render.resolution_percentage = saved["resolution_percentage"]
        if saved["media_type"] is not None and hasattr(img, "media_type"):
            img.media_type = saved["media_type"]
        img.file_format = saved["file_format"]
        img.color_mode = saved["color_mode"]
        scene.render.film_transparent = saved["film_transparent"]

    # ------------------------------------------------------------------
    #  Image saving
    # ------------------------------------------------------------------

    @staticmethod
    def _save_render_result(thumb, filepath_abs, scene=None):
        """Save Render Result to *filepath_abs*. Returns path on success, None otherwise."""
        try:
            thumb.save_render(filepath=filepath_abs)
            if os.path.exists(filepath_abs):
                return filepath_abs
        except Exception:
            pass

        thumb.filepath = filepath_abs
        try:
            thumb.save()
            if os.path.exists(filepath_abs):
                return filepath_abs
        except RuntimeError:
            pass

        try:
            w, h = thumb.size
            tmp_name = "IOPS_Thumbnail_Out"
            if tmp_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[tmp_name], do_unlink=True)
            new_img = bpy.data.images.new(tmp_name, width=w, height=h, alpha=True)
            new_img.filepath = filepath_abs
            buf = array.array('f', [0.0] * (w * h * 4))
            thumb.pixels.foreach_get(buf)
            new_img.pixels.foreach_set(buf)
            new_img.save()
            ok = os.path.exists(filepath_abs)
            bpy.data.images.remove(new_img, do_unlink=True)
            if ok:
                return filepath_abs
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    #  Execute
    # ------------------------------------------------------------------

    def execute(self, context):
        objects_to_frame = get_objects_to_frame(context, self.render_for)
        if self.use_framing and not objects_to_frame:
            self.report({"WARNING"}, "Nothing to frame: no mesh/curve objects for current selection.")

        actual_path = None
        try:
            thumb_dir = os.path.join(tempfile.gettempdir(), "iops_thumb")
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_path = os.path.join(thumb_dir, "thumb_%s.png" % uuid.uuid4().hex[:8])

            actual_path = self.render_viewport(context, thumb_path)
            if not actual_path:
                actual_path = self.render_with_temp_camera(context)
            if not actual_path:
                self.report(
                    {"ERROR"},
                    "Thumbnail render failed or could not write output file. "
                    "Try running from a 3D view with the asset's collection/object visible.",
                )
                return {"CANCELLED"}

            if self.render_for == "COLLECTION":
                _load_custom_preview(context, bpy.context.collection, actual_path)
            elif self.render_for == "OBJECT":
                _load_custom_preview(context, bpy.context.object, actual_path)
            elif self.render_for == "MATERIAL":
                ob = bpy.context.object
                if ob and ob.type == "MESH":
                    try:
                        _load_custom_preview(context, ob.active_material, actual_path)
                    except RuntimeError:
                        self.report({"ERROR"}, "Current object does not have a material marked as asset")
            elif self.render_for == "GEOMETRY":
                ob = bpy.context.object
                if (ob and ob.type == "MESH"
                        and ob.modifiers.active
                        and ob.modifiers.active.type == "NODES"):
                    try:
                        _load_custom_preview(context, ob.modifiers.active.node_group, actual_path)
                    except RuntimeError:
                        self.report({"ERROR"}, "Current object does not have a node group marked as asset")
                else:
                    self.report({"ERROR"}, "Active object is not a mesh")

            return {"FINISHED"}
        finally:
            if actual_path and os.path.exists(actual_path):
                try:
                    os.unlink(actual_path)
                except OSError:
                    pass
