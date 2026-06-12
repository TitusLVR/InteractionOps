"""CCP Data OPS widget — red-file export-category toggles + Update Red File.

Replicates the "Data OPS" / "Export Data Categories" section of the CCP
Tools addon panel (Blender_CCP_Tools ui/panels/pt_data.py). Every toggle
binds to a BoolProperty on the CCP_PG_Scene property group, reachable as
``context.scene.CCP.<prop>`` (PointerProperty registered by CCP Tools).

CCP Tools may be absent or disabled: getters then return (None, False) so
controls render disabled, setters no-op, and the Update button grays out.
This module must import cleanly without ccp_tools — it only resolves the
property group lazily from context, never at import time.
"""
from ..ui.widgets import Widget, Section, FlipBox, ActionButton, Row


def _ccp(context):
    """The CCP scene property group, or None when CCP Tools is absent."""
    return getattr(context.scene, "CCP", None)


def _bind(prop):
    """get/set pair for one CCP export-category BoolProperty.

    Re-resolves the property group from context on every call (never
    cached); single scene-level bool, so is_mixed is always False.
    """
    def get(context):
        ccp = _ccp(context)
        if ccp is None:
            return (None, False)   # CCP Tools missing -> render disabled
        return (bool(getattr(ccp, prop)), False)

    def set(context, value):
        ccp = _ccp(context)
        if ccp is not None:
            setattr(ccp, prop, bool(value))

    return get, set


def _has_ccp(context):
    return _ccp(context) is not None


def _flip(label, prop):
    """FlipBox bound to scene.CCP.<prop>."""
    return FlipBox(label, *_bind(prop))


def _export_row(label, prop, export_op):
    """Toggle + explicit per-item export button — one panel row, same as
    the CCP panel's 2-column grid rows."""
    return Row([_flip(label, prop),
                ActionButton("Export", op=export_op,
                             enabled_get=_has_ccp)])


class CCPDataOpsWidget(Widget):
    """Persistent CCP Data OPS panel: export-category toggles grouped as
    in the CCP panel (Materials / Sets / Light / Locators), one item per
    row with its explicit export action where the panel has one, and the
    Update Red File action."""

    name = "ccp_data_ops"
    title = "CCP Data OPS"
    space = "VIEW_3D"

    def build(self):
        return [
            Section("Materials"),
            _flip("OpaqueAreas", "red_export_opaqueAreas"),
            _flip("DecalAreas", "red_export_decalAreas"),
            _flip("TransparentAreas", "red_export_transparentAreas"),
            _flip("AdditiveAreas", "red_export_additiveAreas"),
            _flip("DistortionAreas", "red_export_distortionAreas"),
            Section("Sets"),
            _export_row("Banner", "red_export_bannerSets",
                        "ccp_tools.export_banner_data"),
            _export_row("Decal", "red_export_decalSets",
                        "ccp_tools.export_decal_data"),
            _export_row("Plane", "red_export_planeSets",
                        "ccp_tools.export_plane_data"),
            _export_row("Sprite", "red_export_spriteSets",
                        "ccp_tools.export_sprite_data"),
            _export_row("Sprite Line", "red_export_spriteLineSets",
                        "ccp_tools.export_sprite_line_sets_data"),
            Section("Light"),
            _export_row("Light", "red_export_lightSets",
                        "ccp_tools.export_light_data"),
            _export_row("Spotlight", "red_export_spotlightSets",
                        "ccp_tools.export_spotlight_data"),
            Section("Locators"),
            _export_row("Booster", "red_export_booster",
                        "ccp_tools.export_booster_data"),
            _export_row("Locator", "red_export_locatorSets",
                        "ccp_tools.export_locator_data"),
            _export_row("Turrets", "red_export_locatorTurrets",
                        "ccp_tools.export_locator_turret_data"),
            ActionButton("Update Red File", op="ccp_tools.update_red_file",
                         kwargs={},
                         enabled_get=_has_ccp),
        ]

    def poll(self, context):
        # Always True: "addon missing" disables controls via (None, False)
        # instead of collapsing the panel (poll False = mode-gating only).
        return True
