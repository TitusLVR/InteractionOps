import math

import pytest

from utils.uv_align_core import (
    bbox_center,
    bbox_of,
    follow_active_angle,
    island_offsets,
    point_line_target,
    rotate_between,
    rotate_uv,
    surface_normal,
    transport_up,
    triangle_uv_direction,
    triangle_uv_frame,
    uv_frame,
    world_up_angle,
    world_up_direction,
)


PTS = [(0.1, 0.2), (0.5, 0.9), (0.3, 0.4)]


# ------------------------------------------------------------- point mode

@pytest.mark.parametrize("d, expected", [
    ("N", (1, 0.9)),
    ("S", (1, 0.2)),
    ("W", (0, 0.1)),
    ("E", (0, 0.5)),
])
def test_point_line_extremes(d, expected):
    axis, value = point_line_target(d, PTS)
    assert axis == expected[0]
    assert value == pytest.approx(expected[1])


def test_point_line_centers():
    assert point_line_target("CENTER_X", PTS) == (0, pytest.approx(0.3))
    assert point_line_target("CENTER_Y", PTS) == (1, pytest.approx(0.5))


def test_point_line_empty_or_other():
    assert point_line_target("N", []) is None
    assert point_line_target("WORLD_UP", PTS) is None


# ------------------------------------------------------------ island mode

BOXES = [(0.0, 0.0, 0.2, 0.1), (0.5, 0.3, 0.6, 0.7)]


def test_bbox_helpers():
    assert bbox_of(PTS) == (0.1, 0.2, 0.5, 0.9)
    assert bbox_center((0.0, 0.0, 2.0, 4.0)) == (1.0, 2.0)


@pytest.mark.parametrize("d, expected", [
    ("N", [(0.0, 0.6), (0.0, 0.0)]),
    ("S", [(0.0, 0.0), (0.0, -0.3)]),
    ("W", [(0.0, 0.0), (-0.5, 0.0)]),
    ("E", [(0.4, 0.0), (0.0, 0.0)]),
])
def test_island_offsets_sides(d, expected):
    got = island_offsets(d, BOXES)
    for g, e in zip(got, expected):
        assert g == (pytest.approx(e[0]), pytest.approx(e[1]))


def test_island_offsets_sides_flush():
    for d, idx in (("N", 3), ("S", 1), ("W", 0), ("E", 2)):
        offs = island_offsets(d, BOXES)
        axis = 1 if idx in (1, 3) else 0
        moved = [b[idx] + o[axis] for b, o in zip(BOXES, offs)]
        assert moved[0] == pytest.approx(moved[1])


def test_island_offsets_centers():
    # centres: (0.1, 0.05) and (0.55, 0.5) -> mean u 0.325, mean v 0.275
    cx = island_offsets("CENTER_X", BOXES)
    assert cx[0] == (pytest.approx(0.225), 0.0)
    assert cx[1] == (pytest.approx(-0.225), 0.0)
    cy = island_offsets("CENTER_Y", BOXES)
    assert cy[0] == (0.0, pytest.approx(0.225))
    assert cy[1] == (0.0, pytest.approx(-0.225))


def test_island_offsets_bad_direction():
    with pytest.raises(ValueError):
        island_offsets("WORLD_UP", BOXES)


# --------------------------------------------------------------- world up

def _quad_tris(p, t):
    """Two triangles from a quad's 4 points and UVs."""
    return [((p[0], p[1], p[2]), (t[0], t[1], t[2])),
            ((p[0], p[2], p[3]), (t[0], t[2], t[3]))]


# A vertical wall facing -Y: x right, z up.
WALL = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]
UV_SQ = [(0, 0), (1, 0), (1, 1), (0, 1)]


def _rot(uvs, angle):
    return [rotate_uv(uv, (0.5, 0.5), angle) for uv in uvs]


def test_triangle_jacobian_maps_up_to_v():
    uv, proj, area = triangle_uv_direction(
        (WALL[0], WALL[1], WALL[2]), (UV_SQ[0], UV_SQ[1], UV_SQ[2]),
        (0, 0, 1))
    assert uv == (pytest.approx(0.0), pytest.approx(1.0))
    assert proj == pytest.approx(1.0)
    assert area == pytest.approx(0.5)


def test_upright_island_needs_no_rotation():
    angle = world_up_angle(_quad_tris(WALL, UV_SQ))
    assert angle == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("rot_deg", [90, -90, 180, 37, -123])
def test_rotated_island_comes_back_upright(rot_deg):
    uvs = _rot(UV_SQ, math.radians(rot_deg))
    tris = _quad_tris(WALL, uvs)
    angle = world_up_angle(tris)
    fixed = _rot(uvs, angle)
    direction, _ = world_up_direction(_quad_tris(WALL, fixed))
    assert direction[0] == pytest.approx(0.0, abs=1e-9)
    assert direction[1] == pytest.approx(1.0)
    # Rotation is rigid: edge lengths kept.
    assert math.dist(fixed[0], fixed[1]) == pytest.approx(1.0)


