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
GROUP_VERSION = 33  # bump when the tree layout changes to force rebuild

FALLOFF_ATTR = "iops_ad_falloff"
CURV_ATTR = "iops_ad_curv"

# socket renames across group versions: old name -> current name, so
# upgrade_modifier can carry values over
_SOCKET_RENAMES = {
    "Curvature Smooth": "Smooth",
    "Curvature Multiply": "Multiply",
    "Curvature Power": "Power",
    "AO Samples": "Rays Samples",
    "AO Angle": "Rays Angle Offset",
    "AO Blur": "Blur Iterations",
}

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

# The mask drives the merge distance: every vertex has a target
# distance lerp(Merge Distance, Detail Merge Distance, mask) — white
# (mask 1) collapses at Detail Merge Distance, black (mask 0) at full
# Merge Distance. The cascade approaches the targets with a geometric
# distance ramp so no region ever jumps more than ~2x per pass (bigger
# jumps fold face flaps over each other):
# gentle whole-mesh warm-up at fractions of Detail Merge Distance...
_DETAIL_STEPS = (0.33, 0.66, 1.0)
# ...then fractions of Merge Distance (geometric, ratio sqrt(2) for a
# fine density gradient), each pass selecting only the vertices whose
# target distance is >= that pass's distance — the transition gets a
# smooth falloff of polygon density instead of min/max banding
_RAMP_STEPS = (0.0625, 0.088, 0.125, 0.177, 0.25, 0.354, 0.5, 0.707,
               1.0)


