"""Headless test of the HUD / Help Shift+Ctrl+Alt+LMB drag handlers.

Blender hands a running modal operator the press, the mouse moves and,
once the drag threshold is passed, a second LEFTMOUSE event whose value
is CLICK_DRAG. Operators that act on LEFTMOUSE without checking the value
would confirm on that event and the drag would "break off", so the drag
handler must swallow every LEFTMOUSE event until RELEASE, treat
INBETWEEN_MOUSEMOVE as a move, request a redraw on every consumed event
and store the release position from the mouse, not from the last draw.
Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_hud_drag.py

No viewport is needed: region, context, events and theme prefs are
SimpleNamespace stand-ins.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback
from types import SimpleNamespace

import bpy

ADDON = "InteractionOps"

hud_mod = None


def enable_addon():
    global hud_mod
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), "addon loaded from %s" % loaded
    from InteractionOps.ui import hud as _hud
    hud_mod = _hud


# --- stand-ins -------------------------------------------------------------------

class FakeRegion:
    def __init__(self):
        self.x, self.y = 100, 50
        self.width, self.height = 1000, 800
        self.redraws = 0

    def tag_redraw(self):
        self.redraws += 1


def context_with(region):
    return SimpleNamespace(region=region, area=SimpleNamespace(type="VIEW_3D"))


def event(type_, value, x, y, *, mods=True, region=None):
    return SimpleNamespace(type=type_, value=value,
                           mouse_x=region.x + x, mouse_y=region.y + y,
                           shift=mods, ctrl=mods, alt=mods)


def theme_prefs():
    return SimpleNamespace(hud_mode="cursor", hud_free_x=40, hud_free_y=40, hud_padding=12,
                           help_corner="left_center", help_free_x=40, help_free_y=40)


def make_hud():
    hud = hud_mod.HUDOverlay("Test")
    hud._last_size = (200, 100)
    return hud


def make_help():
    helpo = hud_mod.HelpOverlay("Test")
    helpo.visible = True
    helpo._last_origin = (300, 300)
    helpo._last_size = (200, 150)
    return helpo


def drag(overlay, prefs, region, *, press, moves, release, extra=()):
    """Press, moves, extra LEFTMOUSE events, release. Returns the list of
    handler results."""
    ctx = context_with(region)
    out = [overlay.handle_drag_event(ctx, event('LEFTMOUSE', 'PRESS', *press, region=region), prefs)]
    for xy in moves:
        out.append(overlay.handle_drag_event(ctx, event('MOUSEMOVE', 'NOTHING', *xy, mods=False, region=region), prefs))
    for type_, value, xy in extra:
        out.append(overlay.handle_drag_event(ctx, event(type_, value, *xy, mods=False, region=region), prefs))
    out.append(overlay.handle_drag_event(ctx, event('LEFTMOUSE', 'RELEASE', *release, mods=False, region=region), prefs))
    return out


# --- tests -----------------------------------------------------------------------

def test_hud_swallows_click_drag_and_click():
    region, prefs, hud = FakeRegion(), theme_prefs(), make_hud()
    res = drag(hud, prefs, region, press=(300, 300), moves=[(320, 310), (380, 330)],
               extra=[('LEFTMOUSE', 'CLICK_DRAG', (380, 330)),
                      ('INBETWEEN_MOUSEMOVE', 'NOTHING', (400, 340)),
                      ('LEFTMOUSE', 'CLICK', (400, 340))],
               release=(420, 350))
    assert all(res), res
    assert not hud._drag.active


def test_hud_release_position_follows_mouse_not_last_draw():
    region, prefs, hud = FakeRegion(), theme_prefs(), make_hud()
    # No draw() runs in this test, so _last_origin stays at the press
    # origin; the stored position must still be where the mouse let go.
    drag(hud, prefs, region, press=(300, 300), moves=[(400, 350)], release=(500, 400))
    assert prefs.hud_mode == "free"
    assert (prefs.hud_free_x, prefs.hud_free_y) == (500, 400 - 100), (prefs.hud_free_x, prefs.hud_free_y)


def test_hud_release_position_is_clamped_to_region():
    region, prefs, hud = FakeRegion(), theme_prefs(), make_hud()
    drag(hud, prefs, region, press=(300, 300), moves=[(50, 20)], release=(-30, -40))
    assert (prefs.hud_free_x, prefs.hud_free_y) == (12, 12), (prefs.hud_free_x, prefs.hud_free_y)


def test_hud_redraws_on_every_consumed_event():
    region, prefs, hud = FakeRegion(), theme_prefs(), make_hud()
    drag(hud, prefs, region, press=(300, 300), moves=[(310, 300), (320, 300)],
         extra=[('LEFTMOUSE', 'CLICK_DRAG', (320, 300))], release=(330, 300))
    # press + 2 moves + release; the swallowed CLICK_DRAG changes nothing.
    assert region.redraws == 4, region.redraws


def test_hud_ignores_events_without_drag():
    region, prefs, hud = FakeRegion(), theme_prefs(), make_hud()
    ctx = context_with(region)
    assert not hud.handle_drag_event(ctx, event('LEFTMOUSE', 'PRESS', 300, 300, mods=False, region=region), prefs)
    assert not hud.handle_drag_event(ctx, event('LEFTMOUSE', 'CLICK_DRAG', 300, 300, region=region), prefs)
    assert not hud.handle_drag_event(ctx, event('MOUSEMOVE', 'NOTHING', 300, 300, region=region), prefs)
    assert prefs.hud_mode == "cursor" and region.redraws == 0


def test_help_swallows_click_drag_and_stores_release():
    region, prefs, helpo = FakeRegion(), theme_prefs(), make_help()
    res = drag(helpo, prefs, region, press=(350, 350), moves=[(400, 400)],
               extra=[('LEFTMOUSE', 'CLICK_DRAG', (400, 400))], release=(450, 420))
    assert all(res), res
    assert not helpo._drag.active
    assert prefs.help_corner == "free"
    # Grabbed 50 px right / 50 px up of the origin, released at (450, 420).
    assert (prefs.help_free_x, prefs.help_free_y) == (400, 370), (prefs.help_free_x, prefs.help_free_y)
    assert region.redraws == 3, region.redraws


def test_help_press_outside_is_left_to_hud():
    region, prefs, helpo = FakeRegion(), theme_prefs(), make_help()
    ctx = context_with(region)
    assert not helpo.handle_drag_event(ctx, event('LEFTMOUSE', 'PRESS', 10, 10, region=region), prefs)
    assert not helpo._drag.active


TESTS = [
    test_hud_swallows_click_drag_and_click,
    test_hud_release_position_follows_mouse_not_last_draw,
    test_hud_release_position_is_clamped_to_region,
    test_hud_redraws_on_every_consumed_event,
    test_hud_ignores_events_without_drag,
    test_help_swallows_click_drag_and_stores_release,
    test_help_press_outside_is_left_to_hud,
]


def main():
    enable_addon()
    failed = 0
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception:
            failed += 1
            print("FAIL", test.__name__)
            traceback.print_exc()
    print("%d/%d passed" % (len(TESTS) - failed, len(TESTS)))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
