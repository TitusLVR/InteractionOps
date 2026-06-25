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
    from ...widgets.composed import resolve_prop  # deferred; see Task 2

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
