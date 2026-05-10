import bpy
from bpy.props import FloatProperty, BoolProperty, EnumProperty
import math
import os
import tempfile
import uuid
import array

from mathutils import Vector, Matrix

from ..utils.assets import (
    find_asset_collections_from_selection,
    resolve_assets_from_selection,
)


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


_FRAMABLE_GEOMETRY_TYPES = ("MESH", "CURVE", "SURFACE", "META", "FONT")


def _is_framable(ob):
    """True for direct geometry or for empties carrying a collection instance.

    Collection-instance empties are framed via the geometry they spawn (handled
    in compute_combined_bound_box), not their display gizmo bound box."""
    if ob.type in _FRAMABLE_GEOMETRY_TYPES:
        return True
    if (
        ob.type == "EMPTY"
        and ob.instance_type == "COLLECTION"
        and ob.instance_collection is not None
    ):
        return True
    return False


def get_objects_to_frame(context, render_for, target_collection=None):
    """Return list of objects to frame in the view based on render_for.

    *target_collection* overrides ``context.collection`` for the COLLECTION
    case — used by the batch path so framing matches the asset being
    rendered. When *target_collection* is given, ``visible_get()`` is NOT
    consulted: the user explicitly picked this asset and we want framing to
    cover its full geometry regardless of viewport eye-icon state on parent
    LayerCollections (which would otherwise make ``visible_get()`` return
    False and yield an empty list → no framing → identical default framing
    across every iteration)."""
    if render_for == "COLLECTION":
        if target_collection is not None:
            return [ob for ob in target_collection.all_objects if _is_framable(ob)]
        coll = context.collection
        return [ob for ob in coll.all_objects if _is_framable(ob) and ob.visible_get()]
    if render_for == "OBJECT":
        ob = context.object
        return [ob] if ob else []
    if render_for in ("MATERIAL", "GEOMETRY"):
        ob = context.object
        return [ob] if ob and ob.type == "MESH" else []
    return []


# ---------------------------------------------------------------------------
#   Isolation (batch render path)
# ---------------------------------------------------------------------------

def _gather_render_keepalive(target_coll):
    """Objects that must stay visible for *target_coll* to render correctly
    when using the per-object hide_viewport fallback. Includes the
    collection's contents plus, recursively, every object in any collection
    referenced via a collection-instance empty."""
    keep = set(target_coll.all_objects)
    seen_colls = {target_coll}
    todo = [target_coll]
    while todo:
        coll = todo.pop()
        for ob in coll.all_objects:
            if (
                ob.type == "EMPTY"
                and ob.instance_type == "COLLECTION"
                and ob.instance_collection is not None
                and ob.instance_collection not in seen_colls
            ):
                inst_coll = ob.instance_collection
                seen_colls.add(inst_coll)
                todo.append(inst_coll)
                keep.update(inst_coll.all_objects)
    return keep


