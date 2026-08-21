import bpy

from . import iops_mod_gn_lib as gn_lib

# Geometry-nodes adaptive decimate: curvature/cavity survives, flat and
# sloped regions collapse. Cotan-Laplacian mean curvature (see
# iops_mod_gn_lib) smoothed into a whole-object field, optional AO
# cavity term -> threshold -> blurred into a 0..1 falloff -> cascaded
# Merge by Distance passes (Connected) that get more aggressive further
# from detail, so the transition is gradual. All knobs are group
# inputs, so they show up in the modifier UI like any GN setup.

GROUP_NAME = "iOps_AdaptiveDecimate"
GROUP_VERSION = 22  # bump when the tree layout changes to force rebuild

MASK_ATTR = "iops_ad_mask"
PREVIEW_MAT = "iOps_AdaptiveDecimate_Preview"

AO_ATTR = "iops_ao"


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

# (mask level, distance fraction) — the mask drives the merge distance
# directly: each pass merges vertices whose mask is <= level, at
# lerp(Merge Distance, Detail Merge Distance, level) * fraction. White
# (mask 1) collapses at Detail Merge Distance, black (mask 0) at full
# Merge Distance, in-between interpolates. Small steps: one aggressive
# pass folds face flaps over each other, several gentle ones collapse
# the same area cleanly.
_BANDS = ((1.0, 1.0), (0.8, 1.0), (0.6, 1.0), (0.4, 1.0), (0.2, 1.0),
          (0.0, 0.5), (0.0, 1.0))


