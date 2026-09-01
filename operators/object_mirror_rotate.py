import bpy
import math
from itertools import combinations
from mathutils import Vector, Matrix

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState,
    capture_event,
)


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context):
    hud = HUDOverlay("object_mirror_rotate")
    hud.title = "Mirror Rotate"
    hud.bind_region(context.region)
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_mirror_rotate")
    helpo.add_section(HUDSection("Mirror Rotate", [
        HUDItem("Pivot (Cursor / Active / Pick object)", "Q", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Mirror axis toggles (combos multiply)", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Orientation (Global / Pivot frame)", "W", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Method (Mirror / Rotate 180°)", "M", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type (Duplicate / Instance / In place)", "D", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply transforms on confirm", "A", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Snap cursor to face (vert/edge-mid/center, Z=normal)", "C + LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reset to defaults", "B", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply", "Space / Enter", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel", "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


def _draw_callback(op, context):
    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


# --- State enums (string constants — Blender modal idiom) ----------------

PIVOT_CURSOR = "CURSOR"
PIVOT_ACTIVE = "ACTIVE"
PIVOT_PICK   = "PICK"        # LMB-click picks any object (empty) as the pivot
PIVOT_CYCLE  = (PIVOT_CURSOR, PIVOT_ACTIVE, PIVOT_PICK)

PIVOT_LABELS = {
    PIVOT_CURSOR: "Cursor",
    PIVOT_ACTIVE: "Active",
    PIVOT_PICK:   "Picked object",
}

METHOD_MIRROR = "MIRROR"     # true reflection (negative determinant)
METHOD_ROTATE = "ROTATE180"  # rigid 180° rotation — no flipped normals
METHOD_CYCLE  = (METHOD_MIRROR, METHOD_ROTATE)

METHOD_LABELS = {
    METHOD_MIRROR: "Mirror",
    METHOD_ROTATE: "Rotate 180°",
}

CLONE_DUP      = "DUPLICATE"
CLONE_INST     = "INSTANCE"
CLONE_IN_PLACE = "IN_PLACE"  # transform the sources themselves, no clones
CLONE_CYCLE    = (CLONE_DUP, CLONE_INST, CLONE_IN_PLACE)

CLONE_LABELS = {
    CLONE_DUP:      "Duplicate",
    CLONE_INST:     "Instance",
    CLONE_IN_PLACE: "In place",
}

ORIENT_GLOBAL = "GLOBAL"
ORIENT_PIVOT  = "PIVOT"      # cursor axes / active local axes / picked object axes
ORIENT_CYCLE  = (ORIENT_GLOBAL, ORIENT_PIVOT)

AXIS_LETTERS = ("X", "Y", "Z")
_AXIS_UNIT = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


def _build_subtree_data(roots):
    """[(obj), root first then children_recursive] per root — clone units."""
    out = []
    for root in roots:
        try:
            root.matrix_world  # noqa: B018 — probe for dead references
        except ReferenceError:
            continue
        out.append([root, *root.children_recursive])
    return out


def _plane_frame(normal):
    """(right, fwd) orthonormal basis spanning the plane perpendicular to normal."""
    up = normal
    right = Vector((1, 0, 0)) if abs(up.x) < 0.9 else Vector((0, 1, 0))
    right = (right - up * right.dot(up)).normalized()
    fwd = up.cross(right)
    return right, fwd


# --- Mesh geometry cache (verbatim pattern from object_radial_array) ------

def _mesh_geom_cache(obj):
    mesh = obj.data
    verts_local = [v.co.copy() for v in mesh.vertices]
    edge_pairs = [(e.vertices[0], e.vertices[1]) for e in mesh.edges]
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            pass
    loops = mesh.loops
    tri_idx = [(loops[lt.loops[0]].vertex_index,
                loops[lt.loops[1]].vertex_index,
                loops[lt.loops[2]].vertex_index)
               for lt in mesh.loop_triangles]
    return verts_local, edge_pairs, tri_idx


def _mesh_edge_segments_world(obj_mw, geom):
    verts_local, edge_pairs, _ = geom
    verts_world = [obj_mw @ v for v in verts_local]
    return [(verts_world[a], verts_world[b]) for a, b in edge_pairs]


def _mesh_face_tris_world(obj_mw, geom):
    verts_local, _, tri_idx = geom
    verts_world = [obj_mw @ v for v in verts_local]
    out = []
    for a, b, c in tri_idx:
        out.append(verts_world[a])
        out.append(verts_world[b])
        out.append(verts_world[c])
    return out


# --- Transform math --------------------------------------------------------

def _axis_reflection(normal, method):
    """3x3 building block for one axis: reflection along `normal` (MIRROR) or a
    rigid 180° spin around it (ROTATE180)."""
    if method == METHOD_MIRROR:
        return Matrix.Scale(-1.0, 3, normal)
    return Matrix.Rotation(math.pi, 3, normal)


def _combo_deltas(op, context):
    """World-space delta matrices, one per clone. Every non-empty subset of the
    enabled axes gets a clone (X+Y → 3 clones, like the Mirror modifier); the
    IN_PLACE mode collapses to the single combined transform of all enabled
    axes, since the source can only move once."""
    normals = _axis_normals(op, context)
    if not normals:
        return []
    letters = sorted(normals.keys(), key=AXIS_LETTERS.index)
    if op.clone_mode == CLONE_IN_PLACE:
        subsets = [tuple(letters)]
    else:
        subsets = [s for r in range(1, len(letters) + 1)
                   for s in combinations(letters, r)]
    T_to = Matrix.Translation(op.pivot_co)
    T_from = Matrix.Translation(-op.pivot_co)
    deltas = []
    for subset in subsets:
        D3 = Matrix.Identity(3)
        for letter in subset:
            D3 = _axis_reflection(normals[letter], op.method) @ D3
        deltas.append(T_to @ D3.to_4x4() @ T_from)
    return deltas


def _pivot_frame_3x3(op, context):
    """Orthonormal frame the mirror-plane normals live in."""
    if op.orient_mode == ORIENT_GLOBAL:
        return Matrix.Identity(3)
    if op.pivot_mode == PIVOT_CURSOR:
        return context.scene.cursor.matrix.to_3x3()
    src = op.pivot_obj if op.pivot_mode == PIVOT_PICK else context.active_object
    if src is not None:
        try:
            return src.matrix_world.to_quaternion().to_matrix()
        except ReferenceError:
            pass
    return Matrix.Identity(3)


def _axis_normals(op, context):
    """{letter: world normal} for every enabled mirror axis."""
    frame = _pivot_frame_3x3(op, context)
    return {letter: (frame @ _AXIS_UNIT[letter]).normalized()
            for letter in AXIS_LETTERS if letter in op.axes}


def _axes_label(op):
    return "+".join(a for a in AXIS_LETTERS if a in op.axes) or "—"


# --- T-pick: snap cursor to a face (pattern from object_radial_array) -----

def _tpick_update(op, context, event):
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        op._tpick = None
        return
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
    mouse = Vector((event.mouse_region_x, event.mouse_region_y))
    origin = region_2d_to_origin_3d(region, rv3d, mouse)
    direction = region_2d_to_vector_3d(region, rv3d, mouse)
    depsgraph = context.evaluated_depsgraph_get()
    hit, loc, normal, idx, obj, mat = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit or obj is None:
        op._tpick = None
        return
    try:
        mesh = obj.evaluated_get(depsgraph).data
        poly = mesh.polygons[idx]
        vids = list(poly.vertices)
        vw = [mat @ mesh.vertices[vi].co for vi in vids]
    except (AttributeError, IndexError, ReferenceError):
        op._tpick = None
        return
    n = len(vw)
    if n < 3:
        op._tpick = None
        return
    center = mat @ poly.center
    mids = [(vw[i] + vw[(i + 1) % n]) * 0.5 for i in range(n)]
    snaps = list(vw) + mids + [center]
    closest = min(snaps, key=lambda p: (p - loc).length)
    tris = []
    for i in range(1, n - 1):
        tris.extend([vw[0], vw[i], vw[i + 1]])
    edges = []
    for i in range(n):
        edges.append(vw[i])
        edges.append(vw[(i + 1) % n])
    nlen = sum((m - center).length for m in mids) / n if n else 0.3
    op._tpick = {
        "tris": tris, "edges": edges, "snaps": snaps,
        "closest": closest, "normal": normal.normalized(),
        "nlen": max(nlen, 1e-3),
    }


def _draw_tpick(op, context):
    tp = getattr(op, "_tpick", None)
    if not tp:
        return
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if tp["tris"]:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(tp["tris"], role=Role.GHOST_DEFAULT, context=context)
    if tp["edges"]:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(tp["edges"], role=Role.CLOSEST_LINE, context=context)
    nlen = tp.get("nlen", 0.3) or 0.3
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
        iops_draw.edges_3d([tp["closest"], tp["closest"] + tp["normal"] * nlen],
                           role=Role.ACTIVE_LINE, context=context)
    with draw_scope(blend="ALPHA", depth="NONE"):
        if tp["snaps"]:
            iops_draw.points(tp["snaps"], role=Role.PREVIEW_POINT, context=context)
        iops_draw.points([tp["closest"]], role=Role.CLOSEST_POINT, context=context)


# --- Preview (POST_VIEW) ----------------------------------------------------

def _sources_extent(op):
    """Radius (from the pivot) that comfortably covers the sources and their
    mirrored clones — used to size the mirror-plane quads."""
    r = 0.0
    for subtree in op.subtree_data:
        for obj in subtree:
            try:
                mw = obj.matrix_world
                for corner in obj.bound_box:
                    r = max(r, (mw @ Vector(corner) - op.pivot_co).length)
            except ReferenceError:
                continue
    return max(r * 1.1, 1.0)


def _build_ghosts(op, context):
    """(segs, tris, plane_quads, plane_outlines, normal_lines) for the preview.
    plane_quads is a flat tri list; outlines / normal_lines are flat edge lists."""
    op.subtree_data = _build_subtree_data([sub[0] for sub in op.subtree_data])

    segs = []
    tris = []
    cache = getattr(op, "_mesh_cache", {})
    for delta in _combo_deltas(op, context):
        for subtree in op.subtree_data:
            for obj in subtree:
                try:
                    clone_mw = delta @ obj.matrix_world
                except ReferenceError:
                    continue
                geom = cache.get(obj)
                if geom is not None:
                    for a, b in _mesh_edge_segments_world(clone_mw, geom):
                        segs.append(a)
                        segs.append(b)
                    tris.extend(_mesh_face_tris_world(clone_mw, geom))

    plane_quads = []
    plane_outlines = []
    normal_lines = []
    ext = _sources_extent(op)
    for n in _axis_normals(op, context).values():
        right, fwd = _plane_frame(n)
        p = op.pivot_co
        c = [p + right * ext + fwd * ext, p - right * ext + fwd * ext,
             p - right * ext - fwd * ext, p + right * ext - fwd * ext]
        plane_quads.extend([c[0], c[1], c[2], c[0], c[2], c[3]])
        for i in range(4):
            plane_outlines.append(c[i])
            plane_outlines.append(c[(i + 1) % 4])
        normal_lines.append(p)
        normal_lines.append(p + n * (ext * 0.25))
    return segs, tris, plane_quads, plane_outlines, normal_lines


def _draw_preview_3d(op, context):
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if op._dirty or getattr(op, "_ghost_cache", None) is None:
        op._ghost_cache = _build_ghosts(op, context)
        op._dirty = False
    segs, tris, plane_quads, plane_outlines, normal_lines = op._ghost_cache

    # Two-pass transparent fill (depth pre-pass, then color at depth=EQUAL) so
    # overlapping clones don't alpha-stack. Culling stays off — mirrored
    # geometry has inverted winding.
    if tris:
        with draw_scope(blend="NONE", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=True,
                        color_mask=(False, False, False, False)):
            iops_draw.tris(tris, role=Role.GHOST_DEFAULT, context=context)
        with draw_scope(blend="ALPHA", depth="EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(tris, role=Role.GHOST_DEFAULT, context=context)
    if segs:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(segs, role=Role.GHOST_EDGE, context=context)

    if plane_quads:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(plane_quads, role=Role.GHOST_LOCKED, context=context)
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(plane_outlines, role=Role.PREVIEW_LINE, context=context)
    if normal_lines:
        with draw_scope(blend="ALPHA", depth="NONE"):
            iops_draw.edges_3d(normal_lines, role=Role.ACTIVE_LINE, context=context)

    with draw_scope(blend="ALPHA", depth="NONE"):
        iops_draw.points([op.pivot_co], role=Role.PIVOT, context=context)

    if getattr(op, "pending_normal_pick", False):
        _draw_tpick(op, context)


class IOPS_OT_Object_Mirror_Rotate(bpy.types.Operator):
    """Mirror-clone selected objects across a plane through the cursor, the
    active object or any picked object — as a true mirror or a 180° rotation"""

    bl_idname = "iops.object_mirror_rotate"
    bl_label = "OBJECT: Mirror Rotate"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        if not sel:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        self.pivot_mode = PIVOT_CURSOR
        self.orient_mode = ORIENT_GLOBAL
        self.method = METHOD_MIRROR
        self.clone_mode = CLONE_DUP
        self.axes = {"X"}
        self.apply_transforms = True
        self.pivot_obj = None            # picked pivot (PIVOT_PICK)
        self.pivot_co = Vector((0, 0, 0))
        self.pending_pivot_pick = False
        self.pending_normal_pick = False
        self._tpick = None
        self._dirty = True

        self._resolve_pivot(context)
        self._rebuild_sources(context)
        if not self.subtree_data:
            self.report({"WARNING"}, "Select at least one source object")
            return {"CANCELLED"}

        self._hud = _build_hud(context)
        self._hud.add_param(HUDParam("Pivot",  lambda: self._pivot_hud_label(), "str"))
        self._hud.add_param(HUDParam("Axes",   lambda: _axes_label(self), "str"))
        self._hud.add_param(HUDParam("Orientation", lambda: "Global" if self.orient_mode == ORIENT_GLOBAL else "Pivot", "str"))
        self._hud.add_param(HUDParam("Method", lambda: METHOD_LABELS[self.method], "str"))
        self._hud.add_param(HUDParam("Clone",  lambda: CLONE_LABELS[self.clone_mode], "str"))
        self._hud.add_param(HUDParam("Apply transforms", lambda: self.apply_transforms, "bool"))
        self._help = _build_help(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _pivot_hud_label(self):
        if self.pivot_mode == PIVOT_PICK:
            if self.pivot_obj is not None:
                try:
                    return f"Picked: {self.pivot_obj.name}"
                except ReferenceError:
                    return "Picked: <gone>"
            return "Pick: click an object"
        return PIVOT_LABELS[self.pivot_mode]

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov is None:
                    continue
                if ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        # Navigation always passes through.
        if event.type == "MIDDLEMOUSE":
            return {"PASS_THROUGH"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        if event.type in {"TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}

        # --- pivot cycle ---
        if event.type == "Q" and event.value == "PRESS":
            self.pivot_mode = _cycle(self.pivot_mode, PIVOT_CYCLE)
            self.pending_pivot_pick = (self.pivot_mode == PIVOT_PICK)
            self._resolve_pivot(context)
            self._rebuild_sources(context)
            self._dirty = True
            if self.pivot_mode == PIVOT_PICK:
                self.report({"INFO"}, "Pivot: click an object (empty) to set the pivot")
            else:
                self.report({"INFO"}, f"Pivot: {PIVOT_LABELS[self.pivot_mode]}")
            return {"RUNNING_MODAL"}

        # --- mirror axes ---
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            letter = event.type
            if letter in self.axes:
                self.axes.discard(letter)
            else:
                self.axes.add(letter)
            self._dirty = True
            self.report({"INFO"}, f"Axes: {_axes_label(self)}")
            return {"RUNNING_MODAL"}

        if event.type == "W" and event.value == "PRESS":
            self.orient_mode = _cycle(self.orient_mode, ORIENT_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Orientation: {'Global' if self.orient_mode == ORIENT_GLOBAL else 'Pivot frame'}")
            return {"RUNNING_MODAL"}

        if event.type == "M" and event.value == "PRESS":
            self.method = _cycle(self.method, METHOD_CYCLE)
            # Two workflows: Mirror bakes transforms (and flips normals on the
            # reflection), Rotate 180° is rigid and needs no bake. A can still
            # override afterwards.
            self.apply_transforms = (self.method == METHOD_MIRROR)
            self._dirty = True
            self.report({"INFO"},
                        f"Method: {METHOD_LABELS[self.method]}  |  Apply transforms: "
                        f"{'on' if self.apply_transforms else 'off'}")
            return {"RUNNING_MODAL"}

        if event.type == "D" and event.value == "PRESS":
            self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Clone: {CLONE_LABELS[self.clone_mode]}")
            return {"RUNNING_MODAL"}

        if event.type == "A" and event.value == "PRESS":
            self.apply_transforms = not self.apply_transforms
            self.report({"INFO"}, f"Apply transforms: {'on' if self.apply_transforms else 'off'}")
            return {"RUNNING_MODAL"}

        if event.type == "B" and event.value == "PRESS":
            self._reset_defaults()
            self._resolve_pivot(context)
            self._rebuild_sources(context)
            self.report({"INFO"}, "Mirror Rotate reset to defaults")
            return {"RUNNING_MODAL"}

        # --- face pick: snap the 3D cursor ---
        if event.type == "C" and event.value == "PRESS":
            self.pending_normal_pick = True
            _tpick_update(self, context, event)
            context.area.tag_redraw()
            self.report({"INFO"}, "Hover a face; click a vert / edge-mid / center to snap the 3D cursor there")
            return {"RUNNING_MODAL"}

        if self.pending_normal_pick and event.type == "MOUSEMOVE":
            _tpick_update(self, context, event)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if self.pending_normal_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            _tpick_update(self, context, event)
            tp = self._tpick
            if tp is not None:
                cursor = context.scene.cursor
                cursor.location = tp["closest"].copy()
                cursor.rotation_mode = "XYZ"
                cursor.rotation_euler = tp["normal"].to_track_quat("Z", "Y").to_euler()
                self.pivot_mode = PIVOT_CURSOR
                self.orient_mode = ORIENT_PIVOT
                self._resolve_pivot(context)
                self._rebuild_sources(context)
                self._dirty = True
                self.report({"INFO"}, "Cursor snapped to face (pivot = Cursor, planes in cursor frame)")
            else:
                self.report({"WARNING"}, "No face under cursor")
            self.pending_normal_pick = False
            self._tpick = None
            return {"RUNNING_MODAL"}

        # --- pivot object pick ---
        if self.pending_pivot_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            picked = self._pick_object(context, event)
            if picked is not None:
                self.pivot_obj = picked
                self.pending_pivot_pick = False
                self._resolve_pivot(context)
                self._rebuild_sources(context)
                self._dirty = True
                self.report({"INFO"}, f"Pivot object: {picked.name}")
            else:
                self.report({"WARNING"}, "No object origin near the click")
            return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._apply(context)
            self._cleanup()
            return {"FINISHED"}

        if self.pending_normal_pick and event.type == "ESC" and event.value == "PRESS":
            self.pending_normal_pick = False
            self._tpick = None
            context.area.tag_redraw()
            self.report({"INFO"}, "Face pick cancelled")
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    # --- pivot / sources -----------------------------------------------------

    def _resolve_pivot(self, context):
        active = context.active_object
        cursor = context.scene.cursor
        if self.pivot_mode == PIVOT_ACTIVE and active is not None:
            self.pivot_co = active.matrix_world.translation.copy()
        elif self.pivot_mode == PIVOT_PICK and self.pivot_obj is not None:
            try:
                self.pivot_co = self.pivot_obj.matrix_world.translation.copy()
            except ReferenceError:
                self.pivot_obj = None
                self.pivot_co = cursor.location.copy()
        else:
            self.pivot_co = cursor.location.copy()

    def _pick_object(self, context, event):
        """Nearest visible object origin to the click, in screen space — works
        for empties too (no geometry to raycast)."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        best, best_d = None, 1e9
        for obj in context.visible_objects:
            try:
                p2 = location_3d_to_region_2d(region, rv3d, obj.matrix_world.translation)
            except ReferenceError:
                continue
            if p2 is None:
                continue
            d = (p2 - mouse).length
            if d < best_d:
                best_d, best = d, obj
        return best if best_d <= 40.0 else None

    def _rebuild_sources(self, context):
        """Sources: the selection, minus the pivot object when it doubles as the
        pivot (active pivot / picked pivot). Children come along per subtree."""
        sel = list(context.selected_objects)
        active = context.active_object
        if self.pivot_mode == PIVOT_ACTIVE and active is not None:
            roots = [o for o in sel if o is not active]
            if not roots:
                roots = [active]     # single object mirrored around itself
        elif self.pivot_mode == PIVOT_PICK and self.pivot_obj is not None:
            roots = [o for o in sel if o is not self.pivot_obj]
        else:
            roots = sel
        self.subtree_data = _build_subtree_data(roots)
        cache = {}
        for subtree in self.subtree_data:
            for obj in subtree:
                if obj.type == "MESH" and obj.data is not None and obj not in cache:
                    try:
                        cache[obj] = _mesh_geom_cache(obj)
                    except (ReferenceError, AttributeError):
                        pass
        self._mesh_cache = cache

    def _reset_defaults(self):
        self.pivot_mode = PIVOT_CURSOR
        self.orient_mode = ORIENT_GLOBAL
        self.method = METHOD_MIRROR
        self.clone_mode = CLONE_DUP
        self.axes = {"X"}
        self.apply_transforms = True
        self.pivot_obj = None
        self.pending_pivot_pick = False
        self.pending_normal_pick = False
        self._tpick = None
        self._dirty = True

    def _cleanup(self):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None

    # --- apply -----------------------------------------------------------------

    def _apply(self, context):
        deltas = _combo_deltas(self, context)
        if not deltas:
            self.report({"WARNING"}, "No mirror axis enabled — nothing to do")
            return
        if not self.subtree_data:
            return

        created_roots = []
        jobs = []       # (obj, target_world), parents always before children

        def _clone_subtree(subtree, delta):
            clone_map = {}
            for obj in subtree:
                new = obj.copy()
                if self.clone_mode == CLONE_DUP and obj.data is not None:
                    new.data = obj.data.copy()
                for c in obj.users_collection:
                    try:
                        c.objects.link(new)
                    except RuntimeError:
                        pass
                clone_map[obj] = new
            for obj in subtree:
                new = clone_map[obj]
                if obj.parent is not None and obj.parent in clone_map:
                    new.parent = clone_map[obj.parent]
                    new.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
                else:
                    new.parent = None
                jobs.append((new, delta @ obj.matrix_world))
            created_roots.append(clone_map[subtree[0]])

        if self.clone_mode == CLONE_IN_PLACE:
            delta = deltas[0]
            for subtree in self.subtree_data:
                for obj in subtree:
                    try:
                        jobs.append((obj, delta @ obj.matrix_world))
                    except ReferenceError:
                        continue
                created_roots.append(subtree[0])
        else:
            for delta in deltas:
                for subtree in self.subtree_data:
                    _clone_subtree(subtree, delta)

        self._finalize_transforms(jobs)
        if not self.apply_transforms and self.method == METHOD_MIRROR:
            self.report({"INFO"}, "Mirror clones keep negative scale (Apply transforms is off)")

        for obj in context.view_layer.objects:
            try:
                obj.select_set(False)
            except RuntimeError:
                pass
        for r in created_roots:
            try:
                r.select_set(True)
            except RuntimeError:
                pass
        if created_roots:
            try:
                context.view_layer.objects.active = created_roots[0]
            except (AttributeError, RuntimeError):
                pass

    def _finalize_transforms(self, jobs):
        """Place every object at its computed target world matrix, optionally
        baking rotation & scale into the mesh data (with a normal flip when the
        transform is a reflection) — the negative-scale cleanup that makes
        mirrored kitbash clones export-safe.

        The target matrices are computed here from scratch and local matrices
        are derived through the parent chain explicitly: the matrix_world
        setter reads the parent's world from the depsgraph, which is stale for
        objects created or moved in the same tick.

        Linked (multi-user) mesh data is made single-user before baking so the
        reflection lands in this clone's own copy; INSTANCE clones keep their
        shared data and stay mirrored at the object level instead."""
        final = {}
        kept_shared = 0
        for obj, target in jobs:
            desired = target
            if self.apply_transforms and obj.type == "MESH" and obj.data is not None:
                data = obj.data
                if data.users > 1:
                    if self.clone_mode == CLONE_INST:
                        data = None       # instances share data — nothing to bake
                        kept_shared += 1
                    else:
                        data = data.copy()
                        obj.data = data
                if data is not None:
                    rs = target.to_3x3()
                    try:
                        data.transform(rs.to_4x4())
                        if rs.determinant() < 0.0:
                            data.flip_normals()
                        desired = Matrix.Translation(target.translation)
                    except RuntimeError:
                        desired = target
            parent = obj.parent
            if parent is not None and parent in final:
                # Local matrix through the just-final parent world — the only
                # reliable route while the depsgraph hasn't re-evaluated.
                try:
                    obj.matrix_basis = (obj.matrix_parent_inverse.inverted()
                                        @ final[parent].inverted() @ desired)
                except ValueError:
                    obj.matrix_world = desired
            else:
                try:
                    obj.matrix_world = desired
                except ReferenceError:
                    continue
            final[obj] = desired
        if kept_shared:
            self.report({"INFO"},
                        f"{kept_shared} instanced mesh(es) keep shared data (mirrored at object level)")
