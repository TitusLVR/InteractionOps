"""Bevel Edge Data Fix — restore seam/sharp/crease/bevel-weight (and optionally UVs)
destroyed by a Bevel modifier, by projecting them back onto the bevel center loop.

Workaround for https://projects.blender.org/blender/blender/issues/48583.
Requires bevel with EVEN segments and profile 1.0 (geometry passes exactly
through the original edges).

Operators:
- iops.bevel_edge_data_fix   modal: auto-creates the pre-bevel source (stack with
  Bevel and everything after it disabled), inserts the "Bevel Edge Data Restore"
  node group right after the Bevel, then waits:
      ENTER/SPACE  keep the live (procedural) setup
      C            collapse: apply the stack through the fix, pin-unwrap the
                   bevel strips in place, remove the helper
      U            toggle UV projection (pin UVs to the source layout)
      ESC          revert everything
- iops.pin_unwrap_bevel      applied duplicate; re-unwrap ONLY the bevel strips
  (conformal, selection-limited) with every other UV pinned in place.
"""

import bpy
import bmesh
from mathutils import Vector, kdtree

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)

RESTORE_GROUP_NAME = "Bevel Edge Data Restore"
EDGE_ATTRS = (
    ("uv_seam", 'BOOLEAN'),
    ("sharp_edge", 'BOOLEAN'),
    ("crease_edge", 'FLOAT'),
    ("bevel_weight_edge", 'FLOAT'),
)


# --------------------------------------------------------------------------- #
# Node group builder
# --------------------------------------------------------------------------- #

