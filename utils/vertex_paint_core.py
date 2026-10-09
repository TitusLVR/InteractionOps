"""Pure math for the Vertex Paint modal (operators/mesh_vertex_paint.py).

bpy-free so it is pytest-covered: brush falloff presets (the same formulas
Blender's BKE_brush_curve_strength uses), per-vertex color blending for the
RGB / alpha channel modes, and the stroke-level undo/redo history the modal
drives with Ctrl+Z / Ctrl+Shift+Z.
"""
import math

# Order matches Blender's Brush.curve_distance_falloff_preset enum; CUSTOM
# is evaluated by the caller through the brush's CurveMapping.
FALLOFF_PRESETS = ("CUSTOM", "SMOOTH", "SMOOTHER", "SPHERE", "ROOT", "SHARP",
                   "LIN", "POW4", "INVSQUARE", "CONSTANT")

CHANNEL_MODES = ("RGB", "ALPHA")

# Quick-pick colors: key -> RGB. Alpha is kept separately (brush alpha).
QUICK_COLORS = {
    "R": (1.0, 0.0, 0.0),
    "G": (0.0, 1.0, 0.0),
    "B": (0.0, 0.0, 1.0),
    "K": (0.0, 0.0, 0.0),
    "W": (1.0, 1.0, 1.0),
}
# Shift + R / G / B: the two-channel mixes (R+G, G+B, B+R).
QUICK_COLORS_SHIFT = {
    "R": (1.0, 1.0, 0.0),
    "G": (0.0, 1.0, 1.0),
    "B": (1.0, 0.0, 1.0),
}


def falloff_weight(preset, p, custom=None):
    """Brush strength multiplier for a vertex at normalized distance `p`
    (0 = brush center, 1 = brush edge). Outside the radius -> 0.

    Presets use Blender's formulas on (1 - p); CUSTOM calls `custom(p)`
    (the brush CurveMapping, 1 at center / 0 at edge by default) and falls
    back to SMOOTH when no evaluator is given.
    """
    if p >= 1.0:
        return 0.0
    if p < 0.0:
        p = 0.0
    if preset == "CUSTOM":
        if custom is None:
            preset = "SMOOTH"
        else:
            try:
                return _clamp01(float(custom(p)))
            except Exception:
                preset = "SMOOTH"
    q = 1.0 - p
    if preset == "SHARP":
        s = q * q
    elif preset == "SMOOTH":
        s = 3.0 * q * q - 2.0 * q * q * q
    elif preset == "SMOOTHER":
        s = q * q * q * (q * (q * 6.0 - 15.0) + 10.0)
    elif preset == "ROOT":
        s = math.sqrt(q)
    elif preset == "LIN":
        s = q
    elif preset == "CONSTANT":
        s = 1.0
    elif preset == "SPHERE":
        s = math.sqrt(max(0.0, 2.0 * q - q * q))
    elif preset == "POW4":
        s = q * q * q * q
    elif preset == "INVSQUARE":
        s = q * (2.0 - q)
    else:
        s = 3.0 * q * q - 2.0 * q * q * q
    return _clamp01(s)


def next_preset(preset, step=1):
    """Cycle through FALLOFF_PRESETS (Shift+Wheel in the modal)."""
    try:
        i = FALLOFF_PRESETS.index(preset)
    except ValueError:
        i = 0
    return FALLOFF_PRESETS[(i + step) % len(FALLOFF_PRESETS)]


def blend_color(base, target, weight, channel_mode="RGB"):
    """Lerp `base` toward `target` by `weight` on the channels the mode
    owns: RGB keeps base alpha, ALPHA keeps base RGB. Returns a 4-tuple.
    `weight` is clamped to [0, 1]."""
    w = _clamp01(weight)
    if w <= 0.0:
        return (base[0], base[1], base[2], base[3])
    if channel_mode == "ALPHA":
        return (base[0], base[1], base[2],
                base[3] + (target[3] - base[3]) * w)
    return (base[0] + (target[0] - base[0]) * w,
            base[1] + (target[1] - base[1]) * w,
            base[2] + (target[2] - base[2]) * w,
            base[3])


def stroke_weight(prev, w, strength):
    """Non-accumulating stroke: the effective weight of a vertex within one
    stroke is the max over all dabs, scaled by brush strength. Returns the
    new per-stroke max (unscaled) and the effective weight to apply."""
    m = max(prev, w)
    return m, _clamp01(m * strength)


