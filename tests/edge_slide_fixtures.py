"""Edge Slide band fixtures shared by the pure-Python tests and the headless Blender tests.

Stdlib only, no pytest: ``tests/blender/test_edge_slide.py`` imports this module inside Blender, where
``utils`` names the add-on's own package, and builds each band as a bmesh mesh. ``test_edge_slide_core``
and ``test_edge_slide_wave`` import these builders back under the same names.
"""

import dataclasses
import math
import random

from utils.edge_slide_core import Band


def _band(pts, faces, chain, side_faces, closed=False, end_edges=(None, None)):
    verts = {i: (float(p[0]), float(p[1]), float(p[2])) for i, p in enumerate(pts)}
    return Band(verts=verts, faces=faces, chain=chain, closed=closed, side_faces=side_faces, end_edges=end_edges)


def ring():
    pts = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)]
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6), 3: (3, 0, 4, 7)}
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2, 3], closed=True)


def u_in_grid():
    # A U-shaped open chain in a 7x6 grid of unit quads (vertex y*8+x, face y*7+x), the side
    # inside the U; the end edges (1,4)->(2,4) and (6,4)->(5,4) run across its mouth.
    pts = [(x, y, 0) for y in range(7) for x in range(8)]
    faces = {
        y * 7 + x: (y * 8 + x, y * 8 + x + 1, (y + 1) * 8 + x + 1, (y + 1) * 8 + x)
        for y in range(6) for x in range(7)
    }
    corners = [(1, 4), (1, 3), (1, 2), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (6, 2), (6, 3), (6, 4)]
    side = [(1, 3), (1, 2), (1, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (5, 1), (5, 2), (5, 3)]
    return _band(pts, faces, [y * 8 + x for x, y in corners], [y * 7 + x for x, y in side], end_edges=(34, 37))


def jittered_grid(seed, jitter=0.3):
    # A 10 x 8 grid of unit quads (vertex y*11+x), each inner vertex moved by up to ``jitter`` along x and along y,
    # seeded; the open chain runs along the bottom border from (2,0) to (8,0), the end edges up from its ends.
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    pts = []
    for y in range(9):
        for x in range(11):
            inner = 0 < y < 8 and 0 < x < 10
            pts.append((x + rnd.uniform(-jitter, jitter), y + rnd.uniform(-jitter, jitter), 0) if inner else (x, y, 0))
    faces = {y * 10 + x: (y * 11 + x, y * 11 + x + 1, (y + 1) * 11 + x + 1, (y + 1) * 11 + x)
             for y in range(8) for x in range(10)}
    return _band(pts, faces, list(range(2, 9)), list(range(2, 8)), end_edges=(13, 19))


def chamfer_ring():
    # A square with chamfered corners, the band inside; segments 1, 3, 5 and the closing 7 are chamfers.
    h, c = 2.0, 0.2
    pts = [(-h + c, -h, 0), (h - c, -h, 0), (h, -h + c, 0), (h, h - c, 0),
           (h - c, h, 0), (-h + c, h, 0), (-h, h - c, 0), (-h, -h + c, 0)]
    return _band(pts, {0: tuple(range(8))}, list(range(8)), [0] * 8, closed=True)


def fanned_u(fan=0.6):
    # u_in_grid with its rows fanned out from the bottom (y = 1): a point's height over it is scaled by 1 - fan at the
    # left arm (x = 1), growing linearly to 1 at the right arm (x = 6). The left arm is 1.2 deep, the right one 3, so
    # the mouth's end wall rises from the start end, and the bottom-left corner reaches it before the arms meet.
    b = u_in_grid()
    return dataclasses.replace(
        b, verts={v: (x, 1.0 + (y - 1.0) * (1.0 - fan * (6.0 - x) / 5.0), z) for v, (x, y, z) in b.verts.items()})


def jittered_u(seed, jitter=0.25, fan=0.0):
    # fanned_u(fan) (u_in_grid for fan 0) with every vertex off the chain moved by up to ``jitter`` along x and y,
    # seeded: its corners fold, and fanned, its start end absorbs the corner.
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    b = fanned_u(fan)
    keep = set(b.chain)
    return dataclasses.replace(b, verts={
        v: p if v in keep else (p[0] + rnd.uniform(-jitter, jitter), p[1] + rnd.uniform(-jitter, jitter), p[2])
        for v, p in sorted(b.verts.items())})


def chain_jittered_u(seed, chain_jitter=0.12, jitter=0.1, fan=0.6):
    # fanned_u(fan) with the chain's inner vertices moved by up to ``chain_jitter`` and every vertex off the chain by up
    # to ``jitter``, along x and y, seeded; the chain ends stay. Its chain bends at every vertex, so default mode's rails
    # carry a width error, and an end that absorbs a rail vertex keeps one.
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    b = fanned_u(fan)
    ends = {b.chain[0], b.chain[-1]}
    verts = {}
    for v, (x, y, z) in sorted(b.verts.items()):
        j = 0.0 if v in ends else chain_jitter if v in b.chain else jitter
        verts[v] = (x + rnd.uniform(-j, j), y + rnd.uniform(-j, j), z)
    return dataclasses.replace(b, verts=verts)


def _flat_band(points, loops, chain, side_faces, closed=False, end_edges=(None, None)):
    # A flat band from named (x, y) points: ``loops`` and ``chain`` list point names, ``side_faces`` face indices.
    ids = {name: i for i, name in enumerate(points)}
    return Band(verts={ids[p]: (float(x), float(y), 0.0) for p, (x, y) in points.items()},
                faces={f: tuple(ids[p] for p in loop) for f, loop in enumerate(loops)},
                chain=[ids[p] for p in chain], closed=closed, side_faces=side_faces,
                end_edges=tuple(None if p is None else ids[p] for p in end_edges))


def u_wall():
    # The user's U case in small: an open U chain c0..c9, the side inside it, whose arm tops lean out so that the arms
    # bend at their second vertices c1 = (1,3) and c8 = (5,3), which therefore stand out into the side. The end edges
    # c0-m1 and c9-m1' run along the mouth y = 4. Under the mouth two holes (open edges, no faces) stand in front of
    # c1 and c8: hole 1 is a-b-c-d = (1.5,3) (2.5,3) (2.5,3.6) (1.3,3.6), hole 2 its mirror in x = 3. By hand:
    # - c1 is a miter: its wedge is the one face F0, 225 degrees. Its offset edges are edge 0 (c0 (0,4) -> c1, side
    #   normal (1,1)/sqrt2: x + y = 4 + sqrt2 w) and edge 1 (x = 1 + w), so it runs on (1 + w, 3 + (sqrt2 - 1) w).
    # - It meets hole 1's left side a-d, x = 1.5 - (y - 3) / 3, at w = 1.5 / (2 + sqrt2) = 0.439340, at (1.43934,
    #   3.18198): before anything else. The start end on the mouth is at (sqrt2 w, 4); segment 2 (c2 = (1,0) at
    #   (1 + w, w), c3 = (1.5,0) at (1.5, w)) folds at 0.5; corner d lies 0.9 / sqrt2 = 0.636 from edge 0's line and
    #   corner a is reached by edge 1's line x = 1 + w at 0.5. So collapse (C) stops at 0.439340: c1 has no room.
    # - In D, c1 opens the loop there. Its left end slides up a-d and on along the hole's top d-c on x + y = 4 + sqrt2 w
    #   (at w = 0.75: (1.46066, 3.6)); its right end slides down a-d and on along a-b on x = 1 + w (at 0.75: (1.75, 3)).
    #   c8 does the same on hole 2. At 0.75 the loop is three pieces with two breaks, every end on a hole's edge.
    # - The left end's wall heads back at c = (2.5,3.6) (down c-b, toward edge 0's line), which it reaches at
    #   w = 2.1 / sqrt2 = 1.484924 (and the snap); the right end's runs level up b-c (x = 2.5), from b, which it reaches
    #   at w = 1.5 (and the snap). c and b are the hole's corners, on the open border: an end there has landed, and
    #   stays. c8's ends do the same on c' and b'. The middle piece, b - (c2..c4) - (c5..c7) - b', closes into a ridge
    #   where its two groups, on (1 + w, w) and (5 - w, w), meet at w = 2: (3, 2), its final state, b - (3, 2) - b'.
    # - The outer pieces go on. c0's piece is its start on the mouth at (sqrt2 w, 4) and c1's left end, staying on c:
    #   segment 0 runs from one to the other, (2.5 - sqrt2 w + 0.4) / sqrt2 = 2.9 / sqrt2 - w long along chain edge 0,
    #   and folds at w = 2.9 / sqrt2 = 2.050610, the start on (2.9, 4): pressed onto its walls, the piece leaves the
    #   start's point and c, a break between them. c8's piece does the same on c' and (3.1, 4). D's limit is there.
    pts = {"c0": (0, 4), "c1": (1, 3), "c2": (1, 0), "c3": (1.5, 0), "c4": (2.5, 0), "c5": (3.5, 0), "c6": (4.5, 0),
           "c7": (5, 0), "c8": (5, 3), "c9": (6, 4), "a": (1.5, 3), "b": (2.5, 3), "c": (2.5, 3.6), "d": (1.3, 3.6),
           "a'": (4.5, 3), "b'": (3.5, 3), "c'": (3.5, 3.6), "d'": (4.7, 3.6), "m1": (1.3, 4), "m2": (2.5, 4),
           "m2'": (3.5, 4), "m1'": (4.7, 4)}
    loops = [("c0", "c1", "c2", "c3", "a", "d", "m1"), ("c3", "c4", "b", "a"), ("c4", "c5", "b'", "b"),
             ("b", "b'", "c'", "c"), ("c", "c'", "m2'", "m2"), ("d", "c", "m2", "m1"),
             ("m1'", "d'", "a'", "c6", "c7", "c8", "c9"), ("a'", "b'", "c5", "c6"), ("m1'", "m2'", "c'", "d'")]
    chain = ["c0", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9"]
    return _flat_band(pts, loops, chain, [0, 0, 0, 1, 2, 7, 6, 6, 6], end_edges=("m1", "m1'"))


def hole_rim(dx=0.0, dy=0.0):
    # A closed diamond chain B (2,4) -> R (3,5) -> T (2,6) -> L (1,5) round a hole in a 7 x 10 grid of unit quads,
    # sliding outward. The four quads round the hole's centre (2,5) are cut along the diamond's edges, and only their
    # outer triangles are faces. Every corner is 270 degrees outside, and its rail runs straight out along the
    # bisector, where the balanced width is t / sqrt2 at t along it, exact. By hand:
    # - L reaches the border x = 0 at (0,5), at w = 1 / sqrt2 = 0.707107; B, T and R reach theirs 4 out, at 2.828427.
    # - From there L is two ends on x = 0, on the offset lines of edges T-L (y = 4 + sqrt2 w) and L-B (y = 6 - sqrt2 w):
    #   at w = 2.5 (0, 7.535534) and (0, 2.464466). Their feet lie on the edges (from w = sqrt2 on), so each is 2.5 from
    #   the chain. L is chain[3], so the break lies mid-way round the points, not at the wrap.
    # - The pieces next to L's ends are used up where those offset lines pass the grid's corners (0,0) and (0,10), at
    #   6 / sqrt2 = 4.242641: past 2.5. Each is pressed into its corner, and the other two go on: the offset lines of
    #   B-R (y = x + 2 - sqrt2 w) and R-T (y = 8 - x + sqrt2 w) pass (7,0) and (7,10) at 9 / sqrt2 = 6.363961, where
    #   the last pieces are used up: D's limit.
    # ``dx`` and ``dy`` shift the diamond (and its hole) on the grid.
    cx, cy = 2.0 + dx, 5.0 + dy
    corner = {(2, 4): (cx, cy - 1), (3, 5): (cx + 1, cy), (2, 6): (cx, cy + 1), (1, 5): (cx - 1, cy)}
    pts = {(x, y): corner.get((x, y), (x, y)) for y in range(11) for x in range(8) if (x, y) != (2, 5)}
    cut = {(2, 4): ((2, 4), (3, 4), (3, 5)), (2, 5): ((3, 5), (3, 6), (2, 6)), (1, 5): ((2, 6), (1, 6), (1, 5)),
           (1, 4): ((1, 5), (1, 4), (2, 4))}   # the outer triangle of each quad round the hole, by its corner
    loops = []
    for y in range(10):
        for x in range(7):
            q = cut.get((x, y), ((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)))
            loops.append(q)
    side = [loops.index(cut[q]) for q in ((2, 4), (2, 5), (1, 5), (1, 4))]
    return _flat_band(pts, loops, [(2, 4), (3, 5), (2, 6), (1, 5)], side, closed=True)


def bumped_arm():
    # One flat face: an open straight chain c0 (0,0) - c1 (1,0) - c2 (2,-1) - c3 (3,0) - c4 (4,0), its middle vertex
    # bumped down off y = 0, the side above, up to y = 6; the end edges run up x = 0 and x = 4. Every vertex is a miter
    # (one face, no rails), so both modes agree. By hand:
    # - c1 and c3 stand out into the side (225 degrees): c1 runs on (1 + (sqrt2 - 1) w, w), c3 on its mirror; c2 runs up
    #   x = 2 on (2, sqrt2 w - 1). Segments 1 and 2 fold together at w = 1 / (sqrt2 - 1) = 2.414214, where all three
    #   meet at (2, 2.414214).
    # - The group's outer edges 0 and 3 are collinear, so their offset lines never cross: collapse (C) stops at the fold.
    #   In D the group carries on from its fold point along their shared normal, on y = w: the loop is the straight
    #   line from (0, w) to (4, w).
    # - At y = 6 the whole loop reaches the top: the group cuts there and its ends, on the level top, stay; the end
    #   walls x = 0 and x = 4 end there too (and the snap), and the ends, finding nothing to land on, stay: D stops.
    pts = {"c0": (0, 0), "c1": (1, 0), "c2": (2, -1), "c3": (3, 0), "c4": (4, 0), "TR": (4, 6), "TL": (0, 6)}
    return _flat_band(pts, [("c0", "c1", "c2", "c3", "c4", "TR", "TL")], ["c0", "c1", "c2", "c3", "c4"], [0, 0, 0, 0],
                      end_edges=("TL", "TR"))


def notch_spike():
    # One flat face: an open V chain A (-2,1.7) - B (-0.3,0) - C (0.3,0) - D (2,1.7), the side inside it, up to y = 5, with
    # a notch cut down from the top to a spike tip T = (0,1.2) (sides T-L to (-0.2,2.2) and T-R to (0.2,2.2), open
    # edges). The end edges run up x = -2 and x = 2. Every vertex is a miter (one face, no rails). By hand:
    # - B runs on (-0.3 + (sqrt2 - 1) w, w) and C on its mirror, so segment 1 folds at 0.3 / (sqrt2 - 1) = 0.724264. The
    #   group's point is where the offset lines of A-B (x + y = -0.3 + sqrt2 w) and C-D meet: (0, sqrt2 w - 0.3).
    # - It reaches T at 1.5 / sqrt2 = 1.060660, exactly on its bisector, while the segments either side still pass
    #   clear of the spike (its sides lean 11.3 degrees off the bisector, the segments 45). The loop opens there: the left
    #   end slides up T-L on A-B's line, at w = 1.3 on (-0.084619, 1.623097), the right end up T-R on C-D's line.
    # - The end walls x = -2 and x = 2 end at the top at 3.3 / sqrt2 = 2.333452 (and the snap): the ends shoot on along
    #   their offset lines, which leave the band at once, and stay there. The cut's ends reach the notch's top corners
    #   NL and NR at 5.1 / sqrt2 = 3.606245 (and the snap) and stay there too: nothing moves any more, and D stops.
    # A group is a convex corner, which runs into the wedge between its own two segments: only a wall vertex exactly on
    # its bisector meets the point first: within the trace's vertex snap (tol), so a 1e-9 tilt changes nothing. Moved
    # further off, the segment beside the point meets T first, a corner inside a segment, which is no event yet.
    pts = {"A": (-2, 1.7), "B": (-0.3, 0), "C": (0.3, 0), "D": (2, 1.7), "TR": (2, 5), "NR": (0.2, 5), "R": (0.2, 2.2),
           "T": (0, 1.2), "L": (-0.2, 2.2), "NL": (-0.2, 5), "TL": (-2, 5)}
    loops = [("A", "B", "C", "D", "TR", "NR", "R", "T", "L", "NL", "TL")]
    return _flat_band(pts, loops, ["A", "B", "C", "D"], [0, 0, 0], end_edges=("TL", "TR"))


def jittered_u_wall(seed, jitter=0.1):
    # u_wall with every point off the chain moved by up to ``jitter`` along x and y, seeded: the holes and the mouth
    # move, so the arms' second vertices reach the holes at other widths and the ends slide along bent walls.
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    b = u_wall()
    keep = set(b.chain)
    return dataclasses.replace(b, verts={
        v: p if v in keep else (p[0] + rnd.uniform(-jitter, jitter), p[1] + rnd.uniform(-jitter, jitter), p[2])
        for v, p in sorted(b.verts.items())})


def jittered_hole_rim(seed, jitter=0.2, shift=0.3):
    # hole_rim with its diamond shifted by up to ``shift`` and every grid point off the chain moved by up to
    # ``jitter``, along x and y, seeded: the corners reach a jagged border at other widths, in another order.
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    b = hole_rim(rnd.uniform(-shift, shift), rnd.uniform(-shift, shift))
    keep = set(b.chain)
    return dataclasses.replace(b, verts={
        v: p if v in keep else (p[0] + rnd.uniform(-jitter, jitter), p[1] + rnd.uniform(-jitter, jitter), p[2])
        for v, p in sorted(b.verts.items())})


def shoot_strip(slant_deg=0.0, no_landing=False):
    # An open straight chain c0 (0,0) .. c4 (4,0), the side above. Face F0 is the row c0..c4, r (4,1), v (0,1) under it;
    # F1 the L-shaped face above F0 and left of c0-v, up to y = 3 (b1, c0, v, r, tr (4,3), t1); F2 the column left of
    # b1-t1, to x = -4. The end edges run up c0-v and c4-r. Every chain vertex is a miter (one face, F0), so both
    # modes agree. By hand:
    # - The start's end wall is c0-v alone: past v its only onward edge v-r turns 90 degrees. Its offset line y = w
    #   leaves the wall at v at width 1, where today's slide clamps (by the anchor snap, 1.000002). The interior
    #   vertices run straight up x = 1, 2, 3 to F1's top at 3; the end's wall runs up x = 4 to tr, at 3 too.
    # - Destructive (D) shoots the start on at v: its offset line y = 1 runs on away from c1, through F1, and crosses
    #   b1-t1, the vertical edge x = -1.5, 1.5 further on, at (-1.5, 1): perpendicular to the line, so the end lands
    #   there and slides up b1-t1 on y = w, its wall now: at 1.5 it is on b1-t1 at (-1.5, 1.5).
    # - ``slant_deg`` leans b1-t1 off vertical by that angle, through (-1.5, 1) still. At 40 degrees it lies 50 off
    #   the line, more than a Shoot Angle of 30 allows: the line goes on through F2 and lands on its open side x = -4.
    #   A Shoot Angle of 45 takes b1-t1.
    # - ``no_landing``: no faces left of c0-v; F1 is v, r, tr, tn (-2,3), whose side v-tn turns 45 degrees off the end
    #   edge, more than Rail Bend, so the wall still ends at v. The line y = 1 leaves the band at v at once (F1 holds
    #   v's directions from 0 to 135 degrees only): the end stays on v for every greater width.
    # Vertex ids: c0..c4 are 0..4, v is 5 (``shoot_strip_wall_end``), b1-t1 is (8, 9) (``shoot_strip_landing_edge``).
    pts = {"c0": (0, 0), "c1": (1, 0), "c2": (2, 0), "c3": (3, 0), "c4": (4, 0), "v": (0, 1), "r": (4, 1), "tr": (4, 3)}
    chain = ["c0", "c1", "c2", "c3", "c4"]
    f0 = ("c0", "c1", "c2", "c3", "c4", "r", "v")
    if no_landing:
        pts["tn"] = (-2, 3)
        return _flat_band(pts, [f0, ("v", "r", "tr", "tn")], chain, [0, 0, 0, 0], end_edges=("v", "r"))
    lean = math.tan(math.radians(slant_deg))
    pts.update({"b1": (-1.5 + lean, 0), "t1": (-1.5 - 2.0 * lean, 3), "tl": (-4, 3), "bl": (-4, 0)})
    loops = [f0, ("b1", "c0", "v", "r", "tr", "t1"), ("b1", "t1", "tl", "bl")]
    return _flat_band(pts, loops, chain, [0, 0, 0, 0], end_edges=("v", "r"))


def shoot_strip_landing_edge():
    """b1-t1 of ``shoot_strip``, sorted vertex ids: the edge its start end lands on."""
    return (8, 9)


def shoot_strip_wall_end():
    """v of ``shoot_strip``: the start's end wall's last vertex."""
    return 5


def shoot_bevel():
    # The user's U loop outward, in small: the open straight chain c0 (0,0) .. c4 (4,0), the side above, its start's end
    # wall c0-v one edge long, up x = 0 to v (0,1). There the onward edges v-r and v-w run along y = 1, both ways,
    # 90 degrees off the wall (v-tw leans 37 off it, more than Rail Bend), like a bevel strip's border; the strip's
    # rung w-tw stands up from w (-1.5, 1), perpendicular. Every chain vertex is a miter (one face, F0). By hand:
    # - The start clamps at width 1 today, where its offset line y = w leaves v. In D it shoots on along y = 1, which
    #   runs along v-w and through w exactly: the end lands on the vertex w (its rung rises perpendicular to the line)
    #   and slides up w-tw on y = w, at 1.5 on (-1.5, 1.5). A 1e-9 tilt passes w within the anchor snap: still w.
    # Vertex ids: c0..c4 are 0..4, v 5, w 8, tw 9.
    pts = {"c0": (0, 0), "c1": (1, 0), "c2": (2, 0), "c3": (3, 0), "c4": (4, 0), "v": (0, 1), "r": (4, 1), "tr": (4, 3),
           "w": (-1.5, 1), "tw": (-1.5, 3), "bw": (-1.5, 0), "wl": (-3, 1), "tl": (-3, 3), "bl": (-3, 0)}
    loops = [("c0", "c1", "c2", "c3", "c4", "r", "v"), ("bw", "c0", "v", "w"), ("v", "r", "tr", "tw"),
             ("w", "v", "tw"), ("bl", "bw", "w", "wl"), ("wl", "w", "tw", "tl")]
    return _flat_band(pts, loops, ["c0", "c1", "c2", "c3", "c4"], [0, 0, 0, 0], end_edges=("v", "r"))


def jittered_shoot_strip(seed, jitter=0.25, chain_jitter=0.1):
    # shoot_strip with every point off the chain moved by up to ``jitter`` and the chain's inner vertices by up to
    # ``chain_jitter``, along x and y, seeded: the end wall leans, the line meets b1-t1 and the left side at other
    # angles and widths, and the top, where the inner vertices cut, is jagged.
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    b = shoot_strip()
    ends = {b.chain[0], b.chain[-1]}
    verts = {}
    for v, (x, y, z) in sorted(b.verts.items()):
        j = 0.0 if v in ends else chain_jitter if v in b.chain else jitter
        verts[v] = (x + rnd.uniform(-j, j), y + rnd.uniform(-j, j), z)
    return dataclasses.replace(b, verts=verts)


def square_in_grid():
    # A closed square chain round the middle quad of a 3 x 3 grid of 2 x 2 quads, 6 x 6 in all (vertex y*4+x at
    # (2x, 2y), face y*3+x): 5 (2,2) -> 6 (4,2) -> 10 (4,4) -> 9 (2,4), the side inward, so the band is that one quad
    # (face 4), with no vertex at its centre. Every chain vertex is a 90-degree miter (one face, no rails). By hand:
    # - each vertex runs in along its bisector, (2 + w, 2 + w) and its mirrors, so every segment is 2 - 2w long and all
    #   four fold together at w = 1, the inradius, where every vertex reaches the centre (3, 3): the apex, a new point
    #   inside face 4 that every anchor shares, joined to all four chain vertices.
    # - Below that the loop is a square ring inside the one face, which the bridge leaves to Inset.
    pts = [(2 * x, 2 * y, 0) for y in range(4) for x in range(4)]
    faces = {y * 3 + x: (y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x)
             for y in range(3) for x in range(3)}
    return _band(pts, faces, [5, 6, 10, 9], [4, 4, 4, 4], closed=True)


_DUMBBELL = [(x, y) for x in range(4) for y in range(1, 5)] + [(x, 2) for x in (4, 5)] \
    + [(x, y) for x in range(6, 12) for y in range(6)]   # the unit quads by their lower-left corner


def dumbbell():
    # Two square rooms of unit quads joined by a neck one quad wide: a small room x in [0, 4], y in [1, 5], the neck
    # x in [4, 6], y in [2, 3], and a big room x in [6, 12], y in [0, 6]. The closed chain runs round the whole outline,
    # counter-clockwise from (0, 1), the side inward, so the band is every one of those quads. Every chain vertex is a
    # miter or a straight one between two quads, so both modes agree. By hand:
    # - the neck's walls y = 2 and y = 3 are 1 apart: their offset lines meet at y = 2.5, at w = 0.5. That is a
    #   self-contact (Task 6): the loop splits there into one closed piece per room.
    # - each room's piece then shrinks as a square does: to an apex at the room's centre, at its inradius
    #   (``dumbbell_room_limits``). The neck's mouth in a room's wall closes behind the split, so the wall's offset
    #   line runs on across it.
    return _cells_band(_DUMBBELL, (0, 1))


def grid_racket():
    # A racket of unit quads: a 3 x 3 room x in [1, 4], y in [1, 4] and a handle one quad wide, x in [4, 7], y in [2, 3];
    # the closed chain round the outline, the side inward. The handle's sides y = 2 and y = 3 meet at y = 2.5 at w = 1/2,
    # a hairpin, while the room, 3 wide, still has 1 to go: a branch closing while the rest of the loop encloses area.
    # The room's reflex corners (4, 2) and (4, 3) touch at (3.5, 2.5) then (a contact): the handle merges into the
    # room's ring, which goes on to its own collapse, an apex at (2.5, 2.5) at 3 / 2.
    cells = [(x, y) for x in range(1, 4) for y in range(1, 4)] + [(x, 2) for x in range(4, 7)]
    return _cells_band(cells, (1, 1))


def dumbbell_hole():
    # ``dumbbell`` with a 2 x 2 hole in its big room, x and y in [8, 10] x [2, 4]: the big room's ring reaches the hole's
    # open border after the split (a ring the loop split into, cut by a wall).
    return _cells_band([c for c in _DUMBBELL if c not in {(8, 2), (9, 2), (8, 3), (9, 3)}], (0, 1))


def racket_hole():
    # ``grid_racket`` with its room's middle quad (2, 2) a hole: the room's ring, past the handle's merge, reaches it.
    return _cells_band([(x, y) for x in range(1, 4) for y in range(1, 4) if (x, y) != (2, 2)]
                       + [(x, 2) for x in range(4, 7)], (1, 1))


def xy_jittered(band, seed, amplitude):
    """``band`` with every vertex moved by up to ``amplitude`` along x and along y, seeded (the chain's too)."""
    rnd = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    return dataclasses.replace(band, verts={v: (p[0] + rnd.uniform(-amplitude, amplitude),
                                                p[1] + rnd.uniform(-amplitude, amplitude), p[2])
                                            for v, p in sorted(band.verts.items())})


def racket_ngon():
    # A racket, one face: a 4 x 4 room and a handle 1 wide, (4, 1.5) to (7, 2.5); the closed chain round it, inward.
    pts = [(0, 0), (4, 0), (4, 1.5), (7, 1.5), (7, 2.5), (4, 2.5), (4, 4), (0, 4)]
    keys = [chr(97 + i) for i in range(len(pts))]
    return _flat_band(dict(zip(keys, pts)), [tuple(keys)], keys, [0] * len(pts), closed=True)


def asymmetric_l_ngon():
    # An L, one face, its arms 1 and 3 wide: (0, 0) (6, 0) (6, 1) (3, 1) (3, 3) (0, 3); the closed chain round it, inward.
    pts = [(0, 0), (6, 0), (6, 1), (3, 1), (3, 3), (0, 3)]
    keys = [chr(97 + i) for i in range(len(pts))]
    return _flat_band(dict(zip(keys, pts)), [tuple(keys)], keys, [0] * len(pts), closed=True)


def _cells_band(cell_list, start):
    # A flat band of the unit quads with lower-left corners ``cell_list``, the closed chain round their outline,
    # counter-clockwise from ``start``, the side inward.
    cells = set(cell_list)
    pts = sorted({(x + dx, y + dy) for x, y in cells for dx in (0, 1) for dy in (0, 1)})
    ids = {p: i for i, p in enumerate(pts)}
    faces = {f: (ids[(x, y)], ids[(x + 1, y)], ids[(x + 1, y + 1)], ids[(x, y + 1)]) for f, (x, y) in enumerate(cell_list)}
    edge_face = {}
    for f, loop in faces.items():
        for i in range(4):
            a, b = loop[i], loop[(i + 1) % 4]
            edge_face[(a, b)] = f   # each quad runs counter-clockwise: the face is on the left of a -> b
    outline = [e for e in edge_face if (e[1], e[0]) not in edge_face]   # the outline, counter-clockwise
    after = dict(outline)
    chain, v = [ids[start]], after[ids[start]]
    while v != chain[0]:
        chain.append(v)
        v = after[v]
    side = [edge_face[(chain[k], chain[(k + 1) % len(chain)])] for k in range(len(chain))]
    return _band([(x, y, 0) for x, y in pts], faces, chain, side, closed=True)


def dumbbell_neck_width():
    """Where ``dumbbell``'s loop touches itself across the neck: half the neck's width, 1 / 2. The neck's walls y = 2 and
    y = 3 have offset lines y = 2 + w and y = 3 - w, which meet at w = 1/2; its reflex corners (4, 2) and (4, 3) run in
    along their bisectors to (4 - w, 2 + w) and (4 - w, 3 - w), which meet there too, at (3.5, 2.5), as do (6, 2) and
    (6, 3) at (6.5, 2.5)."""
    return 0.5


def dumbbell_room_limits():
    """(small, big): where ``dumbbell``'s rooms are used up, each an apex at its centre at its inradius: half the side,
    4 / 2 for the small room and 6 / 2 for the big one."""
    return 2.0, 3.0


def zigzag_ladder(rows=4, n=4, tilt=0.0):
    # Parallel rows of n unit edges, y = 0, 1, .., rows, the chain the bottom row (0,0) .. (n,0), the side above. Each
    # strip between two rows is n quads whose rungs lean half a unit, right on even strips and left on odd ones, so
    # the rows alternate x = 0 .. n and x = 0.5 .. n + 0.5. Every rail path and both end walls turn by 53 degrees at
    # every row (more than Rail Bend), and each row ends where its strip does, on the mesh border: an end wall ends
    # at every row with nothing to shoot on to. By hand:
    # - the slide reaches row 1 at width 1, the whole loop on its vertices; the default mode stops there, and D goes
    #   on with both ends held on the row's end vertices (0.5, 1) and (4.5, 1), only its middle rising;
    # - relayed (D), it passes the baton to row 1 at width 1, row 2 at 2 and row 3 at 3, and stops at the top border
    #   row at 4: the cut at a total width W in (k, k + 1] is row k's at W - k, a straight row at y = W.
    # ``tilt`` raises every row from 2 on by ``tilt`` at its right end (x = n + 0.5), in proportion along it: 0.05 is a
    # row 5% of the spacing off parallel, which the loop at row 1's relay start reaches only close by.
    # Vertex ids: row r, x index i: r * (n + 1) + i. Faces: strip r, quad i: r * n + i.
    def x(r, i):
        return i + 0.5 * (r % 2)

    def y(r, i):
        return r + (tilt * x(r, i) / (n + 0.5) if r >= 2 else 0.0)

    pts = [(x(r, i), y(r, i), 0) for r in range(rows + 1) for i in range(n + 1)]
    faces = {r * n + i: (r * (n + 1) + i, r * (n + 1) + i + 1, (r + 1) * (n + 1) + i + 1, (r + 1) * (n + 1) + i)
             for r in range(rows) for i in range(n)}
    return _band(pts, faces, list(range(n + 1)), list(range(n)), end_edges=(n + 1, 2 * n + 1))
