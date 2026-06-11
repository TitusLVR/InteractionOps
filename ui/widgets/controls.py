"""Widget controls — Control base + Slider, PresetRow, FlipBox,
ActionButton, Section, Row.

IMPORTANT: this module must stay importable WITHOUT bpy. All value<->pixel
math lives in module-level functions so it can be unit-tested with plain
pytest. The only bpy usage is inside `ActionButton.execute()` (a deferred
local import that only runs inside Blender when the user clicks).

Data-binding contract (per the widget design doc):
- getters:  get(context) -> (value, is_mixed). `value is None` means
  "nothing to read" (e.g. no selection) and renders/behaves as disabled.
- setters:  set(context, value) writes uniformly to ALL selected elements.
  Setters must re-acquire bmesh per call — controls cache plain
  floats/bools ONLY, never bmesh/element references.
- optional Slider gesture hooks: snapshot(context) -> token captured at
  drag start (plain data); restore(context, token) puts the pre-drag
  per-element values back on ESC/RMB cancel.
"""
from __future__ import annotations


# ----------------------------------------------------------------------
# Slider value <-> pixel math (pure, pytest-covered)
# ----------------------------------------------------------------------
def clamp(value: float, vmin: float, vmax: float) -> float:
    return max(vmin, min(vmax, value))


def value_from_pixel(mx: float, track_x: float, track_w: float,
                     vmin: float = 0.0, vmax: float = 1.0) -> float:
    """Map a region-pixel x onto the value range, clamped to [vmin, vmax]."""
    if track_w <= 0.0:
        return vmin
    t = (mx - track_x) / track_w
    return clamp(vmin + t * (vmax - vmin), vmin, vmax)


def pixel_from_value(value: float, track_x: float, track_w: float,
                     vmin: float = 0.0, vmax: float = 1.0) -> float:
    """Map a value onto the track pixel span, clamped to the track."""
    span = vmax - vmin
    if span == 0.0:
        return track_x
    t = clamp((value - vmin) / span, 0.0, 1.0)
    return track_x + t * track_w


def snap_value(value: float, snap: float) -> float:
    """Round to the nearest snap increment. snap <= 0 disables snapping."""
    if snap <= 0.0:
        return value
    return round(value / snap) * snap


def slider_drag_value(mx: float, track_x: float, track_w: float,
                      vmin: float = 0.0, vmax: float = 1.0,
                      snap: float = 0.125, smooth: bool = False) -> float:
    """Full drag mapping: pixel -> value, snapped unless `smooth` (Ctrl)."""
    v = value_from_pixel(mx, track_x, track_w, vmin, vmax)
    if not smooth:
        v = clamp(snap_value(v, snap), vmin, vmax)
    return v


def mixed_state(values):
    """Aggregate an iterable of plain values into (value, is_mixed).

    Empty input -> (None, False) — the "disabled / nothing selected"
    sentinel. Helper for widget value adapters and pytest coverage.
    """
    first = None
    seen = False
    for v in values:
        if not seen:
            first = v
            seen = True
        elif v != first:
            return (first, True)
    return (first if seen else None, False)


def preset_cell_rects(rect_x: float, rect_w: float, n: int,
                      gap: float = 4.0):
    """Split a row rect horizontally into n equal cells; returns a list of
    (x, w). Shared by render (drawing) and events (hit-testing) so the two
    can never disagree."""
    n = max(1, int(n))
    cell_w = (rect_w - gap * (n - 1)) / n
    return [(rect_x + i * (cell_w + gap), cell_w) for i in range(n)]


def preset_index(mx: float, rect_x: float, rect_w: float, n: int,
                 gap: float = 4.0) -> int:
    """Resolve which preset cell a pixel x falls in; -1 when in a gap."""
    for i, (x, w) in enumerate(preset_cell_rects(rect_x, rect_w, n, gap)):
        if x <= mx <= x + w:
            return i
    return -1


# ----------------------------------------------------------------------
# Controls
# ----------------------------------------------------------------------
class Control:
    """Base control. Subclasses set `kind` (render/event dispatch key) and
    `interactive` (whether clicks resolve to a gesture)."""

    kind = "control"
    interactive = False
    columns = 1

    def __init__(self):
        self.enabled = True
        # Optional live hook: enabled_get(context) -> bool. Controls
        # without a value getter (PresetRow, ActionButton) use it to go
        # inert/grayed when there is nothing to act on (spec: presets and
        # Clear are inert with no selection). Dirty-cached like values so
        # per-frame draws never rescan the mesh.
        self.enabled_get = None
        self._enabled_dirty = True

    def mark_dirty(self):
        """Invalidate any cached display value / enabled state. Extended
        by value-bearing controls."""
        self._enabled_dirty = True

    def update_enabled(self, context):
        """Resolve `enabled` from the live context via `enabled_get`
        (no-op without the hook). Returns the resolved flag — used by
        render (disabled alpha) and the interact gesture gate."""
        if self.enabled_get is not None and self._enabled_dirty:
            self.enabled = bool(self.enabled_get(context))
            self._enabled_dirty = False
        return self.enabled


