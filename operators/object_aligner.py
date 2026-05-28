import bpy
import bmesh
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

MODE_PICK_REF      = "PICK_REF"
MODE_STAMP         = "STAMP"
MODE_PICK_REF_POLY = "PICK_REF_POLY"      # marking ref polys; Q again commits
MODE_PICK_TGT_POLY = "PICK_TGT_POLY"      # marking target polys; Apply stamps

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


def _bmesh_for(op, obj):
    """Lazy bmesh-cache keyed by obj.original. Reads the **evaluated** mesh
    (with modifiers applied) so picks respect Mirror/Array/SubD/etc. Caller
    must not mutate the bmesh — read-only. Freed in _finish."""
    key = obj.original
    cached = op._bmesh_cache.get(key)
    if cached is not None:
        return cached
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = key.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(eval_mesh)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    # Free the temporary evaluated mesh datablock.
    eval_obj.to_mesh_clear()
    op._bmesh_cache[key] = bm
    return bm


def _evaluated_mesh_for(op, obj):
    """Get a cached evaluated mesh datablock for `obj` (the modifier-applied
    one). Cached by obj.original on op._eval_mesh_cache. Freed in _finish.

    Returns the bpy.types.Mesh you can index .polygons / .vertices on.
    """
    key = obj.original
    cache = op._eval_mesh_cache
    cached = cache.get(key)
    if cached is not None:
        return cached
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = key.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    # Keep the eval_obj alive so the mesh datablock stays valid; store both.
    cache[key] = eval_mesh
    op._eval_mesh_owners = getattr(op, "_eval_mesh_owners", [])
    op._eval_mesh_owners.append(eval_obj)
    return eval_mesh


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


