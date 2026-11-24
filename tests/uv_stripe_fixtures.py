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


def wide_band(segments=24, radii=(1.0, 0.8, 0.6), heights=(0.0, 0.1, 0.2)):
    """A closed band several faces wide: ``len(radii) - 1`` rings of ``segments`` quads round the Z axis (a cone
    band; a flat annulus with equal heights). Ring r's vertex i is ``r * segments + i``; face ``r * segments + i``
    lies between angles i and i + 1 and rings r and r + 1, wound counter-clockwise seen from +Z."""
    verts, faces = {}, {}
    for r, (radius, z) in enumerate(zip(radii, heights)):
        for i in range(segments):
            a = 2 * math.pi * i / segments
            verts[r * segments + i] = (radius * math.cos(a), radius * math.sin(a), z)
    for r in range(len(radii) - 1):
        for i in range(segments):
            j = (i + 1) % segments
            faces[r * segments + i] = (r * segments + i, r * segments + j, (r + 1) * segments + j,
                                       (r + 1) * segments + i)
    return verts, faces


def mitred_l(arm=4):
    """A flat L strip two faces wide with a mitred corner, like a picture frame's corner: the outer rail runs from
    (arm + 2, 0) to the corner (0, 0) and up to (0, arm + 2), the inner rail from (arm + 2, 2) to (2, 2) and up to
    (2, arm + 2); the mitre is the line (0, 0) - (1, 1) - (2, 2). Vertex ids: the mitre 0 .. 2, then each arm's
    columns away from the corner, three vertices (rows 0, 1, 2) each. Returns (vertices, faces)."""
    verts = {k: (float(k), float(k), 0.0) for k in range(3)}
    columns = {"x": [[0, 1, 2]], "y": [[0, 1, 2]]}
    nxt = 3
    for c in range(arm):
        for axis in ("x", "y"):
            ids = []
            for k in range(3):
                verts[nxt] = (3.0 + c, float(k), 0.0) if axis == "x" else (float(k), 3.0 + c, 0.0)
                ids.append(nxt)
                nxt += 1
            columns[axis].append(ids)
    faces, fid = {}, 0
    for axis in ("x", "y"):
        cols = columns[axis]
        for c in range(arm):
            for k in range(2):
                a, b, d, e = cols[c][k], cols[c + 1][k], cols[c + 1][k + 1], cols[c][k + 1]
                faces[fid] = (a, b, d, e) if axis == "x" else (a, e, d, b)
                fid += 1
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


def mixed_band(n=12, radii=(1.0, 1.25, 1.5, 1.75), sweep=120.0, fan=True, rounded_end=False):
    """A flat band round an arc, three faces wide, of mixed faces (a reduced stand-in for a user's wide sample):
    vertex i * 4 + r at column i and radius r; the line beside the inner rail (r = 1) runs through two triangles
    (column 4, both sides of it split on a diagonal) and a hexagon (columns 7 and 8 between r = 1 and 2 merged, so
    vertex 8 * 4 + 1 hangs on its long side); with ``fan`` the inner rail's last two columns are four triangles
    fanned round the rail vertex (n - 1, 0), and with ``rounded_end`` the first end's two middle vertices are pushed
    out and its three faces merged into one n-gon (an end with real corners). Returns (verts, faces) as
    {id: (x, y, z)}, {id: vertex ids}."""
    rows = len(radii)
    a = math.radians(sweep)
    verts = {i * rows + r: (rad * math.cos(a * i / n), rad * math.sin(a * i / n), 0.0)
             for i in range(n + 1) for r, rad in enumerate(radii)}

    def v(i, r):
        return i * rows + r

    quads = {(i, r): (v(i, r), v(i + 1, r), v(i + 1, r + 1), v(i, r + 1)) for i in range(n) for r in range(rows - 1)}
    faces = []
    for (i, r), quad in sorted(quads.items()):
        if i == 4 and r in (0, 1):
            faces += [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]
        elif (i, r) == (7, 1):
            faces.append((v(7, 1), v(8, 1), v(9, 1), v(9, 2), v(8, 2), v(7, 2)))
        elif (i, r) == (8, 1):
            continue
        elif fan and r == 0 and i in (n - 2, n - 1):
            continue
        elif rounded_end and i == 0:
            continue
        else:
            faces.append(quad)
    if fan:
        p = v(n - 1, 0)
        faces += [(v(n - 2, 0), p, v(n - 2, 1)), (p, v(n - 1, 1), v(n - 2, 1)), (p, v(n, 1), v(n - 1, 1)),
                  (p, v(n, 0), v(n, 1))]
    if rounded_end:
        for r in (1, 2):
            x, y, z = verts[v(0, r)]
            verts[v(0, r)] = (x, y - 0.12, z)        # the end bulges out past u = 0: two real corners on it
        faces.append((v(0, 0), v(1, 0), v(1, 1), v(1, 2), v(1, 3), v(0, 3), v(0, 2), v(0, 1)))
    return verts, dict(enumerate(faces))


