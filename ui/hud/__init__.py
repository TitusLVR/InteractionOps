from .items import HUDItem, HUDSection, ItemState
from .overlay import HUDOverlay


def handle_hud_toggle(hud, context, event) -> bool:
    """Convenience: call near the top of a modal operator. If `event`
    matches the configured HUD toggle key (AddonPreferences.hud_toggle_key,
    default "H"), flips HUD visibility, schedules a redraw and returns
    True. The operator should then `return {'RUNNING_MODAL'}`.

    Plain key = visibility toggle; Shift+<same key> = verbosity toggle
    (compact ↔ full). Other modifiers are ignored."""
    if hud is None:
        return False
    try:
        prefs = context.preferences.addons["InteractionOps"].preferences
    except KeyError:
        return False
    key = getattr(prefs, "hud_toggle_key", "H")
    if event.value != "PRESS" or event.type != key:
        return False
    if event.ctrl or event.alt or event.oskey:
        return False
    if event.shift:
        hud.toggle_verbosity()
    else:
        hud.toggle_visibility()
    if context.area is not None:
        context.area.tag_redraw()
    return True


__all__ = ["HUDItem", "HUDSection", "ItemState", "HUDOverlay",
           "handle_hud_toggle"]
