import math

import bpy
import bmesh


CONTINUATION_ANGLE = math.radians(45.0)


def _fix_edit_objects(context, fix_func):
    """Shared multi-object edit-mesh loop: run fix_func(bm) against every
    mesh in context.objects_in_mode_unique_data, mirroring how
    MESH_OT_extrude_region itself operates on every mesh in multi-object
    edit mode, not just the active object."""
    for obj in context.objects_in_mode_unique_data:
        if obj.type != "MESH":
            continue
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        if fix_func(bm):
            bmesh.update_edit_mesh(me)


def fix_extruded_attrs(bm):
    """Propagate sharp / bevel weight / crease from extruded source edges
    onto the rail edges created by MESH_OT_extrude_region.

    Must run AFTER extrude_region and BEFORE any translation: it is purely
    topology-based. At that point new geometry is selected and original
    vertices are deselected.

    A rail edge has exactly one selected (new) vertex. Its sources are the
    edges of its linked faces (the new side quads) whose vertices are both
    unselected and include the rail's old vertex — i.e. the original
    extruded edges left behind. Per attribute: OR for sharp, max for
    bevel weight / crease. Layers are never created; values propagate only
    through layers that already exist.

    Returns the number of rail edges that received data.
    """
    bw = bm.edges.layers.float.get("bevel_weight_edge")
    cr = bm.edges.layers.float.get("crease_edge")
    changed = 0
    for rail in bm.edges:
        v0, v1 = rail.verts
        if v0.select == v1.select:
            continue
        old_v = v1 if v0.select else v0
        sharp = False
        weight = 0.0
        crease = 0.0
        for face in rail.link_faces:
            for edge in face.edges:
                if edge is rail:
                    continue
                if edge.verts[0].select or edge.verts[1].select:
                    continue
                if old_v not in edge.verts:
                    continue
                sharp = sharp or not edge.smooth
                if bw is not None:
                    weight = max(weight, edge[bw])
                if cr is not None:
                    crease = max(crease, edge[cr])
        if not (sharp or weight > 0.0 or crease > 0.0):
            continue
        if sharp:
            rail.smooth = False
        if weight > 0.0:
            rail[bw] = weight
        if crease > 0.0:
            rail[cr] = crease
        changed += 1
    return changed


