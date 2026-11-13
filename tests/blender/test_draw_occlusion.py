"""Lines behind geometry: the theme's Occluded Opacity and ``draw.edges_world``.

Background run (``blender --background --factory-startup --python-exit-code 1 --python <this>``): the theme
setting, its save / load, and that the primitive is exported. Drawing needs a GPU context, which ``--background``
has not; run the same file without ``--background`` (a window opens for a moment) to also draw into an offscreen
buffer and read the pixels back: a line on a face is drawn as is, a line behind it at the theme's factor, in
perspective and orthographic views. The windowed run exits with 1 on any failure.
"""

import math
import os
import sys
import traceback

import bpy

ADDON = "InteractionOps"


def enable_addon():
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"


def _theme_prefs():
    return bpy.context.preferences.addons[ADDON].preferences.iops_theme


# --- theme ------------------------------------------------------------------------------------------------------

def test_theme_carries_occluded_alpha():
    from InteractionOps.ui.draw import DEFAULT_THEME, get_theme
    assert DEFAULT_THEME.occluded_alpha == 0.25
    t = _theme_prefs()
    t.property_unset("occluded_alpha")
    assert t.occluded_alpha == 0.25
    assert get_theme(bpy.context).occluded_alpha == 0.25
    t.occluded_alpha = 0.6
    try:
        assert abs(get_theme(bpy.context).occluded_alpha - 0.6) < 1e-6
    finally:
        t.property_unset("occluded_alpha")


def test_occluded_opacity_property():
    prop = _theme_prefs().bl_rna.properties["occluded_alpha"]
    assert prop.name == "Occluded Opacity"
    assert (prop.hard_min, prop.hard_max, prop.default) == (0.0, 1.0, 0.25)
    assert "behind geometry" in prop.description
    t = _theme_prefs()
    t.occluded_alpha = 3.0
    assert t.occluded_alpha == 1.0
    t.property_unset("occluded_alpha")


def test_theme_preset_round_trips_occluded_alpha():
    from InteractionOps.operators.preferences.io_theme import apply_theme_dict, serialize_theme
    t = _theme_prefs()
    t.occluded_alpha = 0.4
    try:
        data = serialize_theme(t)
        assert abs(data["occluded_alpha"] - 0.4) < 1e-6
        t.occluded_alpha = 0.9
        apply_theme_dict(t, data)
        assert abs(t.occluded_alpha - 0.4) < 1e-6
    finally:
        t.property_unset("occluded_alpha")


def test_bundled_presets_name_occluded_alpha():
    import json
    from InteractionOps.operators.preferences.io_theme import bundled_themes_folder
    for name in ("Default.itheme", "Blender Default.itheme"):
        with open(os.path.join(bundled_themes_folder(), name), encoding="utf-8") as f:
            assert json.load(f)["occluded_alpha"] == 0.25, name


def test_prefs_json_round_trips_occluded_alpha():
    from InteractionOps.operators.preferences.io_addon_preferences import (load_iops_preferences,
                                                                           save_iops_preferences)
    t = _theme_prefs()
    t.occluded_alpha = 0.7
    try:
        assert save_iops_preferences()
        t.occluded_alpha = 0.1
        load_iops_preferences()
        assert abs(t.occluded_alpha - 0.7) < 1e-6, t.occluded_alpha
    finally:
        t.property_unset("occluded_alpha")
        save_iops_preferences()


def test_primitive_is_exported():
    from InteractionOps.ui.draw import primitives
    assert callable(primitives.edges_world)


TESTS = [
    test_theme_carries_occluded_alpha,
    test_occluded_opacity_property,
    test_theme_preset_round_trips_occluded_alpha,
    test_bundled_presets_name_occluded_alpha,
    test_prefs_json_round_trips_occluded_alpha,
    test_primitive_is_exported,
]


# --- drawing (needs a GPU: windowed run only) ----------------------------------------------------------------------

SIZE = 512  # about a viewport's pixel size against the bias
RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)


def _perspective(fov=math.radians(40.0), near=0.1, far=100.0):
    from mathutils import Matrix
    f = 1.0 / math.tan(fov / 2.0)
    return Matrix(((f, 0, 0, 0), (0, f, 0, 0), (0, 0, (far + near) / (near - far), 2 * far * near / (near - far)),
                   (0, 0, -1, 0)))


def _orthographic(width=4.0, near=-50.0, far=50.0):
    from mathutils import Matrix
    return Matrix(((2 / width, 0, 0, 0), (0, 2 / width, 0, 0), (0, 0, -2 / (far - near), -(far + near) / (far - near)),
                   (0, 0, 0, 1)))


