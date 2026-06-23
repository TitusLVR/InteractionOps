# Widget Conditional Rendering + Context Sensitivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a single JSON-composed GPU widget show/hide rows based on context (mode, active-object type, selection, RNA prop) and local "switch" toggles, so one widget can present different controls in different situations.

**Architecture:** Every top-level row gains an optional `show_if` predicate. A new pure evaluator (`ui/widgets/predicates.py`) filters the flat control list each frame against a small `EvalCtx` built from the live `context` + the widget's local `switches` dict. A new `switch` FlipBox binding reads/writes those switches and persists them in `widgets_state`. Because `compute_layout`, `draw_widget`, and the interact modal all funnel through `Widget.rows(context)` / `Widget.control_at(context, …)`, the existing "rects are the single source of truth" invariant is preserved automatically.

**Tech Stack:** Python, Blender `bpy`/`bmesh` (deferred imports), pytest (the pure modules `widgets/composed.py`, `ui/widgets/controls.py`, `ui/widgets/panel.py`, and the new `ui/widgets/predicates.py` stay importable WITHOUT bpy).

## Global Constraints

- `widgets/composed.py` and `ui/widgets/predicates.py` MUST stay importable without `bpy`/`bmesh` — any Blender import is deferred inside a function body. Tests load these files standalone via `importlib` (see existing `tests/ui/widgets/test_composed.py`).
- Schema version stays `SCHEMA_VERSION = 1`; `show_if`/`switch`/`switches` are additive and backward compatible (absent → today's behavior).
- `show_if` is v1-scoped: keys are ANDed; vocab is exactly `mode`, `object_type`, `selection`, `prop`, `switch`, `equals`. No OR/NOT/nesting, no exact counts, no per-cell visibility.
- An invalid/unusable `show_if` clause is DROPPED with a reported error and the row stays **always-visible** (rows never silently vanish from a typo).
- A FlipBox needs EXACTLY ONE of `target` / `prop` / `switch`.
- Run `python -m pytest tests -q` (must stay green) after every task that touches a pure module.
- Commit messages end with the repo's `Co-Authored-By:` trailer.

---

### Task 1: Pure predicate evaluator + EvalCtx (`ui/widgets/predicates.py`)

**Files:**
- Create: `ui/widgets/predicates.py`
- Test: `tests/ui/widgets/test_predicates.py`

**Interfaces:**
- Produces:
  - `as_set(value) -> set[str]` — wrap a str or list-of-str into an upper-cased set.
  - `class EvalCtx` with attrs `mode: str`, `object_type: str | None` and methods `switch(name) -> bool`, `prop(path) -> (value, found: bool)`, `has_selection(kind) -> bool`. Constructor: `EvalCtx(mode, object_type, switches, prop_fn, selection_fn)` where `prop_fn(path) -> (value, found)` and `selection_fn(kind) -> bool`.
  - `eval_show_if(pred, ctx) -> bool` — `pred` is a validated dict or `None` (None → True).
  - `filter_controls(controls, ctx) -> list` — `[c for c in controls if eval_show_if(getattr(c, "_show_if", None), ctx)]`.
  - `build_eval_ctx(context, switches) -> EvalCtx` — bpy-side (deferred imports); built in Task 7's usage but defined here.

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/widgets/test_predicates.py
"""Pure tests for ui/widgets/predicates.py — the show_if evaluator.
Loaded standalone (bpy-free): build_eval_ctx defers its bpy imports."""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load_predicates():
    path = os.path.join(_ROOT, "ui", "widgets", "predicates.py")
    spec = importlib.util.spec_from_file_location("iops_test_predicates", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pred = _load_predicates()


def _ctx(mode="OBJECT", object_type=None, switches=None,
         props=None, selections=None):
    props = props or {}
    selections = selections or {}
    return pred.EvalCtx(
        mode, object_type, switches or {},
        prop_fn=lambda p: (props[p], True) if p in props else (None, False),
        selection_fn=lambda k: bool(selections.get(k, False)),
    )


def test_none_predicate_always_true():
    assert pred.eval_show_if(None, _ctx()) is True
    assert pred.eval_show_if({}, _ctx()) is True


def test_as_set_str_and_list():
    assert pred.as_set("mesh") == {"MESH"}
    assert pred.as_set(["mesh", "Curve"]) == {"MESH", "CURVE"}


def test_mode_match_and_miss():
    assert pred.eval_show_if({"mode": "EDIT_MESH"},
                             _ctx(mode="EDIT_MESH")) is True
    assert pred.eval_show_if({"mode": ["OBJECT", "POSE"]},
                             _ctx(mode="EDIT_MESH")) is False


def test_object_type_none_object_fails():
    assert pred.eval_show_if({"object_type": "MESH"},
                             _ctx(object_type=None)) is False
    assert pred.eval_show_if({"object_type": ["MESH", "CURVE"]},
                             _ctx(object_type="CURVE")) is True


def test_selection_kind():
    assert pred.eval_show_if({"selection": "edges"},
                             _ctx(selections={"edges": True})) is True
    assert pred.eval_show_if({"selection": "edges"},
                             _ctx(selections={"edges": False})) is False


def test_prop_truthy_and_equals_and_missing():
    assert pred.eval_show_if({"prop": "scene.x"},
                             _ctx(props={"scene.x": True})) is True
    assert pred.eval_show_if({"prop": "scene.x"},
                             _ctx(props={"scene.x": False})) is False
    assert pred.eval_show_if({"prop": "scene.n", "equals": 3},
                             _ctx(props={"scene.n": 3})) is True
    assert pred.eval_show_if({"prop": "scene.n", "equals": 3},
                             _ctx(props={"scene.n": 4})) is False
    # Missing path -> False (not an error)
    assert pred.eval_show_if({"prop": "scene.gone"}, _ctx()) is False


def test_switch_truthy_and_equals():
    assert pred.eval_show_if({"switch": "adv"},
                             _ctx(switches={"adv": True})) is True
    assert pred.eval_show_if({"switch": "adv"},
                             _ctx(switches={"adv": False})) is False
    assert pred.eval_show_if({"switch": "adv", "equals": False},
                             _ctx(switches={"adv": False})) is True


def test_keys_are_anded():
    p = {"mode": "EDIT_MESH", "switch": "adv"}
    assert pred.eval_show_if(p, _ctx(mode="EDIT_MESH",
                                     switches={"adv": True})) is True
    assert pred.eval_show_if(p, _ctx(mode="EDIT_MESH",
                                     switches={"adv": False})) is False


def test_filter_controls():
    class C:
        def __init__(self, si):
            self._show_if = si
    a, b, c = C(None), C({"switch": "adv"}), C({"mode": "OBJECT"})
    out = pred.filter_controls([a, b, c],
                               _ctx(mode="OBJECT", switches={"adv": False}))
    assert out == [a, c]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_predicates.py -q`
Expected: FAIL (module `predicates` not found / no such file).

- [ ] **Step 3: Write the implementation**

```python
# ui/widgets/predicates.py
"""show_if predicate evaluation for widget rows.

PURE EVALUATION (eval_show_if / filter_controls / as_set / EvalCtx) is
bpy-free and pytest-covered. `build_eval_ctx()` is the only bpy-aware
entry point and defers every Blender import to call time, so this module
stays importable under plain pytest.

A `show_if` predicate is a dict; all present keys are ANDed. Vocabulary:
    mode         str | list   context.mode in set
    object_type  str | list   active_object.type in set (None obj -> False)
    selection    str          "verts"|"edges"|"faces"|"objects" has-any
    prop         str          RNA dotted path; truthy, or == equals
    switch       str          local switch; truthy, or == equals
    equals       any          equality target for prop/switch in this clause
"""
from __future__ import annotations

SELECTION_KINDS = ("verts", "edges", "faces", "objects")


def as_set(value):
    """A str or list-of-str -> an upper-cased set of strings."""
    if isinstance(value, (list, tuple, set)):
        return {str(v).upper() for v in value}
    return {str(value).upper()}


class EvalCtx:
    """Accessor the evaluator reads. Bpy-side built by build_eval_ctx();
    tests construct it directly with fake prop_fn/selection_fn."""

    def __init__(self, mode, object_type, switches, prop_fn, selection_fn):
        self.mode = mode
        self.object_type = object_type
        self._switches = switches or {}
        self._prop_fn = prop_fn
        self._selection_fn = selection_fn

    def switch(self, name):
        return bool(self._switches.get(name, False))

    def prop(self, path):
        return self._prop_fn(path)

    def has_selection(self, kind):
        return bool(self._selection_fn(kind))


def eval_show_if(pred, ctx):
    """Evaluate one validated show_if dict (or None) against a ctx."""
    if not pred:
        return True
    if "mode" in pred and ctx.mode not in as_set(pred["mode"]):
        return False
    if "object_type" in pred:
        ot = ctx.object_type
        if ot is None or ot not in as_set(pred["object_type"]):
            return False
    if "selection" in pred and not ctx.has_selection(pred["selection"]):
        return False
    if "prop" in pred:
        value, found = ctx.prop(pred["prop"])
        if not found:
            return False
        if "equals" in pred:
            if value != pred["equals"]:
                return False
        elif not value:
            return False
    if "switch" in pred:
        val = ctx.switch(pred["switch"])
        if "equals" in pred:
            if val != pred["equals"]:
                return False
        elif not val:
            return False
    return True


def filter_controls(controls, ctx):
    """Top-level controls whose predicate passes, preserving order."""
    return [c for c in controls
            if eval_show_if(getattr(c, "_show_if", None), ctx)]


def build_eval_ctx(context, switches):
    """Build an EvalCtx from the live Blender context + a switches dict.
    bpy-aware; selection uses the cheap Mesh.total_*_sel counters (no
    bmesh scan) and object selection uses context.selected_objects."""
    from .composed_rna import resolve_prop  # deferred; see Task 7 note

    mode = getattr(context, "mode", "")
    obj = getattr(context, "active_object", None)
    object_type = getattr(obj, "type", None) if obj is not None else None

    def prop_fn(path):
        return resolve_prop(context, path)

    def selection_fn(kind):
        if kind == "objects":
            return bool(getattr(context, "selected_objects", None))
        ob = getattr(context, "active_object", None)
        data = getattr(ob, "data", None)
        attr = {"verts": "total_vert_sel", "edges": "total_edge_sel",
                "faces": "total_face_sel"}.get(kind)
        if data is None or attr is None:
            return False
        return bool(getattr(data, attr, 0))

    return EvalCtx(mode, object_type, switches, prop_fn, selection_fn)
```

> NOTE for Step 3: `build_eval_ctx` references `resolve_prop` from a helper. To avoid a circular import and keep the pure surface clean, define `resolve_prop(context, path) -> (value, found)` in `widgets/composed.py` (it already has `resolve_rna_owner`) and import it lazily. Adjust the deferred import line to `from ...widgets.composed import resolve_prop` (predicates.py is at `ui/widgets/`, composed.py at `widgets/`). The fake `composed_rna` name above is a placeholder — use the real `...widgets.composed` path. `build_eval_ctx` is exercised only inside Blender (Task 9 verify), so it is not unit-tested here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_predicates.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/predicates.py tests/ui/widgets/test_predicates.py
git commit -m "$(cat <<'EOF'
feat(widgets): pure show_if predicate evaluator + EvalCtx

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `show_if` validation + `resolve_prop` (`widgets/composed.py`)

**Files:**
- Modify: `widgets/composed.py` (refactor `_clean_row` into `_clean_row_body` + wrapper; add `_clean_show_if`, `resolve_prop`)
- Test: `tests/ui/widgets/test_composed.py` (append)

**Interfaces:**
- Consumes: `resolve_rna_owner` (existing, `composed.py:91`).
- Produces:
  - `_clean_show_if(raw) -> (clean_dict | None, error | None)`.
  - `resolve_prop(context, path) -> (value, found)`.
  - `_clean_row(row)` now also parses an optional `show_if` on the row, attaching `out["show_if"]` when valid; on invalid show_if it KEEPS the row and reports `"show_if dropped: …"`. ROW *cells* never carry `show_if` (validated via `_clean_row_body`).

- [ ] **Step 1: Write the failing tests** (append to `tests/ui/widgets/test_composed.py`)

```python
# ---- show_if validation ------------------------------------------------
def test_show_if_valid_attached():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SECTION", "label": "Adv",
             "show_if": {"switch": "adv"}},
            {"type": "BUTTON", "label": "Go", "op": "iops.executor",
             "show_if": {"mode": "EDIT_MESH", "object_type": ["MESH"]}},
        ],
    })
    assert errors == []
    assert wdef["rows"][0]["show_if"] == {"switch": "adv"}
    assert wdef["rows"][1]["show_if"]["mode"] == ["EDIT_MESH"]
    assert wdef["rows"][1]["show_if"]["object_type"] == ["MESH"]


