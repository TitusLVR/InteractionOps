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
