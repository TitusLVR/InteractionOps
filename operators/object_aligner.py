import bpy
import numpy as np
from mathutils import Matrix, Vector

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as iops_draw
from ..ui.draw import draw_scope
from ..ui.draw.theme import Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState, capture_event,
)
from ..utils.picking import raycast_from_mouse
from ..utils.alignment_fit import solve_fit


# --- State enums ----------------------------------------------------------

MODE_PICK_REF = "PICK_REF"
MODE_STAMP    = "STAMP"

CLONE_DUP  = "DUPLICATE"
CLONE_INST = "INSTANCE"
CLONE_CYCLE = (CLONE_DUP, CLONE_INST)

SCALE_KEEP    = "KEEP"
SCALE_UNIFORM = "UNIFORM"
SCALE_STRETCH = "STRETCH"
SCALE_CYCLE   = (SCALE_UNIFORM, SCALE_KEEP, SCALE_STRETCH)
SCALE_LABELS  = {SCALE_KEEP: "Keep", SCALE_UNIFORM: "Uniform", SCALE_STRETCH: "Stretch"}

FIT_GEOMETRY = "geometry"
FIT_MATRIX   = "matrix"


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


def _mouse_coord(event):
    return (event.mouse_region_x, event.mouse_region_y)


def _mesh_tris_world(obj):
    """World-space triangle vertices for an object's mesh, or [] if not a mesh.
    Used to fill-highlight a picked object's polygons (no edges)."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mesh = obj.data
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            return []
    mw = obj.matrix_world
    verts = [mw @ v.co for v in mesh.vertices]
    loops = mesh.loops
    out = []
    for lt in mesh.loop_triangles:
        out.append(verts[loops[lt.loops[0]].vertex_index])
        out.append(verts[loops[lt.loops[1]].vertex_index])
        out.append(verts[loops[lt.loops[2]].vertex_index])
    return out


def _mesh_edges_world(obj, world_matrix):
    """Flat list of world-space edge endpoints for `obj.data` transformed by
    `world_matrix`. [] if not a mesh."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mesh = obj.data
    verts = [world_matrix @ v.co for v in mesh.vertices]
    out = []
    for e in mesh.edges:
        out.append(verts[e.vertices[0]])
        out.append(verts[e.vertices[1]])
    return out


def _mesh_tris_world_at(obj, world_matrix):
    """Like _mesh_tris_world but with an explicit placement matrix."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mesh = obj.data
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            return []
    verts = [world_matrix @ v.co for v in mesh.vertices]
    loops = mesh.loops
    out = []
    for lt in mesh.loop_triangles:
        out.append(verts[loops[lt.loops[0]].vertex_index])
        out.append(verts[loops[lt.loops[1]].vertex_index])
        out.append(verts[loops[lt.loops[2]].vertex_index])
    return out


def _verts_world_np(obj):
    """Nx3 NumPy array of an object's mesh vertices in world space."""
    mesh = obj.data
    mw = obj.matrix_world
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mat = np.array(mw)                      # 4x4
    homog = np.hstack([co, np.ones((co.shape[0], 1))])
    world = homog @ mat.T
    return world[:, :3]


def _np_to_matrix(m4):
    """Convert a 4x4 NumPy array to a mathutils.Matrix (row-major)."""
    return Matrix([[float(m4[i][j]) for j in range(4)] for i in range(4)])


def _compute_fit(op, target):
    """Return (T_matrix, fit_kind). geometry fit when topology matches the
    reference; matrix fit otherwise."""
    ref = op.ref_obj
    same_topo = (
        op.ref_world_np is not None
        and target.type == "MESH"
        and len(target.data.vertices) == op.ref_world_np.shape[0]
    )
    if same_topo:
        tgt_np = _verts_world_np(target)
        t_np = solve_fit(op.ref_world_np, tgt_np, op.scale_mode)
        return _np_to_matrix(t_np), FIT_GEOMETRY
    # Matrix fallback: T = M_target @ M_ref^-1
    try:
        t = target.matrix_world @ ref.matrix_world.inverted()
    except (ReferenceError, ValueError):
        t = Matrix.Identity(4)
    return t, FIT_MATRIX


def _target_subcollection(op, source_obj, target):
    """Sub-collection inside the source object's collection, named
    `<source_collection>_<target_name>`. Created on first use, reused after.
    Newly created collections are tracked on `op.created_collections` so cancel
    can clean up empties."""
    parent = source_obj.users_collection[0] if source_obj.users_collection else bpy.context.scene.collection
    name = f"{parent.name}_{target.name}"
    sub = parent.children.get(name)
    if sub is None:
        sub = bpy.data.collections.get(name)
        if sub is None:
            sub = bpy.data.collections.new(name)
            op.created_collections.append(sub)
        if name not in parent.children:
            parent.children.link(sub)
    return sub


