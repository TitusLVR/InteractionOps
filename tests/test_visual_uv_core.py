import pytest

from utils.visual_uv_core import (
    GIZMO_POINTS,
    PIVOT_ANCHOR,
    PIVOT_CENTER,
    PIVOT_CURSOR,
    ViewMapping,
    anchor_uv,
    face_at_uv,
    is_drag,
    next_pivot,
    pivot_after_click,
    pivot_label,
    point_in_triangle,
    uv_mode_handles,
)

BMIN, BMAX = (0.2, 0.1), (0.6, 0.5)


def _close(p, q, tol=1e-9):
    return abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol


# --- anchor pivot -------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ('BL', (0.2, 0.1)), ('BR', (0.6, 0.1)), ('TL', (0.2, 0.5)), ('TR', (0.6, 0.5)),
    ('B', (0.4, 0.1)), ('T', (0.4, 0.5)), ('L', (0.2, 0.3)), ('R', (0.6, 0.3)),
    ('_C', (0.4, 0.3)), ('CENTER', (0.4, 0.3)),
])
def test_anchor_uv_per_point(name, expected):
    assert _close(anchor_uv(BMIN, BMAX, name), expected)


def test_anchor_follows_the_island():
    """The anchor is read from the bbox when a transform begins: after
    the island moves, the same point name lands on the moved bbox."""
    before = anchor_uv(BMIN, BMAX, 'TL')
    off = (0.25, -0.05)
    moved_min = (BMIN[0] + off[0], BMIN[1] + off[1])
    moved_max = (BMAX[0] + off[0], BMAX[1] + off[1])
    after = anchor_uv(moved_min, moved_max, 'TL')
    assert _close(after, (before[0] + off[0], before[1] + off[1]))


def test_anchor_follows_a_scaled_island():
    after = anchor_uv((0.0, 0.0), (2.0, 1.0), 'R')
    assert _close(after, (2.0, 0.5))


def test_anchor_of_another_island_is_that_islands_point():
    """A new active island gives its own point for the same name."""
    assert _close(anchor_uv((1.0, 1.0), (1.5, 2.0), 'BR'), (1.5, 1.0))


# --- pivot cycling and labels -------------------------------------------------

def test_pivot_cycle_without_anchor():
    assert next_pivot(PIVOT_CENTER, None) == PIVOT_CURSOR
    assert next_pivot(PIVOT_CURSOR, None) == PIVOT_CENTER


def test_pivot_cycle_with_anchor():
    assert next_pivot(PIVOT_CENTER, 'TL') == PIVOT_CURSOR
    assert next_pivot(PIVOT_CURSOR, 'TL') == PIVOT_ANCHOR
    assert next_pivot(PIVOT_ANCHOR, 'TL') == PIVOT_CENTER


def test_pivot_cycle_from_unknown_mode_starts_at_center():
    assert next_pivot('SOMETHING', None) == PIVOT_CENTER


@pytest.mark.parametrize("mode, anchor, text", [
    (PIVOT_CENTER, None, "Center"),
    (PIVOT_CURSOR, 'TL', "Cursor"),
    (PIVOT_ANCHOR, 'TL', "Top Left Corner"),
    (PIVOT_ANCHOR, 'BR', "Bottom Right Corner"),
    (PIVOT_ANCHOR, 'L', "Left Side"),
    (PIVOT_ANCHOR, 'T', "Top Side"),
    (PIVOT_ANCHOR, '_C', "Center"),
])
def test_pivot_label_full_words(mode, anchor, text):
    assert pivot_label(mode, anchor) == text


def test_every_gizmo_point_has_a_label():
    for name in GIZMO_POINTS:
        label = pivot_label(PIVOT_ANCHOR, name)
        assert label and len(label.split()) >= 1 and label[0].isupper()


def test_click_on_corner_picks_anchor():
    assert pivot_after_click('TR', PIVOT_CENTER, None) == (PIVOT_ANCHOR, 'TR')
    assert pivot_after_click('L', PIVOT_CURSOR, 'TR') == (PIVOT_ANCHOR, 'L')


def test_click_on_center_returns_to_center_and_keeps_anchor():
    assert pivot_after_click('CENTER', PIVOT_ANCHOR, 'TR') == (PIVOT_CENTER, 'TR')


def test_click_on_unknown_point_changes_nothing():
    assert pivot_after_click(None, PIVOT_CURSOR, 'B') == (PIVOT_CURSOR, 'B')


# --- click or drag ------------------------------------------------------------

def test_within_threshold_is_a_click():
    assert not is_drag((100, 100), (103, 100), 3)
    assert not is_drag((100, 100), (102, 102), 3)


def test_past_threshold_is_a_drag():
    assert is_drag((100, 100), (104, 100), 3)
    assert is_drag((100, 100), (97, 97), 3)


# --- UV Editor view mapping and gizmo -------------------------------------------

class FakeView2D:
    """region pixel = offset + uv * zoom, like an Image Editor View2D."""

    def __init__(self, ox, oy, zoom_x, zoom_y):
        self.ox, self.oy, self.zx, self.zy = ox, oy, zoom_x, zoom_y

    def region_to_view(self, x, y):
        return ((x - self.ox) / self.zx, (y - self.oy) / self.zy)


