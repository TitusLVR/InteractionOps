"""Scene length-unit helpers (pure: no bpy, so they are unit-testable).

Blender's own N-panel formats lengths in the scene's fixed `length_unit`
(e.g. centimeters); `bpy.utils.units.to_string` without a target unit
picks an adaptive one instead (meters for anything above 1 m). These
helpers pick the fixed unit the scene asked for, and when the scene is
ADAPTIVE they still resolve to ONE unit for a whole row of values, so a
dimensions line never reads "1.5 m x 50 cm x 2.3 cm".
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

# Largest -> smallest, the ladder ADAPTIVE walks down until the value
# reads as at least 1.0. The base unit is what zero resolves to.
_ADAPTIVE = {
    "METRIC": (("KILOMETERS", "METERS", "CENTIMETERS", "MILLIMETERS", "MICROMETERS"), "METERS"),
    "IMPERIAL": (("MILES", "FEET", "INCHES", "THOU"), "FEET"),
}


def _table(system):
    return _METRIC if system == "METRIC" else _IMPERIAL if system == "IMPERIAL" else None


def fixed_length_unit(system, length_unit, scale_length=1.0):
    """(multiplier, suffix) for a scene's fixed length unit, or None when
    the scene uses ADAPTIVE / NONE and the caller should fall back to
    Blender's own formatting."""
    table = _table(system)
    if table is None or length_unit not in table:
        return None
    mult, suffix = table[length_unit]
    return mult * scale_length, suffix


def adaptive_length_unit(system, ref_value, scale_length=1.0):
    """(multiplier, suffix) of the largest unit in which `ref_value`
    (Blender units) reads as >= 1.0; the base unit for zero. None for a
    unit-less scene."""
    table = _table(system)
    if table is None:
        return None
    ladder, base = _ADAPTIVE[system]
    ref = abs(ref_value) * scale_length
    chosen = base
    if ref > 0.0:
        chosen = ladder[-1]
        for name in ladder:
            if ref * table[name][0] >= 1.0:
                chosen = name
                break
    mult, suffix = table[chosen]
    return mult * scale_length, suffix


def format_fixed_length(value, system, length_unit, scale_length=1.0, precision=2):
    """'12.34 cm' in the scene's fixed unit, or None for ADAPTIVE / NONE."""
    unit = fixed_length_unit(system, length_unit, scale_length)
    if unit is None:
        return None
    mult, suffix = unit
    return f"{value * mult:.{precision}f} {suffix}"


def format_lengths(values, system, length_unit, scale_length=1.0, precision=2):
    """Format a row of Blender-unit lengths in ONE shared unit.

    Fixed scene unit -> that unit. ADAPTIVE -> the unit the largest value
    resolves to (so every value on the row shares it). NONE -> bare
    numbers."""
    values = list(values)
    unit = fixed_length_unit(system, length_unit, scale_length)
    if unit is None and _table(system) is not None:
        ref = max((abs(v) for v in values), default=0.0)
        unit = adaptive_length_unit(system, ref, scale_length)
    if unit is None:
        return [f"{v:.{precision}f}" for v in values]
    mult, suffix = unit
    return [f"{v * mult:.{precision}f} {suffix}" for v in values]
