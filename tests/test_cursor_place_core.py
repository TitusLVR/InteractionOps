import math

from utils.cursor_place_core import (
    pick_element, slide_element, aim_edge_dir, other_axis, set_normal_axis,
    cycle_edge_axis, build_frame,
)

# Unit square in the XY plane, normal +Z. Edge i runs SQ[i] -> SQ[(i+1)%4].
SQ = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
C = (.5, .5, 0)


def _approx(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _det(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _pick(hit):
    return pick_element(SQ, hit, poly_normal=(0, 0, 1), poly_center=C)


def _slide(hit, threshold=0.1):
    return slide_element(SQ, hit, poly_normal=(0, 0, 1), threshold=threshold)


# --- pick_element (snap): nearest of vertices / edge midpoints / centre ----

def test_nearest_is_vertex():
    p = _pick((0.95, 0.08, 0))
    assert p.kind == "VERT" and p.index == 1
    assert _approx(p.position, (1, 0, 0))


def test_nearest_is_edge_midpoint():
    p = _pick((0.97, 0.5, 0))
    assert p.kind == "EDGE" and p.index == 1
    assert _approx(p.position, (1, .5, 0))
    assert _approx(p.edge[0], (1, 0, 0)) and _approx(p.edge[1], (1, 1, 0))


def test_nearest_is_face_center():
    p = _pick((0.55, 0.48, 0))
    assert p.kind == "FACE" and p.index is None
    assert _approx(p.position, C)
    assert _approx(p.normal, (0, 0, 1))


def test_face_edge_dir_points_to_nearer_endpoint():
    assert _approx(_pick((0.6, 0.3, 0)).edge_dir, (1, 0, 0))     # bottom edge, toward (1,0,0)
    assert _approx(_pick((0.4, 0.3, 0)).edge_dir, (-1, 0, 0))


def test_edge_dir_points_to_nearer_endpoint():
    assert _approx(_pick((0.97, 0.58, 0)).edge_dir, (0, 1, 0))
    assert _approx(_pick((0.97, 0.42, 0)).edge_dir, (0, -1, 0))


def test_vertex_uses_hit_face_normal_and_nearer_incident_edge():
    p = _pick((0.98, 0.80, 0))
    assert p.kind == "VERT" and p.index == 2
    assert _approx(p.normal, (0, 0, 1))                     # face under the mouse, not the vertex normal
    assert _approx(p.edge_dir, (0, -1, 0))                  # right edge nearer than top edge


def test_vertex_at_corner_picks_edge_toward_mouse_side():
    p = _pick((0.80, 0.98, 0))                               # near (1,1): top edge nearer
    assert p.kind == "VERT" and p.index == 2
    assert _approx(p.edge_dir, (-1, 0, 0))


def test_pick_ignores_hit_offset_off_the_plane():
    # Distances are measured in 3D; a small offset along the normal must not matter.
    p = _pick((0.95, 0.08, 0.02))
    assert p.kind == "VERT" and p.index == 1


# --- slide_element -----------------------------------------------------------

def test_slide_free_on_face_uses_hit_location():
    p = _slide((0.4, 0.6, 0))
    assert p.kind == "FACE" and p.index is None
    assert _approx(p.position, (0.4, 0.6, 0))
    assert _approx(p.normal, (0, 0, 1))
    assert _approx(p.edge_dir, (-1, 0, 0))                  # nearest edge is the top one, toward (0,1,0)


def test_slide_near_edge_projects_onto_edge():
    p = _slide((0.97, 0.30, 0))
    assert p.kind == "EDGE" and p.index == 1
    assert _approx(p.position, (1, 0.3, 0))
    assert _approx(p.edge_dir, (0, -1, 0))                  # toward the nearer endpoint (1,0,0)
    assert _approx(p.edge[0], (1, 0, 0)) and _approx(p.edge[1], (1, 1, 0))


def test_slide_edge_projection_is_clamped_to_segment():
    p = _slide((1.03, 1.30, 0), threshold=0.5)
    assert p.kind == "EDGE"
    assert all(0.0 - 1e-9 <= c <= 1.0 + 1e-9 for c in p.position[:2])


def test_slide_threshold_respected():
    assert _slide((0.85, 0.5, 0), threshold=0.1).kind == "FACE"
    assert _slide((0.85, 0.5, 0), threshold=0.2).kind == "EDGE"


# --- aim_edge_dir ------------------------------------------------------------

def test_aim_edge_dir_projects_target_into_tangent_plane():
    d = aim_edge_dir((1, 1, 0), (0, 0, 1), (3, 1, 5))
    assert _approx(d, (1, 0, 0))


def test_aim_edge_dir_degenerate_returns_none():
    assert aim_edge_dir((1, 1, 0), (0, 0, 1), (1, 1, 7)) is None
    assert aim_edge_dir((1, 1, 0), (0, 0, 1), None) is None


# --- axis helpers ----------------------------------------------------------

def test_axis_helpers():
    assert other_axis("Z", "X") == "Y"
    assert set_normal_axis("Z", "X", "X") == ("X", "Z")
    assert set_normal_axis("Z", "X", "Y") == ("Y", "X")
    assert set_normal_axis("Z", "X", "Z") == ("Z", "X")
    assert cycle_edge_axis("Z", "X") == "Y"
    assert cycle_edge_axis("Z", "Y") == "X"


# --- build_frame -----------------------------------------------------------

def test_build_frame_default_mapping():
    m = build_frame((0, 0, 1), (1, 0, 0), "Z", "X")
    assert _approx(m[2], (0, 0, 1)) and _approx(m[0], (1, 0, 0)) and _approx(m[1], (0, 1, 0))


def test_build_frame_projects_edge_and_is_right_handed():
    m = build_frame((0, 0, 1), (1, 0, 1), "Y", "X")
    assert _approx(m[1], (0, 0, 1)) and _approx(m[0], (1, 0, 0))
    assert math.isclose(_det(m), 1.0, abs_tol=1e-9)


def test_build_frame_all_mappings_right_handed():
    for n in "XYZ":
        for e in "XYZ":
            if n == e:
                continue
            m = build_frame((0.3, -0.4, 0.866), (0.2, 0.9, 0.1), n, e)
            assert math.isclose(_det(m), 1.0, abs_tol=1e-9), (n, e)


def test_build_frame_flip_keeps_edge_axis():
    m = build_frame((0, 0, 1), (1, 0, 0), "Z", "X", flip=True)
    assert _approx(m[2], (0, 0, -1)) and _approx(m[0], (1, 0, 0))
    assert math.isclose(_det(m), 1.0, abs_tol=1e-9)


def test_build_frame_zero_normal_falls_back():
    m = build_frame((0, 0, 0), (1, 0, 0), "Z", "X")
    assert math.isclose(_det(m), 1.0, abs_tol=1e-9) and _approx(m[0], (1, 0, 0))


def test_build_frame_degenerate_edge_falls_back():
    m = build_frame((0, 0, 1), (0, 0, 0), "Z", "X")
    assert math.isclose(_det(m), 1.0, abs_tol=1e-9) and _approx(m[2], (0, 0, 1))