class IOPS_OT_extrude_attr_fix(bpy.types.Operator):
    """Copy sharp/bevel weight/crease onto freshly extruded rail edges"""
    bl_idname = "iops.extrude_attr_fix"
    bl_label = "Extrude Attribute Fix"
    bl_options = {"REGISTER"}

    use_selection_marks: bpy.props.BoolProperty(
        name="From Selection",
        description="Copy sharp/bevel weight/crease from the extruded (selected) edges onto the new rail edges",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        if self.use_selection_marks:
            _fix_edit_objects(context, fix_extruded_attrs)
        return {"FINISHED"}


def fix_extruded_attrs_post(bm, cos_limit):
    """Rule B: rails inherit marks from pre-existing non-extruded edges they
    geometrically continue (direction into old vert within the caller-supplied
    continuation angle, expressed as cos_limit, of the rail's direction out of
    it). Runs after the translate; on a cancelled translate rails are
    zero-length and this is a no-op."""
    bw = bm.edges.layers.float.get("bevel_weight_edge")
    cr = bm.edges.layers.float.get("crease_edge")
    changed = 0
    for rail in bm.edges:
        v0, v1 = rail.verts
        if v0.select == v1.select:
            continue
        new_v, old_v = (v0, v1) if v0.select else (v1, v0)
        rail_dir = new_v.co - old_v.co
        if rail_dir.length_squared < 1e-12:
            continue
        rail_dir.normalize()
        # Seed from the rail's CURRENT values (already possibly set by Rule
        # A) so Rule B can only raise sharp/weight/crease, never lower them
        # — a lower-valued continuation edge must not downgrade a rail that
        # Rule A already correctly marked from the extruded source edge.
        sharp = not rail.smooth
        weight = rail[bw] if bw is not None else 0.0
        crease = rail[cr] if cr is not None else 0.0
        for edge in old_v.link_edges:
            if edge is rail:
                continue
            other = edge.other_vert(old_v)
            if other.select:      # new geometry (other rails / duplicates)
                continue
            marked = (not edge.smooth
                      or (bw is not None and edge[bw] > 0.0)
                      or (cr is not None and edge[cr] > 0.0))
            if not marked:
                continue
            edge_dir = old_v.co - other.co   # direction INTO old_v
            if edge_dir.length_squared < 1e-12:
                continue
            edge_dir.normalize()
            if edge_dir.dot(rail_dir) < cos_limit:
                continue
            sharp = sharp or not edge.smooth
            if bw is not None:
                weight = max(weight, edge[bw])
            if cr is not None:
                crease = max(crease, edge[cr])
        if not (sharp or weight > 0.0 or crease > 0.0):
            continue
        if sharp:
            rail.smooth = False
        if weight > 0.0:
            rail[bw] = weight
        if crease > 0.0:
            rail[cr] = crease
        changed += 1
    return changed


class IOPS_OT_extrude_attr_fix_post(bpy.types.Operator):
    """Continue sharp/bevel weight/crease from non-extruded edges onto the
    freshly translated rail edges (Rule B)"""
    bl_idname = "iops.extrude_attr_fix_post"
    bl_label = "Extrude Attribute Fix (Continuation)"
    bl_options = {"REGISTER"}

    use_parent_marks: bpy.props.BoolProperty(
        name="Continue Parents",
        description="Continue sharp/bevel weight/crease from pre-existing marked edges that the new rail edges extend",
        default=True,
    )
    continuation_angle: bpy.props.FloatProperty(
        name="Continuation Angle",
        description="Maximum angle between a rail and a pre-existing marked edge for the rail to count as its continuation",
        subtype="ANGLE",
        default=CONTINUATION_ANGLE,
        min=0.0,
        max=math.radians(90.0),
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        if self.use_parent_marks:
            cos_limit = math.cos(self.continuation_angle)
            _fix_edit_objects(
                context,
                lambda bm: fix_extruded_attrs_post(bm, cos_limit),
            )
        return {"FINISHED"}


class IOPS_OT_mesh_extrude_ex_macro(bpy.types.Macro):
    """Extrude region, fix edge attributes, then move (native-style macro)"""
    bl_idname = "iops.mesh_extrude_ex_macro"
    bl_label = "Extrude Region and Move (Keep Edge Data)"
    bl_options = {"REGISTER", "UNDO"}


def define_extrude_macro():
    """Populate the macro steps. Must be called once per registration,
    AFTER register_classes has run (Macro.define only works on a
    registered macro type)."""
    macro = IOPS_OT_mesh_extrude_ex_macro
    macro.define("MESH_OT_extrude_region")
    macro.define("IOPS_OT_extrude_attr_fix")
    macro.define("TRANSFORM_OT_translate")
    macro.define("IOPS_OT_extrude_attr_fix_post")


class IOPS_OT_mesh_extrude_ex(bpy.types.Operator):
    """Extrude and move, continuing sharp/bevel weight/crease onto the
    new side edges. Face selections translate along the region normal,
    like native E."""
    bl_idname = "iops.mesh_extrude_ex"
    bl_label = "Extrude (Keep Edge Data)"
    # No UNDO here: the macro pushes the single undo step.
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def invoke(self, context, event):
        # Check every mesh in multi-object edit mode, not just the active
        # object: any selected face on any edit object should trigger the
        # normal-constrained translate, matching native E's behavior.
        face_mode = context.tool_settings.mesh_select_mode[2]
        use_normal = False
        if face_mode:
            for obj in context.objects_in_mode_unique_data:
                if obj.type != "MESH":
                    continue
                bm = bmesh.from_edit_mesh(obj.data)
                if any(f.select for f in bm.faces):
                    use_normal = True
                    break
        if use_normal:
            ret = bpy.ops.iops.mesh_extrude_ex_macro(
                "INVOKE_DEFAULT",
                TRANSFORM_OT_translate={
                    "orient_type": "NORMAL",
                    "constraint_axis": (False, False, True),
                },
            )
        else:
            ret = bpy.ops.iops.mesh_extrude_ex_macro("INVOKE_DEFAULT")
        # Non-modal invoke: RUNNING_MODAL cannot be propagated, so map it
        # (and any other non-CANCELLED result) to FINISHED. Only surface
        # an actual cancellation from the underlying macro/extrude call.
        return {"CANCELLED"} if "CANCELLED" in ret else {"FINISHED"}
