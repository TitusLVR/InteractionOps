"""Contextual UV align, driven by the UV Align pie.

Point mode (vertex/edge select): selected UVs collapse onto a line.
Island mode (face/island select): every island holding a selected face moves
rigidly. World Up / Follow Active rotate islands in either mode. Works
across all objects in edit mode with one undo step.
"""
import bmesh
import bpy
from bpy.props import EnumProperty

from ..utils import uv_align_core as core
from ..utils.uv_utils import get_selected_face_islands

#: Rotations below this (radians) are float32 UV noise, not a change.
ROTATE_EPS = 1e-6


def uv_align_mode(context):
    """'POINT' or 'ISLAND' from the current UV / mesh select mode."""
    ts = context.tool_settings
    if ts.use_uv_select_sync:
        v, e, f = ts.mesh_select_mode
        return "ISLAND" if (f and not v and not e) else "POINT"
    return "ISLAND" if ts.uv_select_mode in {"FACE", "ISLAND"} else "POINT"


def _loop_uv_selected(loop, uv_layer):
    sel = getattr(loop, "uv_select_vert", None)
    if sel is None:
        sel = loop[uv_layer].select
    return sel


def _face_uv_selected(face, uv_layer):
    sel = getattr(face, "uv_select", None)
    if sel is None:
        sel = all(_loop_uv_selected(lp, uv_layer) for lp in face.loops)
    return sel


def _sync_uses_mesh_selection(bm):
    """With UV Sync on, Blender 5.x keeps a separate UV selection only while
    `uv_select_sync_valid` is set; otherwise the mesh selection is the UV
    selection."""
    return not getattr(bm, "uv_select_sync_valid", True)


def _visible_faces(bm, use_sync):
    """Faces the UV editor shows: selected faces (sync off) or unhidden ones."""
    if use_sync:
        return [f for f in bm.faces if not f.hide]
    return [f for f in bm.faces if f.select and not f.hide]


def _loop_selected_fn(bm, uv_layer, use_sync):
    if use_sync and _sync_uses_mesh_selection(bm):
        return lambda lp: lp.vert.select
    return lambda lp: _loop_uv_selected(lp, uv_layer)


def _selected_loops(bm, uv_layer, use_sync):
    """UV-selected loops among the faces the UV editor shows. Sync off needs
    the f.select gate (`_visible_faces`): `uv_select_vert` can read True on
    faces the editor does not show."""
    sel = _loop_selected_fn(bm, uv_layer, use_sync)
    return [lp for f in _visible_faces(bm, use_sync) for lp in f.loops
            if sel(lp)]


def _seed_faces(bm, uv_layer, use_sync, visible):
    """Island mode seeds: selected faces."""
    if use_sync:
        return [f.index for f in visible if f.select]
    full = [f.index for f in visible if _face_uv_selected(f, uv_layer)]
    if full:
        return full
    # Face flag not flushed: fall back to any touched face.
    return _point_seed_faces(bm, uv_layer, use_sync, visible)


def _point_seed_faces(bm, uv_layer, use_sync, visible):
    """Point mode seeds: faces holding a selected UV vertex."""
    sel = _loop_selected_fn(bm, uv_layer, use_sync)
    return [f.index for f in visible if any(sel(lp) for lp in f.loops)]


class _Island:
    __slots__ = ("obj", "loops", "faces", "bbox")

    def __init__(self, obj, faces, uv_layer):
        self.obj = obj
        self.faces = faces
        self.loops = [lp for f in faces for lp in f.loops]
        self.bbox = core.bbox_of(
            (lp[uv_layer].uv.x, lp[uv_layer].uv.y) for lp in self.loops)


def _image_aspect(context):
    space = context.space_data
    img = getattr(space, "image", None) if space else None
    try:
        w, h = img.size[0], img.size[1]
    except (AttributeError, IndexError, TypeError):
        return 1.0
    if w > 0 and h > 0:
        return w / h
    return 1.0


def _face_tris(face, mw, uv_layer, wco):
    """Fan triangles of ``face`` as ((world points), (uvs)); ``wco`` caches
    world positions by vertex index for one object."""
    lps = list(face.loops)
    pts = []
    for lp in lps:
        v = lp.vert
        co = wco.get(v.index)
        if co is None:
            co = tuple(mw @ v.co)
            wco[v.index] = co
        pts.append(co)
    uvs = [(lp[uv_layer].uv.x, lp[uv_layer].uv.y) for lp in lps]
    return [((pts[0], pts[i], pts[i + 1]), (uvs[0], uvs[i], uvs[i + 1]))
            for i in range(1, len(lps) - 1)]


