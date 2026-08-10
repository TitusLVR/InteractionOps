# iOps Modifiers Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compact N-panel (iOps tab) with a grid of modifier-type icons for batch add/apply/remove/toggle across the selection, plus stack tools (sort, cleanup, vis-sync, cursor-target, select-users, safe apply transform) and an active-object stack list.

**Architecture:** A descriptor registry (`operators/modifiers/iops_mod_registry.py`) maps each modifier type to its icon, group, smart defaults, object-reference fields, sort weight and cleanup check. One file per modifier type registers a descriptor; one file per tool operator consumes the registry. The panel (`ui/iops_modifiers_panel.py`) is draw-only. Spec: `docs/superpowers/specs/2026-08-10-iops-modifiers-panel-design.md`.

**Tech Stack:** Blender 4.x/5.x Python API (`bpy`), no external deps. Live testing via blender-mcp (`mcp__blender__execute_blender_python`).

## Global Constraints

- `draw()` never scans the selection or scene — only the active object's modifiers.
- Batch operators never abort on one bad object: skip, count, one summary `self.report` at the end.
- Direct data API preferred; `bpy.ops` only for `modifier_apply` / `transform_apply` with `temp_override`.
- All new operator `bl_idname`s start with `iops.mod_`.
- Commit per task, directly on master (user preference). Do not push.
- No test framework exists in this repo. Each task verifies via a blender-mcp script; run it and confirm the printed `OK`-lines before committing. Reload the addon before each verification:

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
print("reloaded OK")
```

---

### Task 1: Modifier registry + shared core (`operators/modifiers/iops_mod_registry.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_registry.py`
- Create: `operators/modifiers/__init__.py` (stub, grows in later tasks)

**Interfaces:**
- Produces: `ModDescriptor` dataclass, `register_descriptor(desc)`, `REGISTRY` (dict `mod_type -> ModDescriptor`), `GROUP_ORDER`, `CURATED_TYPES`, `object_fields(md)`, `type_icon(mod_type)`, `all_mod_type_items()`, `add_with_defaults(obj, mod_type)`, `smart_apply_object(context, obj, mod_type=None, up_to=None) -> (applied:int, skip_reason:str|None)`.

- [ ] **Step 1: Write `operators/modifiers/iops_mod_registry.py`**

```python
"""Modifier panel core: type registry and batch helpers.

Each operators/modifiers/iops_<type>.py file registers a ModDescriptor
here. The panel and all tool operators are driven by this registry, so
adding a new modifier type to the grid = adding one descriptor file.
"""

import bpy
from dataclasses import dataclass, field

GROUP_ORDER = ("GENERATE", "DEFORM", "UTILITY")

REGISTRY = {}  # mod_type -> ModDescriptor, insertion order = grid order

# Types enabled in the grid by default (the curated 6x3 set)
CURATED_TYPES = (
    "BEVEL", "BOOLEAN", "MIRROR", "ARRAY", "SOLIDIFY", "SUBSURF",
    "SCREW", "WELD", "TRIANGULATE", "DECIMATE", "REMESH", "WIREFRAME",
    "CURVE", "LATTICE", "SIMPLE_DEFORM", "DISPLACE", "SHRINKWRAP",
    "WEIGHTED_NORMAL",
)


@dataclass
class ModDescriptor:
    mod_type: str                 # bpy Modifier.type enum id
    icon: str                     # UI icon name
    group: str                    # GENERATE | DEFORM | UTILITY
    defaults: dict = field(default_factory=dict)   # smart defaults
    object_fields: tuple = ()     # pointer props referencing Objects
    requires_target: bool = False # empty object_fields[0] == dead modifier
    sort_weight: int = 50         # Sort band: 10 early, 50 mid, 80+ tail
    scale_props: tuple = ()       # distance props Safe Apply rescales
    is_noop: object = None        # callable(md) -> bool for Cleanup


def register_descriptor(desc):
    REGISTRY[desc.mod_type] = desc
    return desc


# --- RNA-derived data (cached) ---------------------------------------

_TYPE_ITEMS = None   # [(identifier, name, icon), ...] for all modifier types
_FIELDS_CACHE = {}   # mod_type -> tuple of object-pointer prop names


def all_mod_type_items():
    """(identifier, name, icon) for every Object modifier type."""
    global _TYPE_ITEMS
    if _TYPE_ITEMS is None:
        enum = bpy.types.Modifier.bl_rna.properties["type"].enum_items
        _TYPE_ITEMS = [(it.identifier, it.name, it.icon) for it in enum]
    return _TYPE_ITEMS


def type_icon(mod_type):
    desc = REGISTRY.get(mod_type)
    if desc is not None:
        return desc.icon
    for ident, _name, icon in all_mod_type_items():
        if ident == mod_type:
            return icon if icon != "NONE" else "MODIFIER"
    return "MODIFIER"


def object_fields(md):
    """Names of md's props that point at Objects. Registry fast path,
    one-time RNA introspection fallback for unknown types."""
    desc = REGISTRY.get(md.type)
    if desc is not None:
        return desc.object_fields
    fields = _FIELDS_CACHE.get(md.type)
    if fields is None:
        fields = tuple(
            p.identifier for p in md.bl_rna.properties
            if p.type == "POINTER" and not p.is_readonly
            and getattr(p.fixed_type, "identifier", "") in {"Object"}
        )
        _FIELDS_CACHE[md.type] = fields
    return fields


# --- batch helpers ----------------------------------------------------

def add_with_defaults(obj, mod_type):
    """Add a modifier with the saved default preset or the descriptor's
    smart defaults. Returns the modifier or None (incompatible object)."""
    from . import iops_mod_presets as presets
    try:
        md = obj.modifiers.new(name=mod_type.title().replace("_", " "),
                               type=mod_type)
    except (TypeError, RuntimeError):
        return None
    if md is None:
        return None
    settings = presets.load_default(mod_type)
    if settings is None:
        desc = REGISTRY.get(mod_type)
        settings = desc.defaults if desc else {}
    apply_settings(md, settings)
    return md


def apply_settings(md, settings):
    for key, value in settings.items():
        try:
            prop = md.bl_rna.properties.get(key)
            if prop is not None and prop.type == "ENUM" and prop.is_enum_flag:
                value = set(value)
            setattr(md, key, value)
        except Exception:
            pass  # renamed/removed prop from an old preset — skip


def smart_apply_object(context, obj, mod_type=None, up_to=None):
    """Apply obj's modifiers top-down (stack order respected).

    mod_type: only modifiers of this type (None = all).
    up_to: (type, name) — apply every enabled modifier from the top
      through the first modifier matching type and name, inclusive.
      If no match exists on obj, nothing is applied.
    Handles multi-user data (auto single-user copy). Objects with shape
    keys are skipped. Disabled (show_viewport off) modifiers are skipped.
    Returns (applied_count, skip_reason or None).
    """
    if obj.data is not None and getattr(obj.data, "shape_keys", None):
        return 0, "shape keys"

    names = []
    if up_to is not None:
        found = False
        for md in obj.modifiers:
            if md.show_viewport:
                names.append(md.name)
            if md.type == up_to[0] and md.name == up_to[1]:
                found = True
                break
        if not found:
            return 0, "no matching modifier"
    else:
        names = [md.name for md in obj.modifiers
                 if md.show_viewport and (mod_type is None or md.type == mod_type)]

    if not names:
        return 0, None
    if obj.data is not None and obj.data.users > 1:
        obj.data = obj.data.copy()

    applied = 0
    for name in names:
        try:
            with context.temp_override(object=obj, active_object=obj,
                                       selected_editable_objects=[obj]):
                bpy.ops.object.modifier_apply(modifier=name)
            applied += 1
        except RuntimeError as e:
            print(f"IOPS modifiers: apply {name!r} on {obj.name!r} failed: {e}")
    return applied, None


# --- the grid click operator -----------------------------------------

