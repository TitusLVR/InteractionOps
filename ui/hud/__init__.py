from .items import (HUDItem, HUDSection, HUDParam, HUDParamSection,
                    ItemState)
from .overlay import HUDOverlay
from .help import HelpOverlay
from .event_snap import EventSnapshot, capture_event


def handle_hud_toggle(hud, context, event) -> bool:
    """Deprecated no-op. The HUD-kill-switch key was removed when the
    HUD/Help split landed; HUD params are toggled via
    `HUDOverlay.handle_param_toggle_event` and the corner Help is toggled
    via `HelpOverlay.handle_toggle_event`. Kept as a stub so legacy
    imports don't break."""
    return False


def handle_help_toggle(help_overlay, context, event, *, hud=None) -> bool:
    """Forward modal events to the Help (and optionally HUD) overlay.

    Handles:
      * H-key toggle (expand/collapse)
      * Shift+Ctrl+Alt+LMB drag → switches the overlay to Free placement
        and writes Position X/Y back to prefs.

    Returns True when the event was consumed (operator should
    `return {'RUNNING_MODAL'}` instead of falling through to its own
    handlers)."""
    try:
        prefs = context.preferences.addons["InteractionOps"].preferences
        theme_prefs = prefs.iops_theme
    except (KeyError, AttributeError):
        return False
    consumed = False
    if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
        consumed = True
    elif (help_overlay is not None
          and help_overlay.handle_drag_event(context, event, theme_prefs)):
        consumed = True
    elif (help_overlay is not None
          and help_overlay.handle_toggle_event(event, theme_prefs)):
        consumed = True
    if consumed and context.area is not None:
        context.area.tag_redraw()
    return consumed


__all__ = ["HUDItem", "HUDSection", "HUDParam", "HUDParamSection",
           "ItemState", "HUDOverlay", "HelpOverlay",
           "EventSnapshot", "capture_event",
           "handle_hud_toggle", "handle_help_toggle"]
