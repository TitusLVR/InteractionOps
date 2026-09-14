import math

import bpy

# Geometry-nodes Iron: finds and collapses the two defects a merge-based
# decimate leaves behind on triangle meshes, and flattens the surface
# again the way an iron flattens folds:
#
# 1. FOLD-OVER: an edge whose two faces are almost antiparallel (face
#    angle > Fold Angle) — a flap folded back over its neighbor.
#    Fix: merge the apex nearer to the hinge into its nearer hinge
#    vertex; that flap face degenerates and disappears, the hinge stays.
# 2. SLIVER / KINK: a triangle with a corner angle near 180 degrees (the
#    apex sits on its own base line) or near 0 (a needle: two long edges
#    and one tiny). Its neighbors bend around it and read as a kink.
#    Fix: collapse the shorter apex edge (apex onto that base end) or
#    the needle's short edge; the long edges never move.
#
# Both detects resolve to one per-vertex "victim -> target position"
# field. Victims whose target is itself a victim wait for the next
# iteration (no chains: A->B while B->C would leave A at B's old spot).
# Victims are moved onto their target with Set Position and welded by a
# tiny Connected Merge by Distance — an exact edge collapse, not a
# blanket merge radius that would fold new flaps. The pass repeats
# Iterations times because a collapse can expose the next sliver.

GROUP_NAME = "iOps_Iron"
GROUP_VERSION = 1  # bump when the tree layout changes to force rebuild
VERSION_PROP = "iops_iron_version"

PREVIEW_MAT = "iOps_Iron_Preview"
PREVIEW_MAT_VERSION = 1

# socket renames across group versions: old name -> current name
_SOCKET_RENAMES = {}

WELD_DISTANCE = 1e-5  # victims sit exactly on their target after Set Position


def ensure_preview_material(name=PREVIEW_MAT):
    """Flat red emission: assigned only to the faces the next pass
    would touch (Preview socket), so defects pop in any shading mode."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        if mat.get("iops_preview_version") == PREVIEW_MAT_VERSION:
            return mat
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    n_emit = nt.nodes.new("ShaderNodeEmission")
    n_emit.inputs["Color"].default_value = (0.95, 0.08, 0.03, 1.0)
    n_emit.location = (-120, 0)
    n_out = nt.nodes.new("ShaderNodeOutputMaterial")
    n_out.location = (100, 0)
    nt.links.new(n_emit.outputs["Emission"], n_out.inputs["Surface"])
    mat.diffuse_color = (0.95, 0.08, 0.03, 1.0)  # solid mode too
    mat["iops_preview_version"] = PREVIEW_MAT_VERSION
    return mat


class _Builder:
    """Thin helpers over ng.nodes / ng.links: every node gets a
    location; socket arguments link, plain values become defaults."""

    def __init__(self, ng):
        self.ng = ng
        self.ln = ng.links.new

    def node(self, bl_idname, x, y, label=None, **props):
        n = self.ng.nodes.new(bl_idname)
        n.location = (x, y)
        if label:
            n.label = label
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def _feed(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.ln(v, sock)
        else:
            sock.default_value = v

    def link(self, n, **inputs):
        """link(node, Socket_Name=socket_or_value, ...)."""
        for name, src in inputs.items():
            self._feed(n.inputs[name.replace("_", " ")], src)
        return n

    def math(self, op, x, y, a, b=None, c=None, label=None):
        n = self.node("ShaderNodeMath", x, y, label, operation=op)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self._feed(n.inputs[i], v)
        return n.outputs["Value"]

    def vmath(self, op, x, y, a, b=None, label=None):
        n = self.node("ShaderNodeVectorMath", x, y, label, operation=op)
        self._feed(n.inputs[0], a)
        if b is not None:
            self._feed(n.inputs[1], b)
        out = "Value" if op in {"DOT_PRODUCT", "LENGTH", "DISTANCE"} \
            else "Vector"
        return n.outputs[out]

    def compare(self, dtype, op, x, y, a, b, label=None):
        n = self.node("FunctionNodeCompare", x, y, label,
                      data_type=dtype, operation=op)
        self._feed(n.inputs["A"], a)
        self._feed(n.inputs["B"], b)
        return n.outputs["Result"]

    def boolean(self, op, x, y, a, b=None, label=None):
        n = self.node("FunctionNodeBooleanMath", x, y, label, operation=op)
        self._feed(n.inputs[0], a)
        if b is not None:
            self._feed(n.inputs[1], b)
        return n.outputs["Boolean"]

    def switch(self, itype, x, y, cond, false, true, label=None):
        n = self.node("GeometryNodeSwitch", x, y, label, input_type=itype)
        self._feed(n.inputs["Switch"], cond)
        self._feed(n.inputs["False"], false)
        self._feed(n.inputs["True"], true)
        return n.outputs["Output"]

    def sample(self, geo, domain, dtype, x, y, value, index, label=None):
        """Sample Index: evaluate `value` on geo's `domain` at `index`."""
        n = self.node("GeometryNodeSampleIndex", x, y, label,
                      data_type=dtype, domain=domain)
        self.ln(geo, n.inputs["Geometry"])
        self._feed(n.inputs["Value"], value)
        self._feed(n.inputs["Index"], index)
        return n.outputs["Value"]

    def snapshot(self):
        return {n.name for n in self.ng.nodes}

    def frame(self, label, before):
        """Put every node created since `before` into a labeled frame."""
        fr = self.ng.nodes.new("NodeFrame")
        fr.label = label
        for n in self.ng.nodes:
            if n.name != fr.name and n.name not in before \
                    and n.parent is None:
                n.parent = fr
        return self.snapshot()