class IOPS_OT_ModGridClick(bpy.types.Operator):
    """Modifier grid cell: add / apply / remove / toggle by type"""

    bl_idname = "iops.mod_grid_click"
    bl_label = "Modifier"
    bl_options = {"REGISTER", "UNDO"}

    mod_type: bpy.props.StringProperty(options={"SKIP_SAVE"})
    mode: bpy.props.EnumProperty(
        items=[
            ("ADD", "Add", "Add with smart defaults"),
            ("APPLY", "Apply", "Smart Apply all of this type"),
            ("REMOVE", "Remove", "Remove all of this type"),
            ("TOGGLE", "Toggle", "Toggle viewport visibility of this type"),
        ],
        default="ADD",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    @classmethod
    def description(cls, context, properties):
        name = properties.mod_type.title().replace("_", " ")
        return (f"{name}\n"
                "Click: add to selection (smart defaults / saved preset)\n"
                "Ctrl: apply all of this type (Smart Apply)\n"
                "Alt: remove all of this type\n"
                "Shift: toggle viewport visibility of this type")

    def invoke(self, context, event):
        if event.ctrl:
            self.mode = "APPLY"
        elif event.alt:
            self.mode = "REMOVE"
        elif event.shift:
            self.mode = "TOGGLE"
        else:
            self.mode = "ADD"
        return self.execute(context)

    def execute(self, context):
        objects = list(context.selected_objects)
        mt = self.mod_type

        if self.mode == "ADD":
            added = skipped = 0
            for obj in objects:
                if add_with_defaults(obj, mt) is not None:
                    added += 1
                else:
                    skipped += 1
            msg = f"{mt}: added on {added} object(s)"
            if skipped:
                msg += f", {skipped} incompatible skipped"
            self.report({"INFO"}, msg)

        elif self.mode == "APPLY":
            applied = 0
            skipped = {}
            for obj in objects:
                count, reason = smart_apply_object(context, obj, mod_type=mt)
                applied += count
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
            msg = f"{mt}: applied {applied} modifier(s)"
            for reason, n in skipped.items():
                msg += f", {n} object(s) skipped ({reason})"
            self.report({"INFO"}, msg)

        elif self.mode == "REMOVE":
            removed = 0
            for obj in objects:
                for md in [m for m in obj.modifiers if m.type == mt]:
                    obj.modifiers.remove(md)
                    removed += 1
            self.report({"INFO"}, f"{mt}: removed {removed} modifier(s)")

        elif self.mode == "TOGGLE":
            active = context.active_object
            src = active if active in objects else (objects[0] if objects else None)
            state = True
            if src is not None:
                mods = [m for m in src.modifiers if m.type == mt]
                if mods:
                    state = not mods[0].show_viewport
            toggled = 0
            for obj in objects:
                for md in obj.modifiers:
                    if md.type == mt:
                        md.show_viewport = state
                        toggled += 1
            self.report({"INFO"},
                        f"{mt}: viewport {'on' if state else 'off'} "
                        f"for {toggled} modifier(s)")

        return {"FINISHED"}
```

- [ ] **Step 2: Write the `operators/modifiers/__init__.py` stub**

```python
"""iOps Modifiers panel operators. Descriptor files register themselves
into iops_mod_registry.REGISTRY on import; tool operator files are added by later
tasks. `classes` is consumed by the addon root __init__."""

from . import iops_mod_registry

classes = (
    iops_mod_registry.IOPS_OT_ModGridClick,
)
```

- [ ] **Step 3: Verify import via blender-mcp**

Run through `mcp__blender__execute_blender_python` (no addon reload needed yet — the package isn't referenced by the root `__init__` until Task 12):

```python
import importlib, sys
sys.modules.pop("InteractionOps.operators.modifiers", None)
sys.modules.pop("InteractionOps.operators.modifiers.iops_mod_registry", None)
from InteractionOps.operators.modifiers import iops_mod_registry
assert iops_mod_registry.CURATED_TYPES[0] == "BEVEL"
assert iops_mod_registry.type_icon("BEVEL") == "MOD_BEVEL" or iops_mod_registry.type_icon("BEVEL") == "MODIFIER"
items = iops_mod_registry.all_mod_type_items()
assert any(i[0] == "MIRROR" for i in items)
print("registry OK")
```

Expected: `registry OK`. (Note: `presets` import inside `add_with_defaults` is deferred, so the missing presets module is fine until Task 3.)

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_registry.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): descriptor registry, batch core and grid-click operator"
```

---

### Task 2: 18 descriptor files

**Files:**
- Create: `operators/modifiers/iops_mod_bevel.py`, `iops_mod_boolean.py`, `iops_mod_mirror.py`, `iops_mod_array.py`, `iops_mod_solidify.py`, `iops_mod_subsurf.py`, `iops_mod_screw.py`, `iops_mod_weld.py`, `iops_mod_triangulate.py`, `iops_mod_decimate.py`, `iops_mod_remesh.py`, `iops_mod_wireframe.py`, `iops_mod_curve.py`, `iops_mod_lattice.py`, `iops_mod_simple_deform.py`, `iops_mod_displace.py`, `iops_mod_shrinkwrap.py`, `iops_mod_weighted_normal.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `ModDescriptor`, `register_descriptor` from Task 1.
- Produces: populated `iops_mod_registry.REGISTRY` in curated grid order.

- [ ] **Step 1: Write all 18 files**

`iops_mod_bevel.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="BEVEL", icon="MOD_BEVEL", group="GENERATE",
    defaults={
        "width": 0.02, "segments": 2,
        "limit_method": "ANGLE", "angle_limit": 0.5235988,  # 30 deg
        "use_clamp_overlap": True, "harden_normals": False,
    },
    scale_props=("width",),
    sort_weight=50,
    is_noop=lambda md: md.width == 0.0,
))
```

`iops_mod_boolean.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="BOOLEAN", icon="MOD_BOOLEAN", group="GENERATE",
    defaults={"solver": "EXACT"},
    object_fields=("object",),
    requires_target=True,
    sort_weight=50,
))
```

`iops_mod_mirror.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="MIRROR", icon="MOD_MIRROR", group="GENERATE",
    defaults={"use_axis": (True, False, False), "use_clip": True},
    object_fields=("mirror_object",),
    sort_weight=10,
))
```

`iops_mod_array.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="ARRAY", icon="MOD_ARRAY", group="GENERATE",
    defaults={
        "count": 2, "use_relative_offset": True,
        "relative_offset_displace": (1.0, 0.0, 0.0),
    },
    object_fields=("offset_object", "start_cap", "end_cap", "curve"),
    scale_props=("constant_offset_displace",),
    sort_weight=10,
    is_noop=lambda md: md.fit_type == "FIXED_COUNT" and md.count <= 1,
))
```

`iops_mod_solidify.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SOLIDIFY", icon="MOD_SOLIDIFY", group="GENERATE",
    defaults={"thickness": 0.02, "use_even_offset": True},
    scale_props=("thickness",),
    sort_weight=50,
    is_noop=lambda md: md.thickness == 0.0,
))
```

`iops_mod_subsurf.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SUBSURF", icon="MOD_SUBSURF", group="GENERATE",
    defaults={"levels": 2, "render_levels": 2},
    sort_weight=50,
    is_noop=lambda md: md.levels == 0 and md.render_levels == 0,
))
```

`iops_mod_screw.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SCREW", icon="MOD_SCREW", group="GENERATE",
    defaults={"axis": "Z", "steps": 16, "render_steps": 16},
    object_fields=("object",),
    scale_props=("screw_offset",),
    sort_weight=50,
))
```

`iops_mod_weld.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="WELD", icon="AUTOMERGE_OFF", group="GENERATE",
    defaults={"merge_threshold": 0.001},
    scale_props=("merge_threshold",),
    sort_weight=50,
))
```

`iops_mod_triangulate.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="TRIANGULATE", icon="MOD_TRIANGULATE", group="GENERATE",
    defaults={"keep_custom_normals": True, "min_vertices": 5},
    sort_weight=90,
))
```

`iops_mod_decimate.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="DECIMATE", icon="MOD_DECIM", group="GENERATE",
    defaults={"decimate_type": "COLLAPSE", "ratio": 0.5},
    sort_weight=50,
    is_noop=lambda md: md.decimate_type == "COLLAPSE" and md.ratio >= 1.0,
))
```

`iops_mod_remesh.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="REMESH", icon="MOD_REMESH", group="GENERATE",
    defaults={"mode": "VOXEL", "voxel_size": 0.05},
    scale_props=("voxel_size",),
    sort_weight=50,
))
```

`iops_mod_wireframe.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="WIREFRAME", icon="MOD_WIREFRAME", group="GENERATE",
    defaults={"thickness": 0.02, "use_replace": True},
    scale_props=("thickness",),
    sort_weight=50,
    is_noop=lambda md: md.thickness == 0.0,
))
```

`iops_mod_curve.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="CURVE", icon="MOD_CURVE", group="DEFORM",
    defaults={"deform_axis": "POS_X"},
    object_fields=("object",),
    requires_target=True,
    sort_weight=50,
))
```

`iops_mod_lattice.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="LATTICE", icon="MOD_LATTICE", group="DEFORM",
    defaults={},
    object_fields=("object",),
    requires_target=True,
    sort_weight=50,
))
```

`iops_mod_simple_deform.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SIMPLE_DEFORM", icon="MOD_SIMPLEDEFORM", group="DEFORM",
    defaults={"deform_method": "BEND", "angle": 0.7853982},  # 45 deg
    object_fields=("origin",),
    sort_weight=80,
    is_noop=lambda md: md.deform_method in {"BEND", "TWIST"} and md.angle == 0.0,
))
```

`iops_mod_displace.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="DISPLACE", icon="MOD_DISPLACE", group="DEFORM",
    defaults={"strength": 0.1, "direction": "NORMAL"},
    scale_props=("strength",),
    sort_weight=50,
    is_noop=lambda md: md.strength == 0.0,
))
```

`iops_mod_shrinkwrap.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SHRINKWRAP", icon="MOD_SHRINKWRAP", group="DEFORM",
    defaults={"wrap_method": "NEAREST_SURFACEPOINT"},
    object_fields=("target", "auxiliary_target"),
    requires_target=True,
    sort_weight=50,
))
```

`iops_mod_weighted_normal.py`:
```python
from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="WEIGHTED_NORMAL", icon="MOD_NORMALEDIT", group="UTILITY",
    defaults={"keep_sharp": True, "weight": 50},
    sort_weight=85,
))
```

- [ ] **Step 2: Import them in `operators/modifiers/__init__.py`**

Replace the file content with:

```python
"""iOps Modifiers panel operators. Descriptor files register themselves
into iops_mod_registry.REGISTRY on import; tool operator files are added by later
tasks. `classes` is consumed by the addon root __init__."""