def test_mirrored_island_rotates_but_stays_mirrored():
    # Mirror u then rotate 90 deg: winding flipped.
    mirrored = [(1 - u, v) for u, v in UV_SQ]
    uvs = _rot(mirrored, math.radians(90))
    angle = world_up_angle(_quad_tris(WALL, uvs))
    fixed = _rot(uvs, angle)
    direction, _ = world_up_direction(_quad_tris(WALL, fixed))
    assert direction[1] == pytest.approx(1.0)

    def signed_area(t):
        return sum(t[i][0] * t[(i + 1) % 4][1] - t[(i + 1) % 4][0] * t[i][1]
                   for i in range(4))
    assert signed_area(fixed) < 0  # still mirrored (clockwise)


def test_horizontal_island_is_skipped():
    floor = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    assert world_up_angle(_quad_tris(floor, UV_SQ)) is None


def test_sloped_island_uses_downhill_direction():
    # Roof rising along +y at 45 deg; UV v follows the slope.
    roof = [(0, 0, 0), (1, 0, 0), (1, 1, 1), (0, 1, 1)]
    uvs = _rot(UV_SQ, math.radians(90))
    angle = world_up_angle(_quad_tris(roof, uvs))
    assert angle is not None
    fixed = _rot(uvs, angle)
    direction, ratio = world_up_direction(_quad_tris(roof, fixed))
    assert direction[1] == pytest.approx(1.0)
    assert ratio == pytest.approx(math.sqrt(0.5))


def test_non_uniform_scale_world_positions():
    # Wall stretched 10x along x in world space; UVs square. A slanted UV
    # layout must still resolve up correctly from world positions.
    wall = [(0, 0, 0), (10, 0, 0), (10, 0, 1), (0, 0, 1)]
    uvs = _rot(UV_SQ, math.radians(30))
    angle = world_up_angle(_quad_tris(wall, uvs))
    assert angle == pytest.approx(math.radians(-30))


def test_aspect_correct_rotation_keeps_pixel_shape():
    aspect = 2.0  # 2:1 image
    # Island upright in pixel space, then rotated 90 deg in pixel space.
    uvs = [rotate_uv(uv, (0.5, 0.5), math.radians(90), aspect)
           for uv in [(0.25, 0), (0.75, 0), (0.75, 1), (0.25, 1)]]
    tris = _quad_tris(WALL, uvs)
    angle = world_up_angle(tris, aspect=aspect)
    assert angle == pytest.approx(math.radians(-90))
    fixed = [rotate_uv(uv, (0.5, 0.5), angle, aspect) for uv in uvs]
    for got, exp in zip(fixed, [(0.25, 0), (0.75, 0), (0.75, 1), (0.25, 1)]):
        assert got == (pytest.approx(exp[0]), pytest.approx(exp[1], abs=1e-9))


def test_degenerate_triangles_ignored():
    tris = [(((0, 0, 0), (1, 0, 0), (2, 0, 0)), ((0, 0), (1, 0), (2, 0)))]
    assert world_up_angle(tris) is None


# ---------------------------------------------------------- follow active

def _approx_vec(got, exp, abs_=1e-9):
    assert len(got) == len(exp)
    for g, e in zip(got, exp):
        assert g == pytest.approx(e, abs=abs_)


def _rigid_rot(uvs, angle):
    """Rotate about the bbox centre, as the operator does."""
    return [rotate_uv(uv, bbox_center(bbox_of(uvs)), angle) for uv in uvs]


def _assert_same_up_to_translation(got, exp):
    for i in range(1, len(got)):
        _approx_vec((got[i][0] - got[0][0], got[i][1] - got[0][1]),
                    (exp[i][0] - exp[0][0], exp[i][1] - exp[0][1]))


def test_triangle_uv_frame_inverts_jacobian():
    p = (WALL[0], WALL[1], WALL[2])
    t = _rot(UV_SQ, math.radians(30))[:3]
    tu, tv = triangle_uv_frame(p, t)
    for d, exp in ((tu, (1, 0)), (tv, (0, 1))):
        uv, _, _ = triangle_uv_direction(p, t, d)
        _approx_vec(uv, exp)


def test_uv_frame_of_upright_wall():
    tu, tv, n = uv_frame(_quad_tris(WALL, UV_SQ))
    _approx_vec(tu, (1, 0, 0))
    _approx_vec(tv, (0, 0, 1))
    _approx_vec(n, (0, -1, 0))


def test_uv_frame_aspect():
    # 2:1 image, island half as wide in u: square in pixels -> same frame.
    uvs = [(0.25, 0), (0.75, 0), (0.75, 1), (0.25, 1)]
    tu, tv, _n = uv_frame(_quad_tris(WALL, uvs), aspect=2.0)
    _approx_vec(tu, (1, 0, 0))
    _approx_vec(tv, (0, 0, 1))


def test_rotate_between_minimal():
    got = rotate_between((0, 0, 1), (0, -1, 0), (0, 0, 1), (1, 0, 0))
    _approx_vec(got, (0, 1, 0))  # over the top edge
    assert rotate_between((0, 0, 1), (1, 0, 0), (1, 0, 0), None) == (0, 0, 1)


