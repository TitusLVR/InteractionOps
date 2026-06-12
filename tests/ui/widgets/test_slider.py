"""Pure-pytest tests for ui/widgets/controls.py slider math (no bpy).

Covers: pixel<->value mapping in both directions, snap-to-increment
quantization, Ctrl smooth drag (no quantization), clamping to the value
range, and the mixed display state aggregation.
"""
import pytest

from ui.widgets.controls import (
    clamp,
    value_from_pixel,
    pixel_from_value,
    snap_value,
    slider_drag_value,
    mixed_state,
    preset_cell_rects,
    preset_index,
    Slider,
)

# Track used throughout: x in [100, 300] maps onto value in [0, 1].
TX, TW = 100.0, 200.0


# ----------------------------------------------------------------------
# pixel -> value
# ----------------------------------------------------------------------
def test_value_from_pixel_endpoints_and_mid():
    assert value_from_pixel(TX, TX, TW) == pytest.approx(0.0)
    assert value_from_pixel(TX + TW, TX, TW) == pytest.approx(1.0)
    assert value_from_pixel(TX + TW * 0.5, TX, TW) == pytest.approx(0.5)


def test_value_from_pixel_clamps_outside_track():
    assert value_from_pixel(TX - 50.0, TX, TW) == pytest.approx(0.0)
    assert value_from_pixel(TX + TW + 50.0, TX, TW) == pytest.approx(1.0)


def test_value_from_pixel_custom_range():
    assert value_from_pixel(TX + TW * 0.25, TX, TW, vmin=2.0, vmax=6.0) == \
        pytest.approx(3.0)
    # Clamped to custom range too.
    assert value_from_pixel(TX - 999.0, TX, TW, vmin=2.0, vmax=6.0) == \
        pytest.approx(2.0)


def test_value_from_pixel_degenerate_track_returns_vmin():
    assert value_from_pixel(150.0, TX, 0.0, vmin=0.25) == pytest.approx(0.25)
    assert value_from_pixel(150.0, TX, -5.0, vmin=0.25) == pytest.approx(0.25)


# ----------------------------------------------------------------------
# value -> pixel
# ----------------------------------------------------------------------
def test_pixel_from_value_endpoints_and_mid():
    assert pixel_from_value(0.0, TX, TW) == pytest.approx(TX)
    assert pixel_from_value(1.0, TX, TW) == pytest.approx(TX + TW)
    assert pixel_from_value(0.5, TX, TW) == pytest.approx(TX + TW * 0.5)


def test_pixel_from_value_clamps_to_track():
    assert pixel_from_value(-2.0, TX, TW) == pytest.approx(TX)
    assert pixel_from_value(3.0, TX, TW) == pytest.approx(TX + TW)


def test_pixel_from_value_zero_span_returns_track_start():
    assert pixel_from_value(5.0, TX, TW, vmin=1.0, vmax=1.0) == \
        pytest.approx(TX)


def test_pixel_value_round_trip():
    for v in (0.0, 0.125, 0.3, 0.5, 0.875, 1.0):
        px = pixel_from_value(v, TX, TW)
        assert value_from_pixel(px, TX, TW) == pytest.approx(v)


# ----------------------------------------------------------------------
# Snapping
# ----------------------------------------------------------------------
def test_snap_value_quantizes_to_increment():
    assert snap_value(0.30, 0.125) == pytest.approx(0.25)
    assert snap_value(0.32, 0.125) == pytest.approx(0.375)
    assert snap_value(0.0, 0.125) == pytest.approx(0.0)
    assert snap_value(1.0, 0.125) == pytest.approx(1.0)
    assert snap_value(0.49, 0.125) == pytest.approx(0.5)


def test_snap_value_disabled_when_nonpositive():
    assert snap_value(0.30, 0.0) == pytest.approx(0.30)
    assert snap_value(0.30, -1.0) == pytest.approx(0.30)