class Section(Control):
    """Non-interactive section label row."""

    kind = "section"

    def __init__(self, label):
        super().__init__()
        self.label = label


class _ValueControl(Control):
    """Shared cache machinery for controls bound to a get/set pair.

    The cache holds plain (value, is_mixed) only — never bmesh data.
    `value()` recomputes lazily when dirty; `cached()` returns the last
    known pair without touching the getter (used while out of context,
    where calling into bmesh would be invalid).
    """

    def __init__(self, get, set):
        super().__init__()
        self.get = get
        self.set = set
        self._cache = (None, False)
        self._dirty = True

    def mark_dirty(self):
        super().mark_dirty()
        self._dirty = True

    def cached(self):
        return self._cache

    def value(self, context):
        if self._dirty:
            v, mixed = self.get(context)
            self._cache = (v, bool(mixed))
            self._dirty = False
        return self._cache

    def write(self, context, value):
        """Uniform write to all selected elements + optimistic cache update
        (a depsgraph tick will re-mark dirty and confirm on next draw)."""
        self.set(context, value)
        self._cache = (value, False)
        self._dirty = False


class Slider(_ValueControl):
    """Horizontal drag slider. Snaps to `snap` increments by default;
    Ctrl during drag = smooth free values. `value is None` from the
    getter renders as disabled (empty track, no thumb)."""

    kind = "slider"
    interactive = True

    def __init__(self, get, set, vmin=0.0, vmax=1.0, snap=0.125,
                 fmt="{:.3f}", snapshot=None, restore=None):
        super().__init__(get, set)
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.snap = float(snap)
        self.fmt = fmt
        self.snapshot = snapshot
        self.restore = restore
        # Track pixel span, written back by render each frame so the
        # interact modal maps mouse x with the exact drawn geometry.
        self.track_x = 0.0
        self.track_w = 1.0

    def drag_value(self, mx, smooth=False):
        return slider_drag_value(mx, self.track_x, self.track_w,
                                 self.vmin, self.vmax, self.snap, smooth)


class PresetRow(Control):
    """Row of absolute-value preset buttons sharing one setter."""

    kind = "presets"
    interactive = True

    def __init__(self, values, set, fmt="{:g}", enabled_get=None):
        super().__init__()
        self.values = list(values)
        self.set = set
        self.fmt = fmt
        self.enabled_get = enabled_get

    def write(self, context, value):
        self.set(context, value)

    def index_at(self, mx, rect_x, rect_w):
        return preset_index(mx, rect_x, rect_w, len(self.values))


class FlipBox(_ValueControl):
    """Checkbox + label bound to a boolean get/set. Mixed selection draws
    a diagonal half-fill; clicking a mixed box sets ALL to True."""

    kind = "flipbox"
    interactive = True

    def __init__(self, label, get, set):
        super().__init__(get, set)
        self.label = label

    def next_value(self, context):
        """Value a click should write: mixed -> True, else invert."""
        value, mixed = self.value(context)
        if mixed or value is None:
            return True
        return not value


class ActionButton(Control):
    """Fires an operator on click (release inside the button)."""

    kind = "button"
    interactive = True

    def __init__(self, label, op, kwargs=None, role="default",
                 enabled_get=None):
        super().__init__()
        self.label = label
        self.op = op            # operator idname, e.g. "iops.executor"
        self.kwargs = dict(kwargs) if kwargs else {}
        self.role = role        # "default" | "error" (render color hint)
        self.enabled_get = enabled_get

    def execute(self, context):
        # The ONLY bpy touch in this module — deferred so the module stays
        # importable under plain pytest.
        import bpy
        module, _, name = self.op.partition(".")
        op = getattr(getattr(bpy.ops, module), name)
        return op(**self.kwargs)


class Row(Control):
    """Horizontal container: splits the content width equally among its
    children. One layout row, len(children) columns."""

    kind = "row"

    def __init__(self, children):
        super().__init__()
        self.children = list(children)

    @property
    def columns(self):
        return max(1, len(self.children))

    def mark_dirty(self):
        super().mark_dirty()
        for child in self.children:
            child.mark_dirty()
