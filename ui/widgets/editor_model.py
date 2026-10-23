"""Pure (bpy-free) document model for the visual widget editor.

Holds a composed-widget definition in an *edit-normalized* form (merged
flipbox runs become explicit ROWs, top-level flipboxes carry span 12) with
snapshot undo/redo. Every mutation goes through `EditorDoc.commit`, so a
refused edit leaves the document and the history untouched. Paths:
`(row, None)` = top-level row, `(row, cell)` = cell inside ROW `row`.
"""
import copy

# Relative for Blender (addon loads as package InteractionOps); absolute
# fallback for pytest (see composed.build_controls for the same pattern).
try:
    from ...widgets import composed
except ImportError:
    from widgets import composed

GRID = composed.GRID
_MAX_NEW_SPAN = 4

_NEW = {
    "SECTION": {"label": "Section"},
    "SPACER": {},
    "ROW": {"cells": [{"type": "SPACER"}]},
    "BUTTON": {"label": "Button", "op": ""},
    "FLIPBOX": {"label": "Flip", "switch": ""},
    "SLIDER": {"prop": "", "value_type": "FLOAT", "min": 0.0, "max": 1.0},
    "PRESETS": {"target": "BEVEL", "values": [0, 0.5, 1.0]},
    "BUTTONS": {"prop": "", "value_type": "FLOAT", "values": [0, 1]},
    "DROPDOWN": {"label": "Dropdown", "prop": ""},
    "INPUT": {"label": "Input", "prop": "", "value_type": "STRING"},
    "SWATCH": {"color": [1, 1, 1, 1], "op": ""},
}


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------
def normalize_for_edit(wdef):
    """Deep copy where every merged FLIPBOX run is an explicit ROW and
    every remaining top-level FLIPBOX has span 12 (never re-merges)."""
    out = copy.deepcopy(wdef)
    rows = out.get("rows")
    if not isinstance(rows, list):
        return out
    result = []
    for item in composed.merge_flipbox_runs(rows):
        if isinstance(item, list):
            result.append({"type": "ROW", "cells": item})
            continue
        if (isinstance(item, dict) and item.get("type") == "FLIPBOX"
                and "span" not in item):
            item["span"] = GRID
        result.append(item)
    out["rows"] = result
    return out


def new_element(rtype):
    """Fresh placeholder element of `rtype` (usually incomplete until the
    user fills in its binding)."""
    rtype = str(rtype).upper()
    el = {"type": rtype}
    el.update(copy.deepcopy(_NEW[rtype]))
    return el


def is_complete(el):
    """True when the element validates to something usable. A ROW counts
    as complete with >= 1 cell (its cells are checked individually)."""
    if not isinstance(el, dict):
        return False
    if el.get("type") == "ROW":
        cells = el.get("cells")
        return isinstance(cells, list) and len(cells) >= 1
    return composed._clean_row(el)[0] is not None


def resolve_save_name(new, old, taken):
    """Sanitized `new` (or `old` when empty); unique among `taken` except
    `old` itself."""
    clean = composed.sanitize_name(new) or old
    if clean == old:
        return old
    return composed.unique_name(clean, set(taken) - {old})


