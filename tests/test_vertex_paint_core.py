import math

import pytest

from utils.vertex_paint_core import (FALLOFF_PRESETS, StrokeHistory,
                                     blend_color, falloff_weight,
                                     next_preset, stroke_weight)


@pytest.mark.parametrize("preset", FALLOFF_PRESETS)
def test_falloff_center_is_one_edge_is_zero(preset):
    assert falloff_weight(preset, 0.0) == pytest.approx(1.0)
    assert falloff_weight(preset, 1.0) == 0.0
    assert falloff_weight(preset, 1.5) == 0.0


@pytest.mark.parametrize("preset", [p for p in FALLOFF_PRESETS
                                    if p != "CONSTANT"])
def test_falloff_monotonic(preset):
    prev = falloff_weight(preset, 0.0)
    for i in range(1, 21):
        w = falloff_weight(preset, i / 20.0)
        assert w <= prev + 1e-9
        prev = w


def test_falloff_preset_formulas():
    assert falloff_weight("LIN", 0.25) == pytest.approx(0.75)
    assert falloff_weight("SHARP", 0.5) == pytest.approx(0.25)
    assert falloff_weight("ROOT", 0.75) == pytest.approx(0.5)
    assert falloff_weight("SMOOTH", 0.5) == pytest.approx(0.5)
    assert falloff_weight("SPHERE", 0.5) == pytest.approx(math.sqrt(0.75))
    assert falloff_weight("CONSTANT", 0.99) == 1.0


def test_custom_uses_evaluator_and_falls_back():
    assert falloff_weight("CUSTOM", 0.3, custom=lambda p: 1.0 - p) == pytest.approx(0.7)
    # evaluator result is clamped
    assert falloff_weight("CUSTOM", 0.3, custom=lambda p: 5.0) == 1.0
    # no evaluator / broken evaluator -> SMOOTH
    assert falloff_weight("CUSTOM", 0.5) == pytest.approx(0.5)

    def boom(p):
        raise RuntimeError("no curve")
    assert falloff_weight("CUSTOM", 0.5, custom=boom) == pytest.approx(0.5)


def test_next_preset_cycles():
    assert next_preset("CUSTOM") == "SMOOTH"
    assert next_preset("CONSTANT") == "CUSTOM"
    assert next_preset("CUSTOM", -1) == "CONSTANT"
    assert next_preset("???") == "SMOOTH"


def test_blend_rgb_keeps_alpha():
    out = blend_color((0, 0, 0, 0.3), (1, 1, 1, 1), 0.5)
    assert out == pytest.approx((0.5, 0.5, 0.5, 0.3))


def test_blend_alpha_keeps_rgb():
    out = blend_color((0.2, 0.4, 0.6, 1.0), (1, 1, 1, 0.0), 0.5, "ALPHA")
    assert out == pytest.approx((0.2, 0.4, 0.6, 0.5))


def test_blend_weight_clamped():
    assert blend_color((0, 0, 0, 1), (1, 1, 1, 1), 2.0) == pytest.approx((1, 1, 1, 1))
    assert blend_color((0, 0, 0, 1), (1, 1, 1, 1), -1.0) == pytest.approx((0, 0, 0, 1))


def test_stroke_weight_non_accumulating():
    m, w = stroke_weight(0.0, 0.5, 1.0)
    assert (m, w) == (0.5, 0.5)
    m, w = stroke_weight(m, 0.3, 1.0)       # a weaker dab does not add up
    assert (m, w) == (0.5, 0.5)
    m, w = stroke_weight(m, 0.9, 0.5)       # strength scales the effect
    assert (m, w) == (0.9, pytest.approx(0.45))


def test_history_undo_redo_roundtrip():
    colors = {1: "a", 2: "b"}
    h = StrokeHistory()
    h.begin()
    h.touch(1, colors[1])
    colors[1] = "A"
    h.touch(1, "should-not-overwrite")
    assert h.touched(1) and not h.touched(2)
    assert h.commit(lambda k: colors[k]) is True
    assert len(h) == 1

    restore = h.undo()
    assert restore == {1: "a"}
    assert h.undo() is None
    assert h.redo_depth == 1

    redo = h.redo()
    assert redo == {1: "A"}
    assert h.redo() is None


