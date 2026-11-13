"""Shared UV Stripe fixtures (no pytest, no bpy): used by the pure tests and the headless Blender tests."""
import math

# A user's flat strip of three n-gons (quads whose rails carry extra vertices), turning 38.3 and 21.8 degrees.
NGON_VERTS = {
    86: (4.279, 6.583), 142: (3.669, 6.234), 144: (3.242, 5.989), 43: (3.486, 5.777), 115: (4.562, 6.393),
    136: (2.17, 2.164), 135: (2.17, 1.486), 99: (2.475, 1.486), 68: (2.475, 1.782), 40: (2.475, 3.255),
    143: (2.17, 3.314), 137: (2.17, 2.842), 138: (2.253, 3.521), 80: (2.981, 4.516), 141: (3.068, 5.555),
    140: (2.796, 4.877), 139: (2.524, 4.199),
}
NGON_VERTS = {v: (x, y, 4.3) for v, (x, y) in NGON_VERTS.items()}
NGON_FACES = {
    94: (86, 142, 144, 43, 115),
    104: (136, 135, 99, 68, 40, 143, 137),
    105: (138, 143, 40, 80, 43, 144, 141, 140, 139),
}


def exact_ngon_verts():
    """The n-gon strip's topology on exact geometry: width 0.305 between straight mitred rails, headings 90, 68.2
    and 29.9 degrees (turns 21.8 and 38.3), the extra rail vertices where the user's are, the far end slanted.
    The captured coordinates are rounded to 0.001, which bends their rails by up to 0.1 degree."""
    w, heads, lengths = 0.305, [math.radians(a) for a in (90.0, 68.2, 29.9)], [1.8, 2.5, 1.2]
    pts = [(2.3225, 1.486)]
    for h, length in zip(heads, lengths):
        pts.append((pts[-1][0] + length * math.cos(h), pts[-1][1] + length * math.sin(h)))

    def rail(i, side):
        n0 = (-math.sin(heads[max(i - 1, 0)]), math.cos(heads[max(i - 1, 0)]))
        n1 = (-math.sin(heads[min(i, 2)]), math.cos(heads[min(i, 2)]))
        b = (n0[0] + n1[0], n0[1] + n1[1])
        scale = w / 2.0 / (b[0] * n0[0] + b[1] * n0[1])
        return (pts[i][0] + side * b[0] * scale, pts[i][1] + side * b[1] * scale)

    left, right = [rail(i, 1) for i in range(4)], [rail(i, -1) for i in range(4)]
    left[3] = (left[3][0] + 0.3 * math.cos(heads[2]), left[3][1] + 0.3 * math.sin(heads[2]))   # slanted end

    def at(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    xy = {135: left[0], 143: left[1], 144: left[2], 86: left[3], 99: right[0], 40: right[1], 43: right[2],
          115: right[3], 136: at(left[0], left[1], 0.4), 137: at(left[0], left[1], 0.75),
          68: at(right[0], right[1], 0.16), 138: at(left[1], left[2], 0.09), 139: at(left[1], left[2], 0.35),
          140: at(left[1], left[2], 0.6), 141: at(left[1], left[2], 0.86), 80: at(right[1], right[2], 0.5),
          142: at(left[2], left[3], 0.6)}
    return {v: (x, y, 4.3) for v, (x, y) in xy.items()}


def flat_annulus(segments=8, outer=1.0, inner=0.5):
    """A flat ring of quads in the XY plane, wound counter-clockwise: outer vertices 0 .. segments - 1 and
    inner vertices segments .. 2 * segments - 1, face i between angles i and i + 1."""
    verts = {}
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts[i] = (outer * math.cos(a), outer * math.sin(a), 0.0)
        verts[segments + i] = (inner * math.cos(a), inner * math.sin(a), 0.0)
    faces = {i: (i, (i + 1) % segments, segments + (i + 1) % segments, segments + i) for i in range(segments)}
    return verts, faces


def flat_annulus_with_triangle(segments=8, outer=1.0, inner=0.5):
    """``flat_annulus`` with face 0 split into two triangles, faces 0 and ``segments``."""
    verts, faces = flat_annulus(segments, outer, inner)
    a, b, c, d = faces[0]
    faces[0] = (a, b, c)
    faces[segments] = (a, c, d)
    return verts, faces


# A flat strip of five faces whose far rail carries an unmerged double (28 and 21, 0.0002 apart, the strip about
# 0.22 wide), turning about 30 degrees at the double and again at 92 / 24. Coordinates rounded to 1e-4.
DOUBLE_VERTS = {
    167: (1.5193, 1.4862), 168: (1.7251, 1.4862), 90: (1.7145, 3.3180), 26: (1.5191, 3.3177),
    89: (1.7123, 4.8160), 28: (1.5191, 4.9276), 21: (1.5189, 4.9277), 92: (1.9831, 5.2904),
    24: (1.7923, 5.4007), 88: (2.1399, 5.3809), 91: (3.2097, 5.9984), 86: (3.1118, 6.1623),
    108: (4.2526, 6.6003), 107: (4.0757, 6.7186),
}
DOUBLE_VERTS = {v: (x, y, 6.217) for v, (x, y) in DOUBLE_VERTS.items()}
DOUBLE_FACES = {
    67: (167, 168, 90, 26),
    144: (26, 90, 89, 28),
    65: (21, 28, 89, 92, 24),
    64: (24, 92, 88, 91, 86),
    77: (86, 91, 108, 107),
}


# A strip of three faces whose end face is a hexagon with a step in one rail: rail 13 -> 2 on one side, and on the
# other 19 -> 22, a short step 22 -> 21 across the rail (the strip narrows), then 21 -> 5; the real end cap is 5-2.
STEP_VERTS = {
    24: (-0.00006, 0.55901, 0.01200), 25: (-0.00006, 0.53352, 0.02241), 18: (0.23537, 0.53352, 0.02241),
    12: (0.25381, 0.55901, 0.01200), 19: (0.28180, 0.48996, 0.02225), 13: (0.30726, 0.50556, 0.01181),
    2: (0.30726, -0.00019, 0.01031), 22: (0.28180, 0.35219, 0.02177), 21: (0.29752, 0.35221, 0.01529),
    5: (0.29752, -0.00021, 0.01432),
}
STEP_FACES = {
    0: (24, 25, 18, 12),
    1: (18, 19, 13, 12),
    20: (2, 13, 19, 22, 21, 5),
}