def _default_spans(n):
    """Equal split of the grid, remainder to the leftmost cells."""
    base, rem = divmod(GRID, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def _insert_into(rows, tr, tc, el):
    """Insert `el` as cell `tc` of row `tr` (wrapping a non-ROW row).
    Returns the new cell index or None when refused. May leave `rows`
    modified on refusal — callers run inside `commit`, which restores."""
    if el.get("type") == "ROW" or not 0 <= tr < len(rows):
        return None
    row = rows[tr]
    if row.get("type") != "ROW":
        if tc not in (0, 1):
            return None
        # The wrapped row keeps its own show_if as a CELL condition (cells
        # support show_if): lifting it onto the new ROW would hide the
        # inserted element along with it.
        rows[tr] = row = {"type": "ROW", "cells": [row]}
    cells = row["cells"]
    if not 0 <= tc <= len(cells):
        return None
    el.pop("span", None)
    spans = [c.get("span") for c in cells]
    if all(s is None for s in spans):
        cells.insert(tc, el)
        return tc
    spans = composed.normalize_spans(spans)
    free = GRID - sum(spans)
    if free >= 1:
        new_span = min(free, _MAX_NEW_SPAN)
    else:
        n = tc - 1 if tc > 0 else 0
        s = spans[n]
        if s <= 1:
            return None
        spans[n] = (s + 1) // 2
        new_span = s // 2
    for c, sp in zip(cells, spans):
        c["span"] = sp
    el["span"] = new_span
    cells.insert(tc, el)
    return tc


def span_bounds(rows, path):
    """(start_col, span, max_span) of the element at `path` as set_span
    would see it (unspanned ROW cells resolved the same way), or None
    when `path` can't be resized (unknown path, ROW container). Drives
    the resize-drag preview so it snaps exactly where the commit lands."""
    el = _resolve(rows, path)
    if el is None:
        return None
    r, c = path
    if c is None:
        if el.get("type") == "ROW":
            return None
        sp = el.get("span")
        sp = sp if isinstance(sp, int) and not isinstance(sp, bool) \
            else GRID
        return (0, max(1, min(GRID, sp)), GRID)
    cells = rows[r]["cells"]
    if len(cells) > GRID:
        return None
    spans = [x.get("span") for x in cells]
    if any(s is None for s in spans):
        spans = (composed.normalize_spans(spans)
                 if any(s is not None for s in spans)
                 else _default_spans(len(cells)))
    others = sum(spans) - spans[c]
    return (sum(spans[:c]), spans[c], max(1, GRID - others))


def _resolve(rows, path):
    try:
        r, c = path
        if r < 0:
            return None
        row = rows[r]
        if c is None:
            return row
        if row.get("type") != "ROW" or c < 0:
            return None
        return row["cells"][c]
    except (IndexError, KeyError, TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# Document
# ----------------------------------------------------------------------
class EditorDoc:
    _WIDGET_KEYS = ("title", "width", "space", "switches", "name")

    def __init__(self, wdef, history_limit=200):
        self.wdef = normalize_for_edit(wdef)
        self.original = copy.deepcopy(wdef)
        self.selection = None
        self.dirty = False
        self._limit = history_limit
        self._undo = []
        self._redo = []
        # merge_key of the last commit (None after undo/redo or an
        # unkeyed commit) — consecutive same-key commits coalesce.
        self._last_merge = None

    # -- access --------------------------------------------------------
    def get(self, path):
        return _resolve(self.wdef.get("rows", []), path)

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    # -- history -------------------------------------------------------
    def _restore(self, snap):
        self.wdef.clear()
        self.wdef.update(copy.deepcopy(snap))

    def _keep_selection(self):
        if self.selection is not None and self.get(self.selection) is None:
            self.selection = None

    def commit(self, fn, merge_key=None):
        """Run `fn(wdef)` as one undoable edit. False (or an exception)
        restores the pre-edit state and records nothing.

        `merge_key` (hashable, e.g. ("field", path, key)) coalesces a run
        of commits — a dragged N-panel number fires one update per mouse
        step: when the previous commit had the same key and nothing else
        (undo, redo, another commit) happened in between, no new undo
        snapshot is pushed, so the pre-drag state stays the undo target."""
        snap = copy.deepcopy(self.wdef)
        try:
            ok = fn(self.wdef)
        except Exception:
            self._restore(snap)
            raise
        if not ok:
            self._restore(snap)
            return False
        merged = (merge_key is not None and merge_key == self._last_merge
                  and bool(self._undo))
        if not merged:
            self._undo.append(snap)
            if len(self._undo) > self._limit:
                del self._undo[0]
        self._redo.clear()
        self._last_merge = merge_key
        self.dirty = True
        return True

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self.wdef))
        self._restore(self._undo.pop())
        self._last_merge = None
        self.dirty = True
        self._keep_selection()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self.wdef))
        self._restore(self._redo.pop())
        self._last_merge = None
        self.dirty = True
        self._keep_selection()
        return True

    # -- structural edits ---------------------------------------------
    def insert(self, target, element):
        result = []

        def fn(w):
            rows = w.setdefault("rows", [])
            el = copy.deepcopy(element)
            tr, tc = target
            if tc is None:
                if not 0 <= tr <= len(rows):
                    return False
                if el.get("type") == "FLIPBOX" and "span" not in el:
                    el["span"] = GRID
                rows.insert(tr, el)
                result.append((tr, None))
                return True
            idx = _insert_into(rows, tr, tc, el)
            if idx is None:
                return False
            result.append((tr, idx))
            return True

        if not self.commit(fn):
            return None
        self.selection = result[0]
        return self.selection

    def move(self, src, target):
        result = []

        def fn(w):
            rows = w.get("rows", [])
            sr, sc = src
            tr, tc = target
            if _resolve(rows, src) is None:
                return False
            srow = rows[sr]
            if sc is None:
                if srow.get("type") == "ROW" and tc is not None:
                    return False
                if tc is None:
                    if not 0 <= tr <= len(rows):
                        return False
                    adj = tr - 1 if tr > sr else tr
                    rows.insert(adj, rows.pop(sr))
                    result.append((adj, None))
                    return True
                if tr == sr or not 0 <= tr < len(rows):
                    return False
                adj = tr - 1 if tr > sr else tr
                idx = _insert_into(rows, adj, tc, rows.pop(sr))
                if idx is None:
                    return False
                result.append((adj, idx))
                return True
            # source is a cell
            cells = srow["cells"]
            if tc is not None and tr == sr:
                # reorder inside the row, spans travel with the cells
                if not 0 <= tc <= len(cells):
                    return False
                adj = tc - 1 if tc > sc else tc
                cells.insert(adj, cells.pop(sc))
                result.append((sr, adj))
                return True
            nrows = len(rows)
            cell = cells.pop(sc)
            removed = not cells
            if removed:
                rows.pop(sr)
            cell.pop("span", None)
            if tc is None:
                if not 0 <= tr <= nrows:
                    return False
                if removed and tr > sr:
                    tr -= 1
                if cell.get("type") == "FLIPBOX":
                    cell["span"] = GRID
                rows.insert(tr, cell)
                result.append((tr, None))
                return True
            if removed and tr == sr:
                return False
            if removed and tr > sr:
                tr -= 1
            idx = _insert_into(rows, tr, tc, cell)
            if idx is None:
                return False
            result.append((tr, idx))
            return True

        if not self.commit(fn):
            return None
        self.selection = result[0]
        return self.selection

    def delete(self, path):
        def fn(w):
            rows = w.get("rows", [])
            if _resolve(rows, path) is None:
                return False
            r, c = path
            if c is None:
                del rows[r]
            else:
                del rows[r]["cells"][c]
                if not rows[r]["cells"]:
                    del rows[r]
            return True

        if not self.commit(fn):
            return False
        self.selection = None
        return True

    # -- field edits ---------------------------------------------------
    # A no-op edit never lands in the undo history. set_span reports a
    # valid-but-clamped-to-current request as True (nothing to refuse);
    # set_field / set_widget_field report an unchanged value as False.
    def set_span(self, path, span, merge_key=None):
        noop = []

        def fn(w):
            rows = w.get("rows", [])
            el = _resolve(rows, path)
            if (el is None or isinstance(span, bool)
                    or not isinstance(span, int)):
                return False
            r, c = path
            if c is None:
                if el.get("type") == "ROW":
                    return False
                new = max(1, min(GRID, span))
                if el.get("span") == new:
                    noop.append(1)
                    return False
                el["span"] = new
                return True
            cells = rows[r]["cells"]
            if len(cells) > GRID:
                return False
            spans = [x.get("span") for x in cells]
            changed = False
            if any(s is None for s in spans):
                spans = (composed.normalize_spans(spans)
                         if any(s is not None for s in spans)
                         else _default_spans(len(cells)))
                changed = True
            others = sum(spans) - spans[c]
            new = max(1, min(span, GRID - others))
            if spans[c] != new:
                spans[c] = new
                changed = True
            if not changed:
                noop.append(1)
                return False
            for x, sp in zip(cells, spans):
                x["span"] = sp
            return True

        return self.commit(fn, merge_key) or bool(noop)

    def set_field(self, path, key, value, merge_key=None):
        def fn(w):
            el = _resolve(w.get("rows", []), path)
            if el is None or key in ("type", "cells"):
                return False
            if value is None:
                if key not in el:
                    return False
                del el[key]
                return True
            if key in el and el[key] == value:
                return False
            el[key] = copy.deepcopy(value)
            return True

        return self.commit(fn, merge_key)

    def set_widget_field(self, key, value, merge_key=None):
        def fn(w):
            if key not in self._WIDGET_KEYS:
                return False
            if value is None:
                if key == "name" or key not in w:
                    return False
                del w[key]
                return True
            if key in w and w[key] == value:
                return False
            w[key] = copy.deepcopy(value)
            return True

        return self.commit(fn, merge_key)

    def replace_all(self, wdef):
        new = normalize_for_edit(wdef)

        def fn(w):
            w.clear()
            w.update(new)
            return True

        if not self.commit(fn):
            return False
        self._keep_selection()
        return True

    # -- queries -------------------------------------------------------
    def incomplete(self):
        out = []
        for r, row in enumerate(self.wdef.get("rows", [])):
            if row.get("type") == "ROW":
                cells = row.get("cells") or []
                if not cells:
                    out.append((r, None))
                for c, cell in enumerate(cells):
                    if not is_complete(cell):
                        out.append((r, c))
            elif not is_complete(row):
                out.append((r, None))
        return out

    def preview_rows(self):
        """Validated rows, 1:1 with `wdef["rows"]`; incomplete elements
        become labelled SPACER placeholders (ROW cells likewise)."""
        out = []
        for row in self.wdef.get("rows", []):
            if row.get("type") == "ROW":
                out.append(self._preview_row(row))
            elif is_complete(row):
                out.append(composed._clean_row(row)[0])
            else:
                out.append(self._placeholder(row))
        return out

    @staticmethod
    def _label(el):
        return str(el.get("type", "")).title() if isinstance(el, dict) else ""

    def _placeholder(self, el):
        return {"type": "SPACER", "span": el.get("span"),
                "_placeholder": self._label(el)}

    def _preview_row(self, row):
        cells_in = row.get("cells") or []
        if not cells_in:
            return {"type": "SPACER", "span": None, "_placeholder": "Row"}
        tmp = {k: v for k, v in row.items() if k != "cells"}
        tmp["cells"] = []
        marks = {}
        for i, cell in enumerate(cells_in):
            if is_complete(cell):
                tmp["cells"].append(cell)
            else:
                marks[i] = self._label(cell)
                tmp["cells"].append({"type": "SPACER",
                                     "span": cell.get("span")})
        clean = composed._clean_row(tmp)[0]
        if clean is None or len(clean["cells"]) != len(cells_in):
            return {"type": "SPACER", "span": None, "_placeholder": "Row"}
        for i, label in marks.items():
            clean["cells"][i]["_placeholder"] = label
        return clean