def _find_view3d_override():
    """Return (window, area, region) for the first 3D viewport, or (None,)*3."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return window, area, region
    return None, None, None


def _toggle_localview(window, area, region):
    """Toggle local view in *area*. Returns True when local-view state actually
    flipped, False otherwise (poll fail, override mismatch, etc.)."""
    space = area.spaces.active
    before = getattr(space, "local_view", None)
    try:
        with bpy.context.temp_override(
            window=window, screen=window.screen, area=area, region=region
        ):
            try:
                bpy.ops.view3d.localview(frame_selected=False)
            except TypeError:
                bpy.ops.view3d.localview()
    except RuntimeError:
        return False
    after = getattr(space, "local_view", None)
    return (before is None) != (after is None)


def _isolate_collection(context, target_coll):
    """Isolate *target_coll* so the next render only shows its content
    (plus the geometry spawned by any instancer empties inside it).

    Primary path — local view in a 3D viewport. Local view filters that
    viewport's drawn objects per-area, but the depsgraph still generates
    dupli instances for any visible instancer empty regardless of whether
    the source is in local view → instances render correctly while the
    source meshes don't appear directly in the frame.

    Fallback path — per-object ``hide_viewport`` with a keep-alive set that
    leaves instance-source objects visible. Source meshes will render
    directly if they're in the camera frame; used only when local view
    can't be entered (no 3D viewport, headless, etc.).

    Never touches: LayerCollection ``exclude``/``hide_viewport`` (resets
    per-view-layer base state), eye-icon hide_set state."""
    view_layer = context.view_layer

    # ----- Try local view first ---------------------------------------
    window, area, region = _find_view3d_override()
    if area is not None:
        saved_selection = list(context.selected_objects or [])
        saved_active = view_layer.objects.active

        for ob in view_layer.objects:
            try:
                ob.select_set(False)
            except RuntimeError:
                pass

        selected = 0
        first = None
        for ob in target_coll.all_objects:
            if ob.name not in view_layer.objects:
                continue
            try:
                ob.select_set(True)
                selected += 1
                if first is None:
                    first = ob
            except RuntimeError:
                pass

        if first is not None:
            try:
                view_layer.objects.active = first
            except (AttributeError, RuntimeError):
                pass

        if selected == 0:
            # Roll back selection — nothing to isolate via local view.
            for ob in saved_selection:
                try:
                    ob.select_set(True)
                except (RuntimeError, ReferenceError):
                    pass
            if saved_active is not None:
                try:
                    view_layer.objects.active = saved_active
                except (AttributeError, RuntimeError, ReferenceError):
                    pass
        else:
            already_in_localview = (
                getattr(area.spaces.active, "local_view", None) is not None
            )
            entered = False
            if not already_in_localview:
                entered = _toggle_localview(window, area, region)

            if entered:
                try:
                    view_layer.update()
                except AttributeError:
                    pass
                return {
                    "method": "localview",
                    "window": window,
                    "area": area,
                    "region": region,
                    "saved_selection": saved_selection,
                    "saved_active": saved_active,
                }

            # Local view didn't engage — roll back selection and fall through.
            for ob in view_layer.objects:
                try:
                    ob.select_set(False)
                except RuntimeError:
                    pass
            for ob in saved_selection:
                try:
                    ob.select_set(True)
                except (RuntimeError, ReferenceError):
                    pass
            if saved_active is not None:
                try:
                    view_layer.objects.active = saved_active
                except (AttributeError, RuntimeError, ReferenceError):
                    pass

    # ----- Fallback: per-object hide_viewport with keep-alive ---------
    keep = _gather_render_keepalive(target_coll)
    hidden_by_us = []
    for ob in view_layer.objects:
        if ob in keep:
            continue
        if ob.hide_viewport:
            continue
        try:
            ob.hide_viewport = True
            hidden_by_us.append(ob)
        except (AttributeError, ReferenceError):
            pass
    try:
        view_layer.update()
    except AttributeError:
        pass
    return {"method": "hide_viewport", "hidden_by_us": hidden_by_us}


def _restore_isolation(context, state):
    if not state:
        return
    method = state.get("method")

    if method == "localview":
        window = state.get("window")
        area = state.get("area")
        region = state.get("region")
        if area is not None:
            space = area.spaces.active
            if getattr(space, "local_view", None) is not None:
                _toggle_localview(window, area, region)

        view_layer = context.view_layer
        try:
            for ob in view_layer.objects:
                try:
                    ob.select_set(False)
                except RuntimeError:
                    pass
            for ob in state.get("saved_selection", []):
                try:
                    ob.select_set(True)
                except (RuntimeError, ReferenceError):
                    pass
            saved_active = state.get("saved_active")
            if saved_active is not None:
                try:
                    view_layer.objects.active = saved_active
                except (AttributeError, RuntimeError, ReferenceError):
                    pass
        except ReferenceError:
            pass
        return

    if method == "hide_viewport":
        for ob in state.get("hidden_by_us", []):
            try:
                ob.hide_viewport = False
            except (AttributeError, ReferenceError):
                pass


def _expand_bbox_with_corners(matrix_world, local_corners, bb_min, bb_max):
    for corner in local_corners:
        wc = matrix_world @ Vector(corner)
        if wc.x < bb_min.x: bb_min.x = wc.x
        if wc.y < bb_min.y: bb_min.y = wc.y
        if wc.z < bb_min.z: bb_min.z = wc.z
        if wc.x > bb_max.x: bb_max.x = wc.x
        if wc.y > bb_max.y: bb_max.y = wc.y
        if wc.z > bb_max.z: bb_max.z = wc.z


def compute_combined_bound_box(objects, context=None):
    """World-space axis-aligned bbox encompassing *objects*.

    When *context* is given, dependency-graph instances spawned by collection-
    instance empties (and geometry-node instancers) under any root in *objects*
    are included — so empty-based assets frame against the real geometry they
    visualise rather than the empty's tiny display gizmo.
    Returns (min, max) or None.
    """
    if not objects:
        return None
    inf = float("inf")
    bb_min = Vector((inf, inf, inf))
    bb_max = Vector((-inf, -inf, -inf))
    found = False

    for ob in objects:
        if ob.type in _FRAMABLE_GEOMETRY_TYPES:
            _expand_bbox_with_corners(ob.matrix_world, ob.bound_box, bb_min, bb_max)
            found = True

    if context is not None:
        try:
            depsgraph = context.evaluated_depsgraph_get()
        except AttributeError:
            depsgraph = None
        if depsgraph is not None:
            roots = {ob.original for ob in objects}
            for inst in depsgraph.object_instances:
                if not inst.is_instance:
                    continue
                parent = inst.parent
                if parent is None or parent.original not in roots:
                    continue
                inst_ob = inst.object
                if inst_ob is None or inst_ob.type not in _FRAMABLE_GEOMETRY_TYPES:
                    continue
                _expand_bbox_with_corners(
                    inst.matrix_world, inst_ob.bound_box, bb_min, bb_max
                )
                found = True

    if not found:
        # Last-resort fallback: include any provided objects' bound boxes so
        # framing still produces a sensible result for unusual instancer setups.
        for ob in objects:
            _expand_bbox_with_corners(ob.matrix_world, ob.bound_box, bb_min, bb_max)
            found = True

    return (bb_min, bb_max) if found else None


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
        bbox = compute_combined_bound_box(objects, context) if objects else None
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
        objects = get_objects_to_frame(context, self.render_for, self._target_collection)
        if self.use_framing and not objects:
            try:
                objects = [ob for ob in context.visible_objects if _is_framable(ob)]
            except AttributeError:
                objects = [ob for ob in scene.objects if _is_framable(ob) and ob.visible_get()]

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
        bbox = compute_combined_bound_box(objects, context)
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

        objects = get_objects_to_frame(context, self.render_for, self._target_collection)
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
        # Per-call target override used by render methods. None = use context.collection.
        self._target_collection = None

        # Batch path: when rendering for a Collection and the selection spans
        # one or more asset-marked collections, render a thumbnail per asset
        # collection with each isolated in turn so the renders don't overlap.
        if self.render_for == "COLLECTION":
            asset_colls = find_asset_collections_from_selection(context)
            if asset_colls:
                return self._execute_batch_collections(context, asset_colls)

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

            resolved = resolve_assets_from_selection(context)
            if resolved:
                applied = 0
                for datablock, type_label in resolved:
                    if getattr(datablock, "library", None) is not None:
                        continue
                    try:
                        _load_custom_preview(context, datablock, actual_path)
                        applied += 1
                    except RuntimeError:
                        self.report({"WARNING"}, f"Could not set preview on {type_label} '{datablock.name}'")
                if not applied:
                    self.report({"WARNING"}, "No local asset datablocks found in selection")
            else:
                self.report({"WARNING"}, "No asset datablocks found in selection")

            return {"FINISHED"}
        finally:
            if actual_path and os.path.exists(actual_path):
                try:
                    os.unlink(actual_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    #  Batch (multi-collection) path
    # ------------------------------------------------------------------

    def _execute_batch_collections(self, context, collections):
        """Render one thumbnail per asset collection with isolation between renders."""
        thumb_dir = os.path.join(tempfile.gettempdir(), "iops_thumb")
        os.makedirs(thumb_dir, exist_ok=True)

        total = len(collections)
        wm = context.window_manager
        # Cursor progress bar (cheap, no-op on headless).
        try:
            wm.progress_begin(0, total)
        except (AttributeError, RuntimeError):
            wm = None

        # Header text on every 3D view so progress is visible without the console.
        view3d_areas = []
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    view3d_areas.append(area)

        def _set_header(text):
            for area in view3d_areas:
                try:
                    area.header_text_set(text)
                    area.tag_redraw()
                except (AttributeError, RuntimeError):
                    pass

        print(f"[IOPS Thumbnail] Batch start: {total} asset collection(s)")

        rendered = 0
        failed = []
        try:
            for index, coll in enumerate(collections, 1):
                progress_text = (
                    f"IOPS Thumbnail {index}/{total}: rendering '{coll.name}'..."
                )
                print(f"[IOPS Thumbnail] ({index}/{total}) {coll.name} — rendering...")
                _set_header(progress_text)
                if wm is not None:
                    try:
                        wm.progress_update(index - 1)
                    except (AttributeError, RuntimeError):
                        pass

                isolation = None
                actual_path = None
                try:
                    isolation = _isolate_collection(context, coll)
                    self._target_collection = coll

                    thumb_path = os.path.join(
                        thumb_dir, "thumb_%s.png" % uuid.uuid4().hex[:8]
                    )
                    actual_path = self.render_viewport(context, thumb_path)
                    if not actual_path:
                        actual_path = self.render_with_temp_camera(context)

                    if not actual_path:
                        print(
                            f"[IOPS Thumbnail] ({index}/{total}) {coll.name} — FAILED (render produced no image)"
                        )
                        failed.append(coll.name)
                        continue

                    try:
                        _load_custom_preview(context, coll, actual_path)
                        rendered += 1
                        print(
                            f"[IOPS Thumbnail] ({index}/{total}) {coll.name} — OK"
                        )
                    except RuntimeError:
                        self.report(
                            {"WARNING"},
                            f"Could not set preview on Collection '{coll.name}'",
                        )
                        print(
                            f"[IOPS Thumbnail] ({index}/{total}) {coll.name} — FAILED (preview assignment refused)"
                        )
                        failed.append(coll.name)
                finally:
                    self._target_collection = None
                    _restore_isolation(context, isolation)
                    if actual_path and os.path.exists(actual_path):
                        try:
                            os.unlink(actual_path)
                        except OSError:
                            pass
        finally:
            _set_header(None)
            if wm is not None:
                try:
                    wm.progress_end()
                except (AttributeError, RuntimeError):
                    pass

        print(
            f"[IOPS Thumbnail] Batch done: {rendered}/{total} succeeded"
            + (f", failed: {', '.join(failed)}" if failed else "")
        )

        if rendered == 0:
            self.report(
                {"ERROR"},
                f"Thumbnail batch failed for all {total} asset collection(s).",
            )
            return {"CANCELLED"}

        if failed:
            self.report(
                {"WARNING"},
                f"Rendered {rendered}/{total} asset collection thumbnails "
                f"(failed: {', '.join(failed)})",
            )
        else:
            self.report(
                {"INFO"},
                f"Rendered {rendered} asset collection thumbnail(s).",
            )
        return {"FINISHED"}
