from ui.draw.theme import Theme, Role, DEFAULT_THEME


def test_default_theme_has_every_role():
    for role in Role:
        rgba = DEFAULT_THEME.color_for(role)
        assert len(rgba) == 4
        assert all(0.0 <= c <= 1.0 for c in rgba)


def test_default_theme_primary_is_cyan_full_alpha():
    r, g, b, a = DEFAULT_THEME.color_for(Role.PRIMARY)
    assert a == 1.0
    assert b > r and b > g  # cyan-ish: blue dominant


def test_width_token_resolution():
    assert DEFAULT_THEME.width("normal") == 1.5
    assert DEFAULT_THEME.width("thick") == 3.0
    assert DEFAULT_THEME.width("preview") == 2.0


def test_point_size_token_resolution():
    assert DEFAULT_THEME.point_size("small") == 6.0
    assert DEFAULT_THEME.point_size("normal") == 9.0
    assert DEFAULT_THEME.point_size("large") == 12.0


def test_text_size_token_resolution():
    assert DEFAULT_THEME.text_size("small") == 11
    assert DEFAULT_THEME.text_size("normal") == 12
    assert DEFAULT_THEME.text_size("title") == 14


def test_unknown_token_raises():
    import pytest
    with pytest.raises(KeyError):
        DEFAULT_THEME.width("ridiculous")


from unittest.mock import MagicMock


def _fake_context_with_theme_prefs():
    ctx = MagicMock()
    t = ctx.preferences.addons["InteractionOps"].preferences.iops_theme
    t.color_primary = (0.1, 0.2, 0.3, 0.4)
    t.color_secondary = (0.5, 0.5, 0.5, 0.7)
    t.color_locked = (1.0, 0.7, 0.3, 1.0)
    t.color_snap = (1.0, 1.0, 1.0, 0.6)
    t.color_snap_closest = (0.3, 1.0, 0.6, 1.0)
    t.color_preview = (0.3, 0.8, 1.0, 0.4)
    t.color_fill = (0.3, 0.8, 1.0, 0.1)
    t.color_outline = (0.3, 0.8, 1.0, 0.8)
    t.color_hint = (1.0, 1.0, 1.0, 0.25)
    t.color_error = (1.0, 0.35, 0.35, 1.0)
    t.color_success = (0.3, 1.0, 0.6, 1.0)
    t.line_width_normal = 1.5
    t.line_width_thick = 3.0
    t.line_width_preview = 2.0
    t.point_size_small = 6.0
    t.point_size_normal = 9.0
    t.point_size_large = 12.0
    t.text_size_small = 11
    t.text_size_normal = 12
    t.text_size_title = 14
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
    from ui.draw.theme import get_theme, DEFAULT_THEME
    ctx = MagicMock()
    ctx.preferences.addons.__getitem__.side_effect = KeyError
    theme = get_theme(ctx)
    assert theme.color_for(Role.PRIMARY) == DEFAULT_THEME.color_for(Role.PRIMARY)


def test_get_theme_reads_from_prefs():
    from ui.draw.theme import get_theme
    ctx = _fake_context_with_theme_prefs()
    theme = get_theme(ctx)
    assert theme.color_for(Role.PRIMARY) == (0.1, 0.2, 0.3, 0.4)
    assert theme.width("normal") == 1.5
    assert theme.hud.mode == "cursor"
    assert theme.shadow.blur == 3