def _build_group():
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    ng.is_modifier = True

    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT",
                     socket_type="NodeSocketGeometry")
    p_detect = iface.new_panel("Detect")
    p_fix = iface.new_panel("Fix")
    p_out = iface.new_panel("Output")
    s_fold = iface.new_socket("Fold Angle", in_out="INPUT",
                              socket_type="NodeSocketFloat",
                              parent=p_detect)
    s_fold.subtype = "ANGLE"
    s_fold.default_value = math.radians(150.0)
    s_fold.min_value = math.radians(90.0)
    s_fold.max_value = math.radians(180.0)
    s_fold.description = (
        "An edge whose two faces bend by more than this is a fold-over "
        "(the flap is folded back onto its neighbor); the flap apex is "
        "merged into the hinge. 180 = never")
    s_sliver = iface.new_socket("Sliver Angle", in_out="INPUT",
                                socket_type="NodeSocketFloat",
                                parent=p_detect)
    s_sliver.subtype = "ANGLE"
    s_sliver.default_value = math.radians(3.0)
    s_sliver.min_value = 0.0
    s_sliver.max_value = math.radians(45.0)
    s_sliver.description = (
        "A triangle whose corner is within this of 180 degrees is a "
        "sliver (its apex lies on the base line, the surface kinks "
        "around it); the shorter apex edge gets collapsed. 0 = never")
    s_maxlen = iface.new_socket("Max Edge Length", in_out="INPUT",
                                socket_type="NodeSocketFloat",
                                parent=p_detect)
    s_maxlen.subtype = "DISTANCE"
    s_maxlen.default_value = 0.0
    s_maxlen.min_value = 0.0
    s_maxlen.description = (
        "Never collapse an edge longer than this (a collapse moves a "
        "vertex by the edge length). 0 = no limit")
    s_it = iface.new_socket("Iterations", in_out="INPUT",
                            socket_type="NodeSocketInt", parent=p_fix)
    s_it.default_value = 4
    s_it.min_value = 1
    s_it.max_value = 32
    s_it.description = (
        "Detect-and-collapse passes: one collapse can expose the next "
        "sliver or fold behind it")
    s_prev = iface.new_socket("Preview", in_out="INPUT",
                              socket_type="NodeSocketBool", parent=p_out)
    s_prev.default_value = False
    s_prev.description = (
        "Show the input mesh with the faces the first pass would touch "
        "painted red instead of the ironed result")
    iface.new_socket("Geometry", in_out="OUTPUT",
                     socket_type="NodeSocketGeometry")

    b = _Builder(ng)
    n_in = b.node("NodeGroupInput", -1400, 0)
    base_geo = n_in.outputs["Geometry"]

    # ---------------- thresholds shared by every pass ----------------
    _s = b.snapshot()
    # apex test: dot(u, v) < -cos(Sliver Angle)  <=>  corner > 180 - Sliver
    cos_sl = b.math("COSINE", -1200, -300, n_in.outputs["Sliver Angle"])
    neg_cos_sl = b.math("MULTIPLY", -1040, -300, cos_sl, -1.0,
                        label="-cos(Sliver Angle)")
    # Max Edge Length 0 = no limit
    no_limit = b.compare("FLOAT", "LESS_EQUAL", -1200, -460,
                         n_in.outputs["Max Edge Length"], 0.0,
                         label="No Length Limit")
    _s = b.frame("Thresholds", _s)

    # ---------------- the repeat zone: state = geometry ----------------
    n_rin = b.node("GeometryNodeRepeatInput", -800, 0)
    n_rout = b.node("GeometryNodeRepeatOutput", 5000, 0)
    n_rin.pair_with_output(n_rout)
    if not len(n_rout.repeat_items):
        n_rout.repeat_items.new("GEOMETRY", "Geometry")
    b.ln(n_in.outputs["Iterations"], n_rin.inputs["Iterations"])
    b.ln(base_geo, n_rin.inputs["Geometry"])
    geo = n_rin.outputs["Geometry"]

    def defect_fields(x, geo):
        """Everything one pass detects on `geo`. Returns per-POINT
        (victim, target_pos, target_idx) plus the per-FACE preview
        mask. Fields are only meaningful when evaluated on `geo`.

        Every detect ends as a CORNER field "this corner's vertex is a
        victim, and here is its target": the sliver apex/needle corner
        itself, or the corner opposite a fold edge. One Corners of
        Vertex lookup then pulls the first victim corner per vertex."""
        _s = b.snapshot()
        n_pos = b.node("GeometryNodeInputPosition", x, -120)
        n_cidx = b.node("GeometryNodeInputIndex", x, -900, label="Corner")
        # triangles only: Corners of Face total at this corner's face
        n_foc = b.link(b.node("GeometryNodeFaceOfCorner", x, -1500),
                       Corner_Index=n_cidx.outputs["Index"])
        n_cof = b.link(b.node("GeometryNodeCornersOfFace", x + 180, -1500),
                       Face_Index=n_foc.outputs["Face Index"])
        is_tri = b.compare("INT", "EQUAL", x + 360, -1500,
                           n_cof.outputs["Total"], 3, label="Is Triangle")

        # ---- edge domain: length + fold flag + apex-to-apex collapse ----
        ex, ey = x + 600, -200
        n_ev = b.node("GeometryNodeInputMeshEdgeVertices", ex, ey)
        e_len = b.vmath("DISTANCE", ex + 180, ey, n_ev.outputs["Position 1"],
                        n_ev.outputs["Position 2"], label="Edge Length")
        n_ang = b.node("GeometryNodeInputMeshEdgeAngle", ex, ey - 200)
        fold_ang = b.compare("FLOAT", "GREATER_THAN", ex + 180, ey - 200,
                             n_ang.outputs["Unsigned Angle"],
                             n_in.outputs["Fold Angle"], label="Folded")
        # the two faces on the edge: corner c0 / c1 whose next edge is
        # this one; their opposite corner (offset -1) is the apex
        n_c0 = b.link(b.node("GeometryNodeCornersOfEdge", ex, ey - 400),
                      Sort_Index=0)
        n_c1 = b.link(b.node("GeometryNodeCornersOfEdge", ex, ey - 560),
                      Sort_Index=1)
        two_faces = b.compare("INT", "EQUAL", ex + 180, ey - 400,
                              n_c0.outputs["Total"], 2, label="Two Faces")
        tri0 = b.sample(geo, "CORNER", "BOOLEAN", ex + 180, ey - 720, is_tri,
                        n_c0.outputs["Corner Index"])
        tri1 = b.sample(geo, "CORNER", "BOOLEAN", ex + 180, ey - 880, is_tri,
                        n_c1.outputs["Corner Index"])
        n_a0 = b.link(
            b.node("GeometryNodeVertexOfCorner", ex + 540, ey - 400),
            Corner_Index=b.link(
                b.node("GeometryNodeOffsetCornerInFace", ex + 360, ey - 400),
                Corner_Index=n_c0.outputs["Corner Index"],
                Offset=-1).outputs["Corner Index"])
        n_a1 = b.link(
            b.node("GeometryNodeVertexOfCorner", ex + 540, ey - 560),
            Corner_Index=b.link(
                b.node("GeometryNodeOffsetCornerInFace", ex + 360, ey - 560),
                Corner_Index=n_c1.outputs["Corner Index"],
                Offset=-1).outputs["Corner Index"])
        apex0_p = b.sample(geo, "POINT", "FLOAT_VECTOR", ex + 720, ey - 400,
                           n_pos.outputs["Position"],
                           n_a0.outputs["Vertex Index"], label="Apex 0 P")
        apex1_p = b.sample(geo, "POINT", "FLOAT_VECTOR", ex + 720, ey - 560,
                           n_pos.outputs["Position"],
                           n_a1.outputs["Vertex Index"], label="Apex 1 P")
        # victim = the apex nearer to the hinge, target = its nearer
        # hinge vertex. Measured on a decimated asteroid (393 folds, 422
        # slivers, 22 fins): hinge-edge collapse -> 78 folds / 60 fins,
        # apex -> apex -> 210 / 416, face-0 apex -> hinge -> 61 / 37,
        # nearest apex -> hinge -> 4 folds / 3 slivers / 23 fins.
        def hinge_dists(apex_p, y):
            d1 = b.vmath("DISTANCE", ex + 900, y, apex_p,
                         n_ev.outputs["Position 1"])
            d2 = b.vmath("DISTANCE", ex + 900, y - 160, apex_p,
                         n_ev.outputs["Position 2"])
            return d1, d2, b.math("MINIMUM", ex + 1080, y - 80, d1, d2)

        d1_0, d2_0, m0 = hinge_dists(apex0_p, ey - 400)
        d1_1, d2_1, m1 = hinge_dists(apex1_p, ey - 800)
        use0 = b.compare("FLOAT", "LESS_EQUAL", ex + 1260, ey - 600, m0, m1,
                         label="Apex 0 Nearer")
        fold_victim_v = b.switch("INT", ex + 1440, ey - 600, use0,
                                 n_a1.outputs["Vertex Index"],
                                 n_a0.outputs["Vertex Index"],
                                 label="Fold Victim (apex)")
        d1 = b.switch("FLOAT", ex + 1440, ey - 760, use0, d1_1, d1_0)
        d2 = b.switch("FLOAT", ex + 1440, ey - 920, use0, d2_1, d2_0)
        fold_move = b.switch("FLOAT", ex + 1440, ey - 1080, use0, m1, m0,
                             label="Apex Move")
        near1 = b.compare("FLOAT", "LESS_EQUAL", ex + 1620, ey - 480, d1, d2,
                          label="Hinge 1 Nearer")
        fold_target_v = b.switch("INT", ex + 1800, ey - 480, near1,
                                 n_ev.outputs["Vertex Index 2"],
                                 n_ev.outputs["Vertex Index 1"],
                                 label="Fold Target Index")
        fold_target_p = b.switch("VECTOR", ex + 1800, ey - 640, near1,
                                 n_ev.outputs["Position 2"],
                                 n_ev.outputs["Position 1"],
                                 label="Fold Target Position")
        fold_len_ok = b.boolean(
            "OR", ex + 1800, ey - 200, no_limit,
            b.compare("FLOAT", "LESS_EQUAL", ex + 1620, ey - 200, fold_move,
                      n_in.outputs["Max Edge Length"]))
        is_fold = b.boolean(
            "AND", ex + 2160, ey - 200,
            b.boolean("AND", ex + 1980, ey - 200, fold_ang, two_faces),
            b.boolean("AND", ex + 1980, ey - 360,
                      b.boolean("AND", ex + 1800, ey - 360, tri0, tri1),
                      fold_len_ok),
            label="Fold Edge")
        _s = b.frame("Edge: Fold Detect (apex -> apex)", _s)

        # ---- corner domain: sliver apex / needle ----
        cx, cy = x + 2000, -900
        n_next = b.link(
            b.node("GeometryNodeOffsetCornerInFace", cx, cy),
            Corner_Index=n_cidx.outputs["Index"], Offset=1)
        n_prev = b.link(
            b.node("GeometryNodeOffsetCornerInFace", cx, cy - 160),
            Corner_Index=n_cidx.outputs["Index"], Offset=-1)
        p_next = b.sample(geo, "CORNER", "FLOAT_VECTOR", cx + 180, cy,
                          n_pos.outputs["Position"],
                          n_next.outputs["Corner Index"], label="P next")
        p_prev = b.sample(geo, "CORNER", "FLOAT_VECTOR", cx + 180, cy - 160,
                          n_pos.outputs["Position"],
                          n_prev.outputs["Corner Index"], label="P prev")
        u = b.vmath("NORMALIZE", cx + 540, cy,
                    b.vmath("SUBTRACT", cx + 360, cy, p_next,
                            n_pos.outputs["Position"]))
        v = b.vmath("NORMALIZE", cx + 540, cy - 160,
                    b.vmath("SUBTRACT", cx + 360, cy - 160, p_prev,
                            n_pos.outputs["Position"]))
        cos_corner = b.vmath("DOT_PRODUCT", cx + 720, cy, u, v,
                             label="cos(corner)")
        is_apex_raw = b.compare("FLOAT", "LESS_THAN", cx + 900, cy,
                                cos_corner, neg_cos_sl, label="Apex Corner")
        # the two edges meeting at this corner's vertex
        n_eoc = b.link(
            b.node("GeometryNodeEdgesOfCorner", cx, cy - 360),
            Corner_Index=n_cidx.outputs["Index"])
        len_next = b.sample(geo, "EDGE", "FLOAT", cx + 180, cy - 360, e_len,
                            n_eoc.outputs["Next Edge Index"])
        len_prev = b.sample(geo, "EDGE", "FLOAT", cx + 180, cy - 520, e_len,
                            n_eoc.outputs["Previous Edge Index"])
        use_next = b.compare("FLOAT", "LESS_EQUAL", cx + 360, cy - 360,
                             len_next, len_prev, label="Next Is Shorter")
        c_edge = b.switch("INT", cx + 540, cy - 360, use_next,
                          n_eoc.outputs["Previous Edge Index"],
                          n_eoc.outputs["Next Edge Index"],
                          label="Apex Collapse Edge")
        c_len = b.math("MINIMUM", cx + 540, cy - 520, len_next, len_prev)
        c_len_ok = b.boolean(
            "OR", cx + 900, cy - 520, no_limit,
            b.compare("FLOAT", "LESS_EQUAL", cx + 720, cy - 520, c_len,
                      n_in.outputs["Max Edge Length"]))
        is_apex = b.boolean("AND", cx + 1080, cy, is_apex_raw, c_len_ok,
                            label="Apex (collapsible)")
        # far end of the apex collapse edge = whichever vertex is not ours
        n_cv = b.link(
            b.node("GeometryNodeVertexOfCorner", cx + 540, cy - 700),
            Corner_Index=n_cidx.outputs["Index"])
        c_v1 = b.sample(geo, "EDGE", "INT", cx + 720, cy - 700,
                        n_ev.outputs["Vertex Index 1"], c_edge)
        c_v2 = b.sample(geo, "EDGE", "INT", cx + 720, cy - 860,
                        n_ev.outputs["Vertex Index 2"], c_edge)
        c_p1 = b.sample(geo, "EDGE", "FLOAT_VECTOR", cx + 720, cy - 1020,
                        n_ev.outputs["Position 1"], c_edge)
        c_p2 = b.sample(geo, "EDGE", "FLOAT_VECTOR", cx + 720, cy - 1180,
                        n_ev.outputs["Position 2"], c_edge)
        v1_is_me = b.compare("INT", "EQUAL", cx + 900, cy - 700, c_v1,
                             n_cv.outputs["Vertex Index"])
        a_tidx = b.switch("INT", cx + 1080, cy - 700, v1_is_me, c_v1, c_v2,
                          label="Apex Target Index")
        a_tpos = b.switch("VECTOR", cx + 1080, cy - 900, v1_is_me, c_p1,
                          c_p2, label="Apex Target Position")
        # needle: the PREVIOUS corner is the tiny angle, so the short
        # edge is ours -> next (opposite that corner). Victim = us.
        cos_prev = b.sample(geo, "CORNER", "FLOAT", cx + 900, cy + 200,
                            cos_corner, n_prev.outputs["Corner Index"],
                            label="cos(prev corner)")
        needle_len_ok = b.boolean(
            "OR", cx + 1080, cy + 360, no_limit,
            b.compare("FLOAT", "LESS_EQUAL", cx + 900, cy + 360, len_next,
                      n_in.outputs["Max Edge Length"]))
        is_needle = b.boolean(
            "AND", cx + 1260, cy + 200,
            b.compare("FLOAT", "GREATER_THAN", cx + 1080, cy + 200,
                      cos_prev, cos_sl, label="Prev Corner < Sliver"),
            needle_len_ok, label="Needle (collapsible)")
        n_nv = b.link(
            b.node("GeometryNodeVertexOfCorner", cx + 1080, cy + 520),
            Corner_Index=n_next.outputs["Corner Index"])
        is_sliver = b.boolean(
            "AND", cx + 1620, cy,
            b.boolean("OR", cx + 1440, cy, is_apex, is_needle), is_tri,
            label="Sliver Victim Corner")
        # apex wins over needle when a corner is both
        s_tidx = b.switch("INT", cx + 1440, cy - 700, is_apex,
                          n_nv.outputs["Vertex Index"], a_tidx,
                          label="Sliver Target Index")
        s_tpos = b.switch("VECTOR", cx + 1440, cy - 900, is_apex, p_next,
                          a_tpos, label="Sliver Target Position")
        _s = b.frame("Corner: Sliver Detect (apex / needle)", _s)

        # ---- corner domain: does a fold edge want to move my vertex? ----
        fx, fy = x + 2000, -2400
        me_v = n_cv.outputs["Vertex Index"]

        def fold_wants_me(edge, y, label):
            """(flag, target idx, target pos) of the fold edge `edge`
            if it is folded and names this corner's vertex as victim."""
            fold = b.sample(geo, "EDGE", "BOOLEAN", fx + 360, y, is_fold,
                            edge, label=label)
            victim_v = b.sample(geo, "EDGE", "INT", fx + 360, y - 160,
                                fold_victim_v, edge)
            tidx = b.sample(geo, "EDGE", "INT", fx + 360, y - 320,
                            fold_target_v, edge)
            tpos = b.sample(geo, "EDGE", "FLOAT_VECTOR", fx + 360, y - 480,
                            fold_target_p, edge)
            flag = b.boolean(
                "AND", fx + 720, y, fold,
                b.compare("INT", "EQUAL", fx + 540, y - 160, victim_v, me_v),
                label="Fold Victim Corner")
            return flag, tidx, tpos

        # my vertex is the APEX opposite the fold edge = next edge of
        # the next corner
        n_opp = b.link(
            b.node("GeometryNodeEdgesOfCorner", fx + 180, fy),
            Corner_Index=n_next.outputs["Corner Index"])
        is_fold_victim, f_tidx, f_tpos = fold_wants_me(
            n_opp.outputs["Next Edge Index"], fy, "Opposite Edge Folded")
        # combine: slivers win (their target keeps the long edges)
        victim_c = b.boolean("OR", fx + 1260, fy - 700, is_sliver,
                             is_fold_victim, label="Victim Corner")
        tidx_c = b.switch("INT", fx + 1260, fy - 900, is_sliver, f_tidx,
                          s_tidx, label="Target Index")
        tpos_c = b.switch("VECTOR", fx + 1260, fy - 1100, is_sliver, f_tpos,
                          s_tpos, label="Target Position")
        _s = b.frame("Corner: Fold Victim", _s)

        # ---- point domain: first victim corner of this vertex ----
        px = x + 3400
        n_vidx = b.node("GeometryNodeInputIndex", px, 0, label="Vertex")
        victim_w = b.math("SUBTRACT", px, -220, 1.0, victim_c,
                          label="0 = victim first")
        n_cov = b.link(
            b.node("GeometryNodeCornersOfVertex", px + 180, -220),
            Vertex_Index=n_vidx.outputs["Index"], Weights=victim_w,
            Sort_Index=0)
        c_first = n_cov.outputs["Corner Index"]
        victim = b.sample(geo, "CORNER", "BOOLEAN", px + 360, -220, victim_c,
                          c_first, label="Victim")
        target_idx = b.sample(geo, "CORNER", "INT", px + 360, -380, tidx_c,
                              c_first, label="Target Index")
        target_pos = b.sample(geo, "CORNER", "FLOAT_VECTOR", px + 360, -540,
                              tpos_c, c_first, label="Target Position")
        _s = b.frame("Vertex: Victim -> Target", _s)

        # ---- face mask for the preview ----
        n_ff = b.node("GeometryNodeFieldOnDomain", px + 360, 300,
                      data_type="FLOAT", domain="FACE", label="Fold -> Face")
        b.ln(is_fold, n_ff.inputs["Value"])
        n_af = b.node("GeometryNodeFieldOnDomain", px + 360, 460,
                      data_type="FLOAT", domain="FACE",
                      label="Sliver -> Face")
        b.ln(is_sliver, n_af.inputs["Value"])
        face_mask = b.boolean(
            "OR", px + 720, 380,
            b.compare("FLOAT", "GREATER_THAN", px + 540, 300,
                      n_ff.outputs["Value"], 0.0),
            b.compare("FLOAT", "GREATER_THAN", px + 540, 460,
                      n_af.outputs["Value"], 0.0),
            label="Defect Face")
        b.frame("Face: Preview Mask", _s)
        return victim, target_pos, target_idx, face_mask

    victim, target_pos, target_idx, _ = defect_fields(-600, geo)

    # no chains: a victim whose target is itself moving waits a pass -
    # unless the two target each other, then the lower index moves
    _s = b.snapshot()
    x = 3600
    n_vidx = b.node("GeometryNodeInputIndex", x, -600, label="Vertex")
    target_moving = b.sample(geo, "POINT", "BOOLEAN", x, -300, victim,
                             target_idx, label="Target Is Victim")
    target_target = b.sample(geo, "POINT", "INT", x, -460, target_idx,
                             target_idx, label="Target of Target")
    mutual = b.compare("INT", "EQUAL", x + 180, -460, target_target,
                       n_vidx.outputs["Index"], label="Mutual Pair")
    i_am_lower = b.compare("INT", "LESS_THAN", x + 180, -620,
                           n_vidx.outputs["Index"], target_idx)
    go = b.boolean(
        "OR", x + 540, -300,
        b.boolean("NOT", x + 360, -300, target_moving),
        b.boolean("AND", x + 360, -460, mutual, i_am_lower))
    final_sel = b.boolean("AND", x + 720, -300, victim, go,
                          label="Collapse Now")
    n_setpos = b.node("GeometryNodeSetPosition", x + 900, 0)
    b.ln(geo, n_setpos.inputs["Geometry"])
    b.ln(final_sel, n_setpos.inputs["Selection"])
    b.ln(target_pos, n_setpos.inputs["Position"])
    n_merge = b.node("GeometryNodeMergeByDistance", x + 1080, 0)
    # All mode: fold apexes share no edge, so Connected would not weld
    # them. The distance is tiny - victims sit exactly on their target.
    # Duplicate faces left by a weld are removed by the node itself.
    # Blender 5.x exposes the mode as a menu socket; older builds as a
    # node property.
    if "Mode" in n_merge.inputs:
        n_merge.inputs["Mode"].default_value = "All"
    else:
        n_merge.mode = "ALL"
    n_merge.inputs["Distance"].default_value = WELD_DISTANCE
    b.ln(n_setpos.outputs["Geometry"], n_merge.inputs["Geometry"])
    b.ln(n_merge.outputs["Geometry"], n_rout.inputs["Geometry"])
    geo = n_rout.outputs["Geometry"]
    b.frame("Collapse: Move Onto Target + Weld", _s)

    # ---------------- preview: first-pass defects painted red ----------------
    _s = b.snapshot()
    x = 5400
    _, _, _, face_mask = defect_fields(x, base_geo)
    n_mat = b.node("GeometryNodeSetMaterial", x + 4200, -300)
    n_mat.inputs["Material"].default_value = ensure_preview_material()
    b.ln(base_geo, n_mat.inputs["Geometry"])
    b.ln(face_mask, n_mat.inputs["Selection"])
    out = b.switch("GEOMETRY", x + 4400, 0, n_in.outputs["Preview"], geo,
                   n_mat.outputs["Geometry"])
    b.frame("Preview (red = defect faces)", _s)

    n_out = b.node("NodeGroupOutput", x + 4600, 0)
    b.ln(out, n_out.inputs["Geometry"])
    # Stamp only after a complete build: a half-built group (exception
    # mid-way) must never pass the ensure_group version check.
    ng[VERSION_PROP] = GROUP_VERSION
    return ng


