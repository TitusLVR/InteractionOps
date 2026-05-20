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


def handle_help_toggle(help_overlay, context, event) -> bool:
    """Convenience: toggle a HelpOverlay's expanded/collapsed state on
    the configured key (default "H")."""
    if help_overlay is None:
        return False
    try:
        prefs = context.preferences.addons["InteractionOps"].preferences
        theme_prefs = prefs.iops_theme
    except (KeyError, AttributeError):
        return False
    if not help_overlay.handle_toggle_event(event, theme_prefs):
        return False
    if context.area is not None:
        context.area.tag_redraw()
    return True


__all__ = ["HUDItem", "HUDSection", "HUDParam", "HUDParamSection",
           "ItemState", "HUDOverlay", "HelpOverlay",
           "EventSnapshot", "capture_event",
           "handle_hud_toggle", "handle_help_toggle"]
