"""Pure-python match-dimensions math (no bpy) so pytest can cover it.

dimension_scale: per-axis scale factors that bring a target bbox
(tw x th) to a reference bbox (rw x rh).
  'BOTH'    -- per-axis factors so the target bbox equals the reference
               bbox (default).
  'UNIFORM' -- one factor, long side to long side; shape is preserved.
  'WIDTH'   -- scale X only so widths match.
  'HEIGHT'  -- scale Y only so heights match.
A degenerate target side (zero length) is left alone: factor 1.0.
"""

EPS = 1e-10


def dimension_scale(tw, th, rw, rh, mode='BOTH'):
    if mode == 'WIDTH':
        return (rw / tw if tw > EPS else 1.0, 1.0)
    if mode == 'HEIGHT':
        return (1.0, rh / th if th > EPS else 1.0)
    if mode == 'BOTH':
        return (rw / tw if tw > EPS else 1.0,
                rh / th if th > EPS else 1.0)
    t_long = max(tw, th)
    if t_long <= EPS:
        return (1.0, 1.0)
    s = max(rw, rh) / t_long
    return (s, s)


def dimension_fit(tw, th, rw, rh, mode='BOTH'):
    """Like dimension_scale, but orientation-aware: when the target and
    the reference are transposed (one landscape, the other portrait) the
    target is meant to be turned 90 degrees first so it lies along the
    reference instead of across it. Returns (rotate90, sx, sy) where the
    factors apply to the *rotated* target. A square target never turns."""
    t_land = tw > th + EPS
    t_port = th > tw + EPS
    r_land = rw > rh + EPS
    r_port = rh > rw + EPS
    rotate = (t_land and r_port) or (t_port and r_land)
    if rotate:
        tw, th = th, tw
    sx, sy = dimension_scale(tw, th, rw, rh, mode)
    return rotate, sx, sy
