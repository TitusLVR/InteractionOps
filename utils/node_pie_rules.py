"""Rule store for the node-editor pie: shipped defaults, user overrides, merge.

Pure data handling, no bpy, so pytest covers the parts that can be wrong. The
bpy side (`operators/node_pie/store.py`) only supplies file contents and
surfaces the warnings this module returns.
"""
from __future__ import annotations

import json

SCHEMA_VERSION = 1
SLOT_COUNT = 8
#: Blender's pie draw order; `slots` is indexed in this order.
SLOT_LABELS = ("W", "E", "S", "N", "NW", "NE", "SW", "SE")
FALLBACK_KEY = "__fallback__"
#: Node tree types the pie supports. Single source of truth: the bpy-side
#: store re-exports it, the menu poll and the prefs tab read it from there.
TREE_TYPES = ("GeometryNodeTree", "ShaderNodeTree")


#: Optional entry fields and the type each consumer requires. A field of the
#: wrong type is dropped from the entry rather than passed on: `text`/`icon`
#: go straight into `UILayout.operator()`, which raises TypeError inside
#: `Menu.draw` on a non-string, and `props`/`inputs` are `.items()`-ed by the
#: spawn operator, which raises AttributeError on a non-dict. These are
#: hand-edited JSON fields, so both are reachable. `enabled` is read by
#: `is_enabled`, which treats anything but `False` as enabled anyway, so
#: dropping a non-bool merely keeps the stored entry honest.
_OPTIONAL_FIELD_TYPES = {
    "text": str,
    "icon": str,
    "props": dict,
    "inputs": dict,
    "enabled": bool,
}


def is_enabled(entry: object) -> bool:
    """Whether a slot entry should be offered at all.

    `enabled` is optional and absent means enabled, so presets written
    before the field existed (and every shipped default) keep working. A
    non-bool value degrades to enabled — the same "a bad optional field
    costs the field, not the slot" rule `normalise_entry` follows.

    An empty slot (None) is not enabled: the pie draws a separator for it
    either way, so both callers can ask this one question.
    """
    if not isinstance(entry, dict):
        return False
    value = entry.get("enabled", True)
    return value if isinstance(value, bool) else True


def normalise_entry(entry: object) -> dict | None:
    """Return a slot entry with only well-typed fields, or None if unusable.

    `node` is the only required field; without a `str` one the whole slot is
    dropped. Every other field is dropped individually, keeping the rest of
    the entry — a typo'd `icon` should cost the icon, not the pie button.
    """
    if not isinstance(entry, dict) or not isinstance(entry.get("node"), str):
        return None
    clean = {"node": entry["node"]}
    for key, value in entry.items():
        if key == "node":
            continue
        expected = _OPTIONAL_FIELD_TYPES.get(key)
        if expected is not None and not isinstance(value, expected):
            continue
        clean[key] = value
    return clean


def normalise_rule(rule: object) -> list[dict | None]:
    """Return a rule's slots as exactly SLOT_COUNT entries, padded with None.

    Entries without a `node` field are dropped to None rather than raising —
    this data reaches a draw callback, where an exception would break the pie.
    `rule` is untrusted JSON-derived data, so the type is `object` and the
    isinstance guards are load-bearing.
    """
    if not isinstance(rule, dict):
        return [None] * SLOT_COUNT
    slots = rule.get("slots")
    if not isinstance(slots, list):
        return [None] * SLOT_COUNT
    out: list[dict | None] = [
        normalise_entry(entry) for entry in slots[:SLOT_COUNT]
    ]
    return out + [None] * (SLOT_COUNT - len(out))


def merge(defaults: dict, user: dict) -> dict:
    """User rules replace shipped rules per node type, wholesale.

    Whole-entry replacement (rather than per-slot) means an addon update can
    never half-overwrite a rule the user edited.
    """
    merged = dict(defaults)
    if isinstance(user, dict):
        for key, rule in user.items():
            if isinstance(key, str) and isinstance(rule, dict):
                merged[key] = rule
    return merged


def get_entries(rules: dict, node_idname: str) -> list[dict | None] | None:
    """Slots for `node_idname`, or None when the fallback pie should be drawn."""
    rule = rules.get(node_idname)
    if rule is None:
        return None
    slots = normalise_rule(rule)
    if not any(slots):
        return None
    return slots


def load_document(text: str, defaults: dict) -> tuple[dict, list[str]]:
    """Parse a user preset file and layer it over `defaults`.

    Returns `(rules, warnings)`. Any failure degrades to the shipped defaults
    with a warning; the user never ends up with a dead pie because a file was
    hand-edited badly.
    """
    warnings: list[str] = []
    if not text or not text.strip():
        return dict(defaults), warnings
    try:
        doc = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        return dict(defaults), [f"node pie preset is not valid JSON: {exc}"]
    if not isinstance(doc, dict):
        return dict(defaults), ["node pie preset is not a JSON object"]
    version = doc.get("version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        warnings.append(
            f"node pie preset version {version} is newer than supported "
            f"{SCHEMA_VERSION}; loading anyway"
        )
    rules = doc.get("rules")
    if not isinstance(rules, dict):
        warnings.append("node pie preset has no 'rules' object")
        return dict(defaults), warnings
    return merge(defaults, rules), warnings


