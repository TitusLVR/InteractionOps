"""More Options (Tab) and the help legend, shared by the iOps modal HUDs.

A modal HUD lists its everyday options always, the rest only while More Options is on (Tab), and a Tab row also
while its option is away from its default (``also``). Every key works whether its row is shown or not; the help
legend (H, collapsed at the start) lists every key of the operator.

Usage in an operator::

    show_options: more_options_property()           # in the class body: remembered as last used

    def _build_overlays(self, region):
        more = self._more = MoreOptions(self)
        hud = self._hud = HUDOverlay("my_op")
        hud.add_param(HUDParam("Mode (Q)", lambda: self.mode, "enum"))
        hud.add_param(more.row())
        hud.add_param(HUDParam("Seed (R)", lambda: self.seed, "int",
                               visible_getter=more.when(also=lambda: self.seed != 0)))
        self._help = build_help("my_op", [("My Operator", [("Mode", "Q"), ("Seed", "R")])], region)

    # in modal(), before the other keys:
    if self._more.handle(event):
        ...redraw...
        return {"RUNNING_MODAL"}

No bpy at import time: ``more_options_property`` and ``build_help`` import what they need when called.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from .items import HUDItem, HUDParam, HUDSection, ItemState

MORE_OPTIONS_LABEL = "More Options (Tab)"
MORE_OPTIONS_HELP = ("More options in the HUD", "Tab")


def more_options_property(description: str = "List every option in the interactive mode's HUD, "
                                             "not only the main ones"):
    """The operator's ``show_options`` property: off by default, hidden from the redo panel and remembered as last
    used (no SKIP_SAVE)."""
    from bpy.props import BoolProperty
    return BoolProperty(name="More Options", description=description, default=False, options={"HIDDEN"})


class MoreOptions:
    """The More Options switch of one operator instance, read from and written to ``op.<attr>``."""

    def __init__(self, op, attr: str = "show_options"):
        self.op = op
        self.attr = attr

    @property
    def on(self) -> bool:
        return bool(getattr(self.op, self.attr, False))

    def toggle(self) -> bool:
        setattr(self.op, self.attr, not self.on)
        return self.on

    def row(self) -> HUDParam:
        """The "More Options (Tab)" row: always shown, a check mark while on."""
        return HUDParam(MORE_OPTIONS_LABEL, lambda: self.on, "bool")

    def when(self, own: Callable[[], bool] | None = None,
             also: Callable[[], bool] | None = None) -> Callable[[], bool]:
        """A ``visible_getter`` for a row of the More Options section: shown while More Options is on, or while
        ``also()`` holds (its option is in use), and in both cases only while ``own()`` holds (the row applies)."""
        def visible() -> bool:
            if own is not None and not own():
                return False
            return self.on or (also is not None and bool(also()))
        return visible

    def changed(self, *names: str) -> Callable[[], bool]:
        """An ``also`` for ``when``: True while any of the operator properties ``names`` is away from its default.
        The defaults come from ``op.properties.bl_rna``: the operator's own property type (``op.bl_rna`` of an
        operator instance holds only the base Operator fields)."""
        def any_changed() -> bool:
            try:
                props = self.op.properties.bl_rna.properties
            except (AttributeError, TypeError, ReferenceError):
                props = None
            for name in names:
                try:
                    prop = props[name]
                except (KeyError, TypeError):
                    continue
                if getattr(prop, "is_enum_flag", False):
                    default = set(prop.default_flag)
                elif getattr(prop, "is_array", False) and getattr(prop, "array_length", 0) > 0:
                    default = tuple(prop.default_array)
                else:
                    default = prop.default
                value = getattr(self.op, name)
                if isinstance(default, tuple):
                    value = tuple(value)
                if value != default:
                    return True
            return False
        return any_changed

    def handle(self, event) -> bool:
        """Tab pressed (no Ctrl, Alt or OS key): toggle and return True. The caller redraws and returns
        RUNNING_MODAL; only the HUD changes."""
        if getattr(event, "type", None) != "TAB" or getattr(event, "value", None) != "PRESS":
            return False
        if getattr(event, "ctrl", False) or getattr(event, "alt", False) or getattr(event, "oskey", False):
            return False
        self.toggle()
        return True


def help_item(label: str, key: str) -> HUDItem:
    """One line of the help legend: always shown, never marked as changed."""
    return HUDItem(label, key, ItemState.ON, default_state=ItemState.OFF, always_show=True)


def help_sections(sections: Iterable) -> list[HUDSection]:
    """``sections``: HUDSection objects or (title, items) pairs, an item being a HUDItem or a (label, key) pair."""
    out = []
    for section in sections:
        if isinstance(section, HUDSection):
            out.append(section)
            continue
        title, items = section
        out.append(HUDSection(title, [it if isinstance(it, HUDItem) else help_item(*it) for it in items]))
    return out


def build_help(name: str, sections: Iterable, region=None, *, collapsed: bool = True):
    """The operator's help legend (H): ``sections`` as for ``help_sections``, collapsed at the start unless
    ``collapsed`` is False, bound to ``region`` (None in tests)."""
    from .help import HelpOverlay
    helpo = HelpOverlay(name)
    for section in help_sections(sections):
        helpo.add_section(section)
    if collapsed:
        helpo.start_collapsed()
    helpo.bind_region(region)
    return helpo


def help_keys(helpo) -> list[str]:
    """Every key text of a help legend, in order (for tests and checks)."""
    return [it.key for section in helpo.sections for it in section.items]


__all__ = ["MORE_OPTIONS_LABEL", "MORE_OPTIONS_HELP", "MoreOptions", "more_options_property", "help_item",
           "help_sections", "build_help", "help_keys"]
