"""Pure logic for the iOps Attributes panel (no bpy).

Type table, row listing / filtering, value formatting. Later: coercion, maths, chains, predicates and
the heatmap ramp used by the tools and the viewport preview.
"""
from __future__ import annotations

import math
import random
from collections import namedtuple

from .selection_sets_core import ATTR_PREFIX as _SS_PREFIX, unique_name

__all__ = ["DOMAINS", "TypeInfo", "TYPES", "BUILTIN_NAMES", "Row",
           "list_rows", "format_value", "unique_name",
           "default_value", "coerce", "mixed_count", "math_op", "randomize",
           "smooth", "order_chain", "gradient", "select_predicate",
           "HEATMAP_RAMP", "heat_color", "luminance", "scalar_for_preview"]

DOMAINS = ("POINT", "EDGE", "FACE", "CORNER")

TypeInfo = namedtuple("TypeInfo", "bm_layer widget components preview")

_LABELS = frozenset({"LABELS"})
_LABELS_HEAT = frozenset({"LABELS", "HEATMAP"})
_COLOUR = frozenset({"HEATMAP", "GREYSCALE", "COLOUR"})

TYPES = {
    "FLOAT": TypeInfo("float", "FLOAT", 1, _LABELS_HEAT),
    "INT": TypeInfo("int", "INT", 1, _LABELS_HEAT),
    "BOOLEAN": TypeInfo("bool", "BOOL", 1, _LABELS_HEAT),
    "FLOAT_VECTOR": TypeInfo("float_vector", "VECTOR", 3, _LABELS_HEAT),
    "FLOAT_COLOR": TypeInfo("float_color", "COLOR", 4, _COLOUR),
    "BYTE_COLOR": TypeInfo("color", "COLOR", 4, _COLOUR),
    "STRING": TypeInfo("string", "STRING", 1, _LABELS),
    "INT8": TypeInfo(None, "INT", 1, _LABELS_HEAT),
    "FLOAT2": TypeInfo(None, "VECTOR", 2, _LABELS),
    "QUATERNION": TypeInfo(None, "READONLY", 4, _LABELS),
    "FLOAT4": TypeInfo(None, "READONLY", 4, _LABELS),
    "INT16_2D": TypeInfo(None, "READONLY", 2, _LABELS),
    "INT32_2D": TypeInfo(None, "READONLY", 2, _LABELS),
    "FLOAT4X4": TypeInfo(None, "READONLY", 16, _LABELS),
    "VGROUP": TypeInfo("deform", "FLOAT", 1, _LABELS_HEAT),
}

BUILTIN_NAMES = frozenset({
    "position", "sharp_edge", "sharp_face", "material_index",
    "crease_vert", "crease_edge", "bevel_weight_vert", "bevel_weight_edge",
})

Row = namedtuple("Row", "name data_type domain kind editable")


def _is_editable(data_type: str, edit_mode: bool) -> bool:
    if data_type == "STRING":
        return False
    info = TYPES.get(data_type)
    if info is None:
        return False
    return info.bm_layer is not None if edit_mode else True


def list_rows(attributes, vertex_groups, *, show_hidden=False,
              show_builtin=False, show_vgroups=True, uv_names=(),
              color_names=(), edit_mode=True) -> list[Row]:
    """Rows for the UIList from (name, data_type, domain) triples and
    vertex group names. Selection-set layers are never listed."""
    uv_names = set(uv_names)
    color_names = set(color_names)
    rows = []
    for name, data_type, domain in attributes:
        if domain not in DOMAINS or data_type not in TYPES:
            continue
        if name.startswith(_SS_PREFIX):
            continue
        if name.startswith(".") and not show_hidden:
            continue
        builtin = (name in BUILTIN_NAMES or name in uv_names
                   or name in color_names)
        if builtin and not show_builtin:
            continue
        rows.append(Row(name, data_type, domain, "ATTR",
                        _is_editable(data_type, edit_mode)))
    rows.sort(key=lambda r: (DOMAINS.index(r.domain), r.name))
    if show_vgroups:
        for name in vertex_groups:
            rows.append(Row(name, "VGROUP", "POINT", "VGROUP", True))
    return rows


def format_value(value, data_type: str, decimals: int = 2) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    try:
        return " ".join(format_value(v, data_type, decimals) for v in value)
    except TypeError:
        return str(value)