def _duplicate_obj(src, world_matrix, collection, linked):
    """Copy one object (+ its child hierarchy, preserving matrix_local) into
    `collection`. Root placed at `world_matrix`. Returns the list of new objs."""
    new_root = src.copy()
    if not linked and src.type == "MESH" and src.data and src.data.library is None:
        new_root.data = src.data.copy()
    new_root.parent = None
    collection.objects.link(new_root)
    new_root.matrix_world = world_matrix
    created = [new_root]

    def _dup_children(obj, new_parent):
        for child in obj.children:
            new_ob = child.copy()
            if not linked and child.type == "MESH" and child.data and child.data.library is None:
                new_ob.data = child.data.copy()
            new_ob.parent = new_parent
            new_ob.matrix_local = child.matrix_local.copy()
            collection.objects.link(new_ob)
            created.append(new_ob)
            _dup_children(child, new_ob)

    _dup_children(src, new_root)
    return created


def _bias_toward_view(coords, rv3d, factor=0.0015):
    """Nudge world coords slightly toward the viewer so a surface-coincident
    fill clears z-fighting with the geometry it overlays. gpu.state exposes no
    polygon offset, so we bias the vertices instead. The shift scales with
    depth (fraction of eye distance in perspective, view distance in ortho),
    keeping it imperceptible at any zoom."""
    if not coords or rv3d is None:
        return coords
    if rv3d.is_perspective:
        cam = rv3d.view_matrix.inverted().translation
        return [v + (cam - v) * factor for v in coords]
    view_dir = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
    step = view_dir * (rv3d.view_distance * factor)
    return [v + step for v in coords]


def _draw_rig_ghost(op, context, t_matrix, role=Role.GHOST_DEFAULT):
    """Draw the source rig as a GPU ghost at the given fit matrix (fill with a
    self-occlusion depth prepass, plus edges). Used both for the live hovered
    target and for already-committed picks — nothing is realized in the scene
    until _finish."""
    ghost_tris = []
    ghost_edges = []
    for src in op.source_objs:
        try:
            placement = t_matrix @ src.matrix_world
        except (ReferenceError, ValueError):
            continue
        ghost_tris.extend(_mesh_tris_world_at(src, placement))
        ghost_edges.extend(_mesh_edges_world(src, placement))
    if ghost_tris:
        with draw_scope(blend="NONE", depth="LESS_EQUAL",
                        face_culling="BACK", depth_mask=True,
                        color_mask=(False, False, False, False)):
            iops_draw.tris(ghost_tris, role=role, context=context)
        with draw_scope(blend="ALPHA", depth="EQUAL",
                        face_culling="BACK", depth_mask=False):
            iops_draw.tris(ghost_tris, role=role, context=context)
    if ghost_edges:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(ghost_edges, role=Role.GHOST_EDGE, context=context)


