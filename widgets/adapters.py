"""Mesh-attribute value adapters for composed widgets.

A composed row bound with `"attribute": <name>, "domain": POINT|EDGE|FACE`
reads/writes that attribute on the SELECTED elements of every mesh in edit
mode. Facts verified empirically on Blender 5.2.3:
- Generic attributes (bevel_weight_edge, crease_edge, freestyle_edge,
  custom ones) are BMesh layers: `bm.<seq>.layers.<float|int|bool>`. They
  may not exist yet; a missing layer reads as 0 / False and is created on
  the first non-default write.
- sharp_edge / uv_seam / sharp_face are mesh attributes OUTSIDE edit mode
  only: BMesh turns them into element flags (`not e.smooth`, `e.seam`,
  `not f.smooth`) and exposes no layer — see _FLAG_ATTRS.

Binding contract (ui/widgets/controls.py):
- getters return (value, is_mixed); value None = nothing selected.
- setters write uniformly to ALL selected elements.
- bmesh is re-acquired with bmesh.from_edit_mesh() on EVERY call; only
  plain floats/bools/indices are kept between events.
"""
import bmesh

from ..ui.widgets.controls import mixed_state
from .composed import _coerce, _to_display

_SEQ = {"POINT": "verts", "EDGE": "edges", "FACE": "faces"}

# (domain, attribute) -> (read(elem), write(elem, bool)) for attributes
# BMesh stores as element flags instead of layers.
_FLAG_ATTRS = {
    ("EDGE", "sharp_edge"): (lambda e: not e.smooth,
                             lambda e, v: setattr(e, "smooth", not v)),
    ("EDGE", "uv_seam"): (lambda e: e.seam,
                          lambda e, v: setattr(e, "seam", v)),
    ("FACE", "sharp_face"): (lambda f: not f.smooth,
                             lambda f, v: setattr(f, "smooth", not v)),
}
_LAYER_KINDS = ("float", "int", "bool")
_CAST = {"float": float, "int": lambda v: int(round(float(v))),
         "bool": bool}


# ----------------------------------------------------------------------
# bmesh helpers — every entry point re-acquires bmesh, nothing is cached
# ----------------------------------------------------------------------
def _edit_meshes(context):
    """Mesh datablocks currently in edit mode (multi-object edit aware)."""
    objs = getattr(context, "objects_in_mode_unique_data", None)
    if objs:
        return [ob.data for ob in objs if ob.type == "MESH"]
    ob = getattr(context, "edit_object", None)
    if ob is not None and ob.type == "MESH":
        return [ob.data]
    return []


def _update(me):
    """Flush a non-destructive attribute-only bmesh edit back to the mesh."""
    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)


def _seq(bm, domain):
    return getattr(bm, _SEQ[domain])


def has_selected(context, domains):
    """Cheap any-selected-element check over `domains` (early exit on the
    first hit) — the enabled_get hook for presets/buttons, which go inert
    and grayed when nothing is selected."""
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        for domain in domains:
            for el in _seq(bm, domain):
                if el.select:
                    return True
    return False


def _find_layer(seq, name, prefer):
    """(kind, layer) of the existing layer `name`, trying `prefer` first;
    (None, None) when the attribute doesn't exist on this mesh yet."""
    for kind in (prefer,) + tuple(k for k in _LAYER_KINDS if k != prefer):
        lay = getattr(seq.layers, kind).get(name)
        if lay is not None:
            return kind, lay
    return None, None


class _Access:
    """Per-mesh read/write of one attribute on raw (storage) values."""

    def __init__(self, seq, name, domain, prefer):
        self.flag = _FLAG_ATTRS.get((domain, name))
        self.seq, self.name, self.prefer = seq, name, prefer
        self.kind, self.lay = (None, None) if self.flag else \
            _find_layer(seq, name, prefer)

    def read(self, el, default):
        if self.flag:
            return self.flag[0](el)
        return el[self.lay] if self.lay is not None else default

    def ensure(self):
        """Create the layer (preferred kind) when missing."""
        if self.flag is None and self.lay is None:
            self.kind = self.prefer
            self.lay = getattr(self.seq.layers, self.kind).new(self.name)

    def write(self, el, value):
        if self.flag:
            self.flag[1](el, bool(value))
        else:
            el[self.lay] = _CAST[self.kind](value)


def attribute_adapter(name, domain, kind, value_type="FLOAT"):
    """get/set/snapshot/restore bundle for mesh attribute `name` on
    `domain`. kind "bool" (flipbox) or "number" (slider/presets, values in
    author space: degrees when value_type is DEGREES)."""
    is_bool = kind == "bool"
    prefer = "bool" if is_bool else ("int" if value_type == "INT"
                                     else "float")
    default = False if is_bool else 0

    def to_author(raw):
        return bool(raw) if is_bool else _to_display(value_type, raw)

    def get(context):
        def values():
            for me in _edit_meshes(context):
                bm = bmesh.from_edit_mesh(me)
                seq = _seq(bm, domain)
                acc = _Access(seq, name, domain, prefer)
                for el in seq:
                    if el.select:
                        yield to_author(acc.read(el, default))
        return mixed_state(values())

    def set(context, value):
        raw = bool(value) if is_bool else _coerce(value_type, value)
        for me in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(me)
            seq = _seq(bm, domain)
            acc = _Access(seq, name, domain, prefer)
            if acc.flag is None and acc.lay is None and not raw:
                continue        # missing layer already reads as default
            acc.ensure()
            changed = False
            for el in seq:
                if el.select:
                    acc.write(el, raw)
                    changed = True
            if changed:
                _update(me)

    def snapshot(context):
        """(mesh name, [(element index, raw value)]) of the selection —
        plain data for the slider ESC/RMB exact restore."""
        token = []
        for me in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(me)
            seq = _seq(bm, domain)
            seq.index_update()
            acc = _Access(seq, name, domain, prefer)
            items = [(el.index, acc.read(el, default))
                     for el in seq if el.select]
            if items:
                token.append((me.name, items))
        return token

    def restore(context, token):
        """Put snapshot values back per element index (drag gestures never
        change topology, so indices captured at drag start stay valid)."""
        if not token:
            return
        by_name = {me.name: me for me in _edit_meshes(context)}
        for mname, items in token:
            me = by_name.get(mname)
            if me is None:
                continue
            bm = bmesh.from_edit_mesh(me)
            seq = _seq(bm, domain)
            acc = _Access(seq, name, domain, prefer)
            acc.ensure()
            seq.ensure_lookup_table()
            count = len(seq)
            for idx, v in items:
                if 0 <= idx < count:
                    acc.write(seq[idx], v)
            _update(me)

    return {"get": get, "set": set, "snapshot": snapshot,
            "restore": restore}
