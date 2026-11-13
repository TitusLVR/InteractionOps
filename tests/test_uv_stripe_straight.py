"""Straight cross edges (``Strip.layout`` "STRAIGHT") on the strip shapes Inset and Edge Slide build:
repeated far ids, a near row that starts and ends on one vertex, collapsed segments, rungs starting mid-loop and
a seam on a collapse node."""

import pytest

from test_uv_stripe_core import collapsed_seam_ring, signed_areas, square_ring
from utils import uv_stripe_core as core
from utils.uv_stripe_core import Strip, ascending_rungs, straighten, strip_length, stripe_uvs


def repeated_far():
    v = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0), 3: (1.0, 1.0, 0.0)}
    return Strip(verts=v, faces={0: (0, 1, 3), 1: (1, 2, 3)}, near=[0, 1, 2], far=[3, 3, 3],
                 rungs=[(0, 0), (1, 1), (2, 2)], closed=False, height=1.0, corner_far={(0, 3): 0, (1, 3): 2})


def near_seam():
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (1.0, 2.0, 0.0),
         3: (0.0, -1.0, 0.0), 4: (3.0, -1.0, 0.0), 5: (1.0, 3.0, 0.0), 6: (-1.0, 0.0, 0.0)}
    f = {0: (0, 1, 4, 3), 1: (1, 2, 5, 4), 2: (2, 0, 6, 5)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 0], far=[3, 4, 5, 6], rungs=[(k, k) for k in range(4)],
                 closed=False, height=1.0, corner_near={(0, 0): 0, (2, 0): 3})


def collapsed_far_segment():
    v = {i: (float(i), 0.0, 0.0) for i in range(4)} | {4: (0.0, 1.0, 0.0), 5: (1.5, 1.0, 0.0), 6: (3.0, 1.0, 0.0)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 5), 2: (2, 3, 6, 5)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6], rungs=[(0, 0), (1, 1), (2, 1), (3, 2)],
                 closed=False, height=1.0)


def closed_repeated_far():
    v = {0: (0.0, 0.0, 0.0), 1: (4.0, 0.0, 0.0), 2: (4.0, 1.0, 0.0), 3: (0.0, 1.0, 0.0),
         4: (0.5, 0.5, 0.0), 5: (3.5, 0.5, 0.0)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 5), 2: (2, 3, 4, 5), 3: (3, 0, 4)}
    hints = {(0, 4): 0, (0, 5): 1, (1, 5): 1, (2, 5): 2, (2, 4): 3, (3, 4): 3}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 5, 4], rungs=[(k, k) for k in range(4)],
                 closed=True, height=0.5, corner_far=hints)


def collapse_node_seam():
    v = {0: (0.0, 0.0, 0.0), 1: (4.0, 0.0, 0.0), 2: (4.0, 1.0, 0.0), 3: (0.0, 1.0, 0.0),
         10: (0.5, 0.5, 0.0), 11: (3.5, 0.5, 0.0)}
    f = {100: (0, 1, 11, 10), 101: (1, 2, 11), 102: (2, 3, 10, 11), 103: (3, 0, 10)}
    return ascending_rungs(Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[10, 11],
                                 rungs=[(0, 0), (1, 1), (2, 1), (3, 0)], closed=True, height=0.5))


def later_seam():
    s = square_ring()
    s.verts[3] = (-3.0, 2.0, 0.0)
    return s


def skewed_ring():
    """A square ring whose new loop is shifted along x, so arc-length rows lean."""
    s = square_ring()
    s.verts.update({4: (0.5, 0.2, 0.0), 5: (1.9, 0.2, 0.0), 6: (1.9, 1.8, 0.0), 7: (0.5, 1.8, 0.0)})
    return s


SHAPES = [repeated_far, near_seam, collapsed_far_segment, closed_repeated_far,
          lambda: ascending_rungs(collapsed_seam_ring()), collapse_node_seam, later_seam, skewed_ring]


def torn_edges(strip, uv):
    """Edges shared by two faces whose two faces put an end of it at different UVs, but the closed seam rung."""
    seen, torn = {}, set()
    for fid, face in strip.faces.items():
        for k, a in enumerate(face):
            b = face[(k + 1) % len(face)]
            e = tuple(sorted((a, b)))
            ends = {a: uv[(fid, a)], b: uv[(fid, b)]}
            if e in seen:
                other = seen[e]
                if any(abs(ends[x][0] - other[x][0]) > 1e-9 or abs(ends[x][1] - other[x][1]) > 1e-9 for x in e):
                    torn.add(e)
            else:
                seen[e] = ends
    return torn


@pytest.mark.parametrize("make", SHAPES)
def test_straightened_shapes_tile_like_the_row_layout(make):
    old_strip, new_strip = make(), make()
    old = stripe_uvs(old_strip)
    assert straighten(new_strip) is True
    new = stripe_uvs(new_strip)
    length = strip_length(new_strip)
    assert sum(signed_areas(new_strip, new).values()) == pytest.approx(sum(signed_areas(old_strip, old).values()))
    assert all(a > -1e-9 for a in signed_areas(new_strip, new).values())
    assert torn_edges(new_strip, new) == torn_edges(old_strip, old)       # only the seam, as before
    assert all(-1e-9 <= u <= length + 1e-9 for u, _v in new.values())


def test_straight_rungs_stand_the_skewed_rings_rungs_vertical():
    s = skewed_ring()
    s.layout = "STRAIGHT"
    uv = stripe_uvs(s)
    for fid, face in s.faces.items():
        for near, far in zip(s.near, s.far):
            if near in face and far in face:
                assert uv[(fid, near)][0] == pytest.approx(uv[(fid, far)][0])
    old = stripe_uvs(skewed_ring())
    assert abs(old[(0, 1)][0] - old[(0, 5)][0]) > 1e-3


def test_straighten_leans_into_vertical_on_an_uneven_strip():
    v = {0: (0.0, 0.0, 0.0), 1: (0.1, 0.0, 0.0), 2: (2.0, 0.0, 0.0),
         3: (0.0, 1.0, 0.0), 4: (1.9, 1.0, 0.0), 5: (2.0, 1.0, 0.0)}
    f = {0: (0, 1, 4, 3), 1: (1, 2, 5, 4)}
    s = Strip(verts=v, faces=f, near=[0, 1, 2], far=[3, 4, 5], rungs=[(0, 0), (1, 1), (2, 2)],
              closed=False, height=1.0)
    assert straighten(s) is True
    uv = stripe_uvs(s)
    assert uv[(0, 1)][0] == pytest.approx(1.0) and uv[(0, 4)][0] == pytest.approx(1.0)


@pytest.mark.parametrize("bad", ["fold", "tear"])
def test_straighten_keeps_the_row_layout_when_the_posts_go_wrong(monkeypatch, bad):
    make = skewed_ring if bad == "fold" else closed_repeated_far
    s = make()
    old = stripe_uvs(make())
    real = core._post_u

    def broken(strip, un, uf):
        u_near, u_far = real(strip, un, uf)
        if bad == "fold":
            return u_near, [strip_length(strip) - u for u in u_far]
        u_far[2] += 0.3            # one occurrence of the repeated far vertex 5: faces 1 and 2 tear apart there
        return u_near, u_far

    monkeypatch.setattr(core, "_post_u", broken)
    assert straighten(s) is False and s.layout == "EVEN"
    assert stripe_uvs(s) == old
