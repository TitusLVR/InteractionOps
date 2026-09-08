"""Pure-python match-dimensions math (no bpy) so pytest can cover it.

dimension_scale: per-axis scale factors that bring a target bbox
(tw x th) to a reference bbox (rw x rh).
  'UNIFORM' -- one factor, long side to long side; shape is preserved, so
               a strip rotated 90 degrees against the reference still
               matches in size instead of being squashed.
  'WIDTH'   -- scale X only so widths match.
  'HEIGHT'  -- scale Y only so heights match.
A degenerate target side (zero length) is left alone: factor 1.0.
"""

EPS = 1e-10


def dimension_scale(tw, th, rw, rh, mode='UNIFORM'):
    if mode == 'WIDTH':
        return (rw / tw if tw > EPS else 1.0, 1.0)
    if mode == 'HEIGHT':
        return (1.0, rh / th if th > EPS else 1.0)
    t_long = max(tw, th)
    if t_long <= EPS:
        return (1.0, 1.0)
    s = max(rw, rh) / t_long
    return (s, s)