def _build_group():
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    ng.is_modifier = True

    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT",
                     socket_type="NodeSocketGeometry")
    s_csm = iface.new_socket("Smooth", in_out="INPUT",
                             socket_type="NodeSocketInt")
    s_csm.default_value = 2
    s_csm.min_value = 1
    s_csm.max_value = 16
    s_csm.description = (
        "Base blur of the high-frequency curvature band; the field "
        "mixes three octaves (x1 / x4 / x16 of this) into one smooth "
        "whole-object curvature, so blotches disappear")
    s_cmul = iface.new_socket("Multiply", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_cmul.default_value = 1.0
    s_cmul.min_value = 0.0
    s_cmul.description = "Gain of the curvature field"
    s_cpow = iface.new_socket("Power", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_cpow.default_value = 1.0
    s_cpow.min_value = 0.01
    s_cpow.description = ("Contrast of the curvature field: >1 "
                          "sharpens toward strong detail, <1 lifts "
                          "faint mid/low frequencies")
    s_ao = iface.new_socket("AO Influence", in_out="INPUT",
                            socket_type="NodeSocketFloat")
    s_ao.default_value = 0.0
    s_ao.min_value = 0.0
    s_ao.description = (
        "Cuts ambient occlusion out of the curvature mask: occluded "
        "areas lose protection and get optimized harder, weighted by "
        "this. 0 skips the AO computation entirely")
    s_aos = iface.new_socket("Rays Samples", in_out="INPUT",
                             socket_type="NodeSocketInt")
    s_aos.default_value = 20
    s_aos.min_value = 1
    s_aos.max_value = 128
    s_aos.description = "Raycast samples per vertex for the AO term"
    s_aoa = iface.new_socket("Rays Angle Offset", in_out="INPUT",
                             socket_type="NodeSocketFloat")
    s_aoa.subtype = "ANGLE"
    s_aoa.default_value = 1.0471976
    s_aoa.min_value = 0.0
    s_aoa.max_value = 1.5707964
    s_aoa.description = ("Hemisphere spread of the AO rays around the "
                         "normal")
    s_seed = iface.new_socket("Seed", in_out="INPUT",
                              socket_type="NodeSocketInt")
    s_seed.default_value = 0
    s_seed.description = "Random seed for the AO ray directions"
    s_aob = iface.new_socket("Blur Iterations", in_out="INPUT",
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

    def _falloff(x, geo_src):
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

        # the cotan Laplacian is garbage on open-boundary vertices
        # (huge fake curvature that the low blur octave then smears
        # over the whole object) — zero it out there
        n_en = ng.nodes.new("GeometryNodeInputMeshEdgeNeighbors")
        n_en.location = (x + 430, -600)
        n_isb = ng.nodes.new("FunctionNodeCompare")
        n_isb.data_type = "INT"
        n_isb.operation = "LESS_THAN"
        n_isb.inputs["B"].default_value = 2
        n_isb.location = (x + 520, -600)
        ln(n_en.outputs["Face Count"], n_isb.inputs["A"])
        n_bpt = ng.nodes.new("FunctionNodeCompare")
        n_bpt.data_type = "FLOAT"
        n_bpt.operation = "GREATER_THAN"
        n_bpt.inputs["B"].default_value = 0.0
        n_bpt.location = (x + 610, -600)
        ln(n_isb.outputs["Result"], n_bpt.inputs["A"])
        n_keep = ng.nodes.new("ShaderNodeMath")
        n_keep.operation = "SUBTRACT"
        n_keep.inputs[0].default_value = 1.0
        n_keep.location = (x + 700, -600)
        ln(n_bpt.outputs["Result"], n_keep.inputs[1])
        n_hgate = ng.nodes.new("ShaderNodeMath")
        n_hgate.operation = "MULTIPLY"
        n_hgate.location = (x + 700, -460)
        ln(n_hdiv.outputs["Value"], n_hgate.inputs[0])
        ln(n_keep.outputs["Value"], n_hgate.inputs[1])
        curv_src = n_hgate.outputs["Value"]

        # three octaves of the curvature field (high / mid / low
        # frequency = base blur x1 / x4 / x16) averaged into one smooth
        # whole-object field — a single blur radius stays blotchy
        octaves = []
        for i, factor in enumerate((1, 4, 16)):
            n_it = ng.nodes.new("ShaderNodeMath")
            n_it.operation = "MULTIPLY"
            n_it.inputs[1].default_value = factor
            n_it.location = (x + 700, -260 - 160 * i)
            ln(n_in.outputs["Smooth"], n_it.inputs[0])
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

        # normalize over the whole object: min -> 0, max -> 1, so black
        # zones really get the full Merge Distance and white ones the
        # Detail Merge Distance regardless of the field's absolute scale
        n_stat = ng.nodes.new("GeometryNodeAttributeStatistic")
        n_stat.data_type = "FLOAT"
        n_stat.domain = "POINT"
        n_stat.location = (x + 1060, -560)
        ln(geo_src, n_stat.inputs["Geometry"])
        ln(n_avg.outputs["Value"], n_stat.inputs["Attribute"])
        # robust upper bound (mean + 2*std): a single extreme corner
        # would otherwise own the 1.0 and squash normal bevels to grey;
        # outliers just clamp to 1
        n_std2 = ng.nodes.new("ShaderNodeMath")
        n_std2.operation = "MULTIPLY"
        n_std2.inputs[1].default_value = 2.0
        n_std2.location = (x + 1150, -560)
        ln(n_stat.outputs["Standard Deviation"], n_std2.inputs[0])
        n_upper = ng.nodes.new("ShaderNodeMath")
        n_upper.operation = "ADD"
        n_upper.location = (x + 1240, -560)
        ln(n_stat.outputs["Mean"], n_upper.inputs[0])
        ln(n_std2.outputs["Value"], n_upper.inputs[1])
        n_norm = ng.nodes.new("ShaderNodeMapRange")
        n_norm.data_type = "FLOAT"
        n_norm.clamp = True
        n_norm.location = (x + 1060, -100)
        ln(n_avg.outputs["Value"], n_norm.inputs["Value"])
        ln(n_stat.outputs["Min"], n_norm.inputs["From Min"])
        ln(n_upper.outputs["Value"], n_norm.inputs["From Max"])

        # post: field * Multiply, then ^ Power
        n_gain = ng.nodes.new("ShaderNodeMath")
        n_gain.operation = "MULTIPLY"
        n_gain.location = (x + 1150, -180)
        ln(n_norm.outputs["Result"], n_gain.inputs[0])
        ln(n_in.outputs["Multiply"], n_gain.inputs[1])
        n_pow = ng.nodes.new("ShaderNodeMath")
        n_pow.operation = "POWER"
        n_pow.location = (x + 1150, -260)
        ln(n_gain.outputs["Value"], n_pow.inputs[0])
        ln(n_in.outputs["Power"], n_pow.inputs[1])

        # AO term is CUT OUT of the mask: occluded areas lose
        # protection and get optimized harder. The AO attribute is
        # baked once at the start of the graph (or absent -> reads 0
        # -> term is influence * 1 * 0 when influence is 0).
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
        n_sum.operation = "SUBTRACT"
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
        # second return: the absolute smoothed curvature (1/m), for the
        # fold guard (never merge farther than the local feature size)
        return n_blur.outputs["Value"], n_avg.outputs["Value"]

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
    ln(n_in.outputs["Rays Samples"], n_aog.inputs["Rays Samples"])
    ln(n_in.outputs["Rays Angle Offset"], n_aog.inputs["Rays Angle Offset"])
    ln(n_in.outputs["Seed"], n_aog.inputs["Seed"])
    ln(n_in.outputs["Blur Iterations"], n_aog.inputs["Blur Iterations"])
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

    # bake the normalized falloff ONCE on the input geometry: the
    # attribute interpolates through every merge pass, so the density
    # gradient survives. (Recomputing per pass loses it: merged areas
    # read as low curvature and everything drifts to max distance.)
    # Flap protection comes from the geometric distance ramp instead.
    falloff0, curv0 = _falloff(-700, geo)
    n_storef = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    n_storef.data_type = "FLOAT"
    n_storef.domain = "POINT"
    n_storef.inputs["Name"].default_value = FALLOFF_ATTR
    n_storef.location = (900, 0)
    ln(geo, n_storef.inputs["Geometry"])
    ln(falloff0, n_storef.inputs["Value"])
    n_storec = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    n_storec.data_type = "FLOAT"
    n_storec.domain = "POINT"
    n_storec.inputs["Name"].default_value = CURV_ATTR
    n_storec.location = (1000, 0)
    ln(n_storef.outputs["Geometry"], n_storec.inputs["Geometry"])
    ln(curv0, n_storec.inputs["Value"])
    geo = n_storec.outputs["Geometry"]
    base_geo = geo  # input mesh with AO + falloff + curvature baked

    def falloff_attr(fx, fy=-340):
        n = ng.nodes.new("GeometryNodeInputNamedAttribute")
        n.data_type = "FLOAT"
        n.inputs["Name"].default_value = FALLOFF_ATTR
        n.location = (fx, fy)
        return n.outputs["Attribute"]

    x = 1100
    preview_falloff = falloff_attr(900, -400)

    def _merge_pass(distance_socket, selection_socket):
        nonlocal geo, x
        # fold guard: merging farther than ~half the local curvature
        # radius folds geometry across its own curve — require
        # distance * curvature <= 0.5 no matter what the mask says
        n_ca = ng.nodes.new("GeometryNodeInputNamedAttribute")
        n_ca.data_type = "FLOAT"
        n_ca.inputs["Name"].default_value = CURV_ATTR
        n_ca.location = (x + 90, -740)
        n_hd = ng.nodes.new("ShaderNodeMath")
        n_hd.operation = "MULTIPLY"
        n_hd.location = (x + 180, -740)
        ln(n_ca.outputs["Attribute"], n_hd.inputs[0])
        ln(distance_socket, n_hd.inputs[1])
        n_ok = ng.nodes.new("FunctionNodeCompare")
        n_ok.data_type = "FLOAT"
        n_ok.operation = "LESS_EQUAL"
        n_ok.inputs["B"].default_value = 0.5
        n_ok.location = (x + 270, -740)
        ln(n_hd.outputs["Value"], n_ok.inputs["A"])
        sel = n_ok.outputs["Result"]
        if selection_socket is not None:
            n_and = ng.nodes.new("FunctionNodeBooleanMath")
            n_and.operation = "AND"
            n_and.location = (x + 270, -600)
            ln(selection_socket, n_and.inputs[0])
            ln(sel, n_and.inputs[1])
            sel = n_and.outputs["Boolean"]
        n_merge = ng.nodes.new("GeometryNodeMergeByDistance")
        # Connected mode: never welds across gaps. Blender 5.x exposes
        # it as a menu socket; older builds as a node property.
        if "Mode" in n_merge.inputs:
            n_merge.inputs["Mode"].default_value = "Connected"
        else:
            n_merge.mode = "CONNECTED"
        n_merge.location = (x + 270, 0)
        ln(geo, n_merge.inputs["Geometry"])
        ln(sel, n_merge.inputs["Selection"])
        ln(distance_socket, n_merge.inputs["Distance"])
        geo = n_merge.outputs["Geometry"]
        x += 1800

    # warm-up: whole mesh at fractions of Detail Merge Distance (every
    # vertex's target is at least the detail distance)
    for frac in _DETAIL_STEPS:
        n_d = ng.nodes.new("ShaderNodeMath")
        n_d.operation = "MULTIPLY"
        n_d.inputs[1].default_value = frac
        n_d.location = (x + 90, -260)
        ln(n_in.outputs["Detail Merge Distance"], n_d.inputs[0])
        _merge_pass(n_d.outputs["Value"], None)

    # ramp: distance = Merge Distance * frac; the mask maps to the
    # target distance LOGARITHMICALLY — target = Merge^(1-m) * Detail^m
    # — so mid-grey really reads as mid density (a linear lerp is
    # dominated by Merge Distance and mid-greys collapse near max).
    # Select vertices whose target >= D, i.e.
    # mask <= -ln(frac) / ln(Merge / Detail)
    import math as _math
    n_dsafe0 = ng.nodes.new("ShaderNodeMath")
    n_dsafe0.operation = "MAXIMUM"
    n_dsafe0.inputs[1].default_value = 1e-9
    n_dsafe0.location = (x - 360, -580)
    ln(n_in.outputs["Detail Merge Distance"], n_dsafe0.inputs[0])
    n_ratio = ng.nodes.new("ShaderNodeMath")
    n_ratio.operation = "DIVIDE"
    n_ratio.location = (x - 270, -580)
    ln(n_in.outputs["Merge Distance"], n_ratio.inputs[0])
    ln(n_dsafe0.outputs["Value"], n_ratio.inputs[1])
    n_lnr = ng.nodes.new("ShaderNodeMath")
    n_lnr.operation = "LOGARITHM"
    n_lnr.inputs[1].default_value = 2.718281828
    n_lnr.location = (x - 180, -580)
    ln(n_ratio.outputs["Value"], n_lnr.inputs[0])
    n_lnsafe = ng.nodes.new("ShaderNodeMath")
    n_lnsafe.operation = "MAXIMUM"
    n_lnsafe.inputs[1].default_value = 1e-6
    n_lnsafe.location = (x - 90, -580)
    ln(n_lnr.outputs["Value"], n_lnsafe.inputs[0])
    ln_merge_detail = n_lnsafe.outputs["Value"]

    for frac in _RAMP_STEPS:
        falloff = falloff_attr(x - 180)
        n_d = ng.nodes.new("ShaderNodeMath")
        n_d.operation = "MULTIPLY"
        n_d.inputs[1].default_value = frac
        n_d.location = (x, -260)
        ln(n_in.outputs["Merge Distance"], n_d.inputs[0])
        n_level = ng.nodes.new("ShaderNodeMath")
        n_level.operation = "DIVIDE"
        n_level.inputs[0].default_value = -_math.log(frac) if frac < 1 else 0.0
        n_level.location = (x + 90, -420)
        ln(ln_merge_detail, n_level.inputs[1])
        n_sel = ng.nodes.new("FunctionNodeCompare")
        n_sel.data_type = "FLOAT"
        n_sel.operation = "LESS_EQUAL"
        n_sel.location = (x + 90, -180)
        ln(falloff, n_sel.inputs["A"])
        ln(n_level.outputs["Value"], n_sel.inputs["B"])
        _merge_pass(n_d.outputs["Value"], n_sel.outputs["Result"])

    # shrinkwrap: snap merged vertices to the nearest point on the
    # ORIGINAL surface, so collapsed areas don't sink the silhouette.
    # Flat-ish (low mask) zone only: near creases the nearest face is
    # ambiguous and snapping folds triangles over each other.
    wrap_falloff = falloff_attr(x - 180, -380)
    n_wsel = ng.nodes.new("FunctionNodeCompare")
    n_wsel.data_type = "FLOAT"
    n_wsel.operation = "LESS_EQUAL"
    n_wsel.inputs["B"].default_value = 0.2
    n_wsel.location = (x, -380)
    ln(wrap_falloff, n_wsel.inputs["A"])
    x += 200
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
    old_vals = {_SOCKET_RENAMES.get(k, k): v for k, v in old_vals.items()}
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
