from unittest.mock import MagicMock

from ui.draw.theme import (Theme, Role, DEFAULT_THEME, state_from_role,
                           STATES, get_theme)


def test_default_theme_has_every_role():
    for role in Role:
        rgba = DEFAULT_THEME.color_for(role)
        assert len(rgba) == 4
        assert all(0.0 <= c <= 1.0 for c in rgba)


def test_active_point_is_cyan_full_alpha():
    r, g, b, a = DEFAULT_THEME.color_for(Role.ACTIVE_POINT)
    assert a == 1.0
    assert b > r and b > g  # cyan-ish


def test_state_from_role():
    assert state_from_role(Role.POINT) == "default"
    assert state_from_role(Role.CLOSEST_POINT) == "closest"
    assert state_from_role(Role.ACTIVE_LINE) == "active"
    assert state_from_role(Role.LOCKED_TEXT) == "locked"
    assert state_from_role(Role.PREVIEW_POINT) == "preview"


def test_point_size_resolves_per_state():
    for s in STATES:
        assert DEFAULT_THEME.point_size(s) > 0
    assert DEFAULT_THEME.point_size_for(Role.CLOSEST_POINT) == \
           DEFAULT_THEME.point_size("closest")


def test_line_width_resolves_per_state():
    for s in STATES:
        assert DEFAULT_THEME.width(s) > 0
    assert DEFAULT_THEME.line_width_for(Role.LOCKED_LINE) == \
           DEFAULT_THEME.width("locked")


def test_text_size_aliases():
    # "normal"/"small" map to default, "title" maps to active.
    assert DEFAULT_THEME.text_size("normal") == DEFAULT_THEME.text_size("default")
    assert DEFAULT_THEME.text_size("title")  == DEFAULT_THEME.text_size("active")


def test_unknown_token_raises():
    import pytest
    with pytest.raises(KeyError):
        DEFAULT_THEME.width("ridiculous")


def _fake_context_with_theme_prefs():
    ctx = MagicMock()
    t = ctx.preferences.addons["InteractionOps"].preferences.iops_theme
    # Colors (only the ones we assert on need exact values).
    t.color_active_point = (0.1, 0.2, 0.3, 0.4)
    # Provide all per-state sizes / widths consistently.
    for s in STATES:
        setattr(t, f"point_size_{s}",  10.0)
        setattr(t, f"line_width_{s}",   2.0)
        setattr(t, f"text_size_{s}",    13)
    t.shadow_enabled = True
    t.shadow_color = (0.0, 0.0, 0.0, 0.7)
    t.shadow_blur = 3
    t.shadow_offset_x = 1
    t.shadow_offset_y = -1
    t.hud_mode = "cursor"
    t.hud_offset_x = 20
    t.hud_offset_y = -20
    t.hud_free_x = 40
    t.hud_free_y = 40
    t.hud_padding = 12
    t.hud_section_spacing = 8
    t.hud_row_spacing = 2
    t.hud_key_column_width = 60
    t.depth_test_default = "LESS"
    return ctx


def test_get_theme_returns_default_when_prefs_missing():
    ctx = MagicMock()
    ctx.preferences.addons.__getitem__.side_effect = KeyError
    theme = get_theme(ctx)
    assert theme.color_for(Role.ACTIVE_POINT) == DEFAULT_THEME.color_for(Role.ACTIVE_POINT)


def test_get_theme_reads_from_prefs():
    ctx = _fake_context_with_theme_prefs()
    theme = get_theme(ctx)
    assert theme.color_for(Role.ACTIVE_POINT) == (0.1, 0.2, 0.3, 0.4)
    assert theme.point_size("active") == 10.0
    assert theme.width("locked") == 2.0
    assert theme.hud.mode == "cursor"
    assert theme.shadow.blur == 3