def test_rotate_between_anti_parallel_uses_half_turn_axis():
    # Front (-Y) to back (+Y): half turn about the vertical keeps up.
    got = rotate_between((1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, 1))
    _approx_vec(got, (-1, 0, 0))
    up = transport_up(((1, 0, 0), (0, 0, 1), (0, -1, 0)), (0, 1, 0))
    _approx_vec(up, (0, 0, 1))


def test_surface_normal_cancels():
    a = _quad_tris(WALL, UV_SQ)
    flipped = [((p[0], p[2], p[1]), t) for p, t in a]
    assert surface_normal(a + flipped) is None


# L / cube corner around (1, 0, *): front wall facing -Y, right wall facing
# +X, top face facing +Z. Unfolded continuation of the front's UV square.
RIGHT = [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]
RIGHT_UNFOLD = [(1, 0), (2, 0), (2, 1), (1, 1)]
TOP = [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
TOP_UNFOLD = [(0, 1), (1, 1), (1, 2), (0, 2)]
BACK = [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]
BACK_UNFOLD = [(2, 0), (3, 0), (3, 1), (2, 1)]  # around the box


@pytest.mark.parametrize("scramble_deg", [0, 90, -45, 170])
@pytest.mark.parametrize("active_deg, pts, unfold", [
    (a, p, u)
    for a in (0, 30, -90, 180)
    for p, u in ((RIGHT, RIGHT_UNFOLD), (TOP, TOP_UNFOLD))
] + [
    # Anti-parallel: the half turn is about the active face's UV up, so the
    # back face continues "around the box" along the active face's UV
    # sides. With the active upright (or upside down) that is the world
    # wrap around Z; for tilted actives see the test below.
    (a, BACK, BACK_UNFOLD) for a in (0, 180)
])
def test_follow_active_reproduces_unfolded_continuation(
        active_deg, scramble_deg, pts, unfold):
    ra = math.radians(active_deg)
    active_uv = [rotate_uv(uv, (0, 0), ra) for uv in UV_SQ]
    expected = [rotate_uv(uv, (0, 0), ra) for uv in unfold]
    target_uv = _rigid_rot(expected, math.radians(scramble_deg))

    frame = uv_frame(_quad_tris(WALL, active_uv))
    angle = follow_active_angle(frame, _quad_tris(pts, target_uv))
    assert angle is not None
    fixed = _rigid_rot(target_uv, angle)
    _assert_same_up_to_translation(fixed, expected)


def test_follow_active_antiparallel_keeps_active_up():
    # Tilted active: the back island's UV +V reads as the active's T_v.
    frame = uv_frame(_quad_tris(WALL, _rot(UV_SQ, math.radians(30))))
    target = _rot(BACK_UNFOLD, math.radians(80))
    angle = follow_active_angle(frame, _quad_tris(BACK, target))
    fixed = _rigid_rot(target, angle)
    direction, _ = world_up_direction(_quad_tris(BACK, fixed), up=frame[1])
    _approx_vec(direction, (0, 1))


def test_follow_active_shared_edge_lines_up():
    # Right wall's shared vertical edge (1,0,0)-(1,0,1) must run the same UV
    # direction as on the active face after following.
    active_uv = _rot(UV_SQ, math.radians(25))
    frame = uv_frame(_quad_tris(WALL, active_uv))
    target = _rot(RIGHT_UNFOLD, math.radians(-110))
    fixed = _rigid_rot(target, follow_active_angle(
        frame, _quad_tris(RIGHT, target)))
    a = (active_uv[2][0] - active_uv[1][0], active_uv[2][1] - active_uv[1][1])
    b = (fixed[3][0] - fixed[0][0], fixed[3][1] - fixed[0][1])
    _approx_vec(a, b)


def test_follow_active_parallel_island_matches_orientation():
    # Coplanar island (same wall, shifted) just copies the active rotation.
    shifted = [(x + 3, y, z) for x, y, z in WALL]
    frame = uv_frame(_quad_tris(WALL, _rot(UV_SQ, math.radians(40))))
    target = _rot(UV_SQ, math.radians(-75))
    angle = follow_active_angle(frame, _quad_tris(shifted, target))
    assert angle == pytest.approx(math.radians(115))


def test_follow_active_mirrored_island_stays_mirrored():
    frame = uv_frame(_quad_tris(WALL, UV_SQ))
    mirrored = _rot([(1 - u, v) for u, v in RIGHT_UNFOLD], math.radians(60))
    angle = follow_active_angle(frame, _quad_tris(RIGHT, mirrored))
    fixed = _rigid_rot(mirrored, angle)
    # Shared vertical edge now runs +V like on the active face.
    dv = fixed[3][1] - fixed[0][1]
    assert dv == pytest.approx(1.0)
    assert fixed[3][0] - fixed[0][0] == pytest.approx(0.0, abs=1e-9)
