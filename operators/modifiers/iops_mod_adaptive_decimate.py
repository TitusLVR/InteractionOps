import bpy

from . import iops_mod_gn_lib as gn_lib

# Geometry-nodes adaptive decimate, built around two detects:
#
# 1. NORMAL BLUR DIFFERENCE: 1 - dot(N, normalize(blur(N))) —
#    Substance-style curvature-from-normals. Convexity/cavity signal at
#    the scale set by the blur radius, smooth by construction.
# 2. GAUSSIAN CURVATURE (angle defect, iops_mod_gn_lib): catches
#    corners and peaks that the normal difference underrates.
#
# The combined field is signed via dot(P - blur(P), N) (sticks out of
# its neighborhood = convex), range-mapped (auto quartiles or manual
# min/max), and drives cascaded Merge by Distance passes whose distance
# follows the mask logarithmically from Merge Distance (black) to
# Detail Merge Distance (white).

GROUP_NAME = "iOps_AdaptiveDecimate"
GROUP_VERSION = 46  # bump when the tree layout changes to force rebuild

FALLOFF_ATTR = "iops_ad_falloff"
MASK_ATTR = "iops_ad_mask"
PREVIEW_MAT = "iOps_AdaptiveDecimate_Preview"

# socket renames across group versions: old name -> current name, so
# upgrade_modifier can carry values over
_SOCKET_RENAMES = {
    "Smooth": "Normal Blur",
    "Curvature Smooth": "Normal Blur",
    "Min Curvature": "Min Value",
    "Max Curvature": "Max Value",
    "Curvature Power": "Power",
    "Merge Distance": "Max Merge Distance",
    "Detail Merge Distance": "Min Merge Distance",
}


PREVIEW_MAT_VERSION = 2  # heatmap ramp