def _draw_preview_3d(op, context):
    """POST_VIEW: highlight the reference surface, then draw the rig as a GPU
    ghost at every committed pick and at the live hovered target. Real objects
    are only created on confirm (_finish)."""
    rv3d = context.region_data
    # Reference highlight — active surface fill, polygons only.
    if op.ref_obj is not None:
        try:
            tris = _mesh_tris_world(op.ref_obj)
        except ReferenceError:
            tris = []
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)

    # Committed picks — rig ghost at each stored placement (preview only).
    for pend in op.pending:
        _draw_rig_ghost(op, context, pend["matrix"], role=Role.GHOST_PREVIEW)

    # Rig ghost at the live hovered target (fill + edges).
    if op.mode == MODE_STAMP and op.hover_obj is not None and op.ref_obj is not None \
            and op.hover_obj not in op.source_set and op.hover_obj is not op.ref_obj:
        try:
            t_matrix, fit_kind = _compute_fit(op, op.hover_obj)
        except (ReferenceError, ValueError):
            t_matrix, fit_kind = None, ""
        if t_matrix is not None:
            op.last_fit = fit_kind
            _draw_rig_ghost(op, context, t_matrix, role=Role.GHOST_DEFAULT)


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context, op):
    hud = HUDOverlay("object_aligner")
    hud.title = "Object Aligner"
    hud.bind_region(context.region)
    hud.add_param(HUDParam("Mode", lambda: "Pick reference" if op.mode == MODE_PICK_REF else "Stamp"))
    hud.add_param(HUDParam("Reference", lambda: op.ref_name or "—",
                           visible_getter=lambda: bool(op.ref_name)))
    hud.add_param(HUDParam("Clone", lambda: op.clone_mode))
    hud.add_param(HUDParam("Scale", lambda: SCALE_LABELS.get(op.scale_mode, op.scale_mode)))
    hud.add_param(HUDParam("Fit", lambda: op.last_fit or "—",
                           visible_getter=lambda: bool(op.last_fit)))
    hud.add_param(HUDParam("Stamped", lambda: op.stamped_count, kind="int"))
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_aligner")
    helpo.add_section(HUDSection("Object Aligner", [
        HUDItem("Pick reference / target", "LMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Re-pick reference",       "R",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type (Duplicate/Instance)", "D",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Scale (Uniform/Keep/Stretch)",    "S",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",                   "Enter / Space / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel",                  "Esc",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD",              "H",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
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


# --- Operator -------------------------------------------------------------

class IOPS_OT_Object_Aligner(bpy.types.Operator):
    """Stamp the selected rig onto raycast-picked objects, preserving the
    transform relative to a picked reference (topology-aware)."""

    bl_idname = "iops.object_aligner"
    bl_label = "OBJECT: Object Aligner"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        if not sel:
            self.report({"WARNING"}, "Select the rig objects to transfer")
            return {"CANCELLED"}

        self.source_objs = sel
        self.source_set = set(sel)
        self.mode = MODE_PICK_REF
        self.clone_mode = CLONE_DUP
        self.scale_mode = SCALE_UNIFORM
        self.ref_obj = None
        self.ref_name = ""
        self.ref_world_np = None        # cached Nx3 reference verts (world)
        self.hover_obj = None
        self.last_fit = ""
        self.stamped_count = 0
        self.stamped_objs = []          # everything created on finish (for cancel safety)
        self.pending = []               # committed picks: {target, matrix, linked} — realized on finish
        self.created_collections = []   # sub-collections created on finish (for cancel)
        self._last_event = None

        self._hud = _build_hud(context, self)
        self._help = _build_help(context)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None
        if context.area is not None:
            context.area.tag_redraw()

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # HUD/Help drag + toggle handling (verified pattern from
        # object_radial_array.py — the `handle_*_toggle` module helpers have a
        # different arity and must NOT be called as (op, event)).
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

        if event.type in {"ESC"} and event.value == "PRESS":
            return self._cancel(context)
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE", "RIGHTMOUSE"} and event.value == "PRESS":
            self._realize_pending(context)
            self._finish(context)
            self.report({"INFO"}, f"Aligner: stamped {self.stamped_count}")
            return {"FINISHED"}

        if event.value == "PRESS":
            if event.type == "D":
                self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
                return {"RUNNING_MODAL"}
            if event.type == "S":
                self.scale_mode = _cycle(self.scale_mode, SCALE_CYCLE)
                return {"RUNNING_MODAL"}
            if event.type == "R":
                self.mode = MODE_PICK_REF
                return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE":
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self._on_click(context, event)

        return {"PASS_THROUGH"}

    def _cancel(self, context):
        for ob in reversed(self.stamped_objs):
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        self.stamped_objs = []
        # Remove sub-collections we created this session if they are now empty.
        for coll in self.created_collections:
            try:
                if not coll.objects and not coll.children:
                    bpy.data.collections.remove(coll)
            except (ReferenceError, RuntimeError):
                pass
        self.created_collections = []
        self._finish(context)
        self.report({"INFO"}, "Aligner: cancelled")
        return {"CANCELLED"}

    def _pick(self, context, event):
        """Raycast under the mouse, excluding the rig (and reference when
        stamping). Returns the ORIGINAL hit object or None.

        `scene.ray_cast` yields the depsgraph-evaluated object; we return
        `obj.original` so (a) duplication copies the base datablock rather than
        an evaluated/flattened mesh, (b) geometry-fit reads base-mesh verts, and
        (c) membership in the exclude set (which holds originals) matches."""
        exclude = set(self.source_set)
        if self.mode == MODE_STAMP and self.ref_obj is not None:
            exclude.add(self.ref_obj)
        hit, _loc, _n, _fi, obj, _mx = raycast_from_mouse(
            context, _mouse_coord(event), exclude=exclude)
        return obj.original if (hit and obj is not None) else None

    def _update_hover(self, context, event):
        self.hover_obj = self._pick(context, event)

    def _on_click(self, context, event):
        obj = self._pick(context, event)
        if obj is None:
            return {"RUNNING_MODAL"}
        if self.mode == MODE_PICK_REF:
            self.ref_obj = obj
            self.ref_name = obj.name
            self.ref_world_np = _verts_world_np(obj) if obj.type == "MESH" else None
            self.mode = MODE_STAMP
            return {"RUNNING_MODAL"}
        # MODE_STAMP: record the pick as a pending stamp (preview only). The fit
        # matrix and clone mode are frozen at click time; nothing is realized in
        # the scene until _finish.
        t_matrix, fit_kind = _compute_fit(self, obj)
        self.last_fit = fit_kind
        self.pending.append({
            "target": obj,
            "matrix": t_matrix,
            "linked": self.clone_mode == CLONE_INST,
        })
        self.stamped_count += 1
        return {"RUNNING_MODAL"}

    def _realize_pending(self, context):
        """Create the real objects for every committed pick. Only iterate
        top-level roots (objects whose parent is not itself selected) — child
        subtrees are duplicated recursively by _duplicate_obj, so iterating
        every selected object would double-stamp parented rigs."""
        roots = [o for o in self.source_objs if o.parent not in self.source_set]
        for pend in self.pending:
            obj, t_matrix, linked = pend["target"], pend["matrix"], pend["linked"]
            for src in roots:
                sub = _target_subcollection(self, src, obj)
                world_matrix = t_matrix @ src.matrix_world
                created = _duplicate_obj(src, world_matrix, sub, linked)
                self.stamped_objs.extend(created)