def ensure_group():
    ng = bpy.data.node_groups.get(GROUP_NAME)
    if ng is not None:
        if ng.get(VERSION_PROP) == GROUP_VERSION:
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


class IOPS_OT_ModIron(bpy.types.Operator):
    """Add a geometry-nodes Iron modifier: collapses folded-over flaps
    and sliver triangles (the kinks a merge-based decimate leaves
    behind) so the surface reads flat again"""

    bl_idname = "iops.mod_iron"
    bl_label = "Iron"
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
                 and md.node_group.get(VERSION_PROP) is not None),
                None)
            if existing is not None:
                if existing.node_group is ng:
                    skipped["already present"] = \
                        skipped.get("already present", 0) + 1
                else:
                    upgrade_modifier(existing, ng)
                    upgraded += 1
                continue
            md = obj.modifiers.new("Iron", "NODES")
            if md is None:
                skipped["add failed"] = skipped.get("add failed", 0) + 1
                continue
            md.node_group = ng
            added += 1

        msg = f"Iron: added on {added} object(s)"
        if upgraded:
            msg += f", upgraded on {upgraded}"
        for reason, n in skipped.items():
            msg += f"; {n} skipped ({reason})"
        self.report({"INFO"} if (added or upgraded) else {"WARNING"}, msg)
        return {"FINISHED"}