def ensure_restore_group():
    """Return the restore node group, building it if the file doesn't have one."""
    ng = bpy.data.node_groups.get(RESTORE_GROUP_NAME)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(RESTORE_GROUP_NAME, 'GeometryNodeTree')
    ng.is_modifier = True

    iface = ng.interface
    iface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    s_obj = iface.new_socket("Pre-Bevel Source", in_out='INPUT', socket_type='NodeSocketObject')
    s_obj.description = ("Object with the geometry as it enters the Bevel modifier; "
                         "its edge data is projected onto the beveled mesh")
    s_tol = iface.new_socket("Tolerance", in_out='INPUT', socket_type='NodeSocketFloat')
    s_tol.subtype = 'DISTANCE'
    s_tol.default_value = 0.001
    s_tol.min_value = 0.0
    s_tol.description = ("Max distance of both edge endpoints AND the midpoint from an "
                         "original edge (bevel: even segments, profile 1.0)")
    s_uw = iface.new_socket("Unwrap", in_out='INPUT', socket_type='NodeSocketBool')
    s_uw.default_value = False
    s_uw.description = ("Rebuild the UV map by projecting onto the source's UVs — "
                        "layout stays pinned to the source; exact at profile 1.0")
    s_uv = iface.new_socket("UV Map", in_out='INPUT', socket_type='NodeSocketString')
    s_uv.default_value = "UVMap"
    s_uv.description = "UV map name to read on the source and write on the result"
    iface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    nodes, L = ng.nodes, ng.links.new

    def new(idname, x, y, **props):
        n = nodes.new(idname)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    gi = new('NodeGroupInput', -1100, 0)
    go = new('NodeGroupOutput', 2800, 200)
    oinfo = new('GeometryNodeObjectInfo', -880, -200, transform_space='ORIGINAL')
    L(gi.outputs['Pre-Bevel Source'], oinfo.inputs['Object'])

    # on_line: endpoints AND midpoint within tolerance of the source wireframe.
    # The midpoint sample is load-bearing: endpoints alone false-positive on
    # inset-like topology (both endpoints on original verts, edge off-wireframe).
    ev = new('GeometryNodeInputMeshEdgeVertices', -880, 260)
    prox1 = new('GeometryNodeProximity', -650, 160, target_element='EDGES')
    prox2 = new('GeometryNodeProximity', -650, -80, target_element='EDGES')
    prox3 = new('GeometryNodeProximity', -650, -320, target_element='EDGES')  # implicit Position = edge midpoint
    for p in (prox1, prox2, prox3):
        L(oinfo.outputs['Geometry'], p.inputs['Geometry'])
    L(ev.outputs['Position 1'], prox1.inputs['Sample Position'])
    L(ev.outputs['Position 2'], prox2.inputs['Sample Position'])
    mx1 = new('ShaderNodeMath', -440, 40, operation='MAXIMUM')
    mx2 = new('ShaderNodeMath', -360, -140, operation='MAXIMUM')
    cmp = new('FunctionNodeCompare', -200, 40, data_type='FLOAT', operation='LESS_THAN')
    cmp.label = "on_line"
    L(prox1.outputs['Distance'], mx1.inputs[0])
    L(prox2.outputs['Distance'], mx1.inputs[1])
    L(mx1.outputs[0], mx2.inputs[0])
    L(prox3.outputs['Distance'], mx2.inputs[1])
    L(mx2.outputs[0], cmp.inputs[0])
    L(gi.outputs['Tolerance'], cmp.inputs[1])

    near = new('GeometryNodeSampleNearest', -650, -560, domain='EDGE')
    L(oinfo.outputs['Geometry'], near.inputs['Geometry'])

    geo = gi.outputs['Geometry']
    valid = None
    x = 0
    for name, dtype in EDGE_ATTRS:
        named = new('GeometryNodeInputNamedAttribute', x, -520, data_type=dtype)
        named.inputs['Name'].default_value = name
        samp = new('GeometryNodeSampleIndex', x, -300, data_type=dtype, domain='EDGE')
        L(oinfo.outputs['Geometry'], samp.inputs['Geometry'])
        L(named.outputs['Attribute'], samp.inputs['Value'])
        L(near.outputs['Index'], samp.inputs['Index'])
        if dtype == 'BOOLEAN':
            gate = new('FunctionNodeBooleanMath', x + 180, -120, operation='AND')
        else:
            gate = new('ShaderNodeMath', x + 180, -120, operation='MULTIPLY')
        L(samp.outputs['Value'], gate.inputs[0])
        L(cmp.outputs['Result'], gate.inputs[1])
        store = new('GeometryNodeStoreNamedAttribute', x + 180, 200,
                    data_type=dtype, domain='EDGE')
        store.inputs['Name'].default_value = name
        L(geo, store.inputs['Geometry'])
        L(gate.outputs[0], store.inputs['Value'])
        L(prox1.outputs['Is Valid'], store.inputs['Selection'])  # no source -> passthrough
        geo = store.outputs['Geometry']
        valid = prox1.outputs['Is Valid']
        x += 380

    # optional UV projection, pinned to the source layout
    split = new('GeometryNodeSplitEdges', 1550, -350)
    L(oinfo.outputs['Geometry'], split.inputs['Mesh'])
    seam_named = new('GeometryNodeInputNamedAttribute', 1330, -520, data_type='BOOLEAN')
    seam_named.inputs['Name'].default_value = "uv_seam"
    L(seam_named.outputs['Attribute'], split.inputs['Selection'])
    uv_named = new('GeometryNodeInputNamedAttribute', 1550, -640, data_type='FLOAT_VECTOR')
    L(gi.outputs['UV Map'], uv_named.inputs['Name'])
    pos = new('GeometryNodeInputPosition', 1550, -80)
    fod = new('GeometryNodeFieldOnDomain', 1700, -140, domain='FACE', data_type='FLOAT_VECTOR')
    L(pos.outputs['Position'], fod.inputs['Value'])
    mix = new('ShaderNodeMix', 1850, -80, data_type='VECTOR')
    next(s for s in mix.inputs if s.name == 'Factor' and s.type == 'VALUE').default_value = 0.05
    L(pos.outputs['Position'], next(s for s in mix.inputs if s.name == 'A' and s.type == 'VECTOR'))
    L(fod.outputs['Value'], next(s for s in mix.inputs if s.name == 'B' and s.type == 'VECTOR'))
    sns = new('GeometryNodeSampleNearestSurface', 2050, -200, data_type='FLOAT_VECTOR')
    L(split.outputs['Mesh'], sns.inputs['Mesh'])
    L(uv_named.outputs['Attribute'], sns.inputs['Value'])
    L(next(s for s in mix.outputs if s.type == 'VECTOR'), sns.inputs['Sample Position'])
    store_uv = new('GeometryNodeStoreNamedAttribute', 2300, 100, data_type='FLOAT2', domain='CORNER')
    L(geo, store_uv.inputs['Geometry'])
    L(gi.outputs['UV Map'], store_uv.inputs['Name'])
    L(sns.outputs['Value'], store_uv.inputs['Value'])
    L(sns.outputs['Is Valid'], store_uv.inputs['Selection'])
    sw = new('GeometryNodeSwitch', 2550, 200, input_type='GEOMETRY')
    L(gi.outputs['Unwrap'], sw.inputs['Switch'])
    L(geo, sw.inputs['False'])
    L(store_uv.outputs['Geometry'], sw.inputs['True'])
    L(sw.outputs['Output'], go.inputs[0])
    return ng