def _render(projection, factor, plane_tilt=0.0, scale=1.0, behind=True):
    """Offscreen: a blue square (rotated ``plane_tilt`` about X) at the origin seen from +Z at distance 5, a red
    line lying on it along X at y = 0.4 and (``behind``) one 0.5 behind it at y = -0.4, both in the square's own
    frame, all times ``scale``; returns the pixels as rows of RGBA.

    The square is drawn as an object is, its local corners through a model matrix on the GPU, while the lines
    get world-space points computed on the CPU, so the two depths do not come out bit for bit the same."""
    import gpu
    from mathutils import Matrix, Vector
    from InteractionOps.ui.draw import Theme, draw_scope
    from InteractionOps.ui.draw import primitives as draw
    model = Matrix.Rotation(plane_tilt, 4, "X") @ Matrix.Scale(scale, 4)

    def world(x, y, z=0.0):
        return model @ Vector((x, y, z))

    quad = [Vector((x, y, 0.0)) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, -1), (1, 1), (-1, 1))]
    lines = [world(-0.8, 0.4), world(0.8, 0.4)]
    if behind:
        lines += [world(-0.8, -0.4, -0.5), world(0.8, -0.4, -0.5)]
    theme = Theme(occluded_alpha=factor)
    offscreen = gpu.types.GPUOffScreen(SIZE, SIZE)
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
            view = Matrix.Translation((0.0, 0.0, -5.0 * scale))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_projection_matrix(projection)
                gpu.matrix.load_matrix(view @ model)
                with draw_scope(depth="LESS", depth_mask=True):
                    draw.tris(quad, color=BLUE, theme=theme)
                gpu.matrix.load_matrix(view)
                draw.edges_world(lines, color=RED, width="locked", theme=theme)
            buf = fb.read_color(0, 0, SIZE, SIZE, 4, 0, "FLOAT")
            buf.dimensions = SIZE * SIZE * 4
            flat = list(buf)
    finally:
        offscreen.free()
    return [[tuple(flat[(y * SIZE + x) * 4:(y * SIZE + x) * 4 + 4]) for x in range(SIZE)] for y in range(SIZE)]


def _reddest_in_rows(pixels, rows, x):
    return max((pixels[y][x] for y in rows), key=lambda p: p[0] - p[2])


def _full_red(pixels):
    """How many pixels are drawn in the line's colour as is."""
    return sum(1 for row in pixels for p in row if p[0] > 0.9 and p[2] < 0.1)


def _check(name, projection):
    """Face-on square: the line on it full red at every factor, the line behind it red at the factor over blue."""
    half = SIZE // 2
    upper, lower = range(half + 2, half + 100), range(half - 100, half - 2)   # inside the square
    for factor, expect_behind in ((0.25, 0.25), (1.0, 1.0), (0.0, 0.0)):
        pixels = _render(projection, factor)
        for x in (half - 80, half, half + 80):
            front = _reddest_in_rows(pixels, upper, x)
            behind = _reddest_in_rows(pixels, lower, x)
            assert front[0] > 0.9 and front[2] < 0.1, (name, factor, "front", x, front)
            assert abs(behind[0] - expect_behind) < 0.08, (name, factor, "behind", x, behind)
            assert abs(behind[2] - (1.0 - expect_behind)) < 0.08, (name, factor, "behind", x, behind)
        # nothing red off the lines' rows
        assert pixels[half][half][0] < 0.05, (name, factor, pixels[half][half])


def _check_on_face(name, projection, degrees, scale=1.0):
    """The line lying on the square (turned ``degrees`` away from the view) covers as many full-colour pixels
    with the depth test as without it (factor 1): none of it is taken for hidden by the face it lies on."""
    tilt = math.radians(degrees)
    alone = _full_red(_render(projection, 1.0, tilt, scale, behind=False))
    tested = _full_red(_render(projection, 0.0, tilt, scale, behind=False))
    assert alone > 300, (name, degrees, alone)
    assert tested >= alone - 2, (name, degrees, scale, tested, alone)


def gpu_test_perspective():
    _check("perspective", _perspective())


def gpu_test_orthographic():
    _check("orthographic", _orthographic())


def gpu_test_a_line_on_its_face_is_not_dimmed():
    for degrees in (0.0, 30.0, 60.0):
        _check_on_face("perspective", _perspective(), degrees)
        _check_on_face("orthographic", _orthographic(), degrees)


def gpu_test_far_object_at_the_viewport_clip_range():
    """Blender's default view clip range (0.01 to 1000) with the object 50 units away, where depth precision is
    coarse."""
    for degrees in (0.0, 30.0, 60.0):
        _check_on_face("perspective, far", _perspective(near=0.01, far=1000.0), degrees, scale=10.0)
        _check_on_face("orthographic, far", _orthographic(width=40.0, near=-500.0, far=500.0), degrees, scale=10.0)

GPU_TESTS = [gpu_test_perspective, gpu_test_orthographic, gpu_test_a_line_on_its_face_is_not_dimmed,
             gpu_test_far_object_at_the_viewport_clip_range]


def run(tests):
    failed = 0
    for test in tests:
        try:
            test()
            print("PASS", test.__name__)
        except Exception:
            failed += 1
            print("FAIL", test.__name__)
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return failed


def main():
    enable_addon()
    failed = run(TESTS)
    if bpy.app.background:
        print("GPU drawing skipped: --background has no GPU context")
        if failed:
            sys.exit(1)
        return

    def gpu_run():
        code = 1 if failed + run(GPU_TESTS) else 0
        sys.stdout.flush()
        os._exit(code)

    bpy.app.timers.register(gpu_run, first_interval=0.5)


if __name__ == "__main__":
    main()