from . import iops_mod_registry

# Descriptor files — import order defines grid order inside each group.
from . import (
    iops_mod_bevel, iops_mod_boolean, iops_mod_mirror, iops_mod_array, iops_mod_solidify,
    iops_mod_subsurf, iops_mod_screw, iops_mod_weld, iops_mod_triangulate, iops_mod_decimate,
    iops_mod_remesh, iops_mod_wireframe,
    iops_mod_curve, iops_mod_lattice, iops_mod_simple_deform, iops_mod_displace,
    iops_mod_shrinkwrap,
    iops_mod_weighted_normal,
)

classes = (
    iops_mod_registry.IOPS_OT_ModGridClick,
)
```

- [ ] **Step 3: Verify via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators import modifiers
from InteractionOps.operators.modifiers import iops_mod_registry
assert len(iops_mod_registry.REGISTRY) == 18, len(iops_mod_registry.REGISTRY)
assert set(iops_mod_registry.REGISTRY) == set(iops_mod_registry.CURATED_TYPES)
assert iops_mod_registry.REGISTRY["MIRROR"].object_fields == ("mirror_object",)
assert iops_mod_registry.REGISTRY["SHRINKWRAP"].requires_target
assert iops_mod_registry.REGISTRY["BEVEL"].is_noop is not None
groups = {d.group for d in iops_mod_registry.REGISTRY.values()}
assert groups == {"GENERATE", "DEFORM", "UTILITY"}
print("descriptors OK")
```

Expected: `descriptors OK`.

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/
git commit -m "feat(modifiers): descriptor files for the 18 curated modifier types"
```

---

### Task 3: Presets storage (`operators/modifiers/iops_mod_presets.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_presets.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Produces: `load_default(mod_type) -> dict|None`, `save_default(md) -> None`, `clear_default(mod_type) -> bool`, `snapshot(md) -> dict`.
- Consumed by: `iops_mod_registry.add_with_defaults` (Task 1 already calls `presets.load_default`), stack ops (Task 5).

- [ ] **Step 1: Write `operators/modifiers/iops_mod_presets.py`**

```python
"""Default-preset storage for the modifiers grid.

One optional 'default preset' per modifier type, stored as JSON next to
the other IOPS presets: <user scripts>/presets/IOPS/iops_mod_presets.json
Shape: {"BEVEL": {"width": 0.05, ...}, ...} — serializable props only.
"""

import bpy
import json
import os

_SKIP_PROPS = {
    "name", "type", "show_expanded", "is_active", "show_in_editmode",
    "show_viewport", "show_render", "show_on_cage", "use_pin_to_last",
    "is_override_data", "use_apply_on_spline", "execution_time",
    "persistent_uid",
}


def _presets_path():
    return os.path.join(bpy.utils.script_path_user(),
                        "presets", "IOPS", "iops_mod_presets.json")


def _read_all():
    path = _presets_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"IOPS modifiers: preset file unreadable ({e}), ignoring")
        return {}


def _write_all(data):
    path = _presets_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def snapshot(md):
    """Serializable, writable props of a modifier as a plain dict."""
    out = {}
    for p in md.bl_rna.properties:
        pid = p.identifier
        if p.is_readonly or pid in _SKIP_PROPS or p.type == "POINTER":
            continue
        value = getattr(md, pid)
        if p.type == "ENUM":
            value = sorted(value) if p.is_enum_flag else value
        elif p.type in {"FLOAT", "INT", "BOOLEAN"} and p.is_array:
            value = list(value)
        elif p.type not in {"FLOAT", "INT", "BOOLEAN", "STRING"}:
            continue
        out[pid] = value
    return out


def load_default(mod_type):
    return _read_all().get(mod_type)


def save_default(md):
    data = _read_all()
    data[md.type] = snapshot(md)
    _write_all(data)


def clear_default(mod_type):
    data = _read_all()
    if mod_type in data:
        del data[mod_type]
        _write_all(data)
        return True
    return False
```

- [ ] **Step 2: Add `from . import iops_mod_presets as presets` to `operators/modifiers/__init__.py`** (after `from . import iops_mod_registry`).

- [ ] **Step 3: Verify via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_presets as presets, iops_mod_registry
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
obj = bpy.data.objects.new("t", bpy.data.meshes.new("t"))
bpy.context.collection.objects.link(obj)
md = obj.modifiers.new("Bevel", "BEVEL")
md.width = 0.123
snap = presets.snapshot(md)
assert abs(snap["width"] - 0.123) < 1e-6
assert "name" not in snap and "type" not in snap
presets.save_default(md)
loaded = presets.load_default("BEVEL")
assert abs(loaded["width"] - 0.123) < 1e-6
# round-trip through add_with_defaults
obj2 = bpy.data.objects.new("t2", bpy.data.meshes.new("t2"))
bpy.context.collection.objects.link(obj2)
md2 = iops_mod_registry.add_with_defaults(obj2, "BEVEL")
assert abs(md2.width - 0.123) < 1e-6
assert presets.clear_default("BEVEL")
md3 = iops_mod_registry.add_with_defaults(obj2, "BEVEL")
assert abs(md3.width - 0.02) < 1e-6  # back to smart defaults
print("presets OK")
```

Expected: `presets OK`.

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_presets.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): JSON default-preset storage per modifier type"
```

---

### Task 4: Grid click behaviors verified end-to-end

