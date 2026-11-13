"""Synthetic UV Pipe fixtures (no pytest, no bpy): meshes as ``(verts, faces)`` dicts.

``verts`` maps vertex ids to (x, y, z), ``faces`` maps face ids to vertex ids in winding order; every mesh is
wound with its normals pointing out of the tube. A ring's vertex ``i`` sits at angle ``2 * pi * i / sides`` round
the tube's axis; vertex ids are handed out ring by ring in build order.
"""
import math


def _ring(verts, sides, centre, e1, e2, radius, phase=0.0):
    """Add one ring of ``sides`` vertices round ``centre`` in the plane of the unit axes e1, e2; return its ids."""
    ids = []
    for i in range(sides):
        a = 2.0 * math.pi * i / sides + phase
        c, s = radius * math.cos(a), radius * math.sin(a)
        vid = len(verts)
        verts[vid] = tuple(centre[k] + c * e1[k] + s * e2[k] for k in range(3))
        ids.append(vid)
    return ids


def _add(faces, face):
    faces[len(faces)] = tuple(face)


def _wall(faces, rings):
    """Quads between consecutive rings; outward when e1 x e2 points from one ring to the next."""
    for lo, hi in zip(rings, rings[1:]):
        n = len(lo)
        for i in range(n):
            j = (i + 1) % n
            _add(faces, (lo[i], lo[j], hi[j], hi[i]))


def _capped(sides, rows, radius, height, bottom_rings, top_rings, bottom_fan, phase=0.0):
    verts, faces = {}, {}
    x, y = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    wall = [_ring(verts, sides, (0.0, 0.0, height * k / rows), x, y, radius, phase) for k in range(rows + 1)]
    _wall(faces, wall)
    outer = wall[0]                                   # bottom cap, normal -Z
    for r in bottom_rings:
        inner = _ring(verts, sides, (0.0, 0.0, 0.0), x, y, r, phase)
        for i in range(sides):
            j = (i + 1) % sides
            _add(faces, (outer[i], inner[i], inner[j], outer[j]))
        outer = inner
    if bottom_fan:
        c = len(verts)
        verts[c] = (0.0, 0.0, 0.0)
        for i in range(sides):
            _add(faces, (c, outer[(i + 1) % sides], outer[i]))
    else:
        _add(faces, reversed(outer))
    outer = wall[-1]                                  # top cap, normal +Z
    for r in top_rings:
        inner = _ring(verts, sides, (0.0, 0.0, height), x, y, r, phase)
        for i in range(sides):
            j = (i + 1) % sides
            _add(faces, (outer[i], outer[j], inner[j], inner[i]))
        outer = inner
    _add(faces, outer)
    return verts, faces


def capped_cylinder(sides=32, rows=4, radius=1.0, height=2.0, bottom_rings=(0.671, 0.493), top_rings=(0.671,)):
    """A cylinder on the Z axis from z = 0 to ``height``, ``rows`` quad rows on the wall. The bottom cap (z = 0) is
    one flat quad ring per radius in ``bottom_rings`` (outer to inner) round a triangle fan; the top cap one flat quad
    ring per radius in ``top_rings`` round one n-gon. The defaults are the spec's Reference A. Wall ring k (k = 0 at
    the bottom) holds vertex ids ``k * sides .. k * sides + sides - 1``."""
    return _capped(sides, rows, radius, height, bottom_rings, top_rings, bottom_fan=True)


def box_tube():
    """A 4-sided capped tube: a box 2 wide (faces axis-aligned), z = 0 .. 2, two quad rows on the wall, each cap one
    quad. Its rim corners turn 90 degrees, sharper than the default Loop Angle."""
    return _capped(4, 2, math.sqrt(2.0), 2.0, (), (), bottom_fan=False, phase=math.pi / 4.0)


