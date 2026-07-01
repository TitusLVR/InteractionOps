"""Pure UV-rectangle bounds math, free of bpy so it can be unit-tested.

Consumed by operators/uv_info.py (IOPS_OT_UVInfoRect)."""


def uv_rect_bounds(c0, c1):
    """Axis-aligned UV bounds of the rectangle spanned by corners c0, c1.

    Returns (uv_min, uv_max, size) as ((u,v),(u,v),(w,h)), independent of
    which corner was dragged first."""
    u0, v0 = c0
    u1, v1 = c1
    umin, umax = (u0, u1) if u0 <= u1 else (u1, u0)
    vmin, vmax = (v0, v1) if v0 <= v1 else (v1, v0)
    uv_min = (umin, vmin)
    uv_max = (umax, vmax)
    size = (umax - umin, vmax - vmin)
    return uv_min, uv_max, size


def format_uv_rect(uv_min, uv_max, size, ndigits=6):
    """Human-readable one-liner for the clipboard / report."""
    def fmt(p):
        return f"({p[0]:.{ndigits}f}, {p[1]:.{ndigits}f})"
    return f"min: {fmt(uv_min)} max: {fmt(uv_max)} size: {fmt(size)}"
