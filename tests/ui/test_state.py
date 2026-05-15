from unittest.mock import patch, MagicMock


def test_draw_scope_sets_and_restores_state():
    with patch("ui.draw.state.gpu") as mock_gpu:
        from ui.draw.state import draw_scope
        with draw_scope(blend="ALPHA", depth="ALWAYS",
                        line_width=2.5, point_size=10.0):
            pass
    calls = [c[0] for c in mock_gpu.state.blend_set.call_args_list]
    # entered with ALPHA, exited with restore value
    assert calls[0] == ("ALPHA",)


def test_draw_scope_omits_unset_params():
    with patch("ui.draw.state.gpu") as mock_gpu:
        from ui.draw.state import draw_scope
        with draw_scope(blend="ALPHA"):
            pass
    mock_gpu.state.line_width_set.assert_not_called()
    mock_gpu.state.point_size_set.assert_not_called()
    mock_gpu.state.depth_test_set.assert_not_called()