# ---------------------------------------------------------------------------
# Values: defaults, coercion, maths
# ---------------------------------------------------------------------------
_SCALAR_FLOAT = frozenset({"FLOAT", "VGROUP"})
_SCALAR_INT = frozenset({"INT", "INT8"})
_SCALARS = _SCALAR_FLOAT | _SCALAR_INT | {"BOOLEAN"}
_COLOURS = frozenset({"FLOAT_COLOR", "BYTE_COLOR"})
_VECTORS = frozenset({"FLOAT_VECTOR", "FLOAT2", "QUATERNION", "FLOAT4",
                      "INT16_2D", "INT32_2D"}) | _COLOURS


def default_value(data_type: str):
    if data_type in _SCALAR_FLOAT:
        return 0.0
    if data_type in _SCALAR_INT:
        return 0
    if data_type == "BOOLEAN":
        return False
    if data_type == "STRING":
        return ""
    if data_type in _COLOURS:
        return (0.0, 0.0, 0.0, 1.0)
    if data_type == "QUATERNION":
        return (1.0, 0.0, 0.0, 0.0)
    if data_type == "FLOAT4X4":
        return tuple(1.0 if i % 5 == 0 else 0.0 for i in range(16))
    n = TYPES[data_type].components
    zero = 0 if data_type.startswith("INT") else 0.0
    return (zero,) * n


def _to_scalar(value, dst_type):
    if dst_type in _SCALAR_FLOAT:
        return float(value)
    if dst_type in _SCALAR_INT:
        return int(value)
    return bool(value)


def coerce(value, src_type: str, dst_type: str, component: int = 0):
    """Convert between attribute types; None when not convertible."""
    if src_type == "STRING" or dst_type == "STRING":
        return value if src_type == dst_type else None
    if src_type == dst_type:
        return value
    if src_type in _SCALARS and dst_type in _SCALARS:
        return _to_scalar(value, dst_type)
    if src_type in _VECTORS and dst_type in _SCALARS:
        try:
            return _to_scalar(value[component], dst_type)
        except (IndexError, TypeError):
            return None
    if src_type in _SCALARS and dst_type in _VECTORS:
        n = TYPES[dst_type].components
        v = float(value)
        if dst_type in _COLOURS:
            return (v, v, v, 1.0)
        return (v,) * n
    if src_type in _VECTORS and dst_type in _VECTORS:
        n = TYPES[dst_type].components
        vals = list(value)[:n]
        fill = 1.0 if dst_type in _COLOURS else 0.0
        vals += [fill] * (n - len(vals))
        return tuple(vals)
    return None


def _same(a, b, tol=1e-6):
    if isinstance(a, (int, float)) and not isinstance(a, bool) \
            and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, tol)
                                        for x, y in zip(a, b))
    return a == b


def _key(v):
    """Hashable key with the 1e-6 float tolerance baked in."""
    if isinstance(v, bool) or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if isinstance(v, (tuple, list)):
        return tuple(_key(c) for c in v)
    return v


def mixed_count(values) -> int:
    """Number of distinct values; O(n) via a set of rounded keys."""
    return len({_key(v) for v in values})


def _per_component(values, fn):
    out = []
    for v in values:
        if isinstance(v, (tuple, list)):
            out.append(tuple(fn(c) for c in v))
        else:
            out.append(fn(v))
    return out