# --------------------------------------------------------------------------- #
# Core steps (scriptable, used by both operators)
# --------------------------------------------------------------------------- #

def _mod_input_ids(ng):
    return {s.name: s.identifier for s in ng.interface.items_tree
            if getattr(s, "in_out", None) == 'INPUT'}


def create_prebevel_source(context, obj, bevel_mod):
    """Snapshot the evaluated geometry as it enters the Bevel modifier."""
    idx = obj.modifiers.find(bevel_mod.name)
    states = [(m, m.show_viewport) for m in obj.modifiers]
    for m in obj.modifiers[idx:]:
        m.show_viewport = False
    deps = context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(
        obj.evaluated_get(deps), preserve_all_data_layers=True, depsgraph=deps)
    for m, s in states:
        m.show_viewport = s
    name = f"{obj.name}_pre_bevel"
    old = bpy.data.objects.get(name)
    if old:
        old_me = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if old_me and old_me.users == 0:
            bpy.data.meshes.remove(old_me)
    src = bpy.data.objects.new(name, me)
    obj.users_collection[0].objects.link(src)
    src.matrix_world = obj.matrix_world.copy()
    src.hide_viewport = True
    src.hide_render = True
    src.hide_select = True
    return src


def add_restore_modifier(obj, bevel_mod, src, uv_map=None):
    ng = ensure_restore_group()
    mod = obj.modifiers.new("Bevel Edge Data Fix", 'NODES')
    mod.node_group = ng
    target = obj.modifiers.find(bevel_mod.name) + 1
    obj.modifiers.move(obj.modifiers.find(mod.name), target)
    ids = _mod_input_ids(ng)
    inp = mod.properties.inputs
    inp[ids["Pre-Bevel Source"]]["value"] = src
    inp[ids["Tolerance"]]["value"] = 0.001
    if uv_map is None:
        uv_map = obj.data.uv_layers.active.name if obj.data.uv_layers.active else "UVMap"
    inp[ids["UV Map"]]["value"] = uv_map
    return mod


def collapse_fix(context, obj, restore_mod, src):
    """Apply the stack through the fix modifier, then remove the helper object."""
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    context.view_layer.objects.active = obj
    upto = obj.modifiers.find(restore_mod.name)
    names = [m.name for m in obj.modifiers[:upto + 1]]
    with context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        for n in names:
            bpy.ops.object.modifier_apply(modifier=n)
    if src:
        me = src.data
        bpy.data.objects.remove(src, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)


# --------------------------------------------------------------------------- #
# Modal operator
# --------------------------------------------------------------------------- #