def ensure_attr_preview_material(name=PREVIEW_MAT, attr=MASK_ATTR):
    """Flat emission HEATMAP material reading a float/color attribute:
    blue = min merge distance zone ... red = max. Visible in any
    shading mode. A B/W grayscale is a poor read for decimation zones;
    the ramp makes the distance bands obvious."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        if mat.get("iops_preview_version") == PREVIEW_MAT_VERSION:
            return mat
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    n_attr = nt.nodes.new("ShaderNodeAttribute")
    n_attr.attribute_type = "GEOMETRY"
    n_attr.attribute_name = attr
    n_attr.location = (-600, 0)
    n_ramp = nt.nodes.new("ShaderNodeValToRGB")
    n_ramp.location = (-400, 0)
    ramp = n_ramp.color_ramp
    # heatmap: mask 1 (min distance, detail) = blue -> mask 0 (max
    # distance, heavy optimization) = red
    ramp.elements[0].position = 0.0
    ramp.elements[0].color = (0.9, 0.05, 0.02, 1.0)   # red = max merge
    ramp.elements[1].position = 1.0
    ramp.elements[1].color = (0.02, 0.1, 0.9, 1.0)    # blue = min merge
    e = ramp.elements.new(0.35)
    e.color = (0.95, 0.85, 0.05, 1.0)                 # yellow
    e = ramp.elements.new(0.65)
    e.color = (0.05, 0.8, 0.2, 1.0)                   # green
    n_emit = nt.nodes.new("ShaderNodeEmission")
    n_emit.location = (-120, 0)
    n_out = nt.nodes.new("ShaderNodeOutputMaterial")
    n_out.location = (100, 0)
    nt.links.new(n_attr.outputs["Fac"], n_ramp.inputs["Fac"])
    nt.links.new(n_ramp.outputs["Color"], n_emit.inputs["Color"])
    nt.links.new(n_emit.outputs["Emission"], n_out.inputs["Surface"])
    mat["iops_preview_version"] = PREVIEW_MAT_VERSION
    return mat

# The mask drives the merge distance: every vertex has a target
# distance lerp(Merge Distance, Detail Merge Distance, mask), mapped
# LOGARITHMICALLY so mid-grey reads as mid density. The cascade
# approaches the targets with a geometric distance ramp so no region
# ever jumps more than ~2x per pass (bigger jumps fold face flaps over
# each other): gentle whole-mesh warm-up at fractions of Detail Merge
# Distance...
_DETAIL_STEPS = (0.33, 0.66, 1.0)
# ...then fractions of Merge Distance (geometric, ratio sqrt(2)); 24
# steps span a 4096x range so the ramp reaches down to Detail Merge
# Distance even on huge Merge/Detail ratios (giant assets).
_RAMP_STEPS = tuple(2.0 ** (-k / 2.0) for k in range(23, -1, -1))


def _build_group():
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    ng.is_modifier = True

    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT",
                     socket_type="NodeSocketGeometry")
    s_nb = iface.new_socket("Normal Blur", in_out="INPUT",
                            socket_type="NodeSocketInt")
    s_nb.default_value = 4
    s_nb.min_value = 1
    s_nb.max_value = 64
    s_nb.description = (
        "Scale of the normal-blur-difference detect (blur iterations): "
        "small = only sharp features read as detail, large = broad "
        "gentle bends and slopes count too")
    s_gi = iface.new_socket("Gaussian Influence", in_out="INPUT",
                            socket_type="NodeSocketFloat")
    s_gi.default_value = 1.0
    s_gi.min_value = 0.0
    s_gi.max_value = 10.0
    s_gi.description = (
        "Weight of the gaussian-curvature (angle defect) term: boosts "
        "corners, spikes and peaks that the normal difference "
        "underrates. 0 = pure normal blur difference")
    s_cav = iface.new_socket("Cavity Weight", in_out="INPUT",
                             socket_type="NodeSocketFloat")
    s_cav.default_value = 0.0
    s_cav.min_value = 0.0
    s_cav.max_value = 1.0
    s_cav.description = (
        "How much CONCAVE areas (hollows, dents) count as detail. "
        "0 (default): hollows read as smooth and get optimized like "
        "flats, only convex ridges/edges are protected; 1: cavities "
        "are protected the same as ridges")
    s_auto = iface.new_socket("Auto Range", in_out="INPUT",
                              socket_type="NodeSocketBool")
    s_auto.default_value = True
    s_auto.description = (
        "Determine the field range automatically from the object with "
        "robust quartiles (black = Q1, white = Q3 + IQR — the bulk "
        "always spreads into a visible gradient, outliers clamp); "
        "disable to set Min/Max Value by hand")
    s_min = iface.new_socket("Min Value", in_out="INPUT",
                             socket_type="NodeSocketFloat")
    s_min.default_value = 0.0
    s_min.min_value = 0.0
    s_min.description = ("Field value mapped to black (flat) when Auto "
                         "Range is off")
    s_max = iface.new_socket("Max Value", in_out="INPUT",
                             socket_type="NodeSocketFloat")
    s_max.default_value = 0.2
    s_max.min_value = 0.000001
    s_max.description = ("Field value mapped to white (full detail) "
                         "when Auto Range is off")
    s_pow = iface.new_socket("Power", in_out="INPUT",
                             socket_type="NodeSocketFloat")
    s_pow.default_value = 1.0
    s_pow.min_value = 0.01
    s_pow.description = ("Contrast of the mask: >1 squeezes greys "
                         "toward black (harder optimization), <1 "
                         "lifts faint detail")
    s_dist = iface.new_socket("Max Merge Distance", in_out="INPUT",
                              socket_type="NodeSocketFloat")
    s_dist.subtype = "DISTANCE"
    s_dist.default_value = 0.05
    s_dist.min_value = 0.0
    s_dist.description = ("MAXIMUM merge distance — applied in the "
                          "black (flat/optimized) zones of the mask")
    s_ddist = iface.new_socket("Min Merge Distance", in_out="INPUT",
                               socket_type="NodeSocketFloat")
    s_ddist.subtype = "DISTANCE"
    s_ddist.default_value = 0.01
    s_ddist.min_value = 0.0
    s_ddist.description = ("MINIMUM merge distance — applied in the "
                           "white (detail) zones of the mask; "
                           "in-between interpolates logarithmically")
    s_blur = iface.new_socket("Transition Blur", in_out="INPUT",
                              socket_type="NodeSocketInt")
    s_blur.default_value = 4
    s_blur.min_value = 0
    s_blur.max_value = 32
    s_blur.description = ("Softness of the falloff between detail and "
                          "optimized areas")
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
        f"Show the mask as a B/W '{MASK_ATTR}' color attribute on the "
        "undecimated mesh (visible in any shading mode); white = "
        "preserved, black = optimized")
    iface.new_socket("Geometry", in_out="OUTPUT",
                     socket_type="NodeSocketGeometry")

    n_in = ng.nodes.new("NodeGroupInput")
    n_in.location = (-1100, 0)

    curv_group = gn_lib.ensure_mesh_curvature()

    def _falloff(x, geo_src):
        """The 0..1 protection mask: normal blur difference + weighted
        gaussian curvature, signed by convexity, range-mapped, contrast
        shaped, blurred, re-spanned to a true 0..1."""
        ln = ng.links.new
        # --- normal blur difference: 1 - dot(N, normalize(blur(N)))
        n_nrm = ng.nodes.new("GeometryNodeInputNormal")
        n_nrm.location = (x + 160, -180)
        n_bn = ng.nodes.new("GeometryNodeBlurAttribute")
        n_bn.data_type = "FLOAT_VECTOR"
        n_bn.location = (x + 340, -180)
        ln(n_nrm.outputs["Normal"], n_bn.inputs["Value"])
        ln(n_in.outputs["Normal Blur"], n_bn.inputs["Iterations"])
        n_bnn = ng.nodes.new("ShaderNodeVectorMath")
        n_bnn.operation = "NORMALIZE"
        n_bnn.location = (x + 520, -180)
        ln(n_bn.outputs["Value"], n_bnn.inputs[0])
        n_dotn = ng.nodes.new("ShaderNodeVectorMath")
        n_dotn.operation = "DOT_PRODUCT"
        n_dotn.location = (x + 700, -180)
        ln(n_nrm.outputs["Normal"], n_dotn.inputs[0])
        ln(n_bnn.outputs["Vector"], n_dotn.inputs[1])
        n_nd = ng.nodes.new("ShaderNodeMath")
        n_nd.operation = "SUBTRACT"
        n_nd.inputs[0].default_value = 1.0
        n_nd.location = (x + 880, -180)
        ln(n_dotn.outputs["Value"], n_nd.inputs[1])

        # --- gaussian curvature (angle defect): corners and peaks.
        # Garbage on open-boundary vertices — gated out there.
        n_curv = ng.nodes.new("GeometryNodeGroup")
        n_curv.node_tree = curv_group
        n_curv.location = (x + 160, -420)
        n_gabs = ng.nodes.new("ShaderNodeMath")
        n_gabs.operation = "ABSOLUTE"
        n_gabs.location = (x + 340, -420)
        ln(n_curv.outputs["Gaussian Curvature"], n_gabs.inputs[0])
        n_en = ng.nodes.new("GeometryNodeInputMeshEdgeNeighbors")
        n_en.location = (x + 340, -580)
        n_isb = ng.nodes.new("FunctionNodeCompare")
        n_isb.data_type = "INT"
        n_isb.operation = "LESS_THAN"
        n_isb.inputs["B"].default_value = 2
        n_isb.location = (x + 430, -580)
        ln(n_en.outputs["Face Count"], n_isb.inputs["A"])
        n_bpt = ng.nodes.new("FunctionNodeCompare")
        n_bpt.data_type = "FLOAT"
        n_bpt.operation = "GREATER_THAN"
        n_bpt.inputs["B"].default_value = 0.0
        n_bpt.location = (x + 520, -580)
        ln(n_isb.outputs["Result"], n_bpt.inputs["A"])
        n_keep = ng.nodes.new("ShaderNodeMath")
        n_keep.operation = "SUBTRACT"
        n_keep.inputs[0].default_value = 1.0
        n_keep.location = (x + 610, -580)
        ln(n_bpt.outputs["Result"], n_keep.inputs[1])
        n_ggate = ng.nodes.new("ShaderNodeMath")
        n_ggate.operation = "MULTIPLY"
        n_ggate.location = (x + 520, -420)
        ln(n_gabs.outputs["Value"], n_ggate.inputs[0])
        ln(n_keep.outputs["Value"], n_ggate.inputs[1])
        n_gblur = ng.nodes.new("GeometryNodeBlurAttribute")
        n_gblur.data_type = "FLOAT"
        n_gblur.location = (x + 610, -420)
        ln(n_ggate.outputs["Value"], n_gblur.inputs["Value"])
        ln(n_in.outputs["Normal Blur"], n_gblur.inputs["Iterations"])
        n_gw = ng.nodes.new("ShaderNodeMath")
        n_gw.operation = "MULTIPLY"
        n_gw.location = (x + 700, -420)
        ln(n_gblur.outputs["Value"], n_gw.inputs[0])
        ln(n_in.outputs["Gaussian Influence"], n_gw.inputs[1])

        n_mag = ng.nodes.new("ShaderNodeMath")
        n_mag.operation = "ADD"
        n_mag.location = (x + 970, -260)
        ln(n_nd.outputs["Value"], n_mag.inputs[0])
        ln(n_gw.outputs["Value"], n_mag.inputs[1])

        # --- convex/concave: does the vertex stick out above its
        # blurred neighborhood (dot(P - blur(P), N) >= 0 = convex)?
        n_pos = ng.nodes.new("GeometryNodeInputPosition")
        n_pos.location = (x + 160, -740)
        n_bp = ng.nodes.new("GeometryNodeBlurAttribute")
        n_bp.data_type = "FLOAT_VECTOR"
        n_bp.location = (x + 340, -740)
        ln(n_pos.outputs["Position"], n_bp.inputs["Value"])
        ln(n_in.outputs["Normal Blur"], n_bp.inputs["Iterations"])
        n_dv = ng.nodes.new("ShaderNodeVectorMath")
        n_dv.operation = "SUBTRACT"
        n_dv.location = (x + 520, -740)
        ln(n_pos.outputs["Position"], n_dv.inputs[0])
        ln(n_bp.outputs["Value"], n_dv.inputs[1])
        n_sdot = ng.nodes.new("ShaderNodeVectorMath")
        n_sdot.operation = "DOT_PRODUCT"
        n_sdot.location = (x + 610, -740)
        ln(n_dv.outputs["Vector"], n_sdot.inputs[0])
        ln(n_nrm.outputs["Normal"], n_sdot.inputs[1])
        n_cvx = ng.nodes.new("FunctionNodeCompare")
        n_cvx.data_type = "FLOAT"
        n_cvx.operation = "GREATER_EQUAL"
        n_cvx.inputs["B"].default_value = 0.0
        n_cvx.location = (x + 700, -740)
        ln(n_sdot.outputs["Value"], n_cvx.inputs["A"])
        n_1mc = ng.nodes.new("ShaderNodeMath")
        n_1mc.operation = "SUBTRACT"
        n_1mc.inputs[0].default_value = 1.0
        n_1mc.location = (x + 700, -880)
        ln(n_in.outputs["Cavity Weight"], n_1mc.inputs[1])
        n_cfac = ng.nodes.new("ShaderNodeMath")
        n_cfac.operation = "MULTIPLY_ADD"
        n_cfac.location = (x + 790, -740)
        ln(n_cvx.outputs["Result"], n_cfac.inputs[0])
        ln(n_1mc.outputs["Value"], n_cfac.inputs[1])
        ln(n_in.outputs["Cavity Weight"], n_cfac.inputs[2])

        # final raw field
        n_field = ng.nodes.new("ShaderNodeMath")
        n_field.operation = "MULTIPLY"
        n_field.location = (x + 1060, -340)
        ln(n_mag.outputs["Value"], n_field.inputs[0])
        ln(n_cfac.outputs["Value"], n_field.inputs[1])

        # --- range mapping: robust quartiles (Auto Range) or manual.
        # Black = Q1, white = Q3 + IQR: the distribution bulk always
        # spreads into a visible gradient, outliers just clamp.
        n_stat = ng.nodes.new("GeometryNodeAttributeStatistic")
        n_stat.data_type = "FLOAT"
        n_stat.domain = "POINT"
        n_stat.location = (x + 790, -1040)
        ln(geo_src, n_stat.inputs["Geometry"])
        ln(n_field.outputs["Value"], n_stat.inputs["Attribute"])
        n_below = ng.nodes.new("FunctionNodeCompare")
        n_below.data_type = "FLOAT"
        n_below.operation = "LESS_EQUAL"
        n_below.location = (x + 880, -1200)
        ln(n_field.outputs["Value"], n_below.inputs["A"])
        ln(n_stat.outputs["Median"], n_below.inputs["B"])
        n_statl = ng.nodes.new("GeometryNodeAttributeStatistic")
        n_statl.data_type = "FLOAT"
        n_statl.domain = "POINT"
        n_statl.location = (x + 970, -1200)
        ln(geo_src, n_statl.inputs["Geometry"])
        ln(n_below.outputs["Result"], n_statl.inputs["Selection"])
        ln(n_field.outputs["Value"], n_statl.inputs["Attribute"])
        n_above = ng.nodes.new("FunctionNodeCompare")
        n_above.data_type = "FLOAT"
        n_above.operation = "GREATER_EQUAL"
        n_above.location = (x + 880, -1360)
        ln(n_field.outputs["Value"], n_above.inputs["A"])
        ln(n_stat.outputs["Median"], n_above.inputs["B"])
        n_stath = ng.nodes.new("GeometryNodeAttributeStatistic")
        n_stath.data_type = "FLOAT"
        n_stath.domain = "POINT"
        n_stath.location = (x + 970, -1360)
        ln(geo_src, n_stath.inputs["Geometry"])
        ln(n_above.outputs["Result"], n_stath.inputs["Selection"])
        ln(n_field.outputs["Value"], n_stath.inputs["Attribute"])
        n_iqr = ng.nodes.new("ShaderNodeMath")
        n_iqr.operation = "SUBTRACT"
        n_iqr.location = (x + 1060, -1280)
        ln(n_stath.outputs["Median"], n_iqr.inputs[0])
        ln(n_statl.outputs["Median"], n_iqr.inputs[1])
        n_upper = ng.nodes.new("ShaderNodeMath")
        n_upper.operation = "ADD"
        n_upper.location = (x + 1150, -1280)
        ln(n_stath.outputs["Median"], n_upper.inputs[0])
        ln(n_iqr.outputs["Value"], n_upper.inputs[1])
        n_minsw = ng.nodes.new("GeometryNodeSwitch")
        n_minsw.input_type = "FLOAT"
        n_minsw.location = (x + 1060, -1120)
        ln(n_in.outputs["Auto Range"], n_minsw.inputs["Switch"])
        ln(n_in.outputs["Min Value"], n_minsw.inputs["False"])
        ln(n_statl.outputs["Median"], n_minsw.inputs["True"])
        n_maxsw = ng.nodes.new("GeometryNodeSwitch")
        n_maxsw.input_type = "FLOAT"
        n_maxsw.location = (x + 1150, -1120)
        ln(n_in.outputs["Auto Range"], n_maxsw.inputs["Switch"])
        ln(n_in.outputs["Max Value"], n_maxsw.inputs["False"])
        ln(n_upper.outputs["Value"], n_maxsw.inputs["True"])
        n_norm = ng.nodes.new("ShaderNodeMapRange")
        n_norm.data_type = "FLOAT"
        n_norm.clamp = True
        n_norm.location = (x + 1150, -260)
        ln(n_field.outputs["Value"], n_norm.inputs["Value"])
        ln(n_minsw.outputs["Output"], n_norm.inputs["From Min"])
        ln(n_maxsw.outputs["Output"], n_norm.inputs["From Max"])

        # contrast, transition softness
        n_pow = ng.nodes.new("ShaderNodeMath")
        n_pow.operation = "POWER"
        n_pow.location = (x + 1240, -260)
        ln(n_norm.outputs["Result"], n_pow.inputs[0])
        ln(n_in.outputs["Power"], n_pow.inputs[1])
        n_blur = ng.nodes.new("GeometryNodeBlurAttribute")
        n_blur.data_type = "FLOAT"
        n_blur.location = (x + 1330, -260)
        ln(n_pow.outputs["Value"], n_blur.inputs["Value"])
        ln(n_in.outputs["Transition Blur"], n_blur.inputs["Iterations"])

        # final re-span to a true 0..1: the log distance mapping gives
        # the full Merge Distance only to mask 0 (and Detail only to 1)
        n_stat2 = ng.nodes.new("GeometryNodeAttributeStatistic")
        n_stat2.data_type = "FLOAT"
        n_stat2.domain = "POINT"
        n_stat2.location = (x + 1420, -460)
        ln(geo_src, n_stat2.inputs["Geometry"])
        ln(n_blur.outputs["Value"], n_stat2.inputs["Attribute"])
        n_span = ng.nodes.new("ShaderNodeMapRange")
        n_span.data_type = "FLOAT"
        n_span.clamp = True
        n_span.location = (x + 1510, -260)
        ln(n_blur.outputs["Value"], n_span.inputs["Value"])
        ln(n_stat2.outputs["Min"], n_span.inputs["From Min"])
        ln(n_stat2.outputs["Max"], n_span.inputs["From Max"])
        return n_span.outputs["Result"]

    ln = ng.links.new
    geo = n_in.outputs["Geometry"]

    # bake the mask ONCE on the input geometry: the attribute
    # interpolates through every merge pass, so the density gradient
    # survives (recomputing per pass drifts merged areas to max)
    falloff0 = _falloff(-700, geo)
    n_storef = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    n_storef.data_type = "FLOAT"
    n_storef.domain = "POINT"
    n_storef.inputs["Name"].default_value = FALLOFF_ATTR
    n_storef.location = (900, 0)
    ln(geo, n_storef.inputs["Geometry"])
    ln(falloff0, n_storef.inputs["Value"])
    geo = n_storef.outputs["Geometry"]
    base_geo = geo  # input mesh with the mask baked

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
        n_merge = ng.nodes.new("GeometryNodeMergeByDistance")
        # Connected mode: never welds across gaps. Blender 5.x exposes
        # it as a menu socket; older builds as a node property.
        if "Mode" in n_merge.inputs:
            n_merge.inputs["Mode"].default_value = "Connected"
        else:
            n_merge.mode = "CONNECTED"
        n_merge.location = (x + 270, 0)
        ln(geo, n_merge.inputs["Geometry"])
        if selection_socket is not None:
            ln(selection_socket, n_merge.inputs["Selection"])
        ln(distance_socket, n_merge.inputs["Distance"])
        geo = n_merge.outputs["Geometry"]
        x += 520

    # warm-up: whole mesh at fractions of Detail Merge Distance (every
    # vertex's target is at least the detail distance)
    for frac in _DETAIL_STEPS:
        n_d = ng.nodes.new("ShaderNodeMath")
        n_d.operation = "MULTIPLY"
        n_d.inputs[1].default_value = frac
        n_d.location = (x + 90, -260)
        ln(n_in.outputs["Min Merge Distance"], n_d.inputs[0])
        _merge_pass(n_d.outputs["Value"], None)

    # ramp: distance = Merge Distance * frac; the mask maps to the
    # target distance LOGARITHMICALLY — target = Merge^(1-m) * Detail^m
    # — so mid-grey really reads as mid density. Select vertices whose
    # target >= D, i.e. mask <= -ln(frac) / ln(Merge / Detail)
    import math as _math
    n_dsafe0 = ng.nodes.new("ShaderNodeMath")
    n_dsafe0.operation = "MAXIMUM"
    n_dsafe0.inputs[1].default_value = 1e-9
    n_dsafe0.location = (x - 360, -580)
    ln(n_in.outputs["Min Merge Distance"], n_dsafe0.inputs[0])
    n_ratio = ng.nodes.new("ShaderNodeMath")
    n_ratio.operation = "DIVIDE"
    n_ratio.location = (x - 270, -580)
    ln(n_in.outputs["Max Merge Distance"], n_ratio.inputs[0])
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
        ln(n_in.outputs["Max Merge Distance"], n_d.inputs[0])
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

    # B/W mask preview: undecimated mesh with the mask stored as a
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
    """Add a geometry-nodes Adaptive Decimate modifier: flat and
    hollow areas merge together, convex detail is preserved, density
    follows the curvature mask smoothly"""

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