def test_history_commit_drops_redo_and_ignores_empty():
    h = StrokeHistory()
    h.begin(); h.touch(1, 0); h.commit(lambda k: 1)
    h.undo()
    assert h.redo_depth == 1
    h.begin()
    assert h.commit(lambda k: 1) is False      # empty stroke: no entry
    assert h.redo_depth == 1                    # ...and redo kept
    h.begin(); h.touch(2, 0); h.commit(lambda k: 2)
    assert h.redo_depth == 0


def test_history_cancel_returns_before_map():
    h = StrokeHistory()
    h.begin(); h.touch(3, "x")
    assert h.cancel() == {3: "x"}
    assert not h.active and len(h) == 0


def test_history_limit():
    h = StrokeHistory(limit=2)
    for i in range(3):
        h.begin(); h.touch(i, i); h.commit(lambda k: k)
    assert len(h) == 2
    assert h.undo() == {2: 2}
    assert h.undo() == {1: 1}
    assert h.undo() is None


from utils.vertex_paint_core import (filter_color, filter_vertex_colors,
                                     mean_color, neighborhood_mean)


def _line(n):
    """n vertices in a row, each a single corner, black..white ramp."""
    vals = [[(i / (n - 1),) * 3 + (1.0,)] for i in range(n)]
    nb = [[j for j in (i - 1, i + 1) if 0 <= j < n] for i in range(n)]
    return vals, nb


def test_mean_and_neighborhood():
    assert mean_color([(0, 0, 0, 0), (1, 1, 1, 1)]) == (0.5, 0.5, 0.5, 0.5)
    vals, nb = _line(3)
    m = neighborhood_mean(1, vals, nb)
    assert m == pytest.approx((0.5, 0.5, 0.5, 1.0))


def test_filter_color_modes_and_clamp():
    c, m = (0.2, 0.2, 0.2, 0.3), (0.6, 0.6, 0.6, 0.9)
    assert filter_color(c, m, "BLUR", 0.5) == pytest.approx((0.4, 0.4, 0.4, 0.3))
    assert filter_color(c, m, "SHARPEN", 0.5) == pytest.approx((0.0, 0.0, 0.0, 0.3))
    assert filter_color(c, m, "BLUR", 1.0, "ALPHA") == pytest.approx((0.2, 0.2, 0.2, 0.9))
    assert filter_color(c, m, "BLUR", 1.0, "RGBA") == pytest.approx((0.6, 0.6, 0.6, 0.9))


def test_blur_converges_sharpen_diverges():
    vals, nb = _line(5)
    blurred = filter_vertex_colors(vals, nb, "BLUR", 1.0, iterations=20)
    spread = max(v[0][0] for v in blurred) - min(v[0][0] for v in blurred)
    assert spread < 0.35      # ramp flattens (ends keep pulling toward edges)
    # A linear ramp is its own neighborhood mean, so sharpen a bump instead.
    bump = [[(v,) * 3 + (1.0,)] for v in (0.2, 0.2, 0.8, 0.2, 0.2)]
    sharp = filter_vertex_colors(bump, nb, "SHARPEN", 0.5)
    assert sharp[2][0][0] > 0.8 and sharp[1][0][0] < 0.2
    sharp = filter_vertex_colors(bump, nb, "SHARPEN", 1.0, iterations=3)
    assert all(0.0 <= v[0][0] <= 1.0 for v in sharp)


def test_filter_mask_and_shape():
    vals = [[(0, 0, 0, 1), (1, 1, 1, 1)], [(1, 1, 1, 1)]]      # vertex 0 has two corners
    nb = [[1], [0]]
    out = filter_vertex_colors(vals, nb, "BLUR", 1.0, mask={0})
    assert out[1] == vals[1]                 # masked out: untouched
    assert len(out[0]) == 2
    m = neighborhood_mean(0, vals, nb)       # (2/3, ...)
    assert out[0][0] == pytest.approx(m[:3] + (1.0,))
    assert vals[0][0] == (0, 0, 0, 1)        # input not mutated
