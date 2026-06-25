"""Widget controls — Control base + Slider, PresetRow, FlipBox,
ActionButton, Section, Row, Swatch, Dropdown, InputField, ButtonGroup.

IMPORTANT: this module must stay importable WITHOUT bpy. All value<->pixel
math lives in module-level functions so it can be unit-tested with plain
pytest. The only bpy usage is inside `_invoke_operator()` — a deferred
local import that only runs inside Blender when a button or swatch fires
(called by ActionButton.execute and Swatch.execute).

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
        # Optional show_if predicate (validated dict) attached by the
        # composed builder; None = always visible. Read by the framework's
        # row filtering (ui/widgets/predicates.filter_controls).
        self._show_if = None

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


def _invoke_operator(op_idname, kwargs):
    """Fire an operator by idname via INVOKE_DEFAULT. The ONLY bpy touch in
    this module — deferred import so the module stays importable under plain
    pytest. INVOKE_DEFAULT: invoke-only operators (e.g. CCP export ops) raise
    under EXEC_DEFAULT; operators without invoke fall through to execute, so
    this is safe for both kinds. Shared by ActionButton and Swatch."""
    import bpy
    module, _, name = op_idname.partition(".")
    op = getattr(getattr(bpy.ops, module), name)
    return op("INVOKE_DEFAULT", **kwargs)


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
        return _invoke_operator(self.op, self.kwargs)


class Swatch(_ValueControl):
    """Color swatch bound to an RGBA getter, firing an operator on click.

    Read-only binding: `set` is None and `write()` is never called — the
    swatch only displays its color and fires `op` (release-inside, exactly
    like ActionButton). The getter returns (rgba, is_mixed); a None color is
    the disabled sentinel (renders faded, no operator fires). Scalar binding,
    so is_mixed is always False."""

    kind = "swatch"
    interactive = True

    def __init__(self, get, op, kwargs=None, label="", enabled_get=None):
        super().__init__(get, None)
        self.op = op            # operator idname, e.g. "iops.object_color_apply"
        self.kwargs = dict(kwargs) if kwargs else {}
        self.label = label      # optional centered glyph/text on the fill
        self.enabled_get = enabled_get

    def execute(self, context):
        return _invoke_operator(self.op, self.kwargs)


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


# ----------------------------------------------------------------------
# RNA-bound input controls (Dropdown / InputField / ButtonGroup)
#
# These are plain Control subclasses (NOT _ValueControl): their value can be
# changed by an external native popup (Dropdown/InputField delegate editing
# to iops.widget_edit_prop) that never triggers the widget's mark_dirty, so
# they read their getter LIVE on each draw rather than via the dirty cache.
# A scalar getattr per draw is cheap and they always poll in-context (RNA,
# not edge data), so the draw path is always live.
# ----------------------------------------------------------------------
class Dropdown(Control):
    """Enum-bound display box edited IN-OVERLAY: clicking opens a clickable
    item list drawn in the panel (no native popup). Collapsed, it shows the
    current value.

    `get(context) -> (value, is_mixed)` reads the bound enum identifier live;
    `set(context, value)` writes the chosen identifier. `labels` is an
    optional {identifier: display} map (declared in JSON); `items_get(context)
    -> [(identifier, display), ...]` is the runtime fallback list (live enum
    introspection) used when no labels are declared."""

    kind = "dropdown"
    interactive = True

    def __init__(self, get, set, path, items_get=None, labels=None, label=""):
        super().__init__()
        self.get = get
        self.set = set
        self.path = path
        self.items_get = items_get
        self.labels = dict(labels) if labels else {}
        self.label = label

    def items(self, context):
        """Selectable (identifier, display) list. Declared `labels` win (their
        keys ARE the items, in declared order); else the live enum via
        `items_get`; else empty."""
        if self.labels:
            return list(self.labels.items())
        if self.items_get is not None:
            return list(self.items_get(context))
        return []

    def display(self, context):
        """Current-value display string: declared label / live item name for
        the current identifier, else the raw identifier; "—" when None."""
        value, _mixed = self.get(context)
        if value is None:
            return "—"
        if self.labels:
            return self.labels.get(value, value)
        if self.items_get is not None:
            for ident, disp in self.items_get(context):
                if ident == value:
                    return disp
        return value

    def write(self, context, value):
        self.set(context, value)


class InputField(Control):
    """Number/string-bound field edited IN-OVERLAY: clicking starts a text
    caret in the field (no native popup). `get(context) -> (value, is_mixed)`
    reads the live author-space value (degrees for an angle); `set(context,
    text)` writes it (the bound adapter coerces the text to the prop type —
    int/float/degrees->radians/str). `fmt` formats numbers for display."""

    kind = "input"
    interactive = True

    def __init__(self, get, set, path, fmt="{}", label=""):
        super().__init__()
        self.get = get
        self.set = set
        self.path = path
        self.fmt = fmt
        self.label = label

    def display(self, context):
        """Current-value display string: fmt.format(value) for numbers /
        str(value) for strings, "—" when value is None."""
        value, _mixed = self.get(context)
        if value is None:
            return "—"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return self.fmt.format(value)
        return str(value)

    def edit_string(self, context):
        """Seed string for a fresh edit: the current value rendered as text
        ("" when None)."""
        value, _mixed = self.get(context)
        if value is None:
            return ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return self.fmt.format(value)
        return str(value)

    def write(self, context, text):
        """Commit edited text. The bound adapter's set coerces to the prop
        type and may raise (ValueError/TypeError) on unparseable numbers —
        the caller discards on failure."""
        self.set(context, text)


class ButtonGroup(Control):
    """Segmented radio row: an author-defined set of buttons, each holding
    one predefined value. At most one is active — the one whose value matches
    the live bound property. Clicking a button writes its value.

    `options` is a normalized list of (value, label) pairs (see
    `button_group_options`). `get(context) -> (value, is_mixed)` reads the
    live bound value; `set(context, value)` writes a clicked option's value.
    Cell math is shared with PresetRow via `preset_index`."""

    kind = "buttons"
    interactive = True

    def __init__(self, get, set, options, enabled_get=None):
        super().__init__()
        self.get = get
        self.set = set
        self.options = list(options)   # [(value, label), ...]
        self.enabled_get = enabled_get

    def active_index(self, context):
        """Index of the option matching the live bound value; -1 when no
        option matches (honest off-grid state — no button forced on).
        Numbers match within abs<=1e-6, everything else by equality. Read
        live each draw."""
        value, _mixed = self.get(context)
        if value is None:
            return -1
        for i, (opt_value, _label) in enumerate(self.options):
            if (isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and isinstance(opt_value, (int, float))
                    and not isinstance(opt_value, bool)):
                if abs(value - opt_value) <= 1e-6:
                    return i
            elif value == opt_value:
                return i
        return -1

    def index_at(self, mx, rect_x, rect_w):
        return preset_index(mx, rect_x, rect_w, len(self.options))

    def write(self, context, value):
        self.set(context, value)


def button_group_options(values, items, fmt="{:g}", unit=""):
    """Normalize a button group's options into [(value, label), ...].

    Number mode (driven by `values`): each value becomes (value,
    fmt.format(value) + unit). Enum mode (driven by `items`, used when
    `values` is empty/None): each item is either an identifier string ->
    (id, id), or an [identifier, label] pair -> (identifier, label).
    Declared in JSON, never introspected. Pure stdlib."""
    if values:
        return [(v, fmt.format(v) + unit) for v in values]
    out = []
    for item in (items or []):
        if isinstance(item, str):
            out.append((item, item))
        else:
            ident = item[0]
            label = item[1] if len(item) > 1 else item[0]
            out.append((ident, label))
    return out


def dropdown_item_rects(rect_x, rect_y, rect_w, item_h, n):
    """Geometry for an open dropdown list: n cells stacked DOWNWARD from a
    field's bottom edge (`rect_y`). Returns [(x, y, w, h)] in display order
    (item 0 directly below the field). Shared by render (draw) and events
    (hit-test) so the two never disagree. Pure."""
    return [(rect_x, rect_y - (i + 1) * item_h, rect_w, item_h)
            for i in range(n)]


def dropdown_index_at(my, rect_x, rect_y, rect_w, item_h, n):
    """Which open-dropdown item a pixel y falls in; -1 when outside the
    list. (x is not tested — the list spans the field width.) Pure."""
    for i, (_x, y, _w, h) in enumerate(
            dropdown_item_rects(rect_x, rect_y, rect_w, item_h, n)):
        if y <= my <= y + h:
            return i
    return -1


class TextEditState:
    """In-overlay text-field edit buffer with caret + selection. Pure (no
    bpy / no rendering) so the modal stays a thin key->method mapping and the
    editing logic is fully pytest-covered.

    `caret` is the insertion index; `anchor` marks the other end of the
    selection (anchor == caret means no selection). Movement methods take
    `extend` (Shift) to grow the selection instead of collapsing it."""

    def __init__(self, text=""):
        self.text = str(text)
        self.caret = len(self.text)
        self.anchor = self.caret

    @property
    def has_sel(self):
        return self.caret != self.anchor

    def sel_range(self):
        """Normalized (start, end) of the current selection."""
        return (self.anchor, self.caret) if self.anchor <= self.caret \
            else (self.caret, self.anchor)

    def _delete_sel(self):
        a, b = self.sel_range()
        self.text = self.text[:a] + self.text[b:]
        self.caret = self.anchor = a

    def insert(self, s):
        s = str(s)
        if not s:
            return
        if self.has_sel:
            self._delete_sel()
        self.text = self.text[:self.caret] + s + self.text[self.caret:]
        self.caret += len(s)
        self.anchor = self.caret

    def backspace(self):
        if self.has_sel:
            self._delete_sel()
            return
        if self.caret > 0:
            self.text = self.text[:self.caret - 1] + self.text[self.caret:]
            self.caret -= 1
        self.anchor = self.caret

    def delete(self):
        if self.has_sel:
            self._delete_sel()
            return
        if self.caret < len(self.text):
            self.text = self.text[:self.caret] + self.text[self.caret + 1:]
        self.anchor = self.caret

    def left(self, extend=False):
        if self.caret > 0:
            self.caret -= 1
        if not extend:
            self.anchor = self.caret

    def right(self, extend=False):
        if self.caret < len(self.text):
            self.caret += 1
        if not extend:
            self.anchor = self.caret

    def home(self, extend=False):
        self.caret = 0
        if not extend:
            self.anchor = self.caret

    def end(self, extend=False):
        self.caret = len(self.text)
        if not extend:
            self.anchor = self.caret

    def select_all(self):
        self.anchor = 0
        self.caret = len(self.text)

    def selected_text(self):
        a, b = self.sel_range()
        return self.text[a:b]