def _slots(*entries):
    """Build a rule from None, ready-made dicts or (node, text) pairs.

    Raises on anything else rather than guessing. This only ever sees the
    shipped tables below — developer data, not user data — so a typo should
    fail loudly in the test suite, which imports DEFAULTS.
    """
    out = []
    for entry in entries:
        if entry is None:
            out.append(None)
        elif isinstance(entry, dict):
            out.append(entry)
        elif isinstance(entry, tuple):
            out.append({"node": entry[0], "text": entry[1]})
        else:
            raise TypeError(f"node pie slot must be None, dict or tuple: {entry!r}")
    return {"slots": out}


SEARCH_SLOT = {"node": "__search__", "text": "Add New Node", "icon": "VIEWZOOM"}

# --- Geometry Nodes -------------------------------------------------------

GEO_CHAIN = _slots(
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeTransform", "Transform"),
    ("GeometryNodeJoinGeometry", "Join"),
    ("GeometryNodeSetMaterial", "Set Material"),
    ("GeometryNodeMergeByDistance", "Merge by Distance"),
    ("GeometryNodeSubdivisionSurface", "Subdivide"),
    ("GeometryNodeSetShadeSmooth", "Shade Smooth"),
    ("GeometryNodeInstanceOnPoints", "Instance on Points"),
)

GEO_POINTS = _slots(
    ("GeometryNodeInstanceOnPoints", "Instance on Points"),
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
    ("GeometryNodePointsToVertices", "Points to Vertices"),
    ("GeometryNodeJoinGeometry", "Join"),
    ("GeometryNodeDeleteGeometry", "Delete"),
    ("GeometryNodeProximity", "Proximity"),
    ("GeometryNodeAttributeStatistic", "Statistic"),
)