def _mapping(ox=40.0, oy=-25.0, zx=400.0, zy=400.0, w=800, h=600):
    v2d = FakeView2D(ox, oy, zx, zy)
    return ViewMapping.from_region_to_view(v2d.region_to_view, w, h)


def test_view_mapping_round_trip():
    m = _mapping()
    x, y = m.to_region(0.3, 0.7)
    assert _close((x, y), (40.0 + 0.3 * 400.0, -25.0 + 0.7 * 400.0))
    assert _close(m.to_view(x, y), (0.3, 0.7))
    assert _close(m.delta_to_view(40.0, -80.0), (0.1, -0.2))


def test_view_mapping_follows_zoom_and_pan():
    a = _mapping(zx=400.0, zy=400.0)
    b = _mapping(ox=-200.0, oy=90.0, zx=1000.0, zy=1000.0)
    assert not _close(a.to_region(0.5, 0.5), b.to_region(0.5, 0.5))
    assert _close(b.to_region(0.5, 0.5), (-200.0 + 500.0, 90.0 + 500.0))


def test_uv_mode_handles_box_and_axes():
    m = _mapping()
    h = uv_mode_handles(BMIN, BMAX, m.to_region, pad=10.0, rot_offset=20.0)
    x0, y0 = m.to_region(*BMIN)
    x1, y1 = m.to_region(*BMAX)
    assert _close(h['BL'], (x0 - 10, y0 - 10))
    assert _close(h['TR'], (x1 + 10, y1 + 10))
    assert _close(h['T'], ((x0 + x1) * 0.5, y1 + 10))
    assert _close(h['L'], (x0 - 10, (y0 + y1) * 0.5))
    assert _close(h['_C'], ((x0 + x1) * 0.5, (y0 + y1) * 0.5))
    assert _close(h['_ROT'], ((x0 + x1) * 0.5, y1 + 10 + 20))
    # Axes are exactly the projected bbox width and height.
    assert _close(h['_u_dir'], (0.4 * 400.0, 0.0), 1e-6)
    assert _close(h['_v_dir'], (0.0, 0.4 * 400.0), 1e-6)


def test_uv_mode_handles_centre_is_the_bbox_centre():
    m = _mapping()
    h = uv_mode_handles(BMIN, BMAX, m.to_region)
    c = m.to_region(*anchor_uv(BMIN, BMAX, '_C'))
    assert _close(h['_C'], c, 1e-6)


def test_uv_mode_handles_flat_island_has_no_axes():
    m = _mapping()
    h = uv_mode_handles((0.2, 0.3), (0.6, 0.3), m.to_region)
    assert '_u_dir' not in h and '_v_dir' not in h
    assert 'BL' in h and 'TR' in h


def test_uv_mode_grab_follows_the_mouse():
    """A pixel drag decomposed on the UV-mode axes gives the UV offset
    that moves the island under the mouse."""
    m = _mapping()
    h = uv_mode_handles(BMIN, BMAX, m.to_region)
    (ux, uy), (vx, vy) = h['_u_dir'], h['_v_dir']
    dx, dy = 60.0, -20.0
    det = ux * vy - vx * uy
    cu = (dx * vy - dy * vx) / det
    cv = (dy * ux - dx * uy) / det
    uv_w, uv_h = BMAX[0] - BMIN[0], BMAX[1] - BMIN[1]
    assert _close((cu * uv_w, cv * uv_h), m.delta_to_view(dx, dy))


# --- UV-space island picking ----------------------------------------------------

def test_point_in_triangle_either_winding():
    a, b, c = (0.0, 0.0), (1.0, 0.0), (0.0, 1.0)
    assert point_in_triangle((0.2, 0.2), a, b, c)
    assert point_in_triangle((0.2, 0.2), a, c, b)
    assert not point_in_triangle((0.8, 0.8), a, b, c)
    assert point_in_triangle((0.5, 0.0), a, b, c)     # on an edge


def test_face_at_uv_picks_the_face_under_the_point():
    faces = [
        (3, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)]),
        (7, [(0.6, 0.6), (0.9, 0.6), (0.9, 0.9), (0.6, 0.9)]),
        (9, [(0.6, 0.0), (0.9, 0.0), (0.75, 0.3)]),
    ]
    assert face_at_uv(faces, (0.25, 0.25)) == 3
    assert face_at_uv(faces, (0.7, 0.8)) == 7
    assert face_at_uv(faces, (0.75, 0.1)) == 9
    assert face_at_uv(faces, (0.55, 0.55)) == -1
    assert face_at_uv(faces, (0.62, 0.28)) == -1     # in the bbox, outside the tri


def test_face_at_uv_mirrored_face():
    faces = [(1, [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)])]   # clockwise
    assert face_at_uv(faces, (0.5, 0.5)) == 1


def test_face_at_uv_skips_degenerate_polygons():
    assert face_at_uv([(1, [(0.0, 0.0), (1.0, 1.0)])], (0.5, 0.5)) == -1