def test_show_if_invalid_keeps_row_reports():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SECTION", "label": "X", "show_if": {"selection": "x"}},
        ],
    })
    # Row survives (no show_if attached), error reported.
    assert len(wdef["rows"]) == 1
    assert "show_if" not in wdef["rows"][0]
    assert any("show_if" in e for e in errors)


def test_show_if_normalizes_mode_and_selection():
    clean, err = composed._clean_show_if(
        {"mode": "edit_mesh", "selection": "EDGES"})
    assert err is None
    assert clean == {"mode": ["EDIT_MESH"], "selection": "edges"}


def test_show_if_equals_preserved():
    clean, err = composed._clean_show_if({"switch": "n", "equals": False})
    assert err is None
    assert clean == {"switch": "n", "equals": False}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: FAIL (`_clean_show_if` not defined; `show_if` not attached).

- [ ] **Step 3: Write the implementation**

Add near `resolve_rna_owner` in `widgets/composed.py`:

```python
from .predicates_meta import SELECTION_KINDS  # placeholder — see NOTE
```

> NOTE: do NOT add that import (predicates.py imports composed, not vice versa). Instead hard-code the tuple to avoid any import cycle:

```python
SHOW_IF_SELECTION = ("verts", "edges", "faces", "objects")


def resolve_prop(context, path):
    """Resolve a dotted RNA path against context -> (value, found).
    found=False when any segment is missing. Pure (getattr only)."""
    owner, attr = resolve_rna_owner(context, path)
    if owner is None or not hasattr(owner, attr):
        return (None, False)
    return (getattr(owner, attr), True)


def _as_str_list(value):
    """A str or list -> list of non-empty upper-cased strings."""
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip().upper() for v in value]
    else:
        items = [str(value).strip().upper()]
    return [s for s in items if s]


def _clean_show_if(raw):
    """Validate/normalize a show_if clause. Returns (clean|None, err)."""
    if not isinstance(raw, dict):
        return None, "show_if is not an object"
    out = {}
    if "mode" in raw:
        modes = _as_str_list(raw["mode"])
        if not modes:
            return None, "show_if mode is empty"
        out["mode"] = modes
    if "object_type" in raw:
        types = _as_str_list(raw["object_type"])
        if not types:
            return None, "show_if object_type is empty"
        out["object_type"] = types
    if "selection" in raw:
        sel = str(raw["selection"]).strip().lower()
        if sel not in SHOW_IF_SELECTION:
            return None, f"show_if selection '{sel}' invalid"
        out["selection"] = sel
    if "prop" in raw:
        p = str(raw["prop"]).strip()
        if not p:
            return None, "show_if prop is empty"
        out["prop"] = p
    if "switch" in raw:
        s = str(raw["switch"]).strip()
        if not s:
            return None, "show_if switch is empty"
        out["switch"] = s
    if "equals" in raw:
        out["equals"] = raw["equals"]
    if not any(k in out for k in
               ("mode", "object_type", "selection", "prop", "switch")):
        return None, "show_if has no recognized keys"
    return out, None
```

