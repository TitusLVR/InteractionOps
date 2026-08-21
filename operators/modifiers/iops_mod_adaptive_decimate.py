import bpy

# Geometry-nodes adaptive decimate: curvature/cavity survives, flat and
# sloped regions collapse. Smoothed whole-object curvature field ->
# threshold -> blurred into a 0..1 falloff -> cascaded Merge by
# Distance passes (Connected) that get more aggressive further from
# detail, so the transition is gradual. All knobs are group inputs, so
# they show up in the modifier UI like any GN setup.

GROUP_NAME = "iOps_AdaptiveDecimate"
GROUP_VERSION = 17  # bump when the tree layout changes to force rebuild

MASK_ATTR = "iops_ad_mask"
PREVIEW_MAT = "iOps_AdaptiveDecimate_Preview"


def ensure_attr_preview_material(name=PREVIEW_MAT, attr=MASK_ATTR):
    """Flat emission material reading a color attribute, so attribute
    previews are visible in Material Preview / Rendered shading too."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    n_attr = nt.nodes.new("ShaderNodeAttribute")
    n_attr.attribute_type = "GEOMETRY"
    n_attr.attribute_name = attr
    n_attr.location = (-400, 0)
    n_emit = nt.nodes.new("ShaderNodeEmission")
    n_emit.location = (-180, 0)
    n_out = nt.nodes.new("ShaderNodeOutputMaterial")
    n_out.location = (40, 0)
    nt.links.new(n_attr.outputs["Color"], n_emit.inputs["Color"])
    nt.links.new(n_emit.outputs["Emission"], n_out.inputs["Surface"])
    return mat

# (protection level below which the pass merges, fraction of full
# distance) — near detail merge gently, far from it at full strength.
# Small steps: one aggressive pass folds face flaps over each other,
# several gentle ones collapse the same area cleanly.
_BANDS = ((0.8, 0.15), (0.6, 0.3), (0.4, 0.5), (0.2, 0.75),
          (0.0, 0.5), (0.0, 1.0))


def _build_group():
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    ng.is_modifier = True

    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT",
                     socket_type="NodeSocketGeometry")
    s_curv = iface.new_socket("Curvature Threshold", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_curv.default_value = 0.5
    s_curv.min_value = 0.0
    s_curv.description = (
        "Local curvature (edge angle per meter) below which geometry "
        "counts as flat and gets decimated; detail curvier than "
        "1/threshold meters radius is preserved regardless of mesh "
        "density")
    s_csm = iface.new_socket("Curvature Smooth", in_out="INPUT",
                             socket_type="NodeSocketInt")
    s_csm.default_value = 2
    s_csm.min_value = 0
    s_csm.max_value = 64
    s_csm.description = (
        "Blur steps smoothing per-edge curvature into a continuous "
        "whole-object field before thresholding — the detect selects "
        "coherent regions instead of local noise")
    s_dist = iface.new_socket("Merge Distance", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_dist.subtype = "DISTANCE"
    s_dist.default_value = 0.05
    s_dist.min_value = 0.0
    s_dist.description = "How far flat-area vertices collapse together"
    s_ddist = iface.new_socket("Detail Merge Distance", in_out="INPUT",
                               socket_type="NodeSocketFloat")
    s_ddist.subtype = "DISTANCE"
    s_ddist.default_value = 0.01
    s_ddist.min_value = 0.0
    s_ddist.description = ("Gentle merge inside the protected detail "
                           "(mask) zone, for optimizing dense curvature "
                           "without losing its shape; 0 disables")
    s_blur = iface.new_socket("Transition Blur", in_out="INPUT",
                              socket_type="NodeSocketInt")
    s_blur.default_value = 4
    s_blur.min_value = 0
    s_blur.max_value = 32
    s_blur.description = ("Softness of the falloff between protected "
                          "detail and fully optimized areas")
    s_wrap = iface.new_socket("Shrinkwrap", in_out="INPUT",
                              socket_type="NodeSocketBool")
    s_wrap.default_value = True
    s_wrap.description = ("Snap the decimated vertices back onto the "
                          "original surface so the silhouette is kept")
    s_tri = iface.new_socket("Triangulate", in_out="INPUT",
                             socket_type="NodeSocketBool")
    s_tri.default_value = True
    s_tri.description = ("Triangulate the decimated result (merge "
                         "passes leave ngons behind otherwise)")
    s_prev = iface.new_socket("Preview Mask", in_out="INPUT",
                              socket_type="NodeSocketBool")
    s_prev.default_value = False
    s_prev.description = (
        f"Show the protection mask as a B/W '{MASK_ATTR}' color "
        "attribute on the undecimated mesh (viewport Solid shading, "
        "Color: Attribute); white = preserved, black = optimized")
    iface.new_socket("Geometry", in_out="OUTPUT",
                     socket_type="NodeSocketGeometry")

    n_in = ng.nodes.new("NodeGroupInput")
    n_in.location = (-1100, 0)

    def _falloff(x):
        """Protection falloff field: 1 on detail, fading to 0 with
        distance from it. Curvature smoothed into a continuous field,
        thresholded, then the 0/1 mask blurred into the transition
        gradient."""
        n_angle = ng.nodes.new("GeometryNodeInputMeshEdgeAngle")
        n_angle.location = (x, -180)
        # curvature (rad/m) = angle / width ACROSS the edge. The
        # dihedral angle bends across the edge, so it must be divided
        # by the across step, not the edge's own length — on
        # non-uniform grids (catmull-clark) they differ 10-20x. The
        # across width ~= mean adjacent face area / edge length, hence
        # curvature = angle * edge length / face area.
        n_ev = ng.nodes.new("GeometryNodeInputMeshEdgeVertices")
        n_ev.location = (x, -340)
        n_len = ng.nodes.new("ShaderNodeVectorMath")
        n_len.operation = "DISTANCE"
        n_len.location = (x + 180, -340)
        n_area = ng.nodes.new("GeometryNodeInputMeshFaceArea")
        n_area.location = (x + 180, -480)
        n_mul = ng.nodes.new("ShaderNodeMath")
        n_mul.operation = "MULTIPLY"
        n_mul.location = (x + 340, -180)
        n_safe = ng.nodes.new("ShaderNodeMath")
        n_safe.operation = "MAXIMUM"
        n_safe.inputs[1].default_value = 1e-12
        n_safe.location = (x + 340, -340)
        n_div = ng.nodes.new("ShaderNodeMath")
        n_div.operation = "DIVIDE"
        n_div.location = (x + 430, -260)
        # force the metric onto the EDGE domain: evaluated at points the
        # leaves would average angle over ALL edges around a point, and
        # along-the-crest edges (angle ~0) dilute across-the-crest ones
        # — a black slit along every bevel crest otherwise.
        n_eod = ng.nodes.new("GeometryNodeFieldOnDomain")
        n_eod.domain = "EDGE"
        n_eod.data_type = "FLOAT"
        n_eod.location = (x + 610, -260)
        # smooth curvature into a continuous whole-object field FIRST,
        # threshold after: the detect picks coherent regions instead of
        # per-edge noise
        n_csmooth = ng.nodes.new("GeometryNodeBlurAttribute")
        n_csmooth.data_type = "FLOAT"
        n_csmooth.location = (x + 700, -420)
        n_protect = ng.nodes.new("FunctionNodeCompare")
        n_protect.data_type = "FLOAT"
        n_protect.operation = "GREATER_EQUAL"
        n_protect.location = (x + 790, -260)
        n_blur = ng.nodes.new("GeometryNodeBlurAttribute")
        n_blur.data_type = "FLOAT"
        n_blur.location = (x + 970, -260)

        ln = ng.links.new
        ln(n_ev.outputs["Position 1"], n_len.inputs[0])
        ln(n_ev.outputs["Position 2"], n_len.inputs[1])
        ln(n_angle.outputs["Unsigned Angle"], n_mul.inputs[0])
        ln(n_len.outputs["Value"], n_mul.inputs[1])
        ln(n_area.outputs["Area"], n_safe.inputs[0])
        ln(n_mul.outputs["Value"], n_div.inputs[0])
        ln(n_safe.outputs["Value"], n_div.inputs[1])
        ln(n_div.outputs["Value"], n_eod.inputs["Value"])
        ln(n_eod.outputs["Value"], n_csmooth.inputs["Value"])
        ln(n_in.outputs["Curvature Smooth"], n_csmooth.inputs["Iterations"])
        ln(n_csmooth.outputs["Value"], n_protect.inputs["A"])
        ln(n_in.outputs["Curvature Threshold"], n_protect.inputs["B"])
        ln(n_protect.outputs["Result"], n_blur.inputs["Value"])
        ln(n_in.outputs["Transition Blur"], n_blur.inputs["Iterations"])
        return n_blur.outputs["Value"]

    ln = ng.links.new
    geo = n_in.outputs["Geometry"]
    x = -900
    preview_falloff = None  # first band's falloff = mask on input geometry
    for level, dist_frac in _BANDS:
        falloff = _falloff(x)
        if preview_falloff is None:
            preview_falloff = falloff
        n_sel = ng.nodes.new("FunctionNodeCompare")
        n_sel.data_type = "FLOAT"
        n_sel.operation = "LESS_EQUAL"
        n_sel.inputs["B"].default_value = level
        n_sel.location = (x + 1240, -180)
        ln(falloff, n_sel.inputs["A"])
        n_scale = ng.nodes.new("ShaderNodeMath")
        n_scale.operation = "MULTIPLY"
        n_scale.inputs[1].default_value = dist_frac
        n_scale.location = (x + 1240, -340)
        ln(n_in.outputs["Merge Distance"], n_scale.inputs[0])
        n_merge = ng.nodes.new("GeometryNodeMergeByDistance")
        # Connected mode: never welds across gaps. Blender 5.x exposes
        # it as a menu socket; older builds as a node property.
        if "Mode" in n_merge.inputs:
            n_merge.inputs["Mode"].default_value = "Connected"
        else:
            n_merge.mode = "CONNECTED"
        n_merge.location = (x + 1420, 0)
        ln(geo, n_merge.inputs["Geometry"])
        ln(n_sel.outputs["Result"], n_merge.inputs["Selection"])
        ln(n_scale.outputs["Value"], n_merge.inputs["Distance"])
        geo = n_merge.outputs["Geometry"]
        x += 1600

    # gentle passes INSIDE the protected zone: dense curvature also
    # gets optimized, just with its own small distance so the shape and
    # the mask-driven falloff above stay intact. Split into steps for
    # the same reason as _BANDS — one aggressive pass folds flaps where
    # detail patches are dense (e.g. corners where bevels meet).
    for frac in (0.33, 0.66, 1.0):
        d_falloff = _falloff(x)
        n_dsel = ng.nodes.new("FunctionNodeCompare")
        n_dsel.data_type = "FLOAT"
        n_dsel.operation = "GREATER_THAN"
        n_dsel.inputs["B"].default_value = 0.0
        n_dsel.location = (x + 1240, -180)
        ln(d_falloff, n_dsel.inputs["A"])
        n_dscale = ng.nodes.new("ShaderNodeMath")
        n_dscale.operation = "MULTIPLY"
        n_dscale.inputs[1].default_value = frac
        n_dscale.location = (x + 1240, -340)
        ln(n_in.outputs["Detail Merge Distance"], n_dscale.inputs[0])
        n_dmerge = ng.nodes.new("GeometryNodeMergeByDistance")
        if "Mode" in n_dmerge.inputs:
            n_dmerge.inputs["Mode"].default_value = "Connected"
        else:
            n_dmerge.mode = "CONNECTED"
        n_dmerge.location = (x + 1420, 0)
        ln(geo, n_dmerge.inputs["Geometry"])
        ln(n_dsel.outputs["Result"], n_dmerge.inputs["Selection"])
        ln(n_dscale.outputs["Value"], n_dmerge.inputs["Distance"])
        geo = n_dmerge.outputs["Geometry"]
        x += 1600

    # shrinkwrap: snap merged vertices to the nearest point on the
    # ORIGINAL surface, so collapsed areas don't sink the silhouette.
    # Flat (mask 0) zone only: near creases the nearest face is
    # ambiguous and snapping folds triangles over each other.
    wrap_falloff = _falloff(x)
    n_wsel = ng.nodes.new("FunctionNodeCompare")
    n_wsel.data_type = "FLOAT"
    n_wsel.operation = "LESS_EQUAL"
    n_wsel.inputs["B"].default_value = 0.0
    n_wsel.location = (x + 1240, -380)
    ln(wrap_falloff, n_wsel.inputs["A"])
    x += 1250
    n_prox = ng.nodes.new("GeometryNodeProximity")
    n_prox.target_element = "FACES"
    n_prox.location = (x, -220)
    ln(n_in.outputs["Geometry"], n_prox.inputs["Geometry"])
    n_setpos = ng.nodes.new("GeometryNodeSetPosition")
    n_setpos.location = (x + 180, -220)
    ln(geo, n_setpos.inputs["Geometry"])
    ln(n_wsel.outputs["Result"], n_setpos.inputs["Selection"])
    ln(n_prox.outputs["Position"], n_setpos.inputs["Position"])
    n_wswitch = ng.nodes.new("GeometryNodeSwitch")
    n_wswitch.input_type = "GEOMETRY"
    n_wswitch.location = (x + 360, 0)
    ln(n_in.outputs["Shrinkwrap"], n_wswitch.inputs["Switch"])
    ln(geo, n_wswitch.inputs["False"])
    ln(n_setpos.outputs["Geometry"], n_wswitch.inputs["True"])
    geo = n_wswitch.outputs["Output"]
    x += 540

    # triangulate the result (togglable)
    n_tri = ng.nodes.new("GeometryNodeTriangulate")
    n_tri.location = (x, -220)
    ln(geo, n_tri.inputs["Mesh"])
    n_tswitch = ng.nodes.new("GeometryNodeSwitch")
    n_tswitch.input_type = "GEOMETRY"
    n_tswitch.location = (x + 180, 0)
    ln(n_in.outputs["Triangulate"], n_tswitch.inputs["Switch"])
    ln(geo, n_tswitch.inputs["False"])
    ln(n_tri.outputs["Mesh"], n_tswitch.inputs["True"])
    geo = n_tswitch.outputs["Output"]
    x += 360

    # B/W mask preview: undecimated mesh with the falloff stored as a
    # color attribute (float links into color as grayscale implicitly)
    n_store = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    n_store.data_type = "FLOAT_COLOR"
    n_store.domain = "POINT"
    n_store.inputs["Name"].default_value = MASK_ATTR
    n_store.location = (x, -220)
    ln(n_in.outputs["Geometry"], n_store.inputs["Geometry"])
    ln(preview_falloff, n_store.inputs["Value"])
    n_mat = ng.nodes.new("GeometryNodeSetMaterial")
    n_mat.inputs["Material"].default_value = ensure_attr_preview_material()
    n_mat.location = (x + 180, -220)
    ln(n_store.outputs["Geometry"], n_mat.inputs["Geometry"])
    n_switch = ng.nodes.new("GeometryNodeSwitch")
    n_switch.input_type = "GEOMETRY"
    n_switch.location = (x + 360, 0)
    ln(n_in.outputs["Preview Mask"], n_switch.inputs["Switch"])
    ln(geo, n_switch.inputs["False"])
    ln(n_mat.outputs["Geometry"], n_switch.inputs["True"])

    n_out = ng.nodes.new("NodeGroupOutput")
    n_out.location = (x + 540, 0)
    ln(n_switch.outputs["Output"], n_out.inputs["Geometry"])
    # Stamp only after a complete build: a half-built group (exception
    # mid-way) must never pass the ensure_group version check.
    ng["iops_adaptive_decimate_version"] = GROUP_VERSION
    return ng


def ensure_group():
    ng = bpy.data.node_groups.get(GROUP_NAME)
    if ng is not None:
        if ng.get("iops_adaptive_decimate_version") == GROUP_VERSION:
            return ng
        ng.name += "_old"  # stale layout: keep user edits, build fresh
    return _build_group()


class IOPS_OT_ModAdaptiveDecimate(bpy.types.Operator):
    """Add a geometry-nodes Adaptive Decimate modifier: flat and sloped
    areas merge together, curvature and cavity detail is preserved"""

    bl_idname = "iops.mod_adaptive_decimate"
    bl_label = "Adaptive Decimate"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        ng = ensure_group()
        added = 0
        skipped = {}
        for obj in context.selected_objects:
            if obj.type != "MESH":
                skipped["non-mesh"] = skipped.get("non-mesh", 0) + 1
                continue
            if any(md.type == "NODES" and md.node_group is ng
                   for md in obj.modifiers):
                skipped["already present"] = \
                    skipped.get("already present", 0) + 1
                continue
            md = obj.modifiers.new("Adaptive Decimate", "NODES")
            if md is None:
                skipped["add failed"] = skipped.get("add failed", 0) + 1
                continue
            md.node_group = ng
            added += 1

        msg = f"Adaptive Decimate: added on {added} object(s)"
        for reason, n in skipped.items():
            msg += f"; {n} skipped ({reason})"
        self.report({"INFO"} if added else {"WARNING"}, msg)
        return {"FINISHED"}