GEO_FIELD = _slots(
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeVectorMath", "Vector Math"),
    ("ShaderNodeSeparateXYZ", "Separate XYZ"),
    ("ShaderNodeCombineXYZ", "Combine XYZ"),
    ("ShaderNodeMapRange", "Map Range"),
    ("ShaderNodeMix", "Mix"),
    ("GeometryNodeCaptureAttribute", "Capture"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
)

GEO_RAYCAST = _slots(
    ("GeometryNodeCaptureAttribute", "Capture"),
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeVectorMath", "Vector Math"),
    ("ShaderNodeSeparateXYZ", "Separate XYZ"),
    ("GeometryNodeSwitch", "Switch"),
    ("GeometryNodeProximity", "Proximity"),
)

GEO_FALLBACK = _slots(
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeTransform", "Transform"),
    SEARCH_SLOT,
    ("GeometryNodeJoinGeometry", "Join"),
    ("GeometryNodeSwitch", "Switch"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
    ("GeometryNodeCaptureAttribute", "Capture"),
    ("GeometryNodeRealizeInstances", "Realize"),
)

GEO_GEOMETRY_NODES = (
    "GeometryNodeMeshCube", "GeometryNodeMeshLine", "GeometryNodeMeshBoolean",
    "GeometryNodeExtrudeMesh", "GeometryNodeDualMesh",
    "GeometryNodeCurveToMesh", "GeometryNodeMeshToCurve",
    "GeometryNodeResampleCurve", "GeometryNodeFillCurve",
    "GeometryNodeSeparateGeometry", "GeometryNodeDeleteGeometry",
    "GeometryNodeConvexHull", "GeometryNodeBoundBox",
    "GeometryNodeScaleElements", "GeometryNodeFlipFaces",
    "GeometryNodeTriangulate", "GeometryNodeSplitEdges",
    "GeometryNodeSubdivisionSurface", "GeometryNodeMergeByDistance",
    "GeometryNodeSetShadeSmooth", "GeometryNodeSetMaterial",
    "GeometryNodeTransform", "GeometryNodeSetPosition",
    "GeometryNodeJoinGeometry", "GeometryNodeRealizeInstances",
    "GeometryNodeInstanceOnPoints", "GeometryNodeSetID",
    "GeometryNodeSwitch",
)

GEO_FIELD_NODES = (
    "GeometryNodeInputPosition", "GeometryNodeInputNormal",
    "GeometryNodeInputIndex", "GeometryNodeProximity",
    "GeometryNodeAttributeStatistic", "GeometryNodeSampleIndex",
    "GeometryNodeCaptureAttribute",
)

# --- Shader ---------------------------------------------------------------

SHD_SHADER = _slots(
    ("ShaderNodeOutputMaterial", "Material Output"),
    ("ShaderNodeMixShader", "Mix Shader"),
    ("ShaderNodeAddShader", "Add Shader"),
    None, None, None, None, None,
)

SHD_COLOR = _slots(
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeHueSaturation", "Hue/Sat"),
    ("ShaderNodeBrightContrast", "Bright/Contrast"),
    ("ShaderNodeInvert", "Invert"),
    ("ShaderNodeSeparateColor", "Separate Color"),
    ("ShaderNodeBump", "Bump"),
)

SHD_VECTOR = _slots(
    ("ShaderNodeMapping", "Mapping"),
    ("ShaderNodeSeparateXYZ", "Separate XYZ"),
    ("ShaderNodeVectorMath", "Vector Math"),
    ("ShaderNodeTexNoise", "Noise"),
    ("ShaderNodeTexVoronoi", "Voronoi"),
    ("ShaderNodeTexImage", "Image"),
    ("ShaderNodeBump", "Bump"),
    ("ShaderNodeNormalMap", "Normal Map"),
)

SHD_VALUE = _slots(
    ("ShaderNodeMapRange", "Map Range"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeClamp", "Clamp"),
    ("ShaderNodeFloatCurve", "Float Curve"),
    ("ShaderNodeCombineXYZ", "Combine XYZ"),
    ("ShaderNodeMixShader", "Mix Shader"),
)

SHD_TEX_NOISE = _slots(
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeMapRange", "Map Range"),
    ("ShaderNodeBump", "Bump"),
    {"node": "ShaderNodeMath", "text": "Multiply", "props": {"operation": "MULTIPLY"}},
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeDisplacement", "Displacement"),
    ("ShaderNodeSeparateColor", "Separate Color"),
    ("ShaderNodeMapping", "Mapping"),
)

SHD_TEX_IMAGE = _slots(
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeNormalMap", "Normal Map"),
    ("ShaderNodeBump", "Bump"),
    ("ShaderNodeSeparateColor", "Separate Color"),
    ("ShaderNodeHueSaturation", "Hue/Sat"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeDisplacement", "Displacement"),
)

SHD_FALLBACK = _slots(
    ("ShaderNodeBsdfPrincipled", "Principled"),
    ("ShaderNodeTexImage", "Image"),
    SEARCH_SLOT,
    ("ShaderNodeTexNoise", "Noise"),
    ("ShaderNodeMapping", "Mapping"),
    ("ShaderNodeTexCoord", "Texture Coord"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeMath", "Math"),
)

SHD_SHADER_NODES = (
    "ShaderNodeBsdfPrincipled", "ShaderNodeBsdfDiffuse", "ShaderNodeBsdfGlass",
    "ShaderNodeEmission", "ShaderNodeBsdfTransparent", "ShaderNodeMixShader",
    "ShaderNodeAddShader",
)

SHD_COLOR_NODES = (
    "ShaderNodeTexVoronoi", "ShaderNodeTexChecker", "ShaderNodeRGB",
    "ShaderNodeValToRGB", "ShaderNodeMix", "ShaderNodeHueSaturation",
    "ShaderNodeBrightContrast", "ShaderNodeGamma", "ShaderNodeInvert",
    "ShaderNodeRGBCurve", "ShaderNodeCombineColor", "ShaderNodeAttribute",
    "ShaderNodeObjectInfo",
)

SHD_VECTOR_NODES = (
    "ShaderNodeTexCoord", "ShaderNodeMapping", "ShaderNodeNewGeometry",
    "ShaderNodeNormalMap", "ShaderNodeBump", "ShaderNodeCombineXYZ",
    "ShaderNodeVectorTransform",
)

SHD_VALUE_NODES = (
    "ShaderNodeMath", "ShaderNodeValue", "ShaderNodeFresnel",
    "ShaderNodeLayerWeight", "ShaderNodeMapRange", "ShaderNodeClamp",
    "ShaderNodeFloatCurve", "ShaderNodeSeparateXYZ", "ShaderNodeSeparateColor",
)

DEFAULTS = {
    "GeometryNodeTree": {
        **dict.fromkeys(GEO_GEOMETRY_NODES, GEO_CHAIN),
        **dict.fromkeys(GEO_FIELD_NODES, GEO_FIELD),
        "GeometryNodeDistributePointsOnFaces": GEO_POINTS,
        "GeometryNodePointsToVertices": GEO_POINTS,
        "GeometryNodeRaycast": GEO_RAYCAST,
        FALLBACK_KEY: GEO_FALLBACK,
    },
    "ShaderNodeTree": {
        **dict.fromkeys(SHD_SHADER_NODES, SHD_SHADER),
        **dict.fromkeys(SHD_COLOR_NODES, SHD_COLOR),
        **dict.fromkeys(SHD_VECTOR_NODES, SHD_VECTOR),
        **dict.fromkeys(SHD_VALUE_NODES, SHD_VALUE),
        "ShaderNodeTexNoise": SHD_TEX_NOISE,
        "ShaderNodeTexImage": SHD_TEX_IMAGE,
        FALLBACK_KEY: SHD_FALLBACK,
    },
}