def _selected_face_tris_world(op, store: dict) -> list:
    """Flat list of world-space triangle verts for the faces stored in
    `store` (dict[obj_original -> set[face_idx]]). Fan-triangulates n-gons.
    Uses the evaluated mesh so mirrored/arrayed geometry is drawn correctly."""
    out = []
    for obj, face_idx_set in store.items():
        try:
            if obj.type != "MESH" or obj.data is None:
                continue
            mesh = _evaluated_mesh_for(op, obj)
            mw = obj.matrix_world
            for fi in face_idx_set:
                if fi < 0 or fi >= len(mesh.polygons):
                    continue
                poly = mesh.polygons[fi]
                vs = [mw @ mesh.vertices[poly.vertices[i]].co
                      for i in range(len(poly.vertices))]
                for i in range(1, len(vs) - 1):
                    out.extend([vs[0], vs[i], vs[i + 1]])
        except ReferenceError:
            continue
    return out


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
    # Reference highlight — whole-object fill (only when no ref polys marked).
    if op.ref_obj is not None and not op.ref_polys:
        try:
            tris = _mesh_tris_world(op.ref_obj)
        except ReferenceError:
            tris = []
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)

    # Marked ref polys — fill (replaces whole-object highlight when present).
    if op.ref_polys:
        tris = _selected_face_tris_world(op, op.ref_polys)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)

    # Marked target polys (current edit set).
    if op.target_polys:
        tris = _selected_face_tris_world(op, op.target_polys)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_TARGET_SEL, context=context)

    # Match hints — A-key candidates.
    if op.show_match_hints and op.match_hints:
        hint_store = {obj: set().union(*comps) for obj, comps in op.match_hints.items()}
        tris = _selected_face_tris_world(op, hint_store)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_MATCH_HINT, context=context)

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

    def _mode_label():
        return {
            MODE_PICK_REF: "Pick reference",
            MODE_STAMP: "Stamp",
            MODE_PICK_REF_POLY: "Pick ref polys",
            MODE_PICK_TGT_POLY: "Pick target polys",
        }.get(op.mode, op.mode)

    hud.add_param(HUDParam("Mode", _mode_label))
    hud.add_param(HUDParam("Reference", lambda: op.ref_name or "—",
                           visible_getter=lambda: bool(op.ref_name)))
    hud.add_param(HUDParam("Ref polys",
                           lambda: sum(len(s) for s in op.ref_polys.values()),
                           kind="int",
                           visible_getter=lambda: bool(op.ref_polys)))
    hud.add_param(HUDParam("Target polys",
                           lambda: sum(len(s) for s in op.target_polys.values()),
                           kind="int",
                           visible_getter=lambda: bool(op.target_polys)))
    hud.add_param(HUDParam("Match ε",
                           lambda: op.match_rmse_threshold,
                           kind="float", fmt="{:.3f}",
                           visible_getter=lambda: op.mode == MODE_PICK_TGT_POLY))
    hud.add_param(HUDParam("Force fit",
                           lambda: "on" if op.force_mode else "off",
                           visible_getter=lambda: op.mode == MODE_PICK_TGT_POLY))
    hud.add_param(HUDParam("Mirror match",
                           lambda: "on" if op.mirror_mode else "off",
                           visible_getter=lambda: op.mode == MODE_PICK_TGT_POLY))
    hud.add_param(HUDParam("Mirror bake",
                           lambda: "on" if op.apply_mirror_bake else "off",
                           visible_getter=lambda: op.mode == MODE_PICK_TGT_POLY))
    hud.add_param(HUDParam("Clone", lambda: op.clone_mode))
    hud.add_param(HUDParam("Scale", lambda: SCALE_LABELS.get(op.scale_mode, op.scale_mode)))
    hud.add_param(HUDParam("Fit", lambda: op.last_fit or "—",
                           visible_getter=lambda: bool(op.last_fit)))
    hud.add_param(HUDParam("Stamped", lambda: op.stamped_count, kind="int"))
    hud.add_param(HUDParam("Rig hidden",
                           lambda: "yes" if op.rig_hidden else "no",
                           visible_getter=lambda: op.rig_hidden))
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_aligner")
    helpo.add_section(HUDSection("Object Aligner", [
        HUDItem("Pick reference / target", "LMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Re-pick reference",       "R",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle ref-poly mode",    "Q",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Add linked island",       "Shift+LMB",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Add similar (normal/area)", "Ctrl+LMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Remove polygon / island", "Alt+LMB",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle rig visibility",   "X",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle match hints",      "M",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle force fit",        "W",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle mirror match",     "F",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle mirror bake",      "A",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Adjust match threshold",  "Alt+Wheel",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
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

        # Polygon-reference mode state.
        self.ref_polys = {}                    # dict[obj_original -> set[face_idx]]
        self.target_polys = {}                 # dict[obj_original -> set[face_idx]]
        self.ref_signature = None
        self.ref_points_np = None              # Nx3 world
        self.ref_pca_ratios = None
        self.ref_d2 = None
        self.ref_frame_np = None               # 4x4 numpy
        self.ref_bbox_diag = 0.0
        self.match_hints = {}                  # dict[obj_original -> list[set[face_idx]]]
        self.show_match_hints = False
        self.force_mode = False
        self.match_rmse_threshold = 0.05
        self.mirror_mode = False         # F: enable reflection-Procrustes in strict-tier
        self.apply_mirror_bake = False   # A: bake mirror via transform_apply + flip normals on stamp
        self._bmesh_cache = {}
        self._eval_mesh_cache = {}             # dict[obj_original -> evaluated Mesh]
        self._eval_mesh_owners = []            # eval objs holding the meshes alive
        self.rig_hidden = False                # X: rig (source_objs) hidden in viewport

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
        for bm in getattr(self, "_bmesh_cache", {}).values():
            try:
                bm.free()
            except (ReferenceError, RuntimeError):
                pass
        self._bmesh_cache = {}

        for eval_obj in getattr(self, "_eval_mesh_owners", []):
            try:
                eval_obj.to_mesh_clear()
            except (ReferenceError, RuntimeError):
                pass
        self._eval_mesh_owners = []
        self._eval_mesh_cache = {}

        if getattr(self, "rig_hidden", False):
            for ob in getattr(self, "source_objs", []):
                try:
                    ob.hide_viewport = False
                except ReferenceError:
                    pass
            self.rig_hidden = False

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
            if self.mode == MODE_PICK_TGT_POLY:
                m, f, mi, s = self._enqueue_target_poly_stamps(context)
                self._realize_pending(context)
                self._finish(context)
                self.report({"INFO"},
                            f"Aligner: {m} match + {mi} mirror + {f} forced ({s} skipped)")
                return {"FINISHED"}
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
            if event.type == "Q":
                if self.mode == MODE_STAMP and self.ref_obj is not None:
                    self.mode = MODE_PICK_REF_POLY
                    return {"RUNNING_MODAL"}
                if self.mode == MODE_PICK_REF_POLY:
                    if not self.ref_polys:
                        self.report({"WARNING"}, "Ref poly set is empty")
                        return {"RUNNING_MODAL"}
                    self._commit_ref_polys(context)
                    self.mode = MODE_PICK_TGT_POLY
                    return {"RUNNING_MODAL"}
                return {"RUNNING_MODAL"}
            if event.type == "M":
                if self.mode != MODE_PICK_TGT_POLY or self.ref_signature is None:
                    return {"RUNNING_MODAL"}
                if self.show_match_hints:
                    self.show_match_hints = False
                    self.match_hints = {}
                else:
                    self._search_matches(context)
                    self.show_match_hints = True
                return {"RUNNING_MODAL"}
            if event.type == "W":
                if self.mode == MODE_PICK_TGT_POLY:
                    self.force_mode = not self.force_mode
                return {"RUNNING_MODAL"}
            if event.type == "F":
                if self.mode == MODE_PICK_TGT_POLY:
                    self.mirror_mode = not self.mirror_mode
                return {"RUNNING_MODAL"}
            if event.type == "A":
                if self.mode == MODE_PICK_TGT_POLY:
                    self.apply_mirror_bake = not self.apply_mirror_bake
                return {"RUNNING_MODAL"}
            if event.type == "X":
                # Toggle visibility of the pre-selected rig (source_objs) so
                # it stops blocking picks. Always restored in _finish.
                self.rig_hidden = not self.rig_hidden
                for ob in self.source_objs:
                    try:
                        ob.hide_viewport = self.rig_hidden
                    except ReferenceError:
                        pass
                return {"RUNNING_MODAL"}
            if event.alt and event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
                if self.mode != MODE_PICK_TGT_POLY:
                    return {"PASS_THROUGH"}
                step = 0.005
                if event.type == "WHEELUPMOUSE":
                    self.match_rmse_threshold = min(0.5, self.match_rmse_threshold + step)
                else:
                    self.match_rmse_threshold = max(0.001, self.match_rmse_threshold - step)
                return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE":
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self.mode in (MODE_PICK_REF_POLY, MODE_PICK_TGT_POLY):
                obj, face_idx = self._pick_face(context, event)
                if obj is None:
                    return {"RUNNING_MODAL"}
                store = self.ref_polys if self.mode == MODE_PICK_REF_POLY else self.target_polys
                if event.alt:
                    if face_idx in store.get(obj, set()):
                        self._toggle_face(store, obj, face_idx)
                    else:
                        self._remove_island(store, obj, face_idx)
                elif event.shift:
                    self._add_island(store, obj, face_idx)
                elif event.ctrl:
                    self._add_similar(store, obj, face_idx)
                else:
                    self._toggle_face(store, obj, face_idx)
                return {"RUNNING_MODAL"}
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

    def _pick_face(self, context, event):
        """Raycast under the mouse, return (obj.original, face_index) or
        (None, -1). Excludes rig only — ref object is allowed to be re-picked
        in poly modes (per spec: ref-set may live anywhere except rig)."""
        from ..utils.picking import raycast_from_mouse
        hit, _loc, _n, face_idx, obj, _mx = raycast_from_mouse(
            context, _mouse_coord(event), exclude=set(self.source_set))
        if not hit or obj is None:
            return None, -1
        original = obj.original
        if original.type != "MESH" or original.data is None:
            return None, -1
        if not original.visible_get():
            return None, -1
        eval_mesh = _evaluated_mesh_for(self, original)
        if face_idx >= len(eval_mesh.polygons):
            return None, -1
        return original, int(face_idx)

    def _toggle_face(self, store: dict, obj, face_idx: int):
        """Toggle a single face in either self.ref_polys or self.target_polys."""
        s = store.setdefault(obj, set())
        if face_idx in s:
            s.discard(face_idx)
            if not s:
                store.pop(obj, None)
        else:
            s.add(face_idx)

    def _add_island(self, store: dict, obj, face_idx: int):
        from ..utils.polygon_match import face_island
        bm = _bmesh_for(self, obj)
        store.setdefault(obj, set()).update(face_island(bm, face_idx))

    def _add_similar(self, store: dict, obj, face_idx: int):
        from ..utils.polygon_match import similar_by_normal_area
        bm = _bmesh_for(self, obj)
        store.setdefault(obj, set()).update(similar_by_normal_area(bm, face_idx))

    def _remove_island(self, store: dict, obj, face_idx: int):
        from ..utils.polygon_match import face_island
        bm = _bmesh_for(self, obj)
        island = face_island(bm, face_idx)
        s = store.get(obj)
        if s is None:
            return
        s.difference_update(island)
        if not s:
            store.pop(obj, None)

    def _commit_ref_polys(self, context):
        """Snapshot all derived data for the ref poly set at commit time so
        target-side matching is cheap during mouse-move."""
        from ..utils import polygon_match as pm

        verts_all, faces_all = [], []
        face_centroids, face_normals, face_areas = [], [], []
        for obj, face_idx_set in self.ref_polys.items():
            mesh = _evaluated_mesh_for(self, obj)
            mw_np = np.array(obj.matrix_world)
            local_index = {}
            for fi in face_idx_set:
                poly = mesh.polygons[fi]
                f_local = []
                for vi in poly.vertices:
                    if vi not in local_index:
                        co = mesh.vertices[vi].co
                        h = np.array([co.x, co.y, co.z, 1.0]) @ mw_np.T
                        local_index[vi] = len(verts_all)
                        verts_all.append(h[:3])
                    f_local.append(local_index[vi])
                faces_all.append(f_local)
                ws = np.array([verts_all[i] for i in f_local])
                face_centroids.append(ws.mean(axis=0))
                n_local = np.array([poly.normal.x, poly.normal.y, poly.normal.z])
                n_world = mw_np[:3, :3] @ n_local
                nrm = np.linalg.norm(n_world)
                face_normals.append(n_world / nrm if nrm > 0 else np.array([0.0, 0.0, 1.0]))
                face_areas.append(float(poly.area))

        self.ref_points_np = np.asarray(verts_all, dtype=np.float64)
        sig = pm.signature(self.ref_points_np, faces_all)
        self.ref_signature = sig
        self.ref_bbox_diag = sig.bbox_diag
        self.ref_pca_ratios = pm.pca_ratios(self.ref_points_np)
        self.ref_d2 = pm.d2_histogram(self.ref_points_np, faces_all)
        self.ref_frame_np = pm.pca_frame(
            self.ref_points_np,
            np.asarray(face_centroids),
            np.asarray(face_normals),
            np.asarray(face_areas),
        )

    def _search_matches(self, context):
        """Loose-tier similarity scan over all non-rig objects in the scene.
        Populates self.match_hints[obj] with lists of face-index sets, one per
        candidate component. Used only for visual hints — does not auto-select."""
        from ..utils import polygon_match as pm
        self.match_hints = {}
        if self.ref_signature is None:
            return
        loose_ratio_tol = 0.10
        loose_d2_chi2 = 0.05
        for obj in context.scene.objects:
            if obj in self.source_set or obj.type != "MESH" or obj.data is None:
                continue
            if not obj.visible_get():
                continue
            original = obj.original
            try:
                bm = _bmesh_for(self, original)
            except (RuntimeError, ReferenceError):
                continue
            all_face_set = {f.index for f in bm.faces}
            comps = pm.components_in_selection(bm, all_face_set)
            mw_np = np.array(obj.matrix_world)
            kept = []
            for comp in comps:
                verts_world, faces_local = self._extract_component_verts(
                    original, comp, mw_np)
                if verts_world.shape[0] == 0:
                    continue
                ratios = pm.pca_ratios(verts_world)
                ratio_dist = sum(abs(a - b) for a, b in zip(ratios, self.ref_pca_ratios))
                if ratio_dist > loose_ratio_tol:
                    continue
                d2 = pm.d2_histogram(verts_world, faces_local)
                chi2 = float(np.sum((d2 - self.ref_d2) ** 2 / np.maximum(d2 + self.ref_d2, 1e-9)))
                if chi2 > loose_d2_chi2:
                    continue
                kept.append(comp)
            if kept:
                self.match_hints[original] = kept

    def _extract_component_verts(self, obj, face_idx_set, mw_np):
        """Helper: world-space verts (Nx3) and local face index lists for the
        union of the given face set on `obj`. Returns (verts, faces)."""
        mesh = _evaluated_mesh_for(self, obj)
        local_index = {}
        verts = []
        faces = []
        for fi in face_idx_set:
            if fi < 0 or fi >= len(mesh.polygons):
                continue
            poly = mesh.polygons[fi]
            f_local = []
            for vi in poly.vertices:
                if vi not in local_index:
                    co = mesh.vertices[vi].co
                    h = np.array([co.x, co.y, co.z, 1.0]) @ mw_np.T
                    local_index[vi] = len(verts)
                    verts.append(h[:3])
                f_local.append(local_index[vi])
            faces.append(f_local)
        return np.asarray(verts, dtype=np.float64) if verts else np.zeros((0, 3)), faces

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

    def _compute_fit_poly_strict(self, target_obj, component_face_idx_set):
        """Try Procrustes (no reflection) on ref points → component points.

        Returns (T_matrix, rmse, ok, is_mirror) where:
        - ok=True iff strict-tier criteria all pass AND RMSE/diag < self.match_rmse_threshold.
        - is_mirror=True iff non-reflection Procrustes failed but reflection-allowed
          Procrustes produced an acceptable RMSE (requires self.mirror_mode).
        T_matrix is None when neither path passes.
        """
        from ..utils import polygon_match as pm

        mw_np = np.array(target_obj.matrix_world)
        tgt_verts, tgt_faces = self._extract_component_verts(
            target_obj, component_face_idx_set, mw_np)
        tgt_sig = pm.signature(tgt_verts, tgt_faces)
        ref_sig = self.ref_signature
        if (tgt_sig.vert_count != ref_sig.vert_count
                or tgt_sig.face_count != ref_sig.face_count
                or tgt_sig.face_vcount_hist != ref_sig.face_vcount_hist):
            return None, float("inf"), False, False

        corr = pm.greedy_correspondence(self.ref_points_np, tgt_verts)
        tgt_reordered = tgt_verts[corr]
        denom = ref_sig.bbox_diag if ref_sig.bbox_diag > 1e-9 else 1.0

        T_np, rmse = pm.kabsch_with_scale(
            self.ref_points_np, tgt_reordered, scale_mode=self.scale_mode)
        if rmse / denom < self.match_rmse_threshold:
            return _np_to_matrix(T_np), rmse, True, False

        # Non-reflection Procrustes failed. Try mirror if enabled.
        # Re-run greedy_correspondence on a centroid-reflected copy so the
        # PCA pre-alignment inside greedy_correspondence can orient a chiral
        # shape correctly before the mirror Kabsch fit.
        if self.mirror_mode:
            tgt_c = tgt_verts.mean(axis=0)
            tgt_reflected = tgt_verts.copy()
            tgt_reflected[:, 0] = 2.0 * tgt_c[0] - tgt_verts[:, 0]
            corr_m = pm.greedy_correspondence(self.ref_points_np, tgt_reflected)
            tgt_reordered_m = tgt_verts[corr_m]
            T_m, rmse_m = pm.kabsch_mirror_with_scale(
                self.ref_points_np, tgt_reordered_m, scale_mode=self.scale_mode)
            if rmse_m / denom < self.match_rmse_threshold:
                return _np_to_matrix(T_m), rmse_m, True, True

        return None, rmse, False, False

    def _compute_fit_poly_force(self, target_obj, component_face_idx_set):
        """PCA-frame fit: T = frame_target · frame_ref⁻¹."""
        from ..utils import polygon_match as pm

        mw_np = np.array(target_obj.matrix_world)
        mesh = _evaluated_mesh_for(self, target_obj)
        face_centroids, face_normals, face_areas = [], [], []
        verts_world, _ = self._extract_component_verts(
            target_obj, component_face_idx_set, mw_np)
        for fi in component_face_idx_set:
            if fi < 0 or fi >= len(mesh.polygons):
                continue
            poly = mesh.polygons[fi]
            n_local = np.array([poly.normal.x, poly.normal.y, poly.normal.z])
            n_world = mw_np[:3, :3] @ n_local
            nrm = np.linalg.norm(n_world)
            face_normals.append(n_world / nrm if nrm > 0 else np.array([0.0, 0.0, 1.0]))
            face_areas.append(float(poly.area))
            ws_centroid = np.array([0.0, 0.0, 0.0])
            for vi in poly.vertices:
                co = mesh.vertices[vi].co
                h = np.array([co.x, co.y, co.z, 1.0]) @ mw_np.T
                ws_centroid += h[:3]
            ws_centroid /= len(poly.vertices)
            face_centroids.append(ws_centroid)
        tgt_frame = pm.pca_frame(
            verts_world,
            np.asarray(face_centroids),
            np.asarray(face_normals),
            np.asarray(face_areas),
        )
        T_np = tgt_frame @ np.linalg.inv(self.ref_frame_np)
        return _np_to_matrix(T_np)

    def _enqueue_target_poly_stamps(self, context):
        """Decompose self.target_polys per-object into connected components,
        compute a fit for each, append to self.pending. Returns
        (matched, forced, mirrored, skipped) counts for reporting.

        - strict pass → pending entry, last_fit="poly-strict"
        - mirror pass (only when self.mirror_mode) → pending entry with mirror=True,
          last_fit="poly-mirror"
        - else if self.force_mode → PCA-frame fallback, last_fit="poly-force"
        - else → skip
        """
        from ..utils import polygon_match as pm

        matched = forced = mirrored = skipped = 0
        for obj, face_idx_set in self.target_polys.items():
            try:
                bm = _bmesh_for(self, obj)
            except (RuntimeError, ReferenceError):
                skipped += 1
                continue
            comps = pm.components_in_selection(bm, face_idx_set)
            for comp in comps:
                T_strict, _rmse, ok, is_mirror = self._compute_fit_poly_strict(obj, comp)
                if ok:
                    self.pending.append({
                        "target": obj,
                        "matrix": T_strict,
                        "linked": self.clone_mode == CLONE_INST,
                        "mirror": is_mirror,
                    })
                    self.last_fit = "poly-mirror" if is_mirror else "poly-strict"
                    self.stamped_count += 1
                    if is_mirror:
                        mirrored += 1
                    else:
                        matched += 1
                    continue
                if self.force_mode:
                    T_force = self._compute_fit_poly_force(obj, comp)
                    self.pending.append({
                        "target": obj,
                        "matrix": T_force,
                        "linked": self.clone_mode == CLONE_INST,
                        "mirror": False,
                    })
                    self.last_fit = "poly-force"
                    self.stamped_count += 1
                    forced += 1
                else:
                    skipped += 1
        return matched, forced, mirrored, skipped

    def _bake_mirror_objs(self, context, objs):
        """For each mesh object in `objs`, apply location/rotation/scale and
        reverse polygon winding (so the mirror's flipped normals come out
        correct). Skips non-mesh and linked mesh datablocks."""
        # Use a fresh override context so transform_apply works regardless of
        # the user's selection state.
        meshes_to_flip = []
        # Snapshot active/selection to restore later.
        view_layer = context.view_layer
        prev_active = view_layer.objects.active
        prev_selected = [o for o in context.selected_objects]
        try:
            bpy.ops.object.select_all(action="DESELECT")
            for ob in objs:
                if ob.type != "MESH" or ob.data is None:
                    continue
                if ob.data.library is not None:
                    continue
                ob.select_set(True)
                view_layer.objects.active = ob
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
                ob.select_set(False)
                meshes_to_flip.append(ob.data)
        finally:
            bpy.ops.object.select_all(action="DESELECT")
            for ob in prev_selected:
                try:
                    ob.select_set(True)
                except ReferenceError:
                    pass
            if prev_active is not None:
                try:
                    view_layer.objects.active = prev_active
                except ReferenceError:
                    pass

        # Reverse winding on each unique mesh datablock.
        seen = set()
        for mesh in meshes_to_flip:
            if mesh.name in seen:
                continue
            seen.add(mesh.name)
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                for f in bm.faces:
                    f.normal_flip()
                bm.to_mesh(mesh)
                mesh.update()
            finally:
                bm.free()

    def _realize_pending(self, context):
        """Create the real objects for every committed pick. Only iterate
        top-level roots (objects whose parent is not itself selected) — child
        subtrees are duplicated recursively by _duplicate_obj, so iterating
        every selected object would double-stamp parented rigs.

        When a pending entry is a mirror stamp and `self.apply_mirror_bake` is
        on, apply transforms + reverse winding on the duplicates after
        placement so the negative-determinant matrix is baked into geometry."""
        roots = [o for o in self.source_objs if o.parent not in self.source_set]
        for pend in self.pending:
            obj, t_matrix, linked = pend["target"], pend["matrix"], pend["linked"]
            is_mirror = pend.get("mirror", False)
            for src in roots:
                sub = _target_subcollection(self, src, obj)
                world_matrix = t_matrix @ src.matrix_world
                created = _duplicate_obj(src, world_matrix, sub, linked)
                self.stamped_objs.extend(created)
                if is_mirror and self.apply_mirror_bake:
                    self._bake_mirror_objs(context, created)
