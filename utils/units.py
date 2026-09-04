"""Scene length-unit helpers (pure: no bpy, so they are unit-testable).

Blender's own N-panel formats lengths in the scene's fixed `length_unit`
(e.g. centimeters); `bpy.utils.units.to_string` without a target unit
picks an adaptive one instead (meters for anything above 1 m). These
helpers pick the fixed unit the scene asked for.
"""

# length_unit -> (Blender units -> display units multiplier, suffix)
_METRIC = {
    "KILOMETERS": (0.001, "km"),
    "METERS": (1.0, "m"),
    "CENTIMETERS": (100.0, "cm"),
    "MILLIMETERS": (1000.0, "mm"),
    "MICROMETERS": (1e6, "µm"),
}
_IMPERIAL = {
    "MILES": (1.0 / 1609.344, "mi"),
    "FEET": (1.0 / 0.3048, "ft"),
    "INCHES": (1.0 / 0.0254, "in"),
    "THOU": (1000.0 / 0.0254, "thou"),
}


def fixed_length_unit(system, length_unit, scale_length=1.0):
    """(multiplier, suffix) for a scene's fixed length unit, or None when
    the scene uses ADAPTIVE / NONE and the caller should fall back to
    Blender's own formatting."""
    table = _METRIC if system == "METRIC" else _IMPERIAL if system == "IMPERIAL" else None
    if table is None or length_unit not in table:
        return None
    mult, suffix = table[length_unit]
    return mult * scale_length, suffix


def format_fixed_length(value, system, length_unit, scale_length=1.0, precision=2):
    """'12.34 cm' in the scene's fixed unit, or None for ADAPTIVE / NONE."""
    unit = fixed_length_unit(system, length_unit, scale_length)
    if unit is None:
        return None
    mult, suffix = unit
    return f"{value * mult:.{precision}f} {suffix}"