# ----------------------------------------------------------------------
# Full drag mapping (snap vs Ctrl smooth, clamping)
# ----------------------------------------------------------------------
def test_slider_drag_value_snaps_by_default():
    mx = pixel_from_value(0.30, TX, TW)
    assert slider_drag_value(mx, TX, TW) == pytest.approx(0.25)


def test_slider_drag_value_smooth_skips_snap():
    mx = pixel_from_value(0.30, TX, TW)
    assert slider_drag_value(mx, TX, TW, smooth=True) == pytest.approx(0.30)


def test_slider_drag_value_clamps_to_range():
    assert slider_drag_value(TX - 999.0, TX, TW) == pytest.approx(0.0)
    assert slider_drag_value(TX + 999.0, TX, TW) == pytest.approx(1.0)
    assert slider_drag_value(TX - 999.0, TX, TW, smooth=True) == \
        pytest.approx(0.0)
    assert slider_drag_value(TX + 999.0, TX, TW, smooth=True) == \
        pytest.approx(1.0)


def test_slider_drag_value_snap_result_stays_in_range():
    # Snap increment that does not divide the range evenly: the snapped
    # value must still be clamped to [vmin, vmax].
    v = slider_drag_value(TX + 999.0, TX, TW, vmin=0.0, vmax=1.0, snap=0.3)
    assert 0.0 <= v <= 1.0


def test_slider_class_drag_value_uses_track_span():
    sl = Slider(get=lambda ctx: (0.5, False), set=lambda ctx, v: None)
    sl.track_x, sl.track_w = TX, TW
    mx = pixel_from_value(0.30, TX, TW)
    assert sl.drag_value(mx) == pytest.approx(0.25)          # snapped
    assert sl.drag_value(mx, smooth=True) == pytest.approx(0.30)  # Ctrl


# ----------------------------------------------------------------------
# Mixed display state
# ----------------------------------------------------------------------
def test_mixed_state_empty_is_disabled_sentinel():
    assert mixed_state([]) == (None, False)


def test_mixed_state_uniform():
    assert mixed_state([0.25]) == (0.25, False)
    assert mixed_state([0.25, 0.25, 0.25]) == (0.25, False)


def test_mixed_state_mixed_returns_first_value():
    assert mixed_state([0.25, 0.5]) == (0.25, True)
    assert mixed_state([True, False, True]) == (True, True)


def test_slider_cache_and_mixed_flow():
    values = {"v": (0.25, True)}
    writes = []
    sl = Slider(get=lambda ctx: values["v"],
                set=lambda ctx, v: writes.append(v))
    # Lazy recompute caches the (value, mixed) pair.
    assert sl.value(None) == (0.25, True)
    assert sl.cached() == (0.25, True)
    # cached() never calls the getter again, even after the source changed.
    values["v"] = (0.75, False)
    assert sl.cached() == (0.25, True)
    assert sl.value(None) == (0.25, True)  # still clean -> cache
    sl.mark_dirty()
    assert sl.value(None) == (0.75, False)
    # write() = setter call + optimistic un-mixed cache update.
    sl.write(None, 0.5)
    assert writes == [0.5]
    assert sl.cached() == (0.5, False)


# ----------------------------------------------------------------------
# Preset cell math (shared by render + hit-testing)
# ----------------------------------------------------------------------
def test_preset_cells_fill_row_and_index_round_trip():
    cells = preset_cell_rects(TX, TW, 4, gap=4.0)
    assert len(cells) == 4
    assert cells[0][0] == pytest.approx(TX)
    assert cells[-1][0] + cells[-1][1] == pytest.approx(TX + TW)
    for i, (x, w) in enumerate(cells):
        assert preset_index(x + w * 0.5, TX, TW, 4) == i


def test_preset_index_gap_returns_minus_one():
    cells = preset_cell_rects(TX, TW, 4, gap=4.0)
    gap_x = cells[0][0] + cells[0][1] + 2.0  # middle of the first gap
    assert preset_index(gap_x, TX, TW, 4) == -1
    assert preset_index(TX - 10.0, TX, TW, 4) == -1