def _build_group():
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    ng.is_modifier = True

    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT",
                     socket_type="NodeSocketGeometry")
    s_csm = iface.new_socket("Curvature Smooth", in_out="INPUT",
                             socket_type="NodeSocketInt")
    s_csm.default_value = 2
    s_csm.min_value = 1
    s_csm.max_value = 16
    s_csm.description = (
        "Base blur of the high-frequency curvature band; the field "
        "mixes three octaves (x1 / x4 / x16 of this) into one smooth "
        "whole-object curvature, so blotches disappear")
    s_cmul = iface.new_socket("Curvature Multiply", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_cmul.default_value = 1.0
    s_cmul.min_value = 0.0
    s_cmul.description = ("Post gain of the curvature field before "
                          "thresholding")
    s_cpow = iface.new_socket("Curvature Power", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_cpow.default_value = 1.0
    s_cpow.min_value = 0.01
    s_cpow.description = ("Post contrast of the curvature field: >1 "
                          "sharpens toward strong detail, <1 lifts "
                          "faint mid/low frequencies")
    s_ao = iface.new_socket("AO Influence", in_out="INPUT",
                            socket_type="NodeSocketFloat")
    s_ao.default_value = 0.0
    s_ao.min_value = 0.0
    s_ao.description = (
        "Adds ambient-occlusion cavity to the detect: occluded areas "
        "count as detail, weighted by this (in Curvature Threshold "
        "units). 0 skips the AO computation entirely")
    s_aos = iface.new_socket("AO Samples", in_out="INPUT",
                             socket_type="NodeSocketInt")
    s_aos.default_value = 20
    s_aos.min_value = 1
    s_aos.max_value = 128
    s_aos.description = "Raycast samples per vertex for the AO term"
    s_aoa = iface.new_socket("AO Angle", in_out="INPUT",
                             socket_type="NodeSocketFloat")
    s_aoa.subtype = "ANGLE"
    s_aoa.default_value = 1.0471976
    s_aoa.min_value = 0.0
    s_aoa.max_value = 1.5707964
    s_aoa.description = ("Hemisphere spread of the AO rays around the "
                         "normal")
    s_aob = iface.new_socket("AO Blur", in_out="INPUT",
                             socket_type="NodeSocketInt")
    s_aob.default_value = 2
    s_aob.min_value = 0
    s_aob.max_value = 32
    s_aob.description = "Blur steps smoothing the baked AO"
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

    curv_group = gn_lib.ensure_mesh_curvature()

    def _falloff(x):
        """Protection falloff field: 1 on detail, fading to 0 with
        distance from it. Mean curvature smoothed into a continuous
        field, plus the optional AO cavity term, thresholded, then the
        0/1 mask blurred into the transition gradient."""
        ln = ng.links.new
        # cotangent-Laplacian mean curvature (1/m): per-vertex and
        # smooth by construction (iops_mod_gn_lib)
        n_curv = ng.nodes.new("GeometryNodeGroup")
        n_curv.node_tree = curv_group
        n_curv.location = (x + 250, -260)
        # the group outputs the raw |cotan Laplacian|, which scales
        # with local face size; H (1/m) = raw / (2 * vertex area),
        # vertex area ~= mean adjacent face area — density-independent
        n_farea = ng.nodes.new("GeometryNodeInputMeshFaceArea")
        n_farea.location = (x + 250, -440)
        n_2a = ng.nodes.new("ShaderNodeMath")
        n_2a.operation = "MULTIPLY"
        n_2a.inputs[1].default_value = 2.0
        n_2a.location = (x + 430, -440)
        ln(n_farea.outputs["Area"], n_2a.inputs[0])
        n_hsafe = ng.nodes.new("ShaderNodeMath")
        n_hsafe.operation = "MAXIMUM"
        n_hsafe.inputs[1].default_value = 1e-12
        n_hsafe.location = (x + 520, -440)
        ln(n_2a.outputs["Value"], n_hsafe.inputs[0])
        n_hdiv = ng.nodes.new("ShaderNodeMath")
        n_hdiv.operation = "DIVIDE"
        n_hdiv.location = (x + 610, -260)
        ln(n_curv.outputs["Mean Curvature"], n_hdiv.inputs[0])
        ln(n_hsafe.outputs["Value"], n_hdiv.inputs[1])
        curv_src = n_hdiv.outputs["Value"]

        # three octaves of the curvature field (high / mid / low
        # frequency = base blur x1 / x4 / x16) averaged into one smooth
        # whole-object field — a single blur radius stays blotchy
        octaves = []
        for i, factor in enumerate((1, 4, 16)):
            n_it = ng.nodes.new("ShaderNodeMath")
            n_it.operation = "MULTIPLY"
            n_it.inputs[1].default_value = factor
            n_it.location = (x + 700, -260 - 160 * i)
            ln(n_in.outputs["Curvature Smooth"], n_it.inputs[0])
            n_b = ng.nodes.new("GeometryNodeBlurAttribute")
            n_b.data_type = "FLOAT"
            n_b.location = (x + 790, -260 - 160 * i)
            ln(curv_src, n_b.inputs["Value"])
            ln(n_it.outputs["Value"], n_b.inputs["Iterations"])
            octaves.append(n_b.outputs["Value"])
        n_add1 = ng.nodes.new("ShaderNodeMath")
        n_add1.operation = "ADD"
        n_add1.location = (x + 970, -260)
        ln(octaves[0], n_add1.inputs[0])
        ln(octaves[1], n_add1.inputs[1])
        n_add2 = ng.nodes.new("ShaderNodeMath")
        n_add2.operation = "ADD"
        n_add2.location = (x + 970, -420)
        ln(n_add1.outputs["Value"], n_add2.inputs[0])
        ln(octaves[2], n_add2.inputs[1])
        n_avg = ng.nodes.new("ShaderNodeMath")
        n_avg.operation = "MULTIPLY"
        n_avg.inputs[1].default_value = 1.0 / 3.0
        n_avg.location = (x + 1060, -340)
        ln(n_add2.outputs["Value"], n_avg.inputs[0])

        # post: field * Multiply, then ^ Power, then threshold
        n_gain = ng.nodes.new("ShaderNodeMath")
        n_gain.operation = "MULTIPLY"
        n_gain.location = (x + 1060, -180)
        ln(n_avg.outputs["Value"], n_gain.inputs[0])
        ln(n_in.outputs["Curvature Multiply"], n_gain.inputs[1])
        n_pow = ng.nodes.new("ShaderNodeMath")
        n_pow.operation = "POWER"
        n_pow.location = (x + 1150, -260)
        ln(n_gain.outputs["Value"], n_pow.inputs[0])
        ln(n_in.outputs["Curvature Power"], n_pow.inputs[1])

        # AO cavity term: occluded areas count as detail too. The AO
        # attribute is baked once at the start of the graph (or absent
        # -> reads 0 -> term is influence * 1 * 0 when influence is 0).
        n_aoattr = ng.nodes.new("GeometryNodeInputNamedAttribute")
        n_aoattr.data_type = "FLOAT"
        n_aoattr.inputs["Name"].default_value = AO_ATTR
        n_aoattr.location = (x + 1060, -500)
        n_inv = ng.nodes.new("ShaderNodeMath")
        n_inv.operation = "SUBTRACT"
        n_inv.inputs[0].default_value = 1.0
        n_inv.location = (x + 1150, -500)
        ln(n_aoattr.outputs["Attribute"], n_inv.inputs[1])
        n_aow = ng.nodes.new("ShaderNodeMath")
        n_aow.operation = "MULTIPLY"
        n_aow.location = (x + 1240, -500)
        ln(n_inv.outputs["Value"], n_aow.inputs[0])
        ln(n_in.outputs["AO Influence"], n_aow.inputs[1])
        n_sum = ng.nodes.new("ShaderNodeMath")
        n_sum.operation = "ADD"
        n_sum.location = (x + 1240, -380)
        ln(n_pow.outputs["Value"], n_sum.inputs[0])
        ln(n_aow.outputs["Value"], n_sum.inputs[1])

        # no threshold: the mask IS the shaped continuous curvature
        # field, clamped to 0..1; merge passes cut it by their levels
        n_clamp = ng.nodes.new("ShaderNodeMath")
        n_clamp.operation = "ADD"
        n_clamp.inputs[1].default_value = 0.0
        n_clamp.use_clamp = True
        n_clamp.location = (x + 1150, -100)
        ln(n_sum.outputs["Value"], n_clamp.inputs[0])
        n_blur = ng.nodes.new("GeometryNodeBlurAttribute")
        n_blur.data_type = "FLOAT"
        n_blur.location = (x + 1240, -260)
        ln(n_clamp.outputs["Value"], n_blur.inputs["Value"])
        ln(n_in.outputs["Transition Blur"], n_blur.inputs["Iterations"])
        return n_blur.outputs["Value"]

    ln = ng.links.new
    geo = n_in.outputs["Geometry"]

    # bake AO into a named attribute ONCE up front (raycast is
    # expensive; the attribute then survives all merge passes). A
    # switch bypasses the whole computation while AO Influence is 0.
    n_aog = ng.nodes.new("GeometryNodeGroup")
    n_aog.node_tree = gn_lib.ensure_mesh_ao()
    n_aog.inputs["Attribute"].default_value = AO_ATTR
    n_aog.location = (-1100, -300)
    ln(geo, n_aog.inputs["Mesh"])
    ln(n_in.outputs["AO Samples"], n_aog.inputs["Rays Samples"])
    ln(n_in.outputs["AO Angle"], n_aog.inputs["Rays Angle Offset"])
    ln(n_in.outputs["AO Blur"], n_aog.inputs["Blur Iterations"])
    n_aouse = ng.nodes.new("FunctionNodeCompare")
    n_aouse.data_type = "FLOAT"
    n_aouse.operation = "GREATER_THAN"
    n_aouse.inputs["B"].default_value = 0.0
    n_aouse.location = (-1100, -140)
    ln(n_in.outputs["AO Influence"], n_aouse.inputs["A"])
    n_aosw = ng.nodes.new("GeometryNodeSwitch")
    n_aosw.input_type = "GEOMETRY"
    n_aosw.location = (-920, -140)
    ln(n_aouse.outputs["Result"], n_aosw.inputs["Switch"])
    ln(geo, n_aosw.inputs["False"])
    ln(n_aog.outputs["Mesh"], n_aosw.inputs["True"])
    geo = n_aosw.outputs["Output"]
    base_geo = geo  # input mesh with the AO attribute baked (if on)

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
        n_sel.location = (x + 1420, -180)
        ln(falloff, n_sel.inputs["A"])
        # distance = lerp(Merge Distance, Detail Merge Distance, level)
        n_flatw = ng.nodes.new("ShaderNodeMath")
        n_flatw.operation = "MULTIPLY"
        n_flatw.inputs[1].default_value = 1.0 - level
        n_flatw.location = (x + 1420, -340)
        ln(n_in.outputs["Merge Distance"], n_flatw.inputs[0])
        n_detw = ng.nodes.new("ShaderNodeMath")
        n_detw.operation = "MULTIPLY"
        n_detw.inputs[1].default_value = level
        n_detw.location = (x + 1420, -500)
        ln(n_in.outputs["Detail Merge Distance"], n_detw.inputs[0])
        n_lerp = ng.nodes.new("ShaderNodeMath")
        n_lerp.operation = "ADD"
        n_lerp.location = (x + 1510, -420)
        ln(n_flatw.outputs["Value"], n_lerp.inputs[0])
        ln(n_detw.outputs["Value"], n_lerp.inputs[1])
        n_scale = ng.nodes.new("ShaderNodeMath")
        n_scale.operation = "MULTIPLY"
        n_scale.inputs[1].default_value = dist_frac
        n_scale.location = (x + 1510, -260)
        ln(n_lerp.outputs["Value"], n_scale.inputs[0])
        n_merge = ng.nodes.new("GeometryNodeMergeByDistance")
        # Connected mode: never welds across gaps. Blender 5.x exposes
        # it as a menu socket; older builds as a node property.
        if "Mode" in n_merge.inputs:
            n_merge.inputs["Mode"].default_value = "Connected"
        else:
            n_merge.mode = "CONNECTED"
        n_merge.location = (x + 1600, 0)
        ln(geo, n_merge.inputs["Geometry"])
        ln(n_sel.outputs["Result"], n_merge.inputs["Selection"])
        ln(n_scale.outputs["Value"], n_merge.inputs["Distance"])
        geo = n_merge.outputs["Geometry"]
        x += 1800

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
        n_dsel.location = (x + 1420, -180)
        ln(d_falloff, n_dsel.inputs["A"])
        n_dscale = ng.nodes.new("ShaderNodeMath")
        n_dscale.operation = "MULTIPLY"
        n_dscale.inputs[1].default_value = frac
        n_dscale.location = (x + 1420, -340)
        ln(n_in.outputs["Detail Merge Distance"], n_dscale.inputs[0])
        n_dmerge = ng.nodes.new("GeometryNodeMergeByDistance")
        if "Mode" in n_dmerge.inputs:
            n_dmerge.inputs["Mode"].default_value = "Connected"
        else:
            n_dmerge.mode = "CONNECTED"
        n_dmerge.location = (x + 1600, 0)
        ln(geo, n_dmerge.inputs["Geometry"])
        ln(n_dsel.outputs["Result"], n_dmerge.inputs["Selection"])
        ln(n_dscale.outputs["Value"], n_dmerge.inputs["Distance"])
        geo = n_dmerge.outputs["Geometry"]
        x += 1800

    # shrinkwrap: snap merged vertices to the nearest point on the
    # ORIGINAL surface, so collapsed areas don't sink the silhouette.
    # Flat (mask 0) zone only: near creases the nearest face is
    # ambiguous and snapping folds triangles over each other.
    wrap_falloff = _falloff(x)
    n_wsel = ng.nodes.new("FunctionNodeCompare")
    n_wsel.data_type = "FLOAT"
    n_wsel.operation = "LESS_EQUAL"
    n_wsel.inputs["B"].default_value = 0.0
    n_wsel.location = (x + 1420, -380)
    ln(wrap_falloff, n_wsel.inputs["A"])
    x += 1450
    n_prox = ng.nodes.new("GeometryNodeProximity")
    n_prox.target_element = "FACES"
    n_prox.location = (x, -220)
    ln(base_geo, n_prox.inputs["Geometry"])
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
    ln(base_geo, n_store.inputs["Geometry"])
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


def _socket_idents(group):
    return {s.name: s.identifier for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "INPUT"
            and s.name != "Geometry"}


def upgrade_modifier(md, ng):
    """Re-point md from an outdated iOps group to ng, carrying socket
    values over by name (identifiers shift between versions)."""
    old_vals = {}
    for name, ident in _socket_idents(md.node_group).items():
        try:
            old_vals[name] = md.properties.inputs[ident]["value"]
        except (KeyError, TypeError):
            pass
    old_group = md.node_group
    md.node_group = ng
    for name, ident in _socket_idents(ng).items():
        if name in old_vals:
            try:
                md.properties.inputs[ident]["value"] = old_vals[name]
            except (KeyError, TypeError):
                pass
    if old_group.users == 0:
        bpy.data.node_groups.remove(old_group)


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
        upgraded = 0
        for obj in context.selected_objects:
            if obj.type != "MESH":
                skipped["non-mesh"] = skipped.get("non-mesh", 0) + 1
                continue
            existing = next(
                (md for md in obj.modifiers
                 if md.type == "NODES" and md.node_group is not None
                 and md.node_group.get(
                     "iops_adaptive_decimate_version") is not None),
                None)
            if existing is not None:
                if existing.node_group is ng:
                    skipped["already present"] = \
                        skipped.get("already present", 0) + 1
                else:
                    upgrade_modifier(existing, ng)
                    upgraded += 1
                continue
            md = obj.modifiers.new("Adaptive Decimate", "NODES")
            if md is None:
                skipped["add failed"] = skipped.get("add failed", 0) + 1
                continue
            md.node_group = ng
            added += 1

        msg = f"Adaptive Decimate: added on {added} object(s)"
        if upgraded:
            msg += f", upgraded on {upgraded}"
        for reason, n in skipped.items():
            msg += f"; {n} skipped ({reason})"
        self.report({"INFO"} if (added or upgraded) else {"WARNING"}, msg)
        return {"FINISHED"}