class StrokeHistory:
    """Undo/redo stack of strokes. A stroke maps element key -> (before,
    after). `begin()` opens a stroke, `touch(key, before)` records the
    pre-stroke value once per key, `commit(after_of)` closes it (storing
    the final values via the callback) and drops the redo stack. `undo()` /
    `redo()` return the {key: value} map to write back, or None."""

    def __init__(self, limit=64):
        self.limit = max(1, int(limit))
        self._undo = []
        self._redo = []
        self._cur = None

    @property
    def active(self):
        return self._cur is not None

    def begin(self):
        self._cur = {}

    def touch(self, key, before):
        if self._cur is None:
            self._cur = {}
        if key not in self._cur:
            self._cur[key] = before

    def touched(self, key):
        return self._cur is not None and key in self._cur

    def commit(self, after_of):
        cur = self._cur
        self._cur = None
        if not cur:
            return False
        stroke = {k: (v, after_of(k)) for k, v in cur.items()}
        self._undo.append(stroke)
        if len(self._undo) > self.limit:
            del self._undo[0]
        self._redo.clear()
        return True

    def cancel(self):
        """Drop the open stroke and return its {key: before} map so the
        caller can restore it."""
        cur = self._cur or {}
        self._cur = None
        return dict(cur)

    def undo(self):
        if not self._undo:
            return None
        stroke = self._undo.pop()
        self._redo.append(stroke)
        return {k: v[0] for k, v in stroke.items()}

    def redo(self):
        if not self._redo:
            return None
        stroke = self._redo.pop()
        self._undo.append(stroke)
        return {k: v[1] for k, v in stroke.items()}

    def __len__(self):
        return len(self._undo)

    @property
    def redo_depth(self):
        return len(self._redo)


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


# ----------------------------------------------------------------------
# Neighborhood filters (brush Blur tool + the whole-mesh Blur / Sharpen op)
# ----------------------------------------------------------------------
FILTER_MODES = ("BLUR", "SHARPEN")


def mean_color(colors):
    """Component-wise mean of a non-empty list of RGBA tuples."""
    n = float(len(colors))
    r = g = b = a = 0.0
    for c in colors:
        r += c[0]
        g += c[1]
        b += c[2]
        a += c[3]
    return (r / n, g / n, b / n, a / n)


def neighborhood_mean(i, vals, neighbors):
    """Mean color around vertex i: its own corner colors plus every
    neighbor vertex's corners, each corner weighted equally. `vals[v]`
    is the list of RGBA tuples of vertex v (one entry for POINT domain)."""
    pool = list(vals[i])
    for j in neighbors[i]:
        pool.extend(vals[j])
    return mean_color(pool)


def filter_color(c, mean, mode, amount, channel_mode="RGB"):
    """One corner: BLUR moves toward `mean`, SHARPEN away from it
    (unsharp mask), by `amount`; result clamped to [0, 1]. The channel
    mode picks RGB, ALPHA or RGBA."""
    k = amount if mode == "BLUR" else -amount
    out = list(c)
    chans = (3,) if channel_mode == "ALPHA" else ((0, 1, 2) if channel_mode == "RGB" else (0, 1, 2, 3))
    for ch in chans:
        out[ch] = _clamp01(c[ch] + (mean[ch] - c[ch]) * k)
    return tuple(out)


def filter_vertex_colors(vals, neighbors, mode, amount, iterations=1,
                         mask=None, channel_mode="RGB"):
    """Whole-mesh Blur / Sharpen. `vals` is a list (per vertex) of lists
    of RGBA tuples; `neighbors[i]` the edge-adjacent vertex indices;
    `mask` an optional set of vertex indices to change (others stay but
    still contribute to means). Returns a new structure of the same shape.
    Each iteration reads the previous iteration's result (Jacobi)."""
    cur = [list(v) for v in vals]
    amount = _clamp01(amount)
    for _ in range(max(1, int(iterations))):
        nxt = [None] * len(cur)
        for i, corners in enumerate(cur):
            if mask is not None and i not in mask:
                nxt[i] = corners
                continue
            m = neighborhood_mean(i, cur, neighbors)
            nxt[i] = [filter_color(c, m, mode, amount, channel_mode) for c in corners]
        cur = nxt
    return cur