def _build_bedf_hud(context, op):
    hud = HUDOverlay("bevel_edge_data_fix")
    hud.title = "Bevel Edge Data Fix"
    hud.add_param(HUDParam("UV Projection", lambda: op.unwrap, kind="bool"))
    hud.add_param(HUDParam("Seams out", lambda: op.seam_count, kind="int"))
    hud.add_param(HUDParam("Helper", lambda: op.src.name if op.src else "-"))
    hud.bind_region(context.region)
    return hud


def _build_bedf_help(context):
    helpo = HelpOverlay("bevel_edge_data_fix")
    helpo.add_section(HUDSection("Bevel Edge Data Fix", [
        HUDItem("Keep live setup",        "Enter / Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Collapse + pin-unwrap + cleanup", "C",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle UV projection",   "U",                   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / Toggle HUD",      "H",                   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Revert",                 "ESC",                 ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


def _draw_bedf_hud(op, context):
    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


class IOPS_OT_BevelEdgeDataFix(bpy.types.Operator):
    """Restore seams/sharp/crease/bevel-weight destroyed by the Bevel modifier.
Creates the pre-bevel source automatically, inserts the fix after the Bevel,
then: ENTER keep live, C collapse + cleanup, U toggle UV projection, ESC revert"""
    bl_idname = "iops.bevel_edge_data_fix"
    bl_label = "Bevel Edge Data Fix"
    bl_options = {'REGISTER', 'UNDO'}

    collapse: bpy.props.BoolProperty(
        name="Collapse", default=False,
        description="Apply the stack through the fix and remove the pre-bevel helper")
    unwrap: bpy.props.BoolProperty(
        name="Unwrap (project UVs)", default=False,
        description="Also rebuild the UV map pinned to the pre-bevel layout")
    pin_unwrap: bpy.props.BoolProperty(
        name="Pin & Unwrap after collapse", default=True,
        description="After collapsing, re-unwrap the bevel strips with everything else pinned")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'MESH'
                and any(m.type == 'BEVEL' for m in obj.modifiers))

    # ---- core, shared by execute/invoke ----
    def _setup(self, context):
        obj = context.active_object
        if context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bevel = next(m for m in obj.modifiers if m.type == 'BEVEL')
        if bevel.segments % 2 or abs(bevel.profile - 1.0) > 1e-4:
            self.report({'WARNING'},
                        f"'{bevel.name}': needs EVEN segments + profile 1.0 — transfer will miss")
        self.obj = obj
        self.bevel = bevel
        self.src = create_prebevel_source(context, obj, bevel)
        self.mod = add_restore_modifier(obj, bevel, self.src)
        self._ids = _mod_input_ids(self.mod.node_group)
        self._set_unwrap(self.unwrap)

    def _set_unwrap(self, state):
        self.unwrap = state
        self.mod.properties.inputs[self._ids["Unwrap"]]["value"] = state
        self.mod.node_group = self.mod.node_group  # nudge depsgraph
        self.obj.update_tag()

    def _revert(self):
        self.obj.modifiers.remove(self.mod)
        me = self.src.data
        bpy.data.objects.remove(self.src, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)

    def _count_seams(self, context):
        deps = context.evaluated_depsgraph_get()
        eme = self.obj.evaluated_get(deps).to_mesh()
        a = eme.attributes.get("uv_seam")
        self.seam_count = sum(1 for d in a.data if d.value) if a else 0

    def _teardown_hud(self, context):
        handle = getattr(self, "_handle_iops_text", None)
        if handle is not None:
            safe_handler_remove(handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle_iops_text = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()

    def _collapse_and_unwrap(self, context):
        """Collapse the stack, then re-unwrap the bevel strips in place."""
        segs = None
        if self.pin_unwrap:
            segs, err = _beveled_segments(self.src, self.bevel)
            if err:
                self.report({'WARNING'}, f"pin-unwrap skipped: {err}")
                segs = None
        collapse_fix(context, self.obj, self.mod, self.src)
        self.src = None
        if segs:
            n_band = pin_unwrap_object(context, self.obj, segs)
            if isinstance(n_band, str):
                self.report({'WARNING'}, f"pin-unwrap skipped: {n_band}")
            else:
                return n_band
        return None

    # ---- entry points ----
    def execute(self, context):
        self._setup(context)
        if self.collapse:
            self._collapse_and_unwrap(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        self._setup(context)
        self._count_seams(context)
        if context.area and context.area.type == 'VIEW_3D':
            self._hud = _build_bedf_hud(context, self)
            self._help = _build_bedf_help(context)
            self._last_event = capture_event(event, None)
            self._handle_iops_text = safe_handler_add(
                bpy.types.SpaceView3D, _draw_bedf_hud, (self, context),
                "WINDOW", "POST_PIXEL", tick=True)
        else:
            context.workspace.status_text_set(
                "Bevel Edge Data Fix | ENTER: keep · C: collapse · U: UV projection · ESC: revert")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}
        if event.value == 'PRESS':
            if event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'}:
                self._teardown_hud(context)
                self.report({'INFO'}, f"{self.obj.name}: live fix kept "
                                      f"(helper: {self.src.name})")
                return {'FINISHED'}
            if event.type == 'C':
                self._teardown_hud(context)
                n_band = self._collapse_and_unwrap(context)
                msg = f"{self.obj.name}: fix collapsed, helper removed"
                if n_band is not None:
                    msg += f", {n_band} strip UV verts relaxed"
                self.report({'INFO'}, msg)
                return {'FINISHED'}
            if event.type == 'U':
                self._set_unwrap(not self.unwrap)
                self._count_seams(context)
                return {'RUNNING_MODAL'}
            if event.type == 'ESC':
                self._teardown_hud(context)
                self._revert()
                return {'CANCELLED'}
        return {'RUNNING_MODAL'}


# --------------------------------------------------------------------------- #
# Pin & Unwrap operator
# --------------------------------------------------------------------------- #

def _beveled_segments(src_obj, bevel_mod):
    me = src_obj.data
    limit = bevel_mod.limit_method if bevel_mod else 'NONE'
    if limit == 'WEIGHT':
        bwa = me.attributes.get("bevel_weight_edge")
        if bwa is None:
            return None, "source has no bevel_weight_edge attribute"
        picked = [i for i in range(len(me.edges)) if bwa.data[i].value > 0.0]
    elif limit == 'ANGLE':
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.edges.ensure_lookup_table()
        picked = [e.index for e in bm.edges
                  if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > bevel_mod.angle_limit]
        bm.free()
    else:  # NONE / VGROUP fallback
        picked = range(len(me.edges))
    segs = [(Vector(me.vertices[me.edges[i].vertices[0]].co),
             Vector(me.vertices[me.edges[i].vertices[1]].co)) for i in picked]
    return segs, None


def pin_unwrap_object(context, obj, segs, tolerance=0.002, margin=0.001):
    """Relax the bevel-strip UVs of *obj* in place; every other UV stays pinned.

    Pin ALL loops, unpin only UV verts strictly interior to the bevel strips
    (verts whose every face is a band face — the strip outline/center rows),
    then unwrap ALL faces. Each solved island contains pins, so the solver can
    neither repack nor detach anything — strips relax between their pinned
    boundaries. (Selection-limited unwrap of bare strips detaches them: an
    island with zero pins gets normalized/packed into 0-1.)

    *segs* = pre-captured beveled source edge segments (object local space).
    Returns the number of unpinned strip UV verts, or an error string.
    """
    step = max(tolerance * 10.0, 0.01)
    pts, owners = [], []
    for si, (a, b) in enumerate(segs):
        n = max(2, int((b - a).length / step) + 1)
        for k in range(n + 1):
            pts.append(a.lerp(b, k / n))
            owners.append(si)
    kd = kdtree.KDTree(len(pts))
    for i, p in enumerate(pts):
        kd.insert(p, i)
    kd.balance()

    def on_wire(p):
        for _co, idx, _d in kd.find_range(p, step):
            a, b = segs[owners[idx]]
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
            if (p - (a + ab * t)).length < tolerance:
                return True
        return False

    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    context.view_layer.objects.active = obj
    for o in context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    # solver islands must match the existing atlas layout, otherwise the
    # solver welds unmarked island borders -> UV spaghetti between pins
    bpy.ops.uv.seams_from_islands(mark_seams=True, mark_sharp=False)
    bpy.ops.mesh.select_all(action='DESELECT')

    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    uvl = bm.loops.layers.uv.active
    if uvl is None:
        bpy.ops.object.mode_set(mode='OBJECT')
        return "object has no UV map"
    wire = {v.index for v in bm.verts if on_wire(v.co)}
    band_faces = {f.index for f in bm.faces
                  if any(v.index in wire for v in f.verts)}
    # unpin only UV verts strictly interior to the strips
    free_verts = {v.index for v in bm.verts
                  if v.link_faces and all(f.index in band_faces for f in v.link_faces)}
    for f in bm.faces:
        f.select = True
        for l in f.loops:
            l[uvl].pin_uv = l.vert.index not in free_verts
    bmesh.update_edit_mesh(me)
    bpy.ops.mesh.select_all(action='SELECT')
    # whole islands solved together; pins anchor them, nothing repacks
    bpy.ops.uv.unwrap(method='CONFORMAL', fill_holes=True, margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')
    return len(free_verts)


class IOPS_OT_PinUnwrapBevel(bpy.types.Operator):
    """Duplicate + apply the bevel stack, then conformal-unwrap ONLY the bevel strips
with every other UV pinned in place (existing atlas layout untouched)"""
    bl_idname = "iops.pin_unwrap_bevel"
    bl_label = "Pin & Unwrap Bevel"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: bpy.props.FloatProperty(
        name="Tolerance", default=0.002, min=0.0, subtype='DISTANCE',
        description="Max distance of a vertex from a beveled source edge to count as bevel-strip geometry")
    margin: bpy.props.FloatProperty(name="Unwrap Margin", default=0.001, min=0.0)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        bevel_mod = next((m for m in obj.modifiers if m.type == 'BEVEL'), None)
        restore = next((m for m in obj.modifiers if m.type == 'NODES' and m.node_group
                        and m.node_group.name.startswith(RESTORE_GROUP_NAME)), None)
        if restore is None:
            self.report({'ERROR'}, f"No '{RESTORE_GROUP_NAME}' modifier on active object")
            return {'CANCELLED'}
        src = restore.properties.inputs[_mod_input_ids(restore.node_group)["Pre-Bevel Source"]]["value"]
        if not src:
            self.report({'ERROR'}, "Fix modifier has no Pre-Bevel Source object")
            return {'CANCELLED'}
        segs, err = _beveled_segments(src, bevel_mod)
        if err or not segs:
            self.report({'ERROR'}, err or "No beveled edges found on source")
            return {'CANCELLED'}

        if context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        name = f"{obj.name}_unwrapped"
        old = bpy.data.objects.get(name)
        if old:
            old_me = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            if old_me.users == 0:
                bpy.data.meshes.remove(old_me)
        deps = context.evaluated_depsgraph_get()
        dme = bpy.data.meshes.new_from_object(obj.evaluated_get(deps), depsgraph=deps)
        dup = bpy.data.objects.new(name, dme)
        obj.users_collection[0].objects.link(dup)
        dup.matrix_world = obj.matrix_world.copy()

        n_band = pin_unwrap_object(context, dup, segs, self.tolerance, self.margin)
        if isinstance(n_band, str):
            self.report({'ERROR'}, n_band)
            return {'CANCELLED'}
        self.report({'INFO'}, f"{name}: {n_band} strip UV verts relaxed, rest pinned")
        return {'FINISHED'}
