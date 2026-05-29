import bpy
import bmesh
import numpy as np
from contextlib import contextmanager
from mathutils import Matrix, Vector

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as iops_draw
from ..ui.draw import draw_scope
from ..ui.draw.theme import Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState, capture_event,
)
from ..utils.alignment_fit import solve_fit


# --- State enums ----------------------------------------------------------

MODE_PICK_REF      = "PICK_REF"           # Q: click to set ref object
MODE_PICK_TGT_OBJS = "PICK_TGT_OBJS"      # W: click to add/remove target objects
MODE_PICK_REF_POLY = "PICK_REF_POLY"      # E: marking ref polys; E again commits + searches
MODE_PICK_TGT_POLY = "PICK_TGT_POLY"      # after commit: click hint components to skip/keep

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
    Reads the **evaluated** mesh so modifiers (Array/Mirror/SubD/etc.) are
    included in the highlight."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mw = obj.matrix_world
    with _eval_mesh(obj) as mesh:
        if not mesh.loop_triangles:
            try:
                mesh.calc_loop_triangles()
            except RuntimeError:
                return []
        verts = [mw @ v.co for v in mesh.vertices]
        loops = mesh.loops
        out = []
        for lt in mesh.loop_triangles:
            out.append(verts[loops[lt.loops[0]].vertex_index])
            out.append(verts[loops[lt.loops[1]].vertex_index])
            out.append(verts[loops[lt.loops[2]].vertex_index])
    return out


