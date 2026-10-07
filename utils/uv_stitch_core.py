"""Pure-python UV stitch math (no bpy / mathutils) so pytest can cover it.

stitch_transform: the 2D similarity (uniform scale + rotation +
translation) that moves source edge A onto target edge B. The source
island lands on the side of B that the target island does not occupy
(or the same side with `same_side=True`). Points are (x, y) tuples.
"""
import math

EPS = 1e-8


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _side(line_a, line_b, p):
    """Sign of p relative to the directed line line_a -> line_b."""
    return _cross(_sub(line_b, line_a), _sub(p, line_a))


def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def _similarity(src_a, src_b, dst_a, dst_b, keep_scale=False,
                src_length=None):
    """Similarity mapping src_a->dst_a and src_b->dst_b exactly.

    With keep_scale the island size is left alone: the edge is only
    rotated onto the target direction and centred on the target edge's
    midpoint, so the two edges overlap symmetrically. src_length, when
    given, replaces |src_b - src_a| in the scale: a chain of edges is
    fitted by its path length, not by its end-to-end span."""
    sv = _sub(src_b, src_a)
    dv = _sub(dst_b, dst_a)
    angle = math.atan2(dv[1], dv[0]) - math.atan2(sv[1], sv[0])
    if keep_scale:
        xf = {'pivot': src_a, 'scale': 1.0, 'angle': angle,
              'translation': (0.0, 0.0)}
        moved_mid = apply_similarity(_mid(src_a, src_b), xf)
        xf['translation'] = _sub(_mid(dst_a, dst_b), moved_mid)
        return xf
    scale = math.hypot(*dv) / (src_length or math.hypot(*sv))
    return {'pivot': src_a, 'scale': scale, 'angle': angle,
            'translation': _sub(dst_a, src_a)}


def apply_similarity(p, xf):
    """Apply a transform from stitch_transform to a point."""
    px, py = _sub(p, xf['pivot'])
    s, c = math.sin(xf['angle']), math.cos(xf['angle'])
    sc = xf['scale']
    rx = (px * c - py * s) * sc
    ry = (px * s + py * c) * sc
    return (xf['pivot'][0] + rx + xf['translation'][0],
            xf['pivot'][1] + ry + xf['translation'][1])


def stitch_transform(src_a, src_b, dst_a, dst_b, src_centroid, dst_centroid,
                     same_side=False, keep_scale=False, src_length=None):
    """Return the transform dict, or None for a degenerate edge.

    Tries both endpoint pairings and picks the one that puts the source
    centroid on the free side of the target edge. With no side info
    (target centroid on the edge line) the direct pairing is used.
    keep_scale skips the uniform scale (see _similarity).
    """
    if math.hypot(*_sub(src_b, src_a)) < EPS:
        return None
    if math.hypot(*_sub(dst_b, dst_a)) < EPS:
        return None

    direct = _similarity(src_a, src_b, dst_a, dst_b, keep_scale, src_length)
    occupied = _side(dst_a, dst_b, dst_centroid)
    if abs(occupied) < EPS:
        return direct

    landed = _side(dst_a, dst_b, apply_similarity(src_centroid, direct))
    opposite = (landed * occupied) < 0
    if opposite != same_side:
        return direct
    return _similarity(src_a, src_b, dst_b, dst_a, keep_scale, src_length)


def _wrap_angle(a):
    """Wrap to (-pi, pi]."""
    return math.atan2(math.sin(a), math.cos(a))


def align_rotation(src_a, src_b, dst_a, dst_b, flip=False):
    """Rotation (radians) that makes edge src_a->src_b parallel to
    dst_a->dst_b. Either orientation of the target counts, the smaller
    turn wins; flip picks the other one (a half turn away). None for a
    degenerate edge."""
    sv = _sub(src_b, src_a)
    dv = _sub(dst_b, dst_a)
    if math.hypot(*sv) < EPS or math.hypot(*dv) < EPS:
        return None
    delta = math.atan2(dv[1], dv[0]) - math.atan2(sv[1], sv[0])
    # Parallel either way: fold the difference onto (-pi/2, pi/2].
    delta = _wrap_angle(delta)
    if delta > math.pi / 2:
        delta -= math.pi
    elif delta <= -math.pi / 2:
        delta += math.pi
    if flip:
        delta = _wrap_angle(delta + math.pi)
    return delta


def reflect_point(p, a, b):
    """Mirror p across the infinite line through a and b. A degenerate
    line (a == b) leaves p unchanged."""
    d = _sub(b, a)
    length = math.hypot(*d)
    if length < EPS:
        return p
    d = (d[0] / length, d[1] / length)
    v = _sub(p, a)
    t = v[0] * d[0] + v[1] * d[1]
    foot = (a[0] + d[0] * t, a[1] + d[1] * t)
    return (2.0 * foot[0] - p[0], 2.0 * foot[1] - p[1])


def signed_area(points):
    """Shoelace signed area of a polygon: positive for counter-clockwise
    winding, negative when mirrored."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total * 0.5