def open_tube(sides=12, rows=4, twist=0.0):
    """An uncapped tube on the Z axis, radius 1, z = 0 .. 2, ``rows`` quad rows. ``twist`` (radians) turns every odd
    ring by that angle round the axis, so the lengthwise edges zigzag. Ring k holds ids ``k * sides ..``."""
    verts, faces = {}, {}
    x, y = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    rings = [_ring(verts, sides, (0.0, 0.0, 2.0 * k / rows), x, y, 1.0, twist if k % 2 else 0.0)
             for k in range(rows + 1)]
    _wall(faces, rings)
    return verts, faces


def _bend_frames(segments, bend_radius=2.0, run=2.0, run_rows=2):
    """Frames (centre, e1, e2) of a tube running up +Z, turning 90 degrees toward +X round the line x = bend_radius,
    y = 0 in ``segments`` steps, then running along +X. e1 points to the inside of the bend, e2 is +Y; the first
    run starts at z = -run, the bend starts at the origin. Returns the frames and the index of the bend's first."""
    frames = [((0.0, 0.0, -run + run * k / run_rows), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) for k in range(run_rows)]
    first = len(frames)
    for k in range(segments + 1):
        a = 0.5 * math.pi * k / segments
        centre = (bend_radius - bend_radius * math.cos(a), 0.0, bend_radius * math.sin(a))
        frames.append((centre, (math.cos(a), 0.0, -math.sin(a)), (0.0, 1.0, 0.0)))
    end = frames[-1][0]
    for k in range(1, run_rows + 1):
        frames.append(((end[0] + run * k / run_rows, end[1], end[2]), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
    return frames, first


def clean_bend(sides=12, bend_rings=4):
    """An uncapped tube of radius 1: a straight run of 2 up +Z, a 90-degree bend (centre line radius 2) divided into
    ``bend_rings`` equal segments of clean quad rings, a straight run of 2 along +X."""
    verts, faces = {}, {}
    frames, _ = _bend_frames(bend_rings)
    rings = [_ring(verts, sides, c, e1, e2, 1.0) for c, e1, e2 in frames]
    _wall(faces, rings)
    return verts, faces


def bent_pipe(sides=12):
    """The spec's Reference B, reduced: ``clean_bend(sides, 4)`` with the inside of the bend collapsed and both
    ends capped by n-gons. The inner vertices (index 0) of the bend's three middle rings are merged into one pole
    placed halfway between the inner vertices of the bend's end rings, so the pole has eight edges and the four
    quads between those rings beside it become triangles. The lengthwise line along the inside runs straight
    through the pole and turns 45 degrees where the bend meets each straight run."""
    verts, faces = {}, {}
    frames, first = _bend_frames(4)
    rings = [_ring(verts, sides, c, e1, e2, 1.0) for c, e1, e2 in frames]
    _wall(faces, rings)
    _add(faces, reversed(rings[0]))
    _add(faces, rings[-1])
    start, end = verts[rings[first][0]], verts[rings[first + 4][0]]
    pole = rings[first + 2][0]
    verts[pole] = tuple((a + b) / 2.0 for a, b in zip(start, end))
    merged = {rings[first + 1][0]: pole, rings[first + 3][0]: pole}
    out = {}
    for fid, face in faces.items():
        ids = [merged.get(v, v) for v in face]
        ids = [v for i, v in enumerate(ids) if v != ids[i - 1]]
        out[fid] = tuple(ids)
    for v in merged:
        del verts[v]
    return verts, out


def torus(major=12, minor=8):
    """A closed torus round the Z axis: ring radius 2, tube radius 0.5, vertex (i, j) has id ``i * minor + j``."""
    verts, faces = {}, {}
    for i in range(major):
        t = 2.0 * math.pi * i / major
        for j in range(minor):
            p = 2.0 * math.pi * j / minor
            r = 2.0 + 0.5 * math.cos(p)
            verts[i * minor + j] = (r * math.cos(t), r * math.sin(t), 0.5 * math.sin(p))
    for i in range(major):
        for j in range(minor):
            i1, j1 = (i + 1) % major, (j + 1) % minor
            _add(faces, (i * minor + j, i1 * minor + j, i1 * minor + j1, i * minor + j1))
    return verts, faces