def trim_strip(cols=8, rows=3, width=1.0, height=0.5, taper=0.005, notch=0.3):
    """A flat strip several faces wide shaped like a user's trim piece (vertex (i, j) is i + j * (cols + 1)): it
    tapers (row j shrinks by ``taper`` * j about the middle, so its ends slant), its first end's corner on the
    near rail is chamfered (moved 0.8 of a cell along the rail, so the end turns sharply at (0, 1) and its own
    line runs from there), and its far rail has a notch (the vertices at columns 3 and 4 pushed in by ``notch``).
    Returns (verts, faces)."""
    mid = cols * width / 2.0
    verts = {}
    for j in range(rows + 1):
        for i in range(cols + 1):
            verts[i + j * (cols + 1)] = (mid + (i * width - mid) * (1.0 - taper * j), j * height, 0.0)
    verts[0] = (verts[0][0] + 0.8 * (verts[1][0] - verts[0][0]), 0.0, 0.0)
    for i in (3, 4):
        v = i + rows * (cols + 1)
        verts[v] = (verts[v][0], rows * height - notch, 0.0)
    faces = {}
    for j in range(rows):
        for i in range(cols):
            a = i + j * (cols + 1)
            faces[len(faces)] = (a, a + 1, a + cols + 2, a + cols + 1)
    return verts, faces


def fan_band(n=8, radii=(1.0, 1.3, 1.6, 1.9), sweep=120.0, pentagon=5):
    """A flat C-shaped band round an arc, three faces wide, whose outer row is a fan (a reduced stand-in for a
    user's wide strip): the inner three rings have ``n`` + 1 vertices (ring r, column i: vertex r * (n + 1) + i),
    the outer rim twice as many columns (vertex 3 * (n + 1) + j, j = 0 .. 2n), so every outer column is a quad
    and a triangle side by side (column ``pentagon`` one pentagon instead). Every vertex where the outer row meets
    the middle one has five edges: no cross path (``uv_stripe_split_core.cross_path``) runs from rail to rail
    through it. Returns (verts, faces) as {id: (x, y, z)}, {id: vertex ids}."""
    a = math.radians(sweep)
    verts = {}

    def ring(r, count):
        start = r * (n + 1)
        for j in range(count + 1):
            verts[start + j] = (radii[r] * math.cos(a * j / count), radii[r] * math.sin(a * j / count), 0.0)
        return [start + j for j in range(count + 1)]

    rings = [ring(r, n) for r in range(3)] + [ring(3, 2 * n)]
    faces = []
    for r in range(2):
        for i in range(n):
            faces.append((rings[r][i], rings[r][i + 1], rings[r + 1][i + 1], rings[r + 1][i]))
    for i in range(n):
        lo, hi = rings[2][i], rings[2][i + 1]
        c, m, d = rings[3][2 * i], rings[3][2 * i + 1], rings[3][2 * i + 2]
        if i == pentagon:
            faces.append((lo, hi, d, m, c))
        else:
            faces += [(lo, hi, d, m), (lo, m, c)]
    return verts, dict(enumerate(faces))