Now refactor `_clean_row`: rename the existing function body to `_clean_row_body` (identical logic, no signature change), and add a thin wrapper:

```python
def _clean_row(row):
    """Validate one row (delegates to _clean_row_body), then parse an
    optional show_if. Invalid show_if keeps the row always-visible and
    reports — never drops the row for a bad predicate."""
    out, err = _clean_row_body(row)
    if out is None:
        return None, err
    if isinstance(row, dict) and "show_if" in row:
        si, si_err = _clean_show_if(row["show_if"])
        if si_err:
            return out, f"show_if dropped: {si_err}"
        out["show_if"] = si
    return out, err
```

In `_clean_row_body`, change the ROW-cell recursion from `_clean_row(cell)` to `_clean_row_body(cell)` so cells never receive `show_if` (v1 scope).

> The `validate_def` loop already appends `out` when not None even if `err` is set — so an invalid-show_if row is appended AND its error reported. No change needed there.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: PASS. Also run full `python -m pytest tests -q` — green.

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "$(cat <<'EOF'
feat(widgets): validate optional show_if clause on rows

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `switch` FlipBox binding + `switches` map + `collect_switches`

**Files:**
- Modify: `widgets/composed.py` (FLIPBOX branch in `_clean_row_body`; `switches` in `validate_def`; new `collect_switches`)
- Test: `tests/ui/widgets/test_composed.py` (append)

**Interfaces:**
- Produces:
  - FLIPBOX accepts `switch`; exactly one of `target`/`prop`/`switch`. A switch flipbox normalizes to `{"type":"FLIPBOX","switch":<name>,"label":<label>}`.
  - `validate_def` output gains `clean["switches"] = {name: bool}` from the top-level `switches` map (defaults coerced to bool).
  - `collect_switches(wdef) -> {name: bool}` — every switch name referenced by a `switch` flipbox or a `show_if` `switch`, defaulting `False`, overridden by the `switches` map.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ---- switch flipbox + switches map -------------------------------------