def _mesh_edges_world(obj, world_matrix):
    """Flat list of world-space edge endpoints for `obj`'s evaluated mesh
    transformed by `world_matrix`. [] if not a mesh."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    with _eval_mesh(obj) as mesh:
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
    with _eval_mesh(obj) as mesh:
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


@contextmanager
def _eval_mesh(obj):
    """Yield the evaluated (modifier-applied) Mesh datablock for `obj` and
    free it on exit. Use inside a `with` block — do NOT cache the returned
    Mesh across yields, the datablock is invalidated when the depsgraph
    re-evaluates."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.original.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    try:
        yield eval_mesh
    finally:
        try:
            eval_obj.to_mesh_clear()
        except (ReferenceError, RuntimeError):
            pass


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
    `collection`. Root placed at `world_matrix`. Returns the list of new objs.

    Clones inherit ALL properties from `src` via `.copy()` — including
    `hide_viewport` if the rig was X-toggled to hidden. Force visibility on
    every clone so freshly-stamped objects are actually drawn."""
    new_root = src.copy()
    if not linked and src.type == "MESH" and src.data and src.data.library is None:
        new_root.data = src.data.copy()
    new_root.parent = None
    new_root.hide_viewport = False
    new_root.hide_set(False)
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
            new_ob.hide_viewport = False
            collection.objects.link(new_ob)
            new_ob.hide_set(False)
            created.append(new_ob)
            _dup_children(child, new_ob)

    _dup_children(src, new_root)
    return created


def _is_instancer(obj):
    return (obj is not None
            and obj.type == "EMPTY"
            and obj.instance_collection is not None)


def _instancer_geom(op, collection):
    """Cached list of (inner_local_matrix, tris_local, edges_local) for every
    mesh in `collection.all_objects`. inner_local_matrix accounts for
    `collection.instance_offset`, so multiplying by an instancer EMPTY's
    matrix_world reproduces the same placement the depsgraph dupli shows.
    Built once per collection per modal session — collections don't move
    during a pick session, so per-frame `to_mesh` is avoided."""
    cache = op._collection_geom_cache
    cached = cache.get(collection)
    if cached is not None:
        return cached
    offset = Matrix.Translation(-collection.instance_offset)
    entries = []
    for inner in collection.all_objects:
        if inner.type != "MESH" or inner.data is None:
            continue
        inner_mat = offset @ inner.matrix_world
        with _eval_mesh(inner) as mesh:
            if not mesh.loop_triangles:
                try:
                    mesh.calc_loop_triangles()
                except RuntimeError:
                    continue
            verts = [v.co.copy() for v in mesh.vertices]
            loops = mesh.loops
            tris_local = []
            for lt in mesh.loop_triangles:
                tris_local.append(verts[loops[lt.loops[0]].vertex_index])
                tris_local.append(verts[loops[lt.loops[1]].vertex_index])
                tris_local.append(verts[loops[lt.loops[2]].vertex_index])
            edges_local = []
            for e in mesh.edges:
                edges_local.append(verts[e.vertices[0]])
                edges_local.append(verts[e.vertices[1]])
        entries.append((inner_mat, tris_local, edges_local))
    cache[collection] = entries
    return entries


def _instancer_tris_world(op, empty, world_matrix=None):
    """World-space triangles for an EMPTY-instancer's collection contents.
    `world_matrix` overrides empty.matrix_world (used for ghost preview at a
    candidate placement)."""
    coll = empty.instance_collection
    if coll is None:
        return []
    em = world_matrix if world_matrix is not None else empty.matrix_world
    out = []
    for inner_mat, tris_local, _edges in _instancer_geom(op, coll):
        M = em @ inner_mat
        out.extend(M @ v for v in tris_local)
    return out


def _instancer_edges_world(op, empty, world_matrix=None):
    coll = empty.instance_collection
    if coll is None:
        return []
    em = world_matrix if world_matrix is not None else empty.matrix_world
    out = []
    for inner_mat, _tris, edges_local in _instancer_geom(op, coll):
        M = em @ inner_mat
        out.extend(M @ v for v in edges_local)
    return out


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
            with _eval_mesh(obj) as mesh:
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
        if _is_instancer(src):
            ghost_tris.extend(_instancer_tris_world(op, src, placement))
            ghost_edges.extend(_instancer_edges_world(op, src, placement))
        else:
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

    def _draw_obj_fill(obj, role):
        if obj is None:
            return
        try:
            if _is_instancer(obj):
                tris = _instancer_tris_world(op, obj)
            else:
                tris = _mesh_tris_world(obj)
        except ReferenceError:
            return
        if not tris:
            return
        tris = _bias_toward_view(tris, rv3d)
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(tris, role=role, context=context)

    # Whole-object highlights per mode:
    #   PICK_REF        — ref ACTIVE only.
    #   PICK_TGT_OBJS   — ref ACTIVE (bright), targets PREVIEW (faded).
    #   PICK_REF_POLY   — ref + targets all PREVIEW (ref reads as just
    #                     another target). Marked ref polys are layered on
    #                     top with ACTIVE color so the selection pops.
    #   PICK_TGT_POLY   — same as REF_POLY (visual context for hint clicks).
    if op.ref_obj is not None and not op.ref_polys:
        ref_role = (Role.GHOST_ACTIVE
                    if op.mode in (MODE_PICK_REF, MODE_PICK_TGT_OBJS)
                    else Role.GHOST_CLOSEST)
        _draw_obj_fill(op.ref_obj, ref_role)
    if op.mode in (MODE_PICK_TGT_OBJS, MODE_PICK_REF_POLY, MODE_PICK_TGT_POLY):
        for tgt in op.target_objs:
            if tgt is op.ref_obj:
                continue
            _draw_obj_fill(tgt, Role.GHOST_CLOSEST)

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

    # Hover poly preview in poly modes — closest-surface highlight.
    if op.mode in (MODE_PICK_REF_POLY, MODE_PICK_TGT_POLY) \
            and op.hover_obj is not None and op.hover_face_idx >= 0:
        hover_store = {op.hover_obj: {op.hover_face_idx}}
        tris = _selected_face_tris_world(op, hover_store)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_CLOSEST, context=context)

    # Match hints — auto-found candidates the user has skipped (clicked off
    # or inverted with C). Drawn with GHOST_LOCKED (amber) so they read as
    # "available but disabled" — click to re-enable.
    if op.mode == MODE_PICK_TGT_POLY and op.match_hints:
        skipped_store = {}
        for obj, comps in op.match_hints.items():
            sel = op.target_polys.get(obj, set())
            skipped = set().union(*(c for c in comps if not (c & sel)))
            if skipped:
                skipped_store[obj] = skipped
        tris = _selected_face_tris_world(op, skipped_store)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_LOCKED, context=context)

    # Committed picks — rig ghost at each stored placement (preview only).
    for pend in op.pending:
        _draw_rig_ghost(op, context, pend["matrix"], role=Role.GHOST_PREVIEW)

    # Object-mode preview: in PICK_TGT_OBJS draw a rig-ghost at every chosen
    # target so the user sees where Enter will stamp clones.
    if op.mode == MODE_PICK_TGT_OBJS and op.ref_obj is not None:
        for tgt in op.target_objs:
            if tgt is op.ref_obj:
                continue
            try:
                t_matrix, _fit_kind = _compute_fit(op, tgt)
            except (ReferenceError, ValueError):
                continue
            _draw_rig_ghost(op, context, t_matrix, role=Role.GHOST_PREVIEW)

    # Auto-hint placements — rig ghost at each component the user kept in
    # target_polys. Skipped components are hidden until the user clicks them
    # back in.
    if op.mode == MODE_PICK_TGT_POLY and op.hint_fits:
        for obj, fits in op.hint_fits.items():
            sel = op.target_polys.get(obj, set())
            if not sel:
                continue
            for comp, t_matrix, _is_mirror in fits:
                if comp <= sel:
                    _draw_rig_ghost(op, context, t_matrix, role=Role.GHOST_PREVIEW)

# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context, op):
    hud = HUDOverlay("object_aligner")
    hud.title = "Object Aligner"
    hud.bind_region(context.region)

    def _mode_label():
        return {
            MODE_PICK_REF: "Pick reference",
            MODE_PICK_TGT_OBJS: "Pick targets",
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
    hud.add_param(HUDParam("Targets",
                           lambda: len(op.target_objs),
                           kind="int",
                           visible_getter=lambda: bool(op.target_objs)))
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
        HUDItem("Pick / toggle (LMB)",     "LMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Pick ref object",         "Q",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Pick target objects",     "W",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Ref-poly mode / commit",  "E",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reset to start",          "R",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle rig visibility",   "X",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Skip all matches",        "C",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Invert match selection",  "I",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
        # Pierce-set for raycast: source rig + inner objects of any source
        # EMPTY-instancer (clicking through dupli geometry of the source must
        # not register as picking the source itself).
        self.source_excluded = set(self.source_set)
        for src in sel:
            if _is_instancer(src):
                for inner in src.instance_collection.all_objects:
                    self.source_excluded.add(inner)
        self._collection_geom_cache = {}
        self.instancer_cache = self._build_instancer_cache(context)
        self.mode = MODE_PICK_REF
        self.clone_mode = CLONE_DUP
        self.scale_mode = SCALE_UNIFORM
        self.ref_obj = None
        self.ref_name = ""
        self.ref_world_np = None
        self.hover_obj = None
        self.hover_face_idx = -1
        self.last_fit = ""
        self.stamped_count = 0
        self.stamped_objs = []
        self.pending = []
        self.created_collections = []
        self._last_event = None

        # Target objects — explicit user-selected subset of the scene that the
        # pattern search scans (Q/W workflow). Without this the search would
        # iterate every visible mesh and become unusably slow on big scenes.
        self.target_objs = set()

        # Polygon-reference mode state.
        self.ref_polys = {}
        self.target_polys = {}
        self.ref_signature = None
        self.ref_points_np = None
        self.ref_pca_ratios = None
        self.ref_d2 = None
        self.ref_frame_np = None
        self.ref_bbox_diag = 0.0
        self.match_hints = {}
        self.match_orders = {}
        self.match_mirrors = {}
        self.ref_pattern_anchors = None
        self.ref_anchor_offset = 1.0
        self.hint_fits = {}
        self.force_mode = True
        self._bmesh_cache = {}
        self.rig_hidden = False

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
            self._enqueue_target_obj_stamps(context)
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
            if event.type == "Q":
                self.mode = MODE_PICK_REF
                return {"RUNNING_MODAL"}
            if event.type == "W":
                self.mode = MODE_PICK_TGT_OBJS
                return {"RUNNING_MODAL"}
            if event.type == "E":
                if self.ref_obj is None:
                    self.report({"WARNING"}, "Pick a reference object first (Q)")
                    return {"RUNNING_MODAL"}
                if self.ref_obj.type != "MESH":
                    self.report({"WARNING"}, "Poly-pattern mode requires a mesh reference")
                    return {"RUNNING_MODAL"}
                if self.mode == MODE_PICK_REF_POLY:
                    if not self.ref_polys:
                        self.report({"WARNING"}, "Ref poly set is empty")
                        return {"RUNNING_MODAL"}
                    self._commit_ref_polys(context)
                    self._search_matches(context)
                    self.target_polys = {
                        obj: set().union(*comps)
                        for obj, comps in self.match_hints.items()
                    }
                    self._seed_hint_fits()
                    self.mode = MODE_PICK_TGT_POLY
                    self.report({"INFO"},
                                f"Found {sum(len(c) for c in self.match_hints.values())} "
                                f"match component(s) — click to skip/keep")
                    return {"RUNNING_MODAL"}
                self.mode = MODE_PICK_REF_POLY
                return {"RUNNING_MODAL"}
            if event.type == "R":
                # Full reset to the initial state — re-pick everything.
                self.ref_obj = None
                self.ref_name = ""
                self.ref_world_np = None
                self.target_objs = set()
                self.ref_polys = {}
                self.target_polys = {}
                self.match_hints = {}
                self.match_orders = {}
                self.match_mirrors = {}
                self.hint_fits = {}
                self.ref_signature = None
                self.ref_points_np = None
                self.ref_pca_ratios = None
                self.ref_d2 = None
                self.ref_frame_np = None
                self.ref_pattern_anchors = None
                self.pending = []
                self.stamped_count = 0
                self.mode = MODE_PICK_REF
                return {"RUNNING_MODAL"}
            if event.type == "C":
                if self.mode == MODE_PICK_TGT_POLY:
                    self.target_polys = {}
                return {"RUNNING_MODAL"}
            if event.type == "I":
                if self.mode == MODE_PICK_TGT_POLY:
                    for obj, comps in self.match_hints.items():
                        s = self.target_polys.setdefault(obj, set())
                        for comp in comps:
                            if comp & s:
                                s.difference_update(comp)
                            else:
                                s.update(comp)
                        if not s:
                            self.target_polys.pop(obj, None)
                return {"RUNNING_MODAL"}
            if event.type == "X":
                self.rig_hidden = not self.rig_hidden
                for ob in self.source_objs:
                    try:
                        ob.hide_viewport = self.rig_hidden
                    except ReferenceError:
                        pass
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

    def _build_instancer_cache(self, context):
        """Map inner_object_original -> [(instancer_empty_original, dupli_matrix), ...].
        Walked from depsgraph.object_instances once at invoke. The dupli matrix
        disambiguates when one collection is instanced by multiple EMPTYs."""
        deps = context.evaluated_depsgraph_get()
        cache = {}
        for inst in deps.object_instances:
            if not inst.is_instance:
                continue
            parent = inst.parent
            if parent is None:
                continue
            p_orig = parent.original
            if p_orig.type != "EMPTY" or p_orig.instance_collection is None:
                continue
            inner = inst.object.original
            cache.setdefault(inner, []).append((p_orig, inst.matrix_world.copy()))
        return cache

    def _resolve_instancer(self, inner_orig, dupli_matrix):
        """Given a raycast hit's original object + the hit's world matrix,
        return the instancer EMPTY that produced this dupli, or None."""
        candidates = self.instancer_cache.get(inner_orig)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][0]
        best = None
        best_d = float("inf")
        for empty, dupli_m in candidates:
            d = (dupli_matrix.translation - dupli_m.translation).length_squared
            if d < best_d:
                best_d = d
                best = empty
        return best

    def _pick(self, context, event):
        """Raycast under the mouse; pierce through the source rig (and any
        inner objects of source instance collections), resolve dupli hits to
        their instancer EMPTY. Returns the ORIGINAL hit object or None."""
        from bpy_extras.view3d_utils import (
            region_2d_to_vector_3d, region_2d_to_origin_3d)
        region = context.region
        rv3d = context.space_data.region_3d
        if rv3d is None:
            return None
        coord = _mouse_coord(event)
        view_vec = region_2d_to_vector_3d(region, rv3d, coord)
        origin = region_2d_to_origin_3d(region, rv3d, coord)
        deps = context.evaluated_depsgraph_get()
        sv = context.space_data
        viewport = sv if (sv is not None and sv.type == "VIEW_3D") else None
        step_dir = view_vec.normalized()
        cur = origin
        for _ in range(100):
            hit, loc, _n, _fi, obj, mx = context.scene.ray_cast(deps, cur, view_vec)
            if not hit or obj is None:
                return None
            orig = obj.original
            resolved = self._resolve_instancer(orig, mx) if mx is not None else None
            if resolved is None:
                resolved = orig
            blocked = resolved in self.source_excluded or orig in self.source_excluded
            try:
                visible = resolved.visible_get(viewport=viewport)
            except (ReferenceError, TypeError):
                visible = True
            if not blocked and visible:
                return resolved
            if loc is None:
                return None
            cur = loc + step_dir * 0.0001
        return None

    def _pick_face(self, context, event):
        """Raycast under the mouse, return (obj.original, face_index) or
        (None, -1). Excludes rig only — ref object is allowed to be re-picked
        in poly modes (per spec: ref-set may live anywhere except rig)."""
        from ..utils.picking import raycast_from_mouse
        hit, _loc, _n, face_idx, obj, _mx = raycast_from_mouse(
            context, _mouse_coord(event), exclude=set(self.source_set),
            visible_only=True)
        if not hit or obj is None:
            return None, -1
        original = obj.original
        if original.type != "MESH" or original.data is None:
            return None, -1
        with _eval_mesh(original) as eval_mesh:
            if face_idx >= len(eval_mesh.polygons):
                return None, -1
        return original, int(face_idx)

    def _toggle_hint_component(self, obj, face_idx: int):
        """Find the hint component containing `face_idx` on `obj` and toggle
        all of its faces in self.target_polys. No-op if the click landed on a
        face that wasn't part of any auto-found hint."""
        comps = self.match_hints.get(obj)
        if not comps:
            return
        comp = next((c for c in comps if face_idx in c), None)
        if comp is None:
            return
        s = self.target_polys.setdefault(obj, set())
        if comp & s:
            s.difference_update(comp)
            if not s:
                self.target_polys.pop(obj, None)
        else:
            s.update(comp)

    def _toggle_face(self, store: dict, obj, face_idx: int):
        """Toggle a single face in either self.ref_polys or self.target_polys."""
        s = store.setdefault(obj, set())
        if face_idx in s:
            s.discard(face_idx)
            if not s:
                store.pop(obj, None)
        else:
            s.add(face_idx)

    def _commit_ref_polys(self, context):
        """Snapshot all derived data for the ref poly set at commit time so
        target-side matching is cheap during mouse-move."""
        from ..utils import polygon_match as pm

        verts_all, faces_all = [], []
        face_centroids, face_normals, face_areas = [], [], []
        for obj, face_idx_set in self.ref_polys.items():
            with _eval_mesh(obj) as mesh:
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
        """Subgraph-isomorphism scan: find face subsets in every visible mesh
        whose face-adjacency + per-face attributes match the ref selection's
        pattern. Each match is further validated by PCA-ratio + d2-histogram
        similarity to the ref geometry. Populates self.match_hints (set form
        for membership/skip checks) and self.match_orders (ordered list form
        used by the face-correspondence procrustes fit)."""
        from ..utils import polygon_match as pm
        self.match_hints = {}
        self.match_orders = {}
        self.ref_pattern_anchors = None
        if self.ref_signature is None or not self.ref_polys:
            return
        ref_obj, ref_faces = next(iter(self.ref_polys.items()))
        try:
            ref_bm = _bmesh_for(self, ref_obj)
        except (RuntimeError, ReferenceError):
            return
        pattern = pm.build_face_pattern(ref_bm, ref_faces)
        if not pattern["faces"]:
            return
        # Constant anchor offset derived from the ref pattern's mean √area —
        # scales with the pattern's overall size but stays fixed across all
        # target matches (so anchor distance differences don't pollute rmse).
        mean_sqrt_area = float(np.mean([np.sqrt(max(a, 1e-12))
                                        for a in pattern["areas"]]))
        self.ref_anchor_offset = max(0.5 * mean_sqrt_area, 1e-6)
        # Reference anchors computed once in pattern.faces order so every match
        # can be Kabsch-fit against the same reference frame.
        self.ref_pattern_anchors = self._face_anchor_points(ref_obj, pattern["faces"])
        sv = getattr(context, "space_data", None)
        viewport = sv if (sv is not None and sv.type == "VIEW_3D") else None
        # Two-tier scan. Tier 0 is the tight pass; if nothing survives the
        # validation gate, tier 1 reruns with a wider area_tol on the pattern
        # search itself plus more permissive PCA/d2 caps. Tiny patterns (≤3
        # faces) skip the PCA+d2 gate entirely — those statistics are
        # degenerate for so few points and reject genuine matches.
        # Single-tier search: pattern matcher's adjacency + face attrs do the
        # topology gate, Kabsch fit_rmse does the geometry gate. PCA-ratio and
        # d2-histogram checks were dropped — both are noisy on small patterns
        # and Kabsch already gives a sharp, scale-stable signal.
        tier_specs = [
            {"area_tol": 0.20, "fit_rmse": 0.05},
            {"area_tol": 0.35, "fit_rmse": 0.15},
        ]
        ref_set = set(ref_faces)
        ref_bbox_diag = self.ref_signature.bbox_diag if self.ref_signature else 1.0
        ref_bbox_diag = ref_bbox_diag if ref_bbox_diag > 1e-9 else 1.0
        # Scan ref_obj + user-picked target objects. ref_obj is implicit (not
        # in target_objs so it can't be removed via target-click), but search
        # always includes it so its own copies of the pattern are also found.
        scan_objs = set(self.target_objs)
        if ref_obj is not None:
            scan_objs.add(ref_obj)
        for tier_idx, spec in enumerate(tier_specs):
            self.match_hints = {}
            self.match_orders = {}
            self.match_mirrors = {}
            n_objs = n_raw = n_rej_fit = n_kept = n_mirror = 0
            worst_fit = 1e9
            for obj in scan_objs:
                if obj in self.source_set or obj.type != "MESH" or obj.data is None:
                    continue
                if not obj.visible_get(viewport=viewport):
                    continue
                n_objs += 1
                original = obj.original
                try:
                    bm = _bmesh_for(self, original)
                except (RuntimeError, ReferenceError):
                    continue
                raw_matches = pm.find_pattern_matches(
                    bm, pattern, area_tol=spec["area_tol"], allow_overlap=True)
                n_raw += len(raw_matches)
                kept_sets: list[frozenset[int]] = []
                kept_orders: list[tuple[int, ...]] = []
                kept_mirrors: list[bool] = []
                for match in raw_matches:
                    if original is ref_obj and set(match) == ref_set:
                        continue
                    # Try both orientations — mirror detection is automatic.
                    tgt_anchors = self._face_anchor_points(original, match)
                    if tgt_anchors.shape != self.ref_pattern_anchors.shape:
                        n_rej_fit += 1
                        continue
                    _T_n, fit_rmse_n = pm.kabsch_with_scale(
                        self.ref_pattern_anchors, tgt_anchors, scale_mode=self.scale_mode)
                    _T_m, fit_rmse_m = pm.kabsch_mirror_with_scale(
                        self.ref_pattern_anchors, tgt_anchors, scale_mode=self.scale_mode)
                    rmse_rel_n = float(fit_rmse_n) / ref_bbox_diag
                    rmse_rel_m = float(fit_rmse_m) / ref_bbox_diag
                    is_mirror = rmse_rel_m < rmse_rel_n
                    rmse_rel = rmse_rel_m if is_mirror else rmse_rel_n
                    if rmse_rel > spec["fit_rmse"]:
                        n_rej_fit += 1
                        if rmse_rel < worst_fit:
                            worst_fit = rmse_rel
                        continue
                    kept_sets.append(frozenset(match))
                    kept_orders.append(tuple(match))
                    kept_mirrors.append(is_mirror)
                    n_kept += 1
                    if is_mirror:
                        n_mirror += 1
                if kept_sets:
                    self.match_hints[original] = kept_sets
                    self.match_orders[original] = kept_orders
                    self.match_mirrors[original] = kept_mirrors
            print(f"[aligner] search tier {tier_idx} (area={spec['area_tol']} "
                  f"fit_rmse={spec['fit_rmse']}): "
                  f"pattern_faces={len(pattern['faces'])} objs={n_objs} "
                  f"raw={n_raw} rej_fit={n_rej_fit} (best_rej={worst_fit:.4f}) "
                  f"kept={n_kept} (mirror={n_mirror}) hints={len(self.match_hints)}")
            if n_kept > 0:
                return

    def _extract_component_verts(self, obj, face_idx_set, mw_np):
        """Helper: world-space verts (Nx3) and local face index lists for the
        union of the given face set on `obj`. Returns (verts, faces)."""
        local_index = {}
        verts = []
        faces = []
        with _eval_mesh(obj) as mesh:
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
        if self.mode in (MODE_PICK_REF_POLY, MODE_PICK_TGT_POLY):
            obj, fi = self._pick_face(context, event)
            self.hover_obj = obj
            self.hover_face_idx = fi
        else:
            self.hover_obj = self._pick(context, event)
            self.hover_face_idx = -1

    def _on_click(self, context, event):
        """LMB dispatch per mode:
          PICK_REF       — set ref_obj (re-clickable to change).
          PICK_TGT_OBJS  — toggle clicked object in target_objs.
          PICK_REF_POLY  — toggle clicked face in ref_polys (ref_obj only).
          PICK_TGT_POLY  — toggle the hint component the clicked face belongs to.
        """
        if self.mode in (MODE_PICK_REF_POLY, MODE_PICK_TGT_POLY):
            obj, face_idx = self._pick_face(context, event)
            if obj is None:
                return {"RUNNING_MODAL"}
            if self.mode == MODE_PICK_REF_POLY:
                if obj is not self.ref_obj:
                    return {"RUNNING_MODAL"}
                self._toggle_face(self.ref_polys, obj, face_idx)
            else:
                self._toggle_hint_component(obj, face_idx)
            return {"RUNNING_MODAL"}
        obj = self._pick(context, event)
        if obj is None:
            return {"RUNNING_MODAL"}
        if self.mode == MODE_PICK_REF:
            self.ref_obj = obj
            self.ref_name = obj.name
            self.ref_world_np = _verts_world_np(obj) if obj.type == "MESH" else None
            # Auto-advance to target-pick: typical next step.
            self.mode = MODE_PICK_TGT_OBJS
            return {"RUNNING_MODAL"}
        if self.mode == MODE_PICK_TGT_OBJS:
            # Ref is implicitly included in the search — disallow toggling it
            # via target-click so target_objs only holds extra targets.
            if obj is self.ref_obj:
                return {"RUNNING_MODAL"}
            if obj in self.target_objs:
                self.target_objs.discard(obj)
            else:
                self.target_objs.add(obj)
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _compute_fit_poly_force(self, target_obj, component_face_idx_set):
        """PCA-frame fit: T = frame_target · frame_ref⁻¹."""
        from ..utils import polygon_match as pm

        mw_np = np.array(target_obj.matrix_world)
        face_centroids, face_normals, face_areas = [], [], []
        verts_world, _ = self._extract_component_verts(
            target_obj, component_face_idx_set, mw_np)
        with _eval_mesh(target_obj) as mesh:
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

    def _face_anchor_points(self, obj, ordered_face_list):
        """For each face index in `ordered_face_list`, emit two world-space
        points: the face centroid and centroid + ref_anchor_offset * normal.
        A *constant* offset (taken from the ref pattern's mean √area, stored
        as `self.ref_anchor_offset`) keeps target and ref anchors at the same
        relative distance — so Kabsch rmse reflects only rotation/translation
        mismatch, not per-face area variation within the matching tolerance."""
        mw_np = np.array(obj.matrix_world)
        rot_np = mw_np[:3, :3]
        offset = float(self.ref_anchor_offset)
        points = []
        with _eval_mesh(obj) as mesh:
            n_polys = len(mesh.polygons)
            for fi in ordered_face_list:
                if fi < 0 or fi >= n_polys:
                    continue
                poly = mesh.polygons[fi]
                cx = cy = cz = 0.0
                for vi in poly.vertices:
                    co = mesh.vertices[vi].co
                    cx += co.x
                    cy += co.y
                    cz += co.z
                inv = 1.0 / len(poly.vertices)
                c_local = np.array([cx * inv, cy * inv, cz * inv, 1.0])
                c_world = c_local @ mw_np.T
                n_local = np.array([poly.normal.x, poly.normal.y, poly.normal.z])
                n_world = rot_np @ n_local
                nrm = float(np.linalg.norm(n_world))
                n_world = n_world / nrm if nrm > 1e-9 else np.array([0.0, 0.0, 1.0])
                points.append(c_world[:3])
                points.append(c_world[:3] + n_world * offset)
        return np.asarray(points, dtype=np.float64)

    def _compute_fit_poly_pattern(self, target_obj, ordered_target_faces, mirror=False):
        """Face-correspondence procrustes between the ref pattern anchors and
        the target match anchors. Returns (Matrix, rmse) or (None, inf) when
        the anchor sets are inconsistent (e.g. a face was missing in the
        evaluated mesh)."""
        from ..utils import polygon_match as pm
        ref_pts = self.ref_pattern_anchors
        if ref_pts is None or len(ordered_target_faces) == 0:
            return None, float("inf")
        tgt_pts = self._face_anchor_points(target_obj, ordered_target_faces)
        if tgt_pts.shape != ref_pts.shape:
            return None, float("inf")
        if mirror:
            T_np, rmse = pm.kabsch_mirror_with_scale(
                ref_pts, tgt_pts, scale_mode=self.scale_mode)
        else:
            T_np, rmse = pm.kabsch_with_scale(
                ref_pts, tgt_pts, scale_mode=self.scale_mode)
        return _np_to_matrix(T_np), float(rmse)

    def _seed_hint_fits(self):
        """Precompute placement matrices for every auto-found hint using the
        mirror flag that the search already determined per match."""
        self.hint_fits = {}
        for obj, orders in self.match_orders.items():
            mirrors = self.match_mirrors.get(obj, [False] * len(orders))
            fits = []
            for comp_order, is_mirror in zip(orders, mirrors):
                comp_fs = frozenset(comp_order)
                t, _rmse = self._compute_fit_poly_pattern(
                    obj, comp_order, mirror=is_mirror)
                if t is not None:
                    fits.append((comp_fs, t, is_mirror))
            if fits:
                self.hint_fits[obj] = fits

    def _enqueue_target_obj_stamps(self, context):
        """Object-pick mode (W): compute fit per chosen target and enqueue
        placements. Matches the preview path (lines ~471-479) — ref is implicit
        in the search but is NOT a stamping target."""
        for tgt in self.target_objs:
            if tgt is self.ref_obj:
                continue
            try:
                t_matrix, fit_kind = _compute_fit(self, tgt)
            except (ReferenceError, ValueError):
                continue
            self.pending.append({
                "target": tgt,
                "matrix": t_matrix,
                "linked": self.clone_mode == CLONE_INST,
                "mirror": False,
            })
            self.last_fit = fit_kind
            self.stamped_count += 1

    def _enqueue_target_poly_stamps(self, context):
        """Stamp each kept match (auto-hint OR manual addition) using the
        face-correspondence procrustes fit. Auto-hints reuse their ordered
        face list directly (so adjacency-preserving correspondence is fed to
        the fit). Manual additions are decomposed by shared-edge connectivity
        and fit via PCA-frame (no face correspondence available)."""
        from ..utils import polygon_match as pm

        matched = forced = mirrored = skipped = 0
        for obj, face_idx_set in self.target_polys.items():
            try:
                bm = _bmesh_for(self, obj)
            except (RuntimeError, ReferenceError):
                skipped += 1
                continue
            # Iterate auto-hint components in order. The mirror flag was
            # already determined by the search (smallest-rmse orientation).
            orders = self.match_orders.get(obj, [])
            mirrors = self.match_mirrors.get(obj, [False] * len(orders))
            covered: set[int] = set()
            for comp_order, is_mirror in zip(orders, mirrors):
                comp_set = set(comp_order)
                if not comp_set <= face_idx_set:
                    continue
                covered.update(comp_set)
                pick_t, _rmse = self._compute_fit_poly_pattern(
                    obj, comp_order, mirror=is_mirror)
                if pick_t is None:
                    skipped += 1
                    continue
                self.pending.append({
                    "target": obj,
                    "matrix": pick_t,
                    "linked": self.clone_mode == CLONE_INST,
                    "mirror": is_mirror,
                })
                self.last_fit = "poly-mirror" if is_mirror else "poly-strict"
                self.stamped_count += 1
                if is_mirror:
                    mirrored += 1
                else:
                    matched += 1
            leftover = face_idx_set - covered
            if leftover:
                for comp in pm.components_in_selection(bm, leftover):
                    try:
                        T_force = self._compute_fit_poly_force(obj, comp)
                    except (ValueError, np.linalg.LinAlgError):
                        skipped += 1
                        continue
                    self.pending.append({
                        "target": obj,
                        "matrix": T_force,
                        "linked": self.clone_mode == CLONE_INST,
                        "mirror": False,
                    })
                    self.last_fit = "poly-force"
                    self.stamped_count += 1
                    forced += 1
        return matched, forced, mirrored, skipped

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
