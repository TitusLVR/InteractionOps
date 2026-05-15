from ui.hud.layout import compute_origin, clamp_to_region


def _region(w=1920, h=1080):
    class R:
        width = w
        height = h
    return R()


def test_corner_top_left():
    x, y = compute_origin("top_left", region=_region(), mouse=(0, 0),
                          content_size=(200, 100), padding=12,
                          offset=(0, 0), free=(0, 0))
    assert x == 12
    assert y == 1080 - 12 - 100


def test_corner_bottom_right():
    x, y = compute_origin("bottom_right", region=_region(), mouse=(0, 0),
                          content_size=(200, 100), padding=12,
                          offset=(0, 0), free=(0, 0))
    assert x == 1920 - 200 - 12
    assert y == 12


def test_cursor_follow_default_offset():
    x, y = compute_origin("cursor", region=_region(), mouse=(500, 500),
                          content_size=(200, 100), padding=12,
                          offset=(20, -20), free=(0, 0))
    assert x == 520
    assert y == 380  # 500 + (-20) - 100


def test_free_uses_free_coords():
    x, y = compute_origin("free", region=_region(), mouse=(0, 0),
                          content_size=(200, 100), padding=12,
                          offset=(0, 0), free=(300, 400))
    assert (x, y) == (300, 400)


def test_clamp_keeps_hud_inside_region():
    x, y = clamp_to_region(2000, 1200, content_size=(200, 100),
                           region=_region(), padding=4)
    assert x + 200 <= 1920 - 4
    assert y + 100 <= 1080 - 4


def test_clamp_keeps_hud_off_negative_corners():
    x, y = clamp_to_region(-50, -50, content_size=(200, 100),
                           region=_region(), padding=4)
    assert x >= 4
    assert y >= 4