def test_flipbox_switch_binding():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [{"type": "FLIPBOX", "switch": "adv", "label": "Advanced"}],
    })
    assert errors == []
    row = wdef["rows"][0]
    assert row["switch"] == "adv" and row["label"] == "Advanced"
    assert "target" not in row and "prop" not in row


def test_flipbox_requires_exactly_one_binding():
    # zero bindings
    wdef, _ = composed.validate_def(
        {"name": "w", "rows": [{"type": "FLIPBOX", "label": "x"}]})
    assert wdef["rows"] == []
    # two bindings
    wdef, _ = composed.validate_def({
        "name": "w",
        "rows": [{"type": "FLIPBOX", "switch": "a", "target": "SHARP"}]})
    assert wdef["rows"] == []


def test_switches_map_defaults():
    wdef, errors = composed.validate_def({
        "name": "w",
        "switches": {"adv": True, "bad": "yes"},
        "rows": [],
    })
    assert wdef["switches"] == {"adv": True, "bad": True}


def test_collect_switches_from_refs_and_map():
    wdef, _ = composed.validate_def({
        "name": "w",
        "switches": {"adv": True},
        "rows": [
            {"type": "FLIPBOX", "switch": "adv", "label": "Adv"},
            {"type": "SECTION", "label": "extra",
             "show_if": {"switch": "more"}},
        ],
    })
    sw = composed.collect_switches(wdef)
    assert sw == {"adv": True, "more": False}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: FAIL (switch not accepted; `switches` absent; `collect_switches` undefined).

- [ ] **Step 3: Write the implementation**

Replace the FLIPBOX branch in `_clean_row_body`:

```python
    if rtype == "FLIPBOX":
        prop = str(row.get("prop", "")).strip()
        target = str(row.get("target", "")).strip().upper()
        switch = str(row.get("switch", "")).strip()
        bound = [b for b in (prop, target, switch) if b]
        if len(bound) != 1:
            return None, "flipbox needs exactly one of prop/target/switch"
        if switch:
            out["switch"] = switch
            out["label"] = str(row.get("label", "")) or switch
        elif prop:
            out["prop"] = prop
            out["label"] = str(row.get("label", "")) or prop.rsplit(".", 1)[-1]
        else:
            if target not in BOOL_TARGETS:
                return None, f"flipbox target '{target}' invalid"
            out["target"] = target
            out["label"] = str(row.get("label", "")) or target.title()
        return out, None
```

In `validate_def`, after building `clean` (before the rows loop), add the switches map:

```python
    clean["switches"] = {}
    raw_switches = data.get("switches", {})
    if isinstance(raw_switches, dict):
        for k, v in raw_switches.items():
            clean["switches"][str(k)] = bool(v)
```

Add `collect_switches`:

```python
def collect_switches(wdef):
    """Every switch name referenced by the def -> its default bool.
    Default False; overridden by the validated `switches` map. Recurses
    into ROW cells for switch flipboxes (show_if only on top-level rows)."""
    names = set()

    def scan(row):
        if not isinstance(row, dict):
            return
        if row.get("type") == "FLIPBOX" and row.get("switch"):
            names.add(row["switch"])
        if row.get("type") == "ROW":
            for cell in row.get("cells", []):
                scan(cell)
        si = row.get("show_if")
        if isinstance(si, dict) and si.get("switch"):
            names.add(si["switch"])

    for row in wdef.get("rows", []):
        scan(row)
    defaults = wdef.get("switches", {})
    return {name: bool(defaults.get(name, False)) for name in names}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: PASS. Then `python -m pytest tests -q` — green.

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "$(cat <<'EOF'
feat(widgets): switch flipbox binding + switches map + collect_switches

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Merge rule — only merge `show_if`-free flipboxes

**Files:**
- Modify: `widgets/composed.py` (`merge_flipbox_runs`)
- Test: `tests/ui/widgets/test_composed.py` (append)

**Interfaces:**
- Consumes: existing `merge_flipbox_runs(rows)` (`composed.py:277`).
- Produces: a flipbox carrying a `show_if` no longer joins a merge run — it stands alone so its predicate hides exactly it.

- [ ] **Step 1: Write the failing test** (append)

```python
# ---- merge interaction with show_if ------------------------------------
def test_merge_excludes_show_if_flipboxes():
    rows = [
        {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
        {"type": "FLIPBOX", "target": "SEAM", "label": "Seam",
         "show_if": {"switch": "adv"}},
        {"type": "FLIPBOX", "target": "FREESTYLE", "label": "FS"},
    ]
    merged = composed.merge_flipbox_runs(rows)
    # Sharp stands alone (run broken by the show_if box), the show_if box
    # stands alone, FS stands alone — no 2+ run forms.
    assert all(not isinstance(m, list) for m in merged)
    assert len(merged) == 3


def test_merge_still_groups_plain_flipboxes():
    rows = [
        {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
        {"type": "FLIPBOX", "target": "SEAM", "label": "Seam"},
    ]
    merged = composed.merge_flipbox_runs(rows)
    assert len(merged) == 1 and isinstance(merged[0], list)
    assert len(merged[0]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: FAIL (`test_merge_excludes_show_if_flipboxes` — the show_if box currently merges).

- [ ] **Step 3: Write the implementation**

Change the run-condition in `merge_flipbox_runs`:

```python
    for row in rows:
        if row.get("type") == "FLIPBOX" and "show_if" not in row:
            run.append(row)
            continue
```

(Everything else in the function is unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: PASS. Then `python -m pytest tests -q` — green.

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "$(cat <<'EOF'
feat(widgets): keep show_if flipboxes out of auto-merge runs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `_show_if` on Control base + switch adapter + build attaches predicates

**Files:**
- Modify: `ui/widgets/controls.py` (add `self._show_if = None` to `Control.__init__`)
- Modify: `widgets/composed.py` (`switch_adapter`; `build_controls` gains `switch_store`/`on_switch` params and attaches `_show_if`)
- Test: `tests/ui/widgets/test_controls.py` (append) and `tests/ui/widgets/test_composed.py` (append)

**Interfaces:**
- Consumes: `rna_bool_adapter`, `ADAPTERS`, `merge_flipbox_runs` (existing).
- Produces:
  - `Control._show_if` attribute (default `None`).
  - `switch_adapter(store, name, on_change=None) -> {"get", "set"}`. `get(context) -> (bool, False)`; `set(context, value)` writes `store[name]=bool(value)` and calls `on_change(name, value)` if given.
  - `build_controls(row_defs, switch_store=None, on_switch=None)` — switch flipboxes bind via `switch_adapter`; every produced top-level control gets `_show_if` from its row def (`Row` for a merged flipbox run gets `None`; an explicit `ROW` gets the row's `show_if`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_controls.py`:

```python
def test_control_has_show_if_default(controls):
    # `controls` fixture/module import per the file's existing pattern;
    # use a Section as the simplest Control.
    s = controls.Section("x")
    assert s._show_if is None
```

> If `test_controls.py` does not already expose a `controls` handle, load it with the same standalone-importlib pattern used in `test_composed.py` (path `ui/widgets/controls.py`). Match whatever the file already does.

Append to `tests/ui/widgets/test_composed.py`:

```python
# ---- switch adapter + build_controls predicate attach ------------------
def test_switch_adapter_get_set_and_on_change():
    store = {}
    seen = []
    ad = composed.switch_adapter(store, "adv",
                                 on_change=lambda n, v: seen.append((n, v)))
    assert ad["get"](None) == (False, False)
    ad["set"](None, True)
    assert store["adv"] is True
    assert ad["get"](None) == (True, False)
    assert seen == [("adv", True)]


def test_build_controls_attaches_show_if():
    rows = [
        {"type": "SECTION", "label": "A", "show_if": {"switch": "adv"}},
        {"type": "BUTTON", "label": "Go", "op": "iops.executor"},
    ]
    store = {}
    ctrls = composed.build_controls(rows, switch_store=store)
    assert ctrls[0]._show_if == {"switch": "adv"}
    assert ctrls[1]._show_if is None


def test_build_controls_switch_flipbox_uses_store():
    rows = [{"type": "FLIPBOX", "switch": "adv", "label": "Adv"}]
    store = {}
    ctrls = composed.build_controls(rows, switch_store=store)
    fb = ctrls[0]
    # FlipBox get/set wired to the store.
    assert fb.get(None) == (False, False)
    fb.set(None, True)
    assert store["adv"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_controls.py tests/ui/widgets/test_composed.py -q`
Expected: FAIL (`_show_if` missing; `switch_adapter` undefined; `build_controls` ignores switch/`show_if`).

- [ ] **Step 3: Write the implementation**

In `ui/widgets/controls.py`, `Control.__init__`, add after `self._enabled_dirty = True`:

```python
        # Optional show_if predicate (validated dict) attached by the
        # composed builder; None = always visible. Read by the framework's
        # row filtering (ui/widgets/predicates.filter_controls).
        self._show_if = None
```

In `widgets/composed.py`, add the adapter:

```python
def switch_adapter(store, name, on_change=None):
    """get/set bundle for a local widget switch held in `store` (a dict
    on the live widget). set() mutates the store and fires on_change so
    the widget can persist + redraw. Scalar -> is_mixed always False."""
    def get(context):
        return (bool(store.get(name, False)), False)

    def set(context, value):
        store[name] = bool(value)
        if on_change is not None:
            on_change(name, bool(value))

    return {"get": get, "set": set}
```

Update `build_controls` signature and body:

```python
def build_controls(row_defs, switch_store=None, on_switch=None):
    """Materialize a validated `rows` list into framework controls.
    `switch_store` (a dict) backs switch flipboxes; `on_switch(name, value)`
    fires on a switch write (persist + redraw). Each produced top-level
    control carries its `_show_if` predicate (None = always visible)."""
    from ..ui.widgets import (Section, Slider, PresetRow, FlipBox,
                              ActionButton, Row, Swatch)
    from .adapters import ADAPTERS, has_selected_edges

    if switch_store is None:
        switch_store = {}
    edge_bound = _binds_edges(row_defs)
    gate = has_selected_edges if edge_bound else None

    def one(row):
        rtype = row["type"]
        if rtype == "SECTION":
            return Section(row.get("label", ""))
        if rtype == "SLIDER":
            a = ADAPTERS[row["target"]]
            return Slider(get=a["get"], set=a["set"],
                          snap=row.get("snap", 0.125),
                          snapshot=a.get("snapshot"),
                          restore=a.get("restore"))
        if rtype == "PRESETS":
            a = ADAPTERS[row["target"]]
            return PresetRow(row["values"], set=a["set"], enabled_get=gate)
        if rtype == "FLIPBOX":
            if row.get("switch"):
                ad = switch_adapter(switch_store, row["switch"], on_switch)
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            if row.get("prop"):
                ad = rna_bool_adapter(row["prop"])
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            a = ADAPTERS[row["target"]]
            return FlipBox(row["label"], get=a["get"], set=a["set"])
        if rtype == "SWATCH":
            ad = rna_color_adapter(row["prop"])
            return Swatch(get=ad["get"], op=row["op"],
                          kwargs=row.get("op_kwargs") or {},
                          label=row.get("label", ""))
        if rtype == "BUTTON":
            return ActionButton(row["label"], op=row["op"],
                                kwargs=row.get("op_kwargs") or {},
                                role=row.get("role", "default"),
                                enabled_get=gate)
        return None

    controls = []
    for item in merge_flipbox_runs(row_defs):
        if isinstance(item, list):
            ctrl = Row([one(r) for r in item])
            ctrl._show_if = None          # merged plain flipboxes: no predicate
        elif isinstance(item, dict) and item.get("type") == "ROW":
            ctrl = Row([one(r) for r in item["cells"]])
            ctrl._show_if = item.get("show_if")
        else:
            ctrl = one(item)
            if ctrl is None:
                continue
            ctrl._show_if = item.get("show_if")
        controls.append(ctrl)
    return controls
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_controls.py tests/ui/widgets/test_composed.py -q`
Expected: PASS. Then `python -m pytest tests -q` — green.

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/controls.py widgets/composed.py \
        tests/ui/widgets/test_controls.py tests/ui/widgets/test_composed.py
git commit -m "$(cat <<'EOF'
feat(widgets): switch adapter + attach show_if predicates in build_controls

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Framework row filtering — `Widget.rows(context)` / `control_at(context, …)`

**Files:**
- Modify: `ui/widgets/__init__.py` (`Widget.rows`, `Widget.control_at`, default `switches`)
- Test: `tests/ui/widgets/test_widget_rows.py` (create)

**Interfaces:**
- Consumes: `ui/widgets/predicates.filter_controls` and `EvalCtx` (Task 1), `Control._show_if` (Task 5).
- Produces:
  - `Widget.rows(context=None)` — `context=None` returns all controls (back-compat); with a context, returns `filter_controls(self.controls, build_eval_ctx(context, self.switches))`.
  - `Widget.control_at(context, row, col)` — indexes the **filtered** visible list (signature changed from `control_at(row, col)`).
  - `Widget.switches` defaults to `{}` on the base class.

- [ ] **Step 1: Write the failing test** (create `tests/ui/widgets/test_widget_rows.py`)

```python
"""Filtering behavior of Widget.rows()/control_at() via a fake context.

ui/widgets/__init__.py imports bpy-guarded submodules but the Widget base
and predicates filtering are bpy-free. We monkeypatch build_eval_ctx so no
Blender is needed: the test supplies its own EvalCtx."""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load(name, relpath):
    path = os.path.join(_ROOT, *relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


predicates = _load("iops_test_predicates2",
                   ("ui", "widgets", "predicates.py"))
controls = _load("iops_test_controls2", ("ui", "widgets", "controls.py"))


def _ctx(mode="OBJECT", switches=None):
    return predicates.EvalCtx(mode, None, switches or {},
                              prop_fn=lambda p: (None, False),
                              selection_fn=lambda k: False)


class FakeWidget:
    """Minimal stand-in exercising the rows()/control_at() logic copied
    behaviorally — validated against the real methods in Blender (Task 9).
    Here we test the pure filter contract the methods rely on."""
    def __init__(self, ctrls, ctx):
        self.controls = ctrls
        self._ctx = ctx

    def rows(self, context=None):
        if context is None:
            return self.controls
        return predicates.filter_controls(self.controls, self._ctx)


def test_rows_filters_by_switch():
    a = controls.Section("always")
    b = controls.Section("adv"); b._show_if = {"switch": "adv"}
    w_on = FakeWidget([a, b], _ctx(switches={"adv": True}))
    w_off = FakeWidget([a, b], _ctx(switches={"adv": False}))
    assert w_on.rows(context=object()) == [a, b]
    assert w_off.rows(context=object()) == [a]
    # No context -> unfiltered
    assert w_off.rows() == [a, b]
```

> This test pins the **filtering contract** (`filter_controls` + `_show_if`) that `Widget.rows`/`control_at` are built on, without needing bpy. The bpy-wired `build_eval_ctx` path and `control_at` indexing are verified live in Task 9.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/ui/widgets/test_widget_rows.py -q`
Expected: FAIL initially only if `_show_if` assignment isn't present — but since Task 5 added it, this test should PASS once written. If it FAILS, it indicates `_show_if` default is missing. (This task's real deliverable is the `__init__.py` edit below; the test guards the contract.)

- [ ] **Step 3: Write the implementation** (`ui/widgets/__init__.py`)

Add `switches = {}` to the `Widget` class body (class attribute; instances get their own dict in `make_widget`/`__init__`):

```python
    name = ""
    title = ""
    space = "VIEW_3D"
    switches = {}      # name -> bool; composed widgets replace with own dict
```

Replace `rows()` and `control_at()`:

```python
    def rows(self, context=None):
        """Visible top-level controls. With a context, rows are filtered by
        each control's show_if predicate (one visual row each: Row = 1 row,
        N cols). context=None returns the unfiltered list (back-compat)."""
        if context is None:
            return self.controls
        from .predicates import build_eval_ctx, filter_controls
        ctx = build_eval_ctx(context, getattr(self, "switches", None) or {})
        return filter_controls(self.controls, ctx)

    def control_at(self, context, row, col):
        """Resolve a panel hit_test ("control", (row, col)) to a control,
        indexing the SAME filtered visible list the layout/draw used."""
        vis = self.rows(context)
        if not (0 <= row < len(vis)):
            return None
        ctrl = vis[row]
        if isinstance(ctrl, Row):
            if 0 <= col < len(ctrl.children):
                return ctrl.children[col]
            return None
        return ctrl
```

> `Widget.__init__` still sets `self.controls`/`self.panel`; composed widgets bypass `__init__` (via `__new__`) and set `self.switches` in `make_widget` (Task 7). The class-attr `switches = {}` keeps programmatic widgets safe.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/ui/widgets/test_widget_rows.py -q`
Expected: PASS. Then `python -m pytest tests -q` — green.

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/__init__.py tests/ui/widgets/test_widget_rows.py
git commit -m "$(cat <<'EOF'
feat(widgets): filter widget rows by show_if in rows()/control_at()

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Wire switches into `make_widget` + `register_composed` seeding

**Files:**
- Modify: `widgets/composed.py` (`make_widget`, `register_composed`)
- Verify: Blender (MCP / reload) — no pure unit test (bpy-side wiring).

**Interfaces:**
- Consumes: `collect_switches` (Task 3), `build_controls(switch_store, on_switch)` (Task 5), `state.store_switches`/`state.tag_redraw_all` (Task 8), `state.get_state` (existing).
- Produces: a live composed widget whose `inst.switches` is seeded from the def + persisted state; switch writes persist and redraw.

- [ ] **Step 1: Update `make_widget`**

```python
def make_widget(wdef):
    """Create a live Widget instance from a validated definition."""
    from ..ui.widgets import Widget

    class ComposedWidget(Widget):
        pass

    inst = ComposedWidget.__new__(ComposedWidget)
    inst.name = wdef["name"]
    inst.title = wdef["title"]
    inst.space = wdef.get("space", "VIEW_3D")
    inst.composed_def = wdef
    inst.switches = collect_switches(wdef)

    def on_switch(_name, _value):
        # Persist the new switch state and repaint (visible rows change).
        from ..ui.widgets import state
        state.store_switches(inst.name, inst.switches)
        state.tag_redraw_all()

    edge_bound = _binds_edges(wdef["rows"])
    inst.poll = (lambda context: context.mode == "EDIT_MESH") if edge_bound \
        else (lambda context: True)
    inst.controls = build_controls(wdef["rows"], switch_store=inst.switches,
                                   on_switch=on_switch)
    from ..ui.widgets.panel import WidgetPanel
    inst.panel = WidgetPanel(title=inst.title or inst.name)
    return inst
```

- [ ] **Step 2: Update `register_composed`** to re-seed switches from persisted state (alongside x/y):

```python
def register_composed(wdef):
    from ..ui import widgets as framework
    from ..ui.widgets import state
    inst = framework.register_widget(make_widget(wdef))
    st = state.get_state(inst.name)
    inst.panel.x = float(st.get("x", inst.panel.x))
    inst.panel.y = float(st.get("y", inst.panel.y))
    saved = st.get("switches", {})
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in inst.switches:
                inst.switches[k] = bool(v)
    _live.add(wdef["name"])
    return inst, None
```

- [ ] **Step 3: Confirm pure tests still pass** (this task adds no new tests but must not break existing collection)

Run: `python -m pytest tests -q`
Expected: PASS (composed.py still imports without bpy; the new `state` references are inside function bodies / deferred).

- [ ] **Step 4: Commit**

```bash
git add widgets/composed.py
git commit -m "$(cat <<'EOF'
feat(widgets): seed + persist composed-widget switch state

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Persist switches in `widgets_state` (`ui/widgets/state.py`)

**Files:**
- Modify: `ui/widgets/state.py` (`get_state` default, `save_states`, `load_states`, new `store_switches`)
- Verify: Blender (MCP / reload) — no pure unit test (module imports bpy at top).

**Interfaces:**
- Produces: `store_switches(name, switches)` — persist a `{name: bool}` snapshot for a widget; per-widget state grows a `"switches"` key.

- [ ] **Step 1: Default in `get_state`** — add the key:

```python
    if st is None:
        st = {"visible": False, "x": 80.0, "y": 400.0,
              "anchor_area_ptr": 0, "switches": {}}
        _states[name] = st
```

- [ ] **Step 2: Add `store_switches`** (next to `store_position`):

```python
def store_switches(name, switches):
    """Persist a widget's local switch state (a {name: bool} dict)."""
    st = get_state(name)
    st["switches"] = {str(k): bool(v) for k, v in switches.items()}
    save_states()
```

- [ ] **Step 3: Serialize switches in `save_states`** — extend the per-widget dict:

```python
    data = {
        name: {"visible": bool(st.get("visible")),
               "x": float(st.get("x", 80.0)),
               "y": float(st.get("y", 400.0)),
               "switches": {str(k): bool(v)
                            for k, v in st.get("switches", {}).items()}}
        for name, st in _states.items()
    }
```

- [ ] **Step 4: Restore switches in `load_states`** — inside the per-entry loop, after the x/y block and before `st["anchor_area_ptr"] = 0`:

```python
        sw = entry.get("switches", {})
        if isinstance(sw, dict):
            st["switches"] = {str(k): bool(v) for k, v in sw.items()}
            widget = get_widget(name)
            if widget is not None and getattr(widget, "switches", None):
                for k, v in st["switches"].items():
                    if k in widget.switches:
                        widget.switches[k] = bool(v)
```

> `load_states` already calls `get_widget(name)` lower down for panel x/y; keep that block. The switch restore mirrors `register_composed` (Task 7) so order-of-load doesn't matter: whichever runs later wins, both read the same persisted dict.

- [ ] **Step 5: Confirm pure tests unaffected**

Run: `python -m pytest tests -q`
Expected: PASS (state.py is not imported by the pure suite).

- [ ] **Step 6: Commit**

```bash
git add ui/widgets/state.py
git commit -m "$(cat <<'EOF'
feat(widgets): persist local switch state in widgets_state JSON

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Thread `context` through render/events + Blender end-to-end verify

**Files:**
- Modify: `ui/widgets/render.py` (`compute_layout`, `draw_widget` — pass `context` to `rows()`)
- Modify: `ui/widgets/events.py` (`invoke` — `control_at(context, *where)`)
- Verify: Blender via MCP `execute_blender_code` (reload infra: blinker port 9902 / MCP 9999) + manual click-through.

**Interfaces:**
- Consumes: `Widget.rows(context)` / `Widget.control_at(context, …)` (Task 6).

- [ ] **Step 1: `render.py` — pass context to every `rows()` call.** In `compute_layout`, the in-context branch:

```python
    if _in_context(widget, context):
        for control in widget.rows(context):
            if isinstance(control, Row):
                height = max((_row_height(c, th) for c in control.children),
                             default=_row_height(control, th))
                rows.append((height, control.columns))
            else:
                rows.append((_row_height(control, th), 1))
        min_content = max((_control_min_width(c, th)
                           for c in widget.rows(context)), default=0.0)
```

In `draw_widget`, the control loop:

```python
            for r, control in enumerate(widget.rows(context)):
```

- [ ] **Step 2: `events.py` — pass context to `control_at`.** At `events.py:154`:

```python
            control = widget.control_at(context, *where)
```

- [ ] **Step 3: Empty-visible-list sanity.** No code change expected: with zero visible rows in-context, `compute_layout` appends no rows (`min_content` falls back to `PANEL_MIN_CONTENT_W`/title width) and `draw_widget`'s control loop is a no-op, yielding a title-bar-only panel. Confirm by reading `panel.layout()` (`panel.py:84`): `inner_h = 0`, `height = title_h + 2*padding`. If a future change indexes `row_rects[0]` in the in-context path, guard it — but the current code does not.

- [ ] **Step 4: Reload + author a test widget.** Via MCP `execute_blender_code`, reload the addon (blinker 9902 or disable→purge→enable). Then write a JSON widget to the widgets folder, e.g.:

```json
{
  "version": 1,
  "name": "ctx_demo",
  "title": "Context Demo",
  "switches": {"advanced": false},
  "rows": [
    {"type": "FLIPBOX", "switch": "advanced", "label": "Advanced"},
    {"type": "BUTTON", "label": "Always", "op": "iops.executor",
     "op_kwargs": {"script": ""}},
    {"type": "SECTION", "label": "Advanced tools",
     "show_if": {"switch": "advanced"}},
    {"type": "BUTTON", "label": "Adv Only", "op": "iops.executor",
     "op_kwargs": {"script": ""}, "show_if": {"switch": "advanced"}},
    {"type": "SECTION", "label": "Edit-mode only",
     "show_if": {"mode": "EDIT_MESH"}},
    {"type": "SECTION", "label": "Mesh objects",
     "show_if": {"object_type": "MESH"}}
  ]
}
```

- [ ] **Step 5: Verify behavior live.** Run `bpy.ops.iops.scripts_call_widgets_panel()`, summon `ctx_demo`, and confirm via screenshot/inspection:
  - Toggling **Advanced** shows/hides the "Advanced tools" section + "Adv Only" button and the panel relayouts (grows/shrinks).
  - Entering EDIT_MESH on a mesh shows the "Edit-mode only" + "Mesh objects" sections; leaving hides them.
  - Selecting a non-mesh active object hides "Mesh objects".
  - Clicks land on the correct control after rows change (hit-test matches draw).
  - Reload the addon (or re-run `scripts_call_widgets_panel`) → the **Advanced** switch state is preserved.

- [ ] **Step 6: Commit**

```bash
git add ui/widgets/render.py ui/widgets/events.py
git commit -m "$(cat <<'EOF'
feat(widgets): thread context into row filtering for draw + interact

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Docs + memory + final verification

**Files:**
- Modify: `ai_skills/iops-custom-widgets/SKILL.md`
- Modify: `C:\Users\cvitk\.claude\projects\D--git-InteractionOps\memory\project_gpu_widget_system.md` + `MEMORY.md`

- [ ] **Step 1: Update SKILL.md.** Add to the JSON schema section:
  - A `show_if` subsection: the key table (`mode`, `object_type`, `selection`, `prop`, `switch`, `equals`), the AND semantics, the "invalid clause → row stays visible" rule, and the "v1: top-level rows only, no OR/nesting/cells" scope.
  - The FLIPBOX `switch` binding (third mutually-exclusive option) and the top-level `switches` defaults map.
  - A worked example mirroring the Task 9 `ctx_demo` JSON.
  - New gotcha rows:

| Symptom / trap | Reality |
|---|---|
| `show_if` flipbox merged into a multi-col row | Auto-merge skips flipboxes carrying `show_if`; they stand alone so the predicate hides exactly that box |
| Row with a typo'd `show_if` shows always | Invalid `show_if` is dropped + reported; the row stays visible (never silently vanishes) — check `load_def` errors |
| Switch state lost on reload | Switches persist in `widgets_state` like position; a switch with no defining FLIPBOX stays at default |
| Row visibility doesn't update | `show_if` is evaluated live each draw; if context changed without a depsgraph tick, nudge the viewport (same as value cache) |

- [ ] **Step 2: Update memory.** Append to `project_gpu_widget_system.md` a paragraph: per-row `show_if` (vocab: mode/object_type/selection/prop/switch + equals, ANDed), local `switches` dict on the instance persisted in `widgets_state`, pure evaluator in `ui/widgets/predicates.py`, the merge-exclusion rule, and that `rows(context)`/`control_at(context, …)` now filter. Add a one-line pointer if a new memory file is warranted; otherwise update in place. Reference the spec/plan dates (2026-06-23).

- [ ] **Step 3: Full test sweep.**

Run: `python -m pytest tests -q`
Expected: PASS (all green).

- [ ] **Step 4: Commit**

```bash
git add ai_skills/iops-custom-widgets/SKILL.md
git commit -m "$(cat <<'EOF'
docs(widgets): document show_if predicates + switch flipbox

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- §1 schema `show_if` → Tasks 2 (validation), 5 (attach), 1 (eval). ✅
- §1 `switch` flipbox + `switches` map → Task 3. ✅
- §2 local switch state + persistence → Tasks 7 (seed), 8 (persist). ✅
- §3 visible-row resolution (`rows(context)`/`control_at`) → Tasks 6, 9. ✅
- §4 merge rule → Task 4. ✅
- §5 evaluator (pure) → Task 1. ✅
- §6 edge cases: empty panel → Task 9 Step 3; widget poll unchanged → make_widget keeps existing poll (Task 7); press-cell stability → unchanged gesture flow (Task 9 verify). ✅
- §7 out-of-scope honored (no GROUP / OR / counts / cell visibility). ✅
- Docs/tests/verify → Task 10. ✅

**Placeholder scan:** The only intentional placeholder is the `composed_rna`/`predicates_meta` import names in Tasks 1 & 2 — both flagged with explicit NOTEs giving the real path (`...widgets.composed.resolve_prop`) and the hard-coded `SHOW_IF_SELECTION` tuple. No "TBD"/"handle edge cases" left.

**Type consistency:** `_show_if` (dict|None) consistent across controls.py, build_controls, predicates. `switches` dict consistent across make_widget/register_composed/state/build_controls. `rows(context)`/`control_at(context, row, col)` signatures consistent between Task 6 (def) and Task 9 (callers). `resolve_prop -> (value, found)` matches `EvalCtx.prop` and `eval_show_if` usage. `switch_adapter(store, name, on_change)` matches build_controls call. ✅