**Files:**
- Test only — exercises `IOPS_OT_ModGridClick` from Task 1 via a script harness (operator classes aren't registered until Task 12, so call the core helpers directly plus one registered-operator pass at the end of Task 12).

- [ ] **Step 1: Verify ADD / APPLY / REMOVE cores via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_registry
import bpy
bpy.ops.wm.read_homefile(use_empty=True)

# three cubes: normal, multi-user, shape-keyed
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
b = bpy.context.active_object
c = bpy.data.objects.new("c", b.data)  # multi-user with b
bpy.context.collection.objects.link(c)
bpy.ops.mesh.primitive_cube_add(location=(6, 0, 0))
d = bpy.context.active_object
d.shape_key_add(name="Basis")

# ADD with smart defaults
for o in (a, b, c, d):
    md = iops_mod_registry.add_with_defaults(o, "BEVEL")
    assert md is not None and abs(md.width - 0.02) < 1e-6

# incompatible object -> None
empty = bpy.data.objects.new("e", None)
bpy.context.collection.objects.link(empty)
assert iops_mod_registry.add_with_defaults(empty, "BEVEL") is None

# Smart Apply: multi-user auto-copy, shape keys skipped
n, reason = iops_mod_registry.smart_apply_object(bpy.context, b, mod_type="BEVEL")
assert n == 1 and reason is None and b.data.users == 1
n, reason = iops_mod_registry.smart_apply_object(bpy.context, d, mod_type="BEVEL")
assert n == 0 and reason == "shape keys"

# disabled modifiers are not applied
a.modifiers[0].show_viewport = False
n, reason = iops_mod_registry.smart_apply_object(bpy.context, a, mod_type="BEVEL")
assert n == 0 and len(a.modifiers) == 1
print("grid core OK")
```

Expected: `grid core OK`.

- [ ] **Step 2: Commit (only if fixes were needed)**

```powershell
git add operators/modifiers/
git commit -m "fix(modifiers): grid-click core issues found by smoke tests"
```

---

### Task 5: Stack-list actions (`operators/modifiers/iops_mod_stack.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_stack.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `iops_mod_registry.smart_apply_object`, `presets.save_default`.
- Produces: `IOPS_OT_ModStackAction` (`iops.mod_stack_action`) with `index: IntProperty`, `action: EnumProperty` in {MOVE_UP, MOVE_DOWN, APPLY, APPLY_UP_TO, REMOVE, SAVE_PRESET}.

- [ ] **Step 1: Write `operators/modifiers/iops_mod_stack.py`**

```python
import bpy

from . import iops_mod_registry, iops_mod_presets as presets


class IOPS_OT_ModStackAction(bpy.types.Operator):
    """Row action in the active object's modifier stack list"""

    bl_idname = "iops.mod_stack_action"
    bl_label = "Modifier Stack Action"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(options={"SKIP_SAVE"})
    action: bpy.props.EnumProperty(
        items=[
            ("MOVE_UP", "Move Up", "Move modifier up"),
            ("MOVE_DOWN", "Move Down", "Move modifier down"),
            ("APPLY", "Apply", "Apply this modifier"),
            ("APPLY_UP_TO", "Apply Up To Here",
             "Apply the stack through this modifier on the whole "
             "selection, in stack order"),
            ("REMOVE", "Remove", "Remove this modifier"),
            ("SAVE_PRESET", "Save As Default Preset",
             "Use this modifier's settings when adding this type "
             "from the grid"),
        ],
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == "OBJECT" and context.active_object
                and context.active_object.modifiers)

    def execute(self, context):
        obj = context.active_object
        if self.index < 0 or self.index >= len(obj.modifiers):
            self.report({"WARNING"}, "Modifier index out of range")
            return {"CANCELLED"}
        md = obj.modifiers[self.index]

        if self.action == "MOVE_UP":
            obj.modifiers.move(self.index, max(0, self.index - 1))
        elif self.action == "MOVE_DOWN":
            obj.modifiers.move(self.index,
                               min(len(obj.modifiers) - 1, self.index + 1))
        elif self.action == "APPLY":
            name = md.name
            try:
                with context.temp_override(object=obj, active_object=obj,
                                           selected_editable_objects=[obj]):
                    bpy.ops.object.modifier_apply(modifier=name)
                self.report({"INFO"}, f"Applied {name}")
            except RuntimeError as e:
                self.report({"WARNING"}, f"Apply failed: {e}")
                return {"CANCELLED"}
        elif self.action == "APPLY_UP_TO":
            target = (md.type, md.name)
            applied = 0
            skipped = {}
            for o in context.selected_objects:
                count, reason = iops_mod_registry.smart_apply_object(context, o,
                                                        up_to=target)
                applied += count
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
            msg = f"Applied {applied} modifier(s) up to {md.name}"
            for reason, n in skipped.items():
                msg += f", {n} object(s) skipped ({reason})"
            self.report({"INFO"}, msg)
        elif self.action == "REMOVE":
            obj.modifiers.remove(md)
        elif self.action == "SAVE_PRESET":
            presets.save_default(md)
            self.report({"INFO"},
                        f"{md.type}: saved as default preset for the grid")
        return {"FINISHED"}
```

- [ ] **Step 2: Register in `operators/modifiers/__init__.py`**

Add `from . import iops_mod_stack` after the descriptor imports and extend:

```python
classes = (
    iops_mod_registry.IOPS_OT_ModGridClick,
    iops_mod_stack.IOPS_OT_ModStackAction,
)
```

- [ ] **Step 3: Verify APPLY_UP_TO core via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_registry
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
for t, n in (("MIRROR", "Mirror"), ("BEVEL", "Bevel"), ("SUBSURF", "Sub")):
    a.modifiers.new(n, t)
# up_to Bevel: Mirror + Bevel applied, Subsurf stays
n, reason = iops_mod_registry.smart_apply_object(bpy.context, a, up_to=("BEVEL", "Bevel"))
assert n == 2 and reason is None, (n, reason)
assert [m.type for m in a.modifiers] == ["SUBSURF"]
# object without a match: untouched
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
b = bpy.context.active_object
b.modifiers.new("Solid", "SOLIDIFY")
n, reason = iops_mod_registry.smart_apply_object(bpy.context, b, up_to=("BEVEL", "Bevel"))
assert n == 0 and reason == "no matching modifier"
assert len(b.modifiers) == 1
print("stack core OK")
```

Expected: `stack core OK`.

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_stack.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): stack-list row actions incl. selection-wide Apply Up To Here"
```

---

### Task 6: Sort (`operators/modifiers/iops_mod_sort.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_sort.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `iops_mod_registry.REGISTRY`.
- Produces: `IOPS_OT_ModSortStack` (`iops.mod_sort_stack`); helper `sort_weight(md) -> int` reused nowhere else but kept module-level for testing.

- [ ] **Step 1: Write `operators/modifiers/iops_mod_sort.py`**

```python
import bpy

from . import iops_mod_registry

# Geometry-nodes "Smooth by Angle" (Blender 4.1+ auto smooth) must stay
# at the very end of the stack or shading breaks.
_SMOOTH_BY_ANGLE = "smooth by angle"
_TAIL_NODES_WEIGHT = 95


def sort_weight(md):
    if md.type == "NODES":
        ng = getattr(md, "node_group", None)
        if ng is not None and _SMOOTH_BY_ANGLE in ng.name.lower():
            return _TAIL_NODES_WEIGHT
        return 50
    desc = iops_mod_registry.REGISTRY.get(md.type)
    return desc.sort_weight if desc else 50


class IOPS_OT_ModSortStack(bpy.types.Operator):
    """Sort modifier stacks across the selection: Mirror/Array first,
    Weighted Normal / Triangulate / Smooth by Angle last"""

    bl_idname = "iops.mod_sort_stack"
    bl_label = "Sort Modifier Stacks"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        changed = 0
        for obj in context.selected_objects:
            if len(obj.modifiers) < 2:
                continue
            # stable: equal weights keep their relative order
            desired = sorted(obj.modifiers,
                             key=lambda m: sort_weight(m))
            desired_names = [m.name for m in desired]
            if desired_names == [m.name for m in obj.modifiers]:
                continue
            for target_idx, name in enumerate(desired_names):
                current_idx = obj.modifiers.find(name)
                if current_idx != target_idx:
                    obj.modifiers.move(current_idx, target_idx)
            changed += 1
        self.report({"INFO"}, f"Sorted stacks on {changed} object(s)")
        return {"FINISHED"}
```

Note: `sorted()` is stable, so within a weight band the user's manual order survives.

- [ ] **Step 2: Register** — add `from . import iops_mod_sort` and `iops_mod_sort.IOPS_OT_ModSortStack` to `classes`.

- [ ] **Step 3: Verify via blender-mcp** (operator not registered yet — test the pure logic):

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_sort
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
a.modifiers.new("WN", "WEIGHTED_NORMAL")
a.modifiers.new("Tri", "TRIANGULATE")
a.modifiers.new("Bevel", "BEVEL")
a.modifiers.new("Mirror", "MIRROR")
weights = [iops_mod_sort.sort_weight(m) for m in a.modifiers]
assert weights == [85, 90, 50, 10], weights
order = [m.name for m in sorted(a.modifiers, key=iops_mod_sort.sort_weight)]
assert order == ["Mirror", "Bevel", "WN", "Tri"], order
print("sort OK")
```

Expected: `sort OK`.

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_sort.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): rule-based stack sort across the selection"
```

---

### Task 7: Cleanup (`operators/modifiers/iops_mod_cleanup.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_cleanup.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `iops_mod_registry.REGISTRY`, `iops_mod_registry.object_fields`.
- Produces: `IOPS_OT_ModCleanup` (`iops.mod_cleanup`); module-level `is_dead(md) -> str|None` (reason or None) for testing.

- [ ] **Step 1: Write `operators/modifiers/iops_mod_cleanup.py`**

```python
import bpy

from . import iops_mod_registry

# Types outside the curated registry whose first object field is required
_REQUIRED_FALLBACK = {"HOOK", "DATA_TRANSFER", "MESH_DEFORM",
                      "SURFACE_DEFORM", "MASK"}


def is_dead(md):
    """Reason string if the modifier does nothing, else None."""
    if not md.show_viewport and not md.show_render:
        return "disabled everywhere"
    desc = iops_mod_registry.REGISTRY.get(md.type)
    requires = (desc.requires_target if desc
                else md.type in _REQUIRED_FALLBACK)
    if requires:
        fields = iops_mod_registry.object_fields(md)
        if fields and getattr(md, fields[0], None) is None:
            return "missing target"
    if desc is not None and desc.is_noop is not None:
        try:
            if desc.is_noop(md):
                return "no-op settings"
        except AttributeError:
            pass
    return None


class IOPS_OT_ModCleanup(bpy.types.Operator):
    """Remove dead modifiers across the selection: missing required
    targets, disabled in both viewport and render, or no-op settings
    (Bevel width 0, Array count 1, Subsurf levels 0, ...)"""

    bl_idname = "iops.mod_cleanup"
    bl_label = "Cleanup Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        removed = 0
        touched = set()
        for obj in context.selected_objects:
            for md in list(obj.modifiers):
                if is_dead(md):
                    obj.modifiers.remove(md)
                    removed += 1
                    touched.add(obj.name)
        self.report({"INFO"},
                    f"Removed {removed} modifier(s) on {len(touched)} object(s)")
        return {"FINISHED"}
```

- [ ] **Step 2: Register** — add `from . import iops_mod_cleanup` and `iops_mod_cleanup.IOPS_OT_ModCleanup` to `classes`.

- [ ] **Step 3: Verify via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_cleanup
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
dead_bool = a.modifiers.new("B", "BOOLEAN")          # no object
noop_bevel = a.modifiers.new("Bv", "BEVEL"); noop_bevel.width = 0.0
off = a.modifiers.new("S", "SUBSURF")
off.show_viewport = False; off.show_render = False
alive = a.modifiers.new("Bv2", "BEVEL")              # default width > 0
assert iops_mod_cleanup.is_dead(dead_bool) == "missing target"
assert iops_mod_cleanup.is_dead(noop_bevel) == "no-op settings"
assert iops_mod_cleanup.is_dead(off) == "disabled everywhere"
assert iops_mod_cleanup.is_dead(alive) is None
print("cleanup OK")
```

Expected: `cleanup OK`.

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_cleanup.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): cleanup of dead and no-op modifiers across the selection"
```

---

### Task 8: Sync Vis + Select Users (`iops_mod_sync_vis.py`, `iops_mod_select_users.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_sync_vis.py`
- Create: `operators/modifiers/iops_mod_select_users.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `iops_mod_registry.object_fields`.
- Produces: `IOPS_OT_ModSyncVis` (`iops.mod_sync_vis`), `IOPS_OT_ModSelectTargetUsers` (`iops.mod_select_target_users`); module-level `find_users(view_layer_objects, target) -> list` for testing.

- [ ] **Step 1: Write `operators/modifiers/iops_mod_sync_vis.py`**

```python
import bpy


class IOPS_OT_ModSyncVis(bpy.types.Operator):
    """Set every modifier's render visibility to match its viewport
    visibility, across the selection"""

    bl_idname = "iops.mod_sync_vis"
    bl_label = "Sync Render Visibility"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        synced = 0
        for obj in context.selected_objects:
            for md in obj.modifiers:
                if md.show_render != md.show_viewport:
                    md.show_render = md.show_viewport
                    synced += 1
        self.report({"INFO"}, f"Synced {synced} modifier(s)")
        return {"FINISHED"}
```

- [ ] **Step 2: Write `operators/modifiers/iops_mod_select_users.py`**

```python
import bpy

from . import iops_mod_registry


def find_users(objects, target):
    """Objects whose modifiers reference `target`. Registry object-field
    fast path; identity comparison; no bpy.ops."""
    users = []
    for obj in objects:
        if obj is target:
            continue
        for md in obj.modifiers:
            hit = False
            for fname in iops_mod_registry.object_fields(md):
                if getattr(md, fname, None) is target:
                    hit = True
                    break
            if hit:
                users.append(obj)
                break
    return users


class IOPS_OT_ModSelectTargetUsers(bpy.types.Operator):
    """Select every object that uses the active object as a modifier
    target (Boolean object, Mirror object, Curve, Lattice, ...)"""

    bl_idname = "iops.mod_select_target_users"
    bl_label = "Select Modifier Users of Active"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object

    def execute(self, context):
        active = context.active_object
        users = find_users(context.view_layer.objects, active)
        for obj in users:
            obj.select_set(True)
        self.report({"INFO"},
                    f"{active.name}: selected {len(users)} user object(s)")
        return {"FINISHED"}
```

- [ ] **Step 3: Register both** — `from . import iops_mod_sync_vis, iops_mod_select_users`; extend `classes` with `iops_mod_sync_vis.IOPS_OT_ModSyncVis, iops_mod_select_users.IOPS_OT_ModSelectTargetUsers`.

- [ ] **Step 4: Verify via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_select_users
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
target = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
u1 = bpy.context.active_object
u1.modifiers.new("B", "BOOLEAN").object = target
bpy.ops.mesh.primitive_cube_add(location=(6, 0, 0))
u2 = bpy.context.active_object
u2.modifiers.new("M", "MIRROR").mirror_object = target
bpy.ops.mesh.primitive_cube_add(location=(9, 0, 0))
bystander = bpy.context.active_object
# unknown-to-registry type via RNA fallback
u2.modifiers.new("H", "HOOK").object = target
users = iops_mod_select_users.find_users(bpy.context.view_layer.objects, target)
assert set(o.name for o in users) == {u1.name, u2.name}, users
print("select users OK")
```

Expected: `select users OK`.

- [ ] **Step 5: Commit**

```powershell
git add operators/modifiers/iops_mod_sync_vis.py operators/modifiers/iops_mod_select_users.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): render-vis sync and reverse target-user selection"
```

---

### Task 9: Cursor → Target (`operators/modifiers/iops_mod_cursor_target.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_cursor_target.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `iops_mod_registry.object_fields`.
- Produces: `IOPS_OT_ModCursorTarget` (`iops.mod_cursor_target`).

- [ ] **Step 1: Write the operator**

```python
import bpy

from . import iops_mod_registry


class IOPS_OT_ModCursorTarget(bpy.types.Operator):
    """Create an empty at the 3D cursor (location AND rotation) and
    assign it as target: to the active object's active modifier, and to
    same-type modifiers with an empty target across the selection"""

    bl_idname = "iops.mod_cursor_target"
    bl_label = "Cursor to Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (context.mode == "OBJECT" and obj is not None
                and obj.modifiers.active is not None
                and iops_mod_registry.object_fields(obj.modifiers.active))

    def execute(self, context):
        active = context.active_object
        md = active.modifiers.active
        field = iops_mod_registry.object_fields(md)[0]

        empty = bpy.data.objects.new(f"iops_target_{md.type.lower()}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        context.collection.objects.link(empty)
        empty.matrix_world = context.scene.cursor.matrix

        assigned = 0
        setattr(md, field, empty)
        assigned += 1
        for obj in context.selected_objects:
            for other in obj.modifiers:
                if other is md or other.type != md.type:
                    continue
                if getattr(other, field, None) is None:
                    setattr(other, field, empty)
                    assigned += 1
        self.report({"INFO"},
                    f"{empty.name}: assigned to {assigned} modifier(s)")
        return {"FINISHED"}
```

- [ ] **Step 2: Register** — `from . import iops_mod_cursor_target`; add `iops_mod_cursor_target.IOPS_OT_ModCursorTarget` to `classes`.

- [ ] **Step 3: Verify via blender-mcp** (logic-level, operator registration comes in Task 12):

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
from InteractionOps.operators.modifiers import iops_mod_registry
import bpy, math
from mathutils import Euler
bpy.ops.wm.read_homefile(use_empty=True)
cur = bpy.context.scene.cursor
cur.location = (1, 2, 3)
cur.rotation_euler = Euler((0.3, 0.4, 0.5))
# poll preconditions: active modifier with an object field
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
md = a.modifiers.new("M", "MIRROR")
a.modifiers.active = md
assert iops_mod_registry.object_fields(md) == ("mirror_object",)
# cursor matrix carries rotation+location
m = cur.matrix
assert all(abs(m.translation[i] - (1, 2, 3)[i]) < 1e-6 for i in range(3))
print("cursor target preconditions OK")
```

Expected: `cursor target preconditions OK`. (Full operator run happens in Task 12's registered pass.)

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_cursor_target.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): cursor-placed empty as modifier target across selection"
```

---

### Task 10: Safe Apply Transform (`operators/modifiers/iops_mod_safe_apply.py`)

**Files:**
- Create: `operators/modifiers/iops_mod_safe_apply.py`
- Modify: `operators/modifiers/__init__.py`

**Interfaces:**
- Consumes: `iops_mod_registry.REGISTRY`, `iops_mod_registry.object_fields`, `iops_mod_select_users.find_users`.
- Produces: `IOPS_OT_ModSafeApplyTransform` (`iops.mod_safe_apply_transform`) with `location/rotation/scale` BoolProperties (all default True).

**Mechanics** (from spec, made concrete):

- *Scenario A — the object is a target of other objects' modifiers.* Modifiers that use the target's world matrix directly (`MIRROR`, `ARRAY`, `SIMPLE_DEFORM`, `SCREW`, `CAST`) would shift when the target's matrix collapses to identity. Fix: before applying, create a pivot empty at the object's current world matrix, swap those modifier fields to the empty, apply, then parent the empty to the object with `matrix_parent_inverse` so it keeps following. Modifiers that consume the target's evaluated world-space geometry (`BOOLEAN`, `SHRINKWRAP`, `DATA_TRANSFER`) need nothing — applied transform keeps world geometry identical. `CURVE` and `LATTICE` targets deform through their own data space; skip the object with a report.
- *Scenario B — the object carries modifiers with local-distance parameters.* Applying scale re-scales the mesh data, so `scale_props` (Bevel width, Solidify thickness, ...) must be multiplied by the applied scale to keep world-space size. Non-uniform scale uses the mean factor with a warning.
- Empties can't apply transforms — skipped with a report. Multi-user data gets `data.copy()` first.

- [ ] **Step 1: Write the operator**

```python
import bpy

from . import iops_mod_registry
from .iops_mod_select_users import find_users

# Targets whose world matrix feeds the modifier directly
_MATRIX_TARGET_TYPES = {"MIRROR", "ARRAY", "SIMPLE_DEFORM", "SCREW", "CAST"}
# Targets that deform through their own data space — can't compensate
_DATA_SPACE_TYPES = {"CURVE", "LATTICE", "MESH_DEFORM", "SURFACE_DEFORM"}


class IOPS_OT_ModSafeApplyTransform(bpy.types.Operator):
    """Apply object transform without breaking modifiers: pivots
    matrix-based targets through a compensating empty and rescales
    distance-based modifier settings (Bevel width, Solidify thickness...)"""

    bl_idname = "iops.mod_safe_apply_transform"
    bl_label = "Safe Apply Transform"
    bl_options = {"REGISTER", "UNDO"}

    location: bpy.props.BoolProperty(name="Location", default=True)
    rotation: bpy.props.BoolProperty(name="Rotation", default=True)
    scale: bpy.props.BoolProperty(name="Scale", default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        applied = 0
        skipped = {}
        warnings = []
        all_objects = list(context.view_layer.objects)

        for obj in context.selected_objects:
            if obj.type == "EMPTY":
                skipped["empty (no data)"] = skipped.get("empty (no data)", 0) + 1
                continue

            # --- scenario A: who references me, and how badly ---
            matrix_refs = []   # (modifier, field) pairs to re-pivot
            blocked = False
            for user in find_users(all_objects, obj):
                for md in user.modifiers:
                    for fname in iops_mod_registry.object_fields(md):
                        if getattr(md, fname, None) is not obj:
                            continue
                        if md.type in _DATA_SPACE_TYPES:
                            blocked = True
                        elif md.type in _MATRIX_TARGET_TYPES:
                            matrix_refs.append((md, fname))
            if blocked:
                skipped["data-space deform target (Curve/Lattice)"] = \
                    skipped.get("data-space deform target (Curve/Lattice)", 0) + 1
                continue

            matrix_before = obj.matrix_world.copy()
            pivot = None
            if matrix_refs:
                pivot = bpy.data.objects.new(f"iops_pivot_{obj.name}", None)
                pivot.empty_display_type = "PLAIN_AXES"
                pivot.empty_display_size = 0.5
                context.collection.objects.link(pivot)
                pivot.matrix_world = matrix_before
                for md, fname in matrix_refs:
                    setattr(md, fname, pivot)

            # --- apply ---
            if obj.data is not None and obj.data.users > 1:
                obj.data = obj.data.copy()
            try:
                with context.temp_override(
                        active_object=obj,
                        selected_editable_objects=[obj]):
                    bpy.ops.object.transform_apply(
                        location=self.location,
                        rotation=self.rotation,
                        scale=self.scale)
            except RuntimeError as e:
                skipped[str(e)] = skipped.get(str(e), 0) + 1
                if pivot is not None:
                    for md, fname in matrix_refs:
                        setattr(md, fname, obj)
                    bpy.data.objects.remove(pivot)
                continue

            if pivot is not None:
                pivot.parent = obj
                pivot.matrix_parent_inverse = obj.matrix_world.inverted()
                pivot.matrix_world = matrix_before

            # --- scenario B: rescale distance-based settings ---
            if self.scale:
                s = matrix_before.to_scale()
                if any(abs(c - 1.0) > 1e-6 for c in s):
                    factor = (s.x + s.y + s.z) / 3.0
                    if max(s) - min(s) > 1e-4:
                        warnings.append(
                            f"{obj.name}: non-uniform scale, distance "
                            f"settings rescaled by mean {factor:.3f}")
                    for md in obj.modifiers:
                        desc = iops_mod_registry.REGISTRY.get(md.type)
                        if desc is None:
                            continue
                        for pname in desc.scale_props:
                            try:
                                value = getattr(md, pname)
                                if hasattr(value, "__len__"):
                                    setattr(md, pname,
                                            [v * c for v, c in zip(value, s)])
                                else:
                                    setattr(md, pname, value * factor)
                            except AttributeError:
                                pass
            applied += 1

        msg = f"Safe-applied transform on {applied} object(s)"
        for reason, n in skipped.items():
            msg += f"; {n} skipped ({reason})"
        level = "WARNING" if (skipped or warnings) else "INFO"
        for w in warnings:
            print("IOPS Safe Apply:", w)
        self.report({level}, msg)
        return {"FINISHED"}
```

- [ ] **Step 2: Register** — `from . import iops_mod_safe_apply`; add `iops_mod_safe_apply.IOPS_OT_ModSafeApplyTransform` to `classes`.

- [ ] **Step 3: Verify the pivot math via blender-mcp**

```python
import sys
for k in [k for k in sys.modules if "InteractionOps.operators.modifiers" in k]:
    sys.modules.pop(k)
import bpy, math
from mathutils import Vector
bpy.ops.wm.read_homefile(use_empty=True)
# mirror-target scenario: cube mirrored across a moved/rotated target cube
bpy.ops.mesh.primitive_cube_add(location=(2, 0, 0))
target = bpy.context.active_object
target.rotation_euler = (0, 0, math.radians(30))
target.scale = (2, 2, 2)
bpy.ops.mesh.primitive_cube_add(location=(5, 1, 0))
user = bpy.context.active_object
user.modifiers.new("M", "MIRROR").mirror_object = target
deg = bpy.context.evaluated_depsgraph_get()
before = [tuple(round(c, 4) for c in (user.matrix_world @ v.co))
          for v in user.evaluated_get(deg).data.vertices]
# emulate the operator's pivot trick manually
pivot = bpy.data.objects.new("pivot", None)
bpy.context.collection.objects.link(pivot)
pivot.matrix_world = target.matrix_world.copy()
user.modifiers["M"].mirror_object = pivot
with bpy.context.temp_override(active_object=target,
                               selected_editable_objects=[target]):
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
deg = bpy.context.evaluated_depsgraph_get()
after = [tuple(round(c, 4) for c in (user.matrix_world @ v.co))
         for v in user.evaluated_get(deg).data.vertices]
assert before == after, "mirror result moved!"
print("safe apply pivot OK")
```

Expected: `safe apply pivot OK`.

- [ ] **Step 4: Commit**

```powershell
git add operators/modifiers/iops_mod_safe_apply.py operators/modifiers/__init__.py
git commit -m "feat(modifiers): safe apply transform with pivot compensation and setting rescale"
```

---

### Task 11: Preferences (`prefs/addon_preferences.py`)

**Files:**
- Modify: `prefs/addon_preferences.py` (props near `modifier_window_method` ~line 613; draw section in the PREFS tab near the "Modifier Window" section ~line 941)

**Interfaces:**
- Consumes: `CURATED_TYPES`, `all_mod_type_items` from `operators.modifiers.iops_mod_registry` (safe import: registry only imports bpy).
- Produces: `modifiers_grid_columns: IntProperty(default=6)`, `modifiers_show_stack: BoolProperty(default=True)`, per-type `mod_grid_show_<type_lower>: BoolProperty` (default True for curated types), `show_section_modifiers_panel: BoolProperty`. Helper `enabled_grid_types(prefs) -> list[str]` lives in `operators/modifiers/iops_mod_registry.py`.

- [ ] **Step 1: Add props to `IOPS_AddonPreferences`**

Inside the class, next to `modifier_window_method`:

```python
    # iOps Modifiers panel (grid)
    modifiers_grid_columns: IntProperty(
        name="Grid Columns",
        description="Number of icon columns in the iOps Modifiers panel",
        default=6, min=2, max=12,
    )
    modifiers_show_stack: BoolProperty(
        name="Show Stack List",
        description="Show the active object's modifier stack under the grid",
        default=True,
    )
    show_section_modifiers_panel: BoolProperty(default=False)
```

(Match how the other `show_section_*` toggles are declared in this file — follow the existing pattern exactly.)

After the class definition (module level), generate the per-type toggles:

```python
# Per-modifier-type visibility toggles for the iOps Modifiers panel grid.
# Generated for every modifier type Blender knows; curated set on by default.
from ..operators.modifiers.iops_mod_registry import CURATED_TYPES as _MOD_CURATED

def _register_mod_grid_toggles():
    import bpy as _bpy
    enum = _bpy.types.Modifier.bl_rna.properties["type"].enum_items
    for it in enum:
        IOPS_AddonPreferences.__annotations__[
            f"mod_grid_show_{it.identifier.lower()}"
        ] = BoolProperty(name=it.name, default=it.identifier in _MOD_CURATED)

_register_mod_grid_toggles()
```

- [ ] **Step 2: Add `enabled_grid_types` helper to `operators/modifiers/iops_mod_registry.py`**

```python
def enabled_grid_types(prefs):
    """Modifier types enabled in the grid: registry order first, then any
    extra types the user switched on, in RNA order."""
    enabled = []
    for mod_type in REGISTRY:
        if getattr(prefs, f"mod_grid_show_{mod_type.lower()}", False):
            enabled.append(mod_type)
    for ident, _name, _icon in all_mod_type_items():
        if ident in REGISTRY:
            continue
        if getattr(prefs, f"mod_grid_show_{ident.lower()}", False):
            enabled.append(ident)
    return enabled
```

- [ ] **Step 3: Add the prefs UI section** in the PREFS tab draw, after the "Modifier Window" section:

```python
            # iOps Modifiers panel
            body = _section(column_main, self, "show_section_modifiers_panel",
                            "Modifiers Panel", icon="MODIFIER")
            if body is not None:
                row = body.row(align=True)
                row.prop(self, "modifiers_grid_columns")
                row.prop(self, "modifiers_show_stack", toggle=True)
                body.separator()
                body.label(text="Modifier types shown in the grid:")
                import bpy as _bpy
                enum = _bpy.types.Modifier.bl_rna.properties["type"].enum_items
                grid = body.grid_flow(columns=4, align=True)
                for it in enum:
                    grid.prop(self, f"mod_grid_show_{it.identifier.lower()}",
                              toggle=True)
```

- [ ] **Step 4: Verify via blender-mcp** (full addon reload — prefs class changed):

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
assert prefs.modifiers_grid_columns == 6
assert prefs.modifiers_show_stack
assert prefs.mod_grid_show_bevel
assert not prefs.mod_grid_show_cloth  # not curated -> off by default
from InteractionOps.operators.modifiers.iops_mod_registry import enabled_grid_types
types = enabled_grid_types(prefs)
assert len(types) == 18 and types[0] == "BEVEL", types
print("prefs OK")
```

Expected: `prefs OK`. NOTE: this requires Task 12's root-`__init__` wiring for the addon to import the modifiers package on enable — if running Task 11 standalone, defer this verification to Task 12 and only confirm the addon still enables cleanly.

- [ ] **Step 5: Commit**

```powershell
git add prefs/addon_preferences.py operators/modifiers/iops_mod_registry.py
git commit -m "feat(modifiers): grid prefs — columns, stack toggle, per-type visibility"
```

---

### Task 12: Panel + registration (`ui/iops_modifiers_panel.py`, root `__init__.py`)

**Files:**
- Create: `ui/iops_modifiers_panel.py`
- Modify: `__init__.py` (imports near line 116 where other ui panels import; `classes` tuple near line 480)

**Interfaces:**
- Consumes: `enabled_grid_types`, `REGISTRY`, `GROUP_ORDER`, `type_icon` from `operators.modifiers.iops_mod_registry`; `classes` from `operators.modifiers`.
- Produces: `IOPS_PT_Modifiers_Panel` registered; all `iops.mod_*` operators registered.

- [ ] **Step 1: Write `ui/iops_modifiers_panel.py`**

```python
"""iOps Modifiers micro-panel.

Grid of modifier-type icons (grouped Generate/Deform/Utility) that add /
apply / remove / toggle modifiers across the selection, a tools row, and
a compact stack list for the active object. Draw-only: all logic lives in
operators/modifiers/. Per the perf rules, draw() only ever inspects the
active object's modifiers — never the selection or the scene.
"""

import bpy

from ..operators.modifiers.iops_mod_registry import (
    GROUP_ORDER,
    REGISTRY,
    enabled_grid_types,
    type_icon,
)

_GROUP_LABELS = {
    "GENERATE": "Generate",
    "DEFORM": "Deform",
    "UTILITY": "Utility",
}


class IOPS_PT_Modifiers_Panel(bpy.types.Panel):
    """Modifier grid + tools + active stack"""

    bl_label = "IOPS Modifiers"
    bl_idname = "IOPS_PT_Modifiers_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons["InteractionOps"].preferences
        active = context.active_object
        active_types = {md.type for md in active.modifiers} if active else set()

        enabled = enabled_grid_types(prefs)
        columns = prefs.modifiers_grid_columns

        # --- icon grid, grouped ---
        col = layout.column(align=True)
        extras = [t for t in enabled if t not in REGISTRY]
        for group in GROUP_ORDER:
            group_types = [t for t in enabled
                           if t in REGISTRY and REGISTRY[t].group == group]
            if not group_types:
                continue
            col.label(text=_GROUP_LABELS[group])
            grid = col.grid_flow(columns=columns, even_columns=True,
                                 align=True)
            for mod_type in group_types:
                op = grid.operator("iops.mod_grid_click", text="",
                                   icon=type_icon(mod_type),
                                   depress=mod_type in active_types)
                op.mod_type = mod_type
            col.separator(factor=0.5)
        if extras:
            col.label(text="Other")
            grid = col.grid_flow(columns=columns, even_columns=True,
                                 align=True)
            for mod_type in extras:
                op = grid.operator("iops.mod_grid_click", text="",
                                   icon=type_icon(mod_type),
                                   depress=mod_type in active_types)
                op.mod_type = mod_type

        # --- tools ---
        layout.separator(factor=0.5)
        tools = layout.column(align=True)
        row = tools.row(align=True)
        row.operator("iops.mod_sort_stack", text="Sort", icon="SORTSIZE")
        row.operator("iops.mod_cleanup", text="Cleanup", icon="BRUSH_DATA")
        row.operator("iops.mod_sync_vis", text="Sync Vis",
                     icon="RESTRICT_RENDER_OFF")
        row = tools.row(align=True)
        row.operator("iops.mod_cursor_target", text="Cursor Target",
                     icon="PIVOT_CURSOR")
        row.operator("iops.mod_select_target_users", text="Users",
                     icon="RESTRICT_SELECT_OFF")
        row.operator("iops.mod_safe_apply_transform", text="Safe Apply",
                     icon="CHECKMARK")

        # --- active object stack list ---
        if not prefs.modifiers_show_stack or active is None:
            return
        if not active.modifiers:
            return
        layout.separator(factor=0.5)
        box = layout.column(align=True)
        for i, md in enumerate(active.modifiers):
            row = box.row(align=True)
            row.label(text="", icon=type_icon(md.type))
            row.prop(md, "name", text="")
            row.prop(md, "show_viewport", text="", emboss=False)
            sub = row.row(align=True)
            sub.alert = md.show_render != md.show_viewport
            sub.prop(md, "show_render", text="", emboss=False)
            for action, icon in (
                ("MOVE_UP", "TRIA_UP"),
                ("MOVE_DOWN", "TRIA_DOWN"),
                ("APPLY", "CHECKMARK"),
                ("APPLY_UP_TO", "IMPORT"),
                ("REMOVE", "X"),
                ("SAVE_PRESET", "FILE_TICK"),
            ):
                op = row.operator("iops.mod_stack_action", text="",
                                  icon=icon, emboss=False)
                op.index = i
                op.action = action
```

- [ ] **Step 2: Wire into root `__init__.py`**

Near the other ui imports (after `from .ui.iops_mod_window import IOPS_OT_Modifier_Window`):

```python
from .ui.iops_modifiers_panel import IOPS_PT_Modifiers_Panel
from .operators.modifiers import classes as _modifiers_classes
```

In the `classes` tuple, right after `IOPS_OT_Modifier_Window,`:

```python
    *_modifiers_classes,
    IOPS_PT_Modifiers_Panel,
```

- [ ] **Step 3: Full registered verification via blender-mcp**

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
bpy.ops.wm.read_homefile(use_empty=True)

ops = ["mod_grid_click", "mod_stack_action", "mod_sort_stack",
       "mod_cleanup", "mod_sync_vis", "mod_cursor_target",
       "mod_select_target_users", "mod_safe_apply_transform"]
for name in ops:
    assert hasattr(bpy.ops.iops, name), name
assert hasattr(bpy.types, "IOPS_PT_Modifiers_Panel")

# registered operator end-to-end: add bevel to a 2-object selection
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
b = bpy.context.active_object
a.select_set(True)
bpy.ops.iops.mod_grid_click(mod_type="BEVEL", mode="ADD")
assert [m.type for m in a.modifiers] == ["BEVEL"]
assert [m.type for m in b.modifiers] == ["BEVEL"]
bpy.ops.iops.mod_grid_click(mod_type="BEVEL", mode="TOGGLE")
assert not a.modifiers[0].show_viewport and not b.modifiers[0].show_viewport
bpy.ops.iops.mod_grid_click(mod_type="BEVEL", mode="REMOVE")
assert not a.modifiers and not b.modifiers

# cursor target end-to-end
md = a.modifiers.new("M", "MIRROR")
a.modifiers.active = md
bpy.context.scene.cursor.location = (1, 2, 3)
bpy.ops.iops.mod_cursor_target()
assert md.mirror_object is not None
assert tuple(round(c, 4) for c in md.mirror_object.matrix_world.translation) == (1.0, 2.0, 3.0)
print("panel + registration OK")
```

Expected: `panel + registration OK`. Also re-run the Task 11 prefs verification now.

- [ ] **Step 4: Visual check** — screenshot via blender-mcp if available, or ask the user to eyeball the panel (grid grouping, depress state, stack row alert). Confirm no console errors on redraw.

- [ ] **Step 5: Commit**

```powershell
git add ui/iops_modifiers_panel.py __init__.py
git commit -m "feat(modifiers): iOps Modifiers micro-panel — grid, tools row, stack list"
```

---

### Task 13: End-to-end smoke + regression sweep

**Files:** none (verification only; fixes get their own focused commits).

- [ ] **Step 1: Full-feature scene via blender-mcp**

```python
import bpy, math
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
bpy.ops.wm.read_homefile(use_empty=True)

# scene: 3 cubes (one multi-user pair, one shape-keyed) + curve target
bpy.ops.mesh.primitive_cube_add()
a = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
b = bpy.context.active_object
c = bpy.data.objects.new("c_link", b.data)
bpy.context.collection.objects.link(c)
bpy.ops.mesh.primitive_cube_add(location=(6, 0, 0))
d = bpy.context.active_object
d.shape_key_add(name="Basis")
for o in (a, b, c, d):
    o.select_set(True)
bpy.context.view_layer.objects.active = a

# grid add + smart apply across the messy selection
bpy.ops.iops.mod_grid_click(mod_type="BEVEL", mode="ADD")
bpy.ops.iops.mod_grid_click(mod_type="BEVEL", mode="APPLY")
assert not a.modifiers and not b.modifiers
assert len(d.modifiers) == 1  # shape keys -> skipped, not crashed

# sort + cleanup on a dirty stack
a.modifiers.new("WN", "WEIGHTED_NORMAL")
a.modifiers.new("Dead", "BOOLEAN")
a.modifiers.new("Mirror", "MIRROR")
bpy.ops.iops.mod_sort_stack()
assert [m.type for m in a.modifiers] == ["MIRROR", "BOOLEAN", "WEIGHTED_NORMAL"]
bpy.ops.iops.mod_cleanup()
assert [m.type for m in a.modifiers] == ["MIRROR", "WEIGHTED_NORMAL"]

# sync vis
a.modifiers[0].show_render = False
bpy.ops.iops.mod_sync_vis()
assert a.modifiers[0].show_render

# select users
bpy.ops.object.select_all(action="DESELECT")
b.modifiers.new("B", "BOOLEAN").object = a
bpy.context.view_layer.objects.active = a
a.select_set(True)
bpy.ops.iops.mod_select_target_users()
assert b.select_set(True) is None and b.select_get()

# safe apply transform: scaled carrier keeps bevel world-size
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.mesh.primitive_cube_add(location=(9, 0, 0))
e = bpy.context.active_object
e.scale = (2, 2, 2)
bv = e.modifiers.new("Bv", "BEVEL")
bv.width = 0.1
bpy.ops.iops.mod_safe_apply_transform()
assert abs(e.scale.x - 1.0) < 1e-6
assert abs(bv.width - 0.2) < 1e-6, bv.width
print("E2E OK")
```

Expected: `E2E OK`.

- [ ] **Step 2: Addon disable/enable cycle twice** — confirm clean unregister (no console tracebacks), since dynamic prefs annotations and the new package are involved.

- [ ] **Step 3: Regression check** — open the addon prefs PREFS tab via a screenshot or ask the user; confirm the new "Modifiers Panel" section renders and existing sections are intact.

- [ ] **Step 4: Final commit if fixes landed; otherwise nothing to commit.**

---

## Self-review notes

- Spec coverage: grid+groups+depress (T2/T12), click modes incl. Smart Apply (T1/T4), tools row — sort (T6), cleanup (T7), sync vis + select users (T8), cursor target (T9), safe apply (T10), stack list + apply-up-to + presets (T3/T5/T12), prefs 6-col default + per-type toggles + stack toggle (T11), perf rules (constraints + T12 draw), error summaries (T1/T5/T7/T10).
- Deliberate deviations from spec wording: none.
- Known risk spots called out to implementers: `temp_override` context keys for `modifier_apply`/`transform_apply` differ between Blender versions — if a call fails with "context is incorrect", add `object=obj` / `selected_objects=[obj]` keys and retest; dynamic `__annotations__` on prefs must run before class registration (module import time — it does).