def _island_tris(isl, uv_layer, world_cache):
    mw = isl.obj.matrix_world
    wco = world_cache.setdefault(isl.obj.name, {})
    return [t for f in isl.faces for t in _face_tris(f, mw, uv_layer, wco)]


class IOPS_OT_UV_Align_Contextual(bpy.types.Operator):
    """Align selected UVs (vertex/edge mode) or whole islands (face/island
    mode) in the chosen direction"""

    bl_idname = "iops.uv_align_contextual"
    bl_label = "IOPS UV Align"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        items=[
            ("N", "Top", "Align to the top-most selection"),
            ("S", "Bottom", "Align to the bottom-most selection"),
            ("W", "Left", "Align to the left-most selection"),
            ("E", "Right", "Align to the right-most selection"),
            ("CENTER_X", "Center X", "Share one U (vertical line)"),
            ("CENTER_Y", "Center Y", "Share one V (horizontal line)"),
            ("WORLD_UP", "World Up",
             "Rotate islands so world +Z points to UV +V"),
            ("FOLLOW_ACTIVE", "Follow Active",
             "Rotate islands to continue the active face's UV orientation "
             "as if they were connected to it on the model"),
        ],
        default="N",
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "IMAGE_EDITOR"
            and context.mode == "EDIT_MESH"
        )

    # ------------------------------------------------------------ gather
    def _objects(self, context):
        out = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                continue
            bm.faces.ensure_lookup_table()
            out.append((obj, bm, uv_layer))
        return out

    def _islands(self, objs, use_sync, seed_fn):
        islands = []
        for obj, bm, uv_layer in objs:
            visible = _visible_faces(bm, use_sync)
            seed = seed_fn(bm, uv_layer, use_sync, visible)
            if not seed:
                continue
            groups, _ = get_selected_face_islands(
                bm, uv_layer, seed_faces=seed,
                restrict_to=[f.index for f in visible])
            for g in groups:
                faces = [bm.faces[i] for i in g]
                islands.append((_Island(obj, faces, uv_layer), uv_layer))
        return islands

    # ------------------------------------------------------------ execute
    def execute(self, context):
        use_sync = context.tool_settings.use_uv_select_sync
        mode = uv_align_mode(context)
        objs = self._objects(context)
        if not objs:
            self.report({"INFO"}, "No mesh with a UV map in edit mode")
            return {"CANCELLED"}

        d = self.direction
        if d in {"WORLD_UP", "FOLLOW_ACTIVE"}:
            seed_fn = _point_seed_faces if mode == "POINT" else _seed_faces
            if d == "WORLD_UP":
                result = self._world_up(context, objs, use_sync, seed_fn)
            else:
                result = self._follow_active(context, objs, use_sync, seed_fn)
        elif mode == "POINT":
            result = self._point(context, objs, use_sync, d)
        else:
            result = self._island(objs, use_sync, d)

        if result == {"FINISHED"}:
            for obj, _bm, _uv in objs:
                bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                                       destructive=False)
        return result

    def _point(self, context, objs, use_sync, d):
        sel = []
        for obj, bm, uv_layer in objs:
            sel.extend((lp, uv_layer)
                       for lp in _selected_loops(bm, uv_layer, use_sync))
        if not sel:
            self.report({"INFO"}, "No UVs selected")
            return {"CANCELLED"}

        # One entry per unique UV position: welded loops count once so the
        # centre average is not biased by vertex valence.
        uniq = {}
        for lp, uv_layer in sel:
            uv = lp[uv_layer].uv
            uniq.setdefault((round(uv.x, 6), round(uv.y, 6)), (uv.x, uv.y))
        target = core.point_line_target(d, uniq.values())
        if target is None:
            return {"CANCELLED"}
        axis, value = target
        for lp, uv_layer in sel:
            luv = lp[uv_layer]
            if axis == 0:
                luv.uv.x = value
            else:
                luv.uv.y = value
        return {"FINISHED"}

    def _island(self, objs, use_sync, d):
        islands = self._islands(objs, use_sync, _seed_faces)
        if not islands:
            self.report({"INFO"}, "No UV faces selected")
            return {"CANCELLED"}
        if len(islands) < 2:
            self.report({"INFO"}, "Need at least two islands to align")
            return {"CANCELLED"}
        bboxes = [isl.bbox for isl, _ in islands]
        offsets = core.island_offsets(d, bboxes)
        for (isl, uv_layer), (du, dv) in zip(islands, offsets):
            if du == 0.0 and dv == 0.0:
                continue
            for lp in isl.loops:
                luv = lp[uv_layer]
                luv.uv.x += du
                luv.uv.y += dv
        return {"FINISHED"}

    @staticmethod
    def _rotate_island(isl, uv_layer, angle, aspect):
        center = core.bbox_center(isl.bbox)
        for lp in isl.loops:
            luv = lp[uv_layer]
            luv.uv = core.rotate_uv((luv.uv.x, luv.uv.y), center, angle, aspect)

    def _world_up(self, context, objs, use_sync, seed_fn):
        islands = self._islands(objs, use_sync, seed_fn)
        if not islands:
            self.report({"INFO"}, "Nothing selected")
            return {"CANCELLED"}
        aspect = _image_aspect(context)
        rotated = skipped = 0
        world_cache = {}
        for isl, uv_layer in islands:
            tris = _island_tris(isl, uv_layer, world_cache)
            angle = core.world_up_angle(tris, aspect=aspect)
            if angle is None:
                skipped += 1
                continue
            if abs(angle) < ROTATE_EPS:
                continue
            self._rotate_island(isl, uv_layer, angle, aspect)
            rotated += 1
        if not rotated:
            self.report({"INFO"},
                        "Islands face up/down - no world-up direction"
                        if skipped else "Islands already point up")
            return {"CANCELLED"}
        if skipped:
            self.report({"INFO"},
                        f"Skipped {skipped} up/down-facing island(s)")
        return {"FINISHED"}

    def _active_face(self, context, objs, use_sync):
        """(obj, face, uv_layer) of the active object's active face, when the
        UV editor shows it."""
        edit = context.edit_object
        if edit is None or edit.type != "MESH":
            return None
        for obj, bm, uv_layer in objs:
            # objects_in_mode_unique_data may list another user of the mesh.
            if obj.data.name != edit.data.name:
                continue
            face = bm.faces.active
            if face is None or not face.is_valid or face.hide:
                return None
            if not use_sync and not face.select:
                return None
            return edit, face, uv_layer
        return None

    def _follow_active(self, context, objs, use_sync, seed_fn):
        active = self._active_face(context, objs, use_sync)
        if active is None:
            self.report({"INFO"}, "No active face")
            return {"CANCELLED"}
        act_obj, act_face, act_uv = active
        aspect = _image_aspect(context)
        world_cache = {}
        frame = core.uv_frame(
            _face_tris(act_face, act_obj.matrix_world, act_uv,
                       world_cache.setdefault(act_obj.name, {})),
            aspect)
        if frame is None:
            self.report({"INFO"}, "Active face has degenerate UVs")
            return {"CANCELLED"}

        islands = self._islands(objs, use_sync, seed_fn)
        act_data, act_index = act_obj.data.name, act_face.index
        targets = [(isl, uv_layer) for isl, uv_layer in islands
                   if not (isl.obj.data.name == act_data
                           and any(f.index == act_index for f in isl.faces))]
        if not targets:
            self.report({"INFO"}, "No other islands selected")
            return {"CANCELLED"}

        rotated = skipped = 0
        for isl, uv_layer in targets:
            tris = _island_tris(isl, uv_layer, world_cache)
            angle = core.follow_active_angle(frame, tris, aspect)
            if angle is None:
                skipped += 1
                continue
            if abs(angle) < ROTATE_EPS:
                continue
            self._rotate_island(isl, uv_layer, angle, aspect)
            rotated += 1
        if not rotated:
            self.report({"INFO"},
                        "No island could follow the active face"
                        if skipped else "Islands already follow the active face")
            return {"CANCELLED"}
        if skipped:
            self.report({"INFO"}, f"Skipped {skipped} island(s)")
        return {"FINISHED"}