def _invert_one(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return -v
    return 1.0 - v


def math_op(values, op: str, a=0.0, b=1.0):
    values = list(values)
    if not values:
        return []
    if op == "ADD":
        return _per_component(values, lambda v: v + a)
    if op == "MULTIPLY":
        return _per_component(values, lambda v: v * a)
    if op == "CLAMP":
        lo, hi = min(a, b), max(a, b)
        return _per_component(values, lambda v: min(max(v, lo), hi))
    if op == "INVERT":
        return _per_component(values, _invert_one)
    if op == "ROUND":
        nd = int(a)
        return _per_component(values, lambda v: v if isinstance(v, bool)
                              else round(v, nd))
    if op == "REMAP":
        if isinstance(values[0], (tuple, list)):
            n = len(values[0])
            cols = [[v[i] for v in values] for i in range(n)]
            remapped = [math_op(c, "REMAP", a, b) for c in cols]
            return [tuple(remapped[i][k] for i in range(n))
                    for k in range(len(values))]
        lo, hi = min(values), max(values)
        if hi - lo <= 1e-12:
            return [a for _ in values]
        return [a + (v - lo) / (hi - lo) * (b - a) for v in values]
    raise ValueError(f"unknown math op {op!r}")


def randomize(n: int, lo, hi, seed: int, data_type: str):
    rng = random.Random(seed)   # noqa: S311 - seeded, not cryptographic
    comps = TYPES[data_type].components
    if data_type in _SCALAR_INT:
        def pick():
            return rng.randint(int(lo), int(hi))
    elif data_type == "BOOLEAN":
        def pick():
            return rng.random() < 0.5
    else:
        def pick():
            return rng.uniform(float(lo), float(hi))
    if comps == 1:
        return [pick() for _ in range(n)]
    return [tuple(pick() for _ in range(comps)) for _ in range(n)]


def smooth(values, neighbours, iterations: int = 1, factor: float = 0.5):
    cur = list(values)
    if not cur:
        return cur
    vec = isinstance(cur[0], (tuple, list))
    for _ in range(max(1, int(iterations))):
        nxt = []
        for i, v in enumerate(cur):
            nb = neighbours[i] if i < len(neighbours) else ()
            if not nb:
                nxt.append(v)
                continue
            if vec:
                n = len(v)
                mean = [sum(cur[j][c] for j in nb) / len(nb)
                        for c in range(n)]
                nxt.append(tuple(v[c] + factor * (mean[c] - v[c])
                                 for c in range(n)))
            else:
                mean = sum(cur[j] for j in nb) / len(nb)
                nxt.append(v + factor * (mean - v))
        cur = nxt
    return cur


# ---------------------------------------------------------------------------
# Chains and gradients
# ---------------------------------------------------------------------------
def order_chain(vert_indices, edges):
    """Order `vert_indices` along a single open path or a closed loop
    given the selected edges between them; None if branching,
    disconnected or fewer than 2 verts."""
    verts = list(vert_indices)
    if len(verts) < 2:
        return None
    vset = set(verts)
    adj = {v: [] for v in verts}
    for a, b in edges:
        if a in vset and b in vset and a != b:
            adj[a].append(b)
            adj[b].append(a)
    if any(len(nb) > 2 for nb in adj.values()):
        return None
    ends = [v for v in verts if len(adj[v]) == 1]
    if len(ends) == 2:
        start = min(ends)
    elif not ends and all(len(adj[v]) == 2 for v in verts):
        start = min(verts)
    else:
        return None
    out = [start]
    prev, cur = None, start
    while True:
        nxt = [n for n in adj[cur] if n != prev]
        if not nxt or nxt[0] == start:
            break
        out.append(nxt[0])
        prev, cur = cur, nxt[0]
        if len(out) > len(verts):
            return None
    if len(out) != len(verts):
        return None
    return out


def gradient(n: int, v0, v1, mode: str = "LINEAR"):
    if n <= 0:
        return []
    if n == 1:
        return [v0]

    def ease(t):
        return t * t * (3.0 - 2.0 * t) if mode == "EASE_IN_OUT" else t

    out = []
    vec = isinstance(v0, (tuple, list))
    for i in range(n):
        t = ease(i / (n - 1))
        if vec:
            out.append(tuple(a + (b - a) * t for a, b in zip(v0, v1)))
        else:
            out.append(v0 + (v1 - v0) * t)
    return out


# ---------------------------------------------------------------------------
# Predicates and preview helpers
# ---------------------------------------------------------------------------
def _length(v):
    return math.sqrt(sum(float(c) * float(c) for c in v))


def _scalar(v):
    return _length(v) if isinstance(v, (tuple, list)) else float(v)


def select_predicate(op: str, ref, tol: float = 1e-6, hi=None):
    if op == "EQUAL":
        return lambda v: _same(v, ref, tol)
    if op == "NOT_EQUAL":
        return lambda v: not _same(v, ref, tol)
    r = _scalar(ref)
    if op == "LESS":
        return lambda v: _scalar(v) < r
    if op == "GREATER":
        return lambda v: _scalar(v) > r
    if op == "RANGE":
        h = _scalar(hi if hi is not None else ref)
        lo_, hi_ = min(r, h), max(r, h)
        return lambda v: lo_ <= _scalar(v) <= hi_
    raise ValueError(f"unknown predicate {op!r}")


HEATMAP_RAMP = ((0, 0, 1), (0, 1, 1), (0, 1, 0), (1, 1, 0), (1, 0, 0))


def heat_color(t: float):
    t = min(max(float(t), 0.0), 1.0)
    n = len(HEATMAP_RAMP) - 1
    pos = t * n
    i = min(int(pos), n - 1)
    f = pos - i
    if f <= 0.0:
        return HEATMAP_RAMP[i]
    a, b = HEATMAP_RAMP[i], HEATMAP_RAMP[i + 1]
    return tuple(x + (y - x) * f for x, y in zip(a, b))


def luminance(rgba) -> float:
    return 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]


def scalar_for_preview(value, data_type: str) -> float:
    if data_type in _COLOURS:
        return luminance(value)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (tuple, list)):
        return _length(value)
    if isinstance(value, str):
        return 0.0
    return float(value)
