# Object Radial Array Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modal operator `iops.object_radial_array` that radially distributes copies (linked instances or full duplicates) of selected object hierarchies around a pivot, with live GPU preview and arc/full-circle modes including arc-from-active-to-selected.

**Architecture:** A single modal operator file modeled after [operators/mesh_straight_bevel.py](../../../operators/mesh_straight_bevel.py) (HUD + GPU preview) and [operators/easy_mod_array.py](../../../operators/easy_mod_array.py) (HUD/Help, key handling). State lives on the operator instance; geometry math + transform computation in pure helpers within the same file; preview drawn via `ui.draw` Role-based primitives (no real objects until apply); commit step materializes clones.

**Tech Stack:** Blender Python (`bpy`, `mathutils`, `gpu`, `gpu_extras.batch`), existing addon modules: `ui.draw` (`edges_3d`, `points`, `lines_3d`), `ui.draw.theme` (`Role`, `get_theme`), `ui.hud` (`HUDOverlay`, `HelpOverlay`, `HUDSection`, `HUDItem`, `HUDParam`).

**Spec:** [docs/superpowers/specs/2026-05-26-object-radial-array-design.md](../specs/2026-05-26-object-radial-array-design.md)

**Testing note:** This is a Blender addon. There is no pytest suite — verification at each checkpoint uses the `blender-mcp` skill to load the addon in a running Blender, run the operator on a known scene, and inspect resulting state via `bpy`. Each task ends with an MCP-driven smoke check, then a commit.

---

## File Structure

- Create: `operators/object_radial_array.py` — the operator, helpers, draw callbacks, HUD/Help builders, all in one file (~500 LOC). Mirrors the convention used by `easy_mod_array.py` and `mesh_straight_bevel.py`.
- Modify: `__init__.py` — import + register `IOPS_OT_Object_Radial_Array` in the addon's classes list.

No new theme keys. The spec mentions axis/guide/pivot colors; the existing theme already provides:
- `Role.PIVOT` — pivot marker.
- `Role.PREVIEW_LINE` — ghost wires + axis + circle/arc outline.
- `Role.ACTIVE_LINE` — arc-fill highlight stroke.
- `Role.BBOX` — fallback for non-mesh children (small bbox).

---

### Task 1: Scaffold the operator + minimal modal loop

**Files:**
- Create: `operators/object_radial_array.py`
- Modify: `__init__.py` (import + classes list)

- [ ] **Step 1: Create the operator file with a minimal modal that opens HUD/Help and exits cleanly**

Write `operators/object_radial_array.py`:

```python
import bpy
from mathutils import Vector, Matrix, Quaternion

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState,
    handle_hud_toggle, handle_help_toggle, capture_event,
)


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context):
    hud = HUDOverlay("object_radial_array")
    hud.title = "Radial Array"
    hud.bind_region(context.region)
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_radial_array")
    helpo.add_section(HUDSection("Radial Array", [
        HUDItem("Pivot mode",     "P",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type",     "I",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Arc mode",       "A",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Axis X/Y/Z",     "X / Y / Z",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Local axis",     "L",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("View axis",      "V",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Normal pick",    "N + LMB",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Face outward",   "R",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Skip first",     "O",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("End inclusive",  "E",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Count +/-",      "+ / -  or  Wheel",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Angle drag",     "G + mouse",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Start offset",   "S + digits",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",          "LMB / Enter / Space",ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel",         "Esc / RMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD",     "H",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


def _draw_callback(op, context):
    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


# --- Operator -------------------------------------------------------------

class IOPS_OT_Object_Radial_Array(bpy.types.Operator):
    """Radially array selected object hierarchies around a pivot"""

    bl_idname = "iops.object_radial_array"
    bl_label = "OBJECT: Radial Array"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        active = context.active_object
        if not sel or active is None:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        self._hud = _build_hud(context)
        self._help = _build_help(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov is None:
                    continue
                if ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value != "PRESS":
            return {"PASS_THROUGH"}

        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._cleanup()
            return {"FINISHED"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _cleanup(self):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
```

- [ ] **Step 2: Register the operator**

Modify `__init__.py`:

After the existing `from .operators.easy_mod_array import (...)` block, add:

```python
from .operators.object_radial_array import IOPS_OT_Object_Radial_Array
```

In the `classes` tuple/list (around line 381–387, near `IOPS_OT_Easy_Mod_Array_Caps`), add:

```python
    IOPS_OT_Object_Radial_Array,
```

- [ ] **Step 3: Reload addon in Blender and smoke-test the modal**

Using the `blender-mcp` skill:

```python
# 1. Reload addon
import bpy
import importlib, sys
mod = sys.modules.get("InteractionOps")
if mod:
    bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")

# 2. Set up a scene
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(location=(2, 0, 0))
cube = bpy.context.active_object
bpy.ops.object.empty_add(location=(0, 0, 0))
empty = bpy.context.active_object
empty.select_set(True); cube.select_set(True)
bpy.context.view_layer.objects.active = empty

# 3. Check poll
assert bpy.ops.iops.object_radial_array.poll() is True, "operator should poll True"
```

Expected: no exceptions, `poll()` returns True. Operator does not crash on invoke (test by `bpy.ops.iops.object_radial_array('INVOKE_DEFAULT')` then sending `ESC` is not easily scriptable — accept poll + import success here).

- [ ] **Step 4: Commit**

```bash
git add operators/object_radial_array.py __init__.py
git commit -m "feat(object_radial_array): scaffold modal operator with HUD/Help"
```

---

### Task 2: State model, selection resolution, hierarchy capture

**Files:**
- Modify: `operators/object_radial_array.py`

- [ ] **Step 1: Add state enums, defaults, and selection-resolution helper**

Insert after the `_draw_callback` function and before the `class` definition:

```python
# --- State enums (string constants — Blender modal idiom) ----------------

PIVOT_ACTIVE       = "ACTIVE"
PIVOT_CURSOR       = "CURSOR"
PIVOT_LAST         = "LAST_SELECTED"
PIVOT_CYCLE        = (PIVOT_ACTIVE, PIVOT_CURSOR, PIVOT_LAST)

CLONE_DUP          = "DUPLICATE"
CLONE_INST         = "INSTANCE"
CLONE_CYCLE        = (CLONE_DUP, CLONE_INST)

ARC_FULL           = "FULL_360"
ARC_ANGLE          = "ARC_ANGLE"
ARC_TWO_POINTS     = "ARC_TWO_POINTS"
ARC_CYCLE          = (ARC_FULL, ARC_ANGLE, ARC_TWO_POINTS)

AXIS_GLOBAL_X      = "GX"
AXIS_GLOBAL_Y      = "GY"
AXIS_GLOBAL_Z      = "GZ"
AXIS_LOCAL_X       = "LX"
AXIS_LOCAL_Y       = "LY"
AXIS_LOCAL_Z       = "LZ"
AXIS_VIEW          = "VIEW"
AXIS_NORMAL        = "NORMAL"


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


def _subtree_roots_and_descendants(obj):
    """Return [root, *children_recursive] in stable order."""
    return [obj, *obj.children_recursive]


def _resolve_selection(context, pivot_mode):
    """Return (pivot_world_co, pivot_object_or_none, source_roots, end_target_or_none).

    end_target is the last-selected object (for ARC_TWO_POINTS), distinct from pivot_object and
    from source_roots[0]. May be None if not applicable.
    """
    sel = list(context.selected_objects)
    active = context.active_object

    if pivot_mode == PIVOT_ACTIVE:
        pivot_obj = active
        pivot_co = active.matrix_world.translation.copy() if active else None
        sources = [o for o in sel if o is not active]
    elif pivot_mode == PIVOT_CURSOR:
        pivot_obj = None
        pivot_co = context.scene.cursor.location.copy()
        sources = list(sel)
    else:  # PIVOT_LAST
        non_active = [o for o in sel if o is not active]
        pivot_obj = non_active[-1] if non_active else active
        pivot_co = pivot_obj.matrix_world.translation.copy() if pivot_obj else None
        sources = [o for o in sel if o is not pivot_obj]

    # end target = last selected that isn't pivot and isn't sources[0]
    end_target = None
    if sources:
        for o in reversed(sel):
            if o is pivot_obj:
                continue
            if o is sources[0]:
                continue
            end_target = o
            break

    return pivot_co, pivot_obj, sources, end_target
```

- [ ] **Step 2: Initialize state in `invoke()` and store captured selection**

Replace the body of `invoke()` (after the `if not sel or active is None: ... return CANCELLED` block, before the HUD build) with:

```python
        # --- mode defaults ---
        self.pivot_mode  = PIVOT_ACTIVE
        self.clone_mode  = CLONE_DUP
        self.arc_mode    = ARC_FULL
        self.axis_mode   = AXIS_GLOBAL_Z
        self.align_to_radius = False
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.arc_angle = 0.0          # radians
        self.start_offset = 0.0       # radians
        self.start_offset_enabled = False
        self.numeric_channel = None   # None | "ANGLE" | "OFFSET"
        self.numeric_string = ""
        self.pending_normal_pick = False
        self._cached_axis_vec = Vector((0, 0, 1))
        self._dirty = True

        pivot_co, pivot_obj, sources, end_target = _resolve_selection(context, self.pivot_mode)
        if not sources:
            self.report({"WARNING"}, "Select at least one source object besides the pivot")
            return {"CANCELLED"}

        self.pivot_co  = pivot_co
        self.pivot_obj = pivot_obj
        self.sources   = sources
        self.end_target = end_target

        # snapshot subtree matrices once (relative to source root)
        self.subtree_data = []
        for root in sources:
            root_inv = root.matrix_world.inverted()
            subtree = []
            for child in _subtree_roots_and_descendants(root):
                subtree.append((child, root_inv @ child.matrix_world))
            self.subtree_data.append(subtree)
```

- [ ] **Step 3: Smoke-check via blender-mcp**

```python
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(location=(0,0,0))
piv = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(2,0,0))
src = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(2,0,1))
child = bpy.context.active_object
child.parent = src

piv.select_set(True); src.select_set(True); child.select_set(False)
bpy.context.view_layer.objects.active = piv

# Import helpers directly
from InteractionOps.operators import object_radial_array as ora
pivot_co, pivot_obj, sources, end_target = ora._resolve_selection(bpy.context, ora.PIVOT_ACTIVE)
assert pivot_obj is piv, pivot_obj
assert sources == [src], sources

subtree = ora._subtree_roots_and_descendants(src)
assert subtree[0] is src and child in subtree, subtree
print("Task 2 OK")
```

Expected: `Task 2 OK` printed, no asserts fail.

- [ ] **Step 4: Commit**

```bash
git add operators/object_radial_array.py
git commit -m "feat(object_radial_array): state model + selection/hierarchy capture"
```

---

### Task 3: Geometry — axis, radius, per-clone matrix

**Files:**
- Modify: `operators/object_radial_array.py`

- [ ] **Step 1: Add geometry helpers**

Insert after the `_resolve_selection` helper:

```python
import math


def _resolve_axis(self, context):
    """Return a normalized world-space axis vector based on self.axis_mode."""
    am = self.axis_mode
    if am == AXIS_GLOBAL_X: return Vector((1, 0, 0))
    if am == AXIS_GLOBAL_Y: return Vector((0, 1, 0))
    if am == AXIS_GLOBAL_Z: return Vector((0, 0, 1))
    if am in (AXIS_LOCAL_X, AXIS_LOCAL_Y, AXIS_LOCAL_Z):
        if self.pivot_obj is None:
            return Vector((0, 0, 1))  # cursor pivot fallback
        rot = self.pivot_obj.matrix_world.to_3x3()
        local = {AXIS_LOCAL_X: Vector((1,0,0)),
                 AXIS_LOCAL_Y: Vector((0,1,0)),
                 AXIS_LOCAL_Z: Vector((0,0,1))}[am]
        return (rot @ local).normalized()
    if am == AXIS_VIEW:
        rv3d = context.region_data
        if rv3d is None:
            return Vector((0, 0, 1))
        return (rv3d.view_rotation @ Vector((0, 0, -1))).normalized()
    if am == AXIS_NORMAL:
        return self._cached_axis_vec.copy() if self._cached_axis_vec.length > 0 else Vector((0,0,1))
    return Vector((0, 0, 1))


def _signed_angle_around(v_from, v_to, axis):
    """Signed angle from v_from to v_to about axis (right-hand). Returns radians in (-pi, pi]."""
    a = v_from.normalized()
    b = v_to.normalized()
    n = axis.normalized()
    # project a and b onto plane
    a = (a - n * a.dot(n)).normalized()
    b = (b - n * b.dot(n)).normalized()
    if a.length < 1e-8 or b.length < 1e-8:
        return 0.0
    dot = max(-1.0, min(1.0, a.dot(b)))
    ang = math.acos(dot)
    if a.cross(b).dot(n) < 0:
        ang = -ang
    return ang


def _compute_arc(self, axis_vec):
    """Return (arc_angle_radians, step_radians, n_clones) for the current mode."""
    n = max(2, int(self.count))
    if self.arc_mode == ARC_FULL:
        step = 2 * math.pi / n
        return 2 * math.pi, step, n - 1  # source occupies index 0
    if self.arc_mode == ARC_ANGLE:
        ang = self.arc_angle
        if abs(ang) < 1e-8:
            return 0.0, 0.0, 0
        step = ang / (n - 1) if self.end_inclusive else ang / n
        return ang, step, n - 1
    # ARC_TWO_POINTS
    if not self.sources or self.end_target is None:
        return 0.0, 0.0, 0
    start_vec = self.sources[0].matrix_world.translation - self.pivot_co
    end_vec   = self.end_target.matrix_world.translation - self.pivot_co
    ang = _signed_angle_around(start_vec, end_vec, axis_vec)
    if abs(ang) < 1e-6:
        ang = 2 * math.pi  # treat coincident as full circle
    step = ang / (n - 1) if self.end_inclusive else ang / n
    return ang, step, n - 1


def _clone_matrix(pivot_co, axis_vec, angle, align_to_radius, source_mw):
    """Compute world matrix for a clone of a source root at given angle around pivot."""
    R = Matrix.Rotation(angle, 4, axis_vec)
    T_to   = Matrix.Translation(pivot_co)
    T_from = Matrix.Translation(-pivot_co)
    M = T_to @ R @ T_from @ source_mw

    if align_to_radius:
        # additional rotation so source's +X faces outward in the rotation plane
        clone_pos = M.translation
        radial = (clone_pos - pivot_co)
        # project onto plane
        radial = radial - axis_vec * radial.dot(axis_vec)
        if radial.length > 1e-6:
            radial.normalize()
            # current source +X in world
            src_x = (source_mw.to_3x3() @ Vector((1, 0, 0)))
            src_x = src_x - axis_vec * src_x.dot(axis_vec)
            if src_x.length > 1e-6:
                src_x.normalize()
                extra_ang = _signed_angle_around(src_x, radial, axis_vec)
                R_extra = Matrix.Rotation(extra_ang, 4, axis_vec)
                # rotate around clone's own position
                T_cto   = Matrix.Translation(clone_pos)
                T_cfrom = Matrix.Translation(-clone_pos)
                M = T_cto @ R_extra @ T_cfrom @ M
    return M


def _iter_clone_angles(start_offset, step, n_clones):
    """Yield (clone_index, angle) for each clone. Index 0 reserved for source position."""
    for i in range(1, n_clones + 1):
        yield i, start_offset + i * step
```

Note: `import math` goes at the top of the file with the other imports.

- [ ] **Step 2: Smoke-check via blender-mcp**

```python
import math
from mathutils import Vector, Matrix
from InteractionOps.operators import object_radial_array as ora

# axis resolution
class Fake: pass
f = Fake(); f.axis_mode = ora.AXIS_GLOBAL_Z; f.pivot_obj = None; f._cached_axis_vec = Vector((0,0,1))
import bpy
ax = ora._resolve_axis(f, bpy.context)
assert (ax - Vector((0,0,1))).length < 1e-6, ax

# signed angle
a = Vector((1,0,0)); b = Vector((0,1,0)); n = Vector((0,0,1))
assert abs(ora._signed_angle_around(a, b, n) - math.pi/2) < 1e-6

# clone matrix: 90 deg around Z about origin, source at (2,0,0)
src_mw = Matrix.Translation(Vector((2,0,0)))
M = ora._clone_matrix(Vector((0,0,0)), Vector((0,0,1)), math.pi/2, False, src_mw)
p = M.translation
assert abs(p.x) < 1e-6 and abs(p.y - 2) < 1e-6 and abs(p.z) < 1e-6, p

# full 360 with count=4 => step=90deg, 3 clones
f.arc_mode = ora.ARC_FULL; f.count = 4; f.end_inclusive = True
ang, step, ncl = ora._compute_arc(f, Vector((0,0,1)))
assert ncl == 3 and abs(step - math.pi/2) < 1e-6, (ang, step, ncl)

print("Task 3 OK")
```

Expected: `Task 3 OK`.

- [ ] **Step 3: Commit**

```bash
git add operators/object_radial_array.py
git commit -m "feat(object_radial_array): geometry helpers (axis, arc, clone matrix)"
```

---

### Task 4: GPU preview — ghost wires + axis/circle/pivot

**Files:**
- Modify: `operators/object_radial_array.py`

- [ ] **Step 1: Add ghost-wire batch builder + 3D draw callback**

Insert after geometry helpers:

```python
# --- Preview (POST_VIEW) -------------------------------------------------

def _mesh_edge_segments_world(obj_mw, mesh):
    """Return list of (Vector, Vector) world-space edge segments for a mesh."""
    verts_world = [obj_mw @ v.co for v in mesh.vertices]
    return [(verts_world[e.vertices[0]], verts_world[e.vertices[1]]) for e in mesh.edges]


def _build_ghost_segments(op, context):
    """Build the list of edge segments (in world space) for every predicted clone."""
    axis_vec = _resolve_axis(op, context)
    ang_total, step, n_clones = _compute_arc(op, axis_vec)

    segs = []  # list[(Vector, Vector)]
    crosses = []  # list[Vector] — anchor points for non-mesh placeholders

    for subtree in op.subtree_data:
        root_obj, root_rel = subtree[0]   # root_rel is Identity by construction
        root_mw = root_obj.matrix_world.copy()

        for ci, angle in _iter_clone_angles(op.start_offset, step, n_clones):
            if op.skip_first and ci == 0:
                continue
            M_root = _clone_matrix(op.pivot_co, axis_vec, angle, op.align_to_radius, root_mw)
            # delta from root_mw to M_root: apply same delta to each descendant
            delta = M_root @ root_mw.inverted()
            for child_obj, rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                if child_obj.type == "MESH" and child_obj.data is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, child_obj.data):
                        segs.append((a, b))
                else:
                    crosses.append(child_clone_mw.translation.copy())

    return segs, crosses, axis_vec, ang_total


def _draw_preview_3d(op, context):
    """POST_VIEW draw: ghost wires + axis line + arc/circle + pivot."""
    from .. ui import draw as iops_draw  # local import to avoid cycle in headless tests

    if op._dirty or getattr(op, "_ghost_cache", None) is None:
        op._ghost_cache = _build_ghost_segments(op, context)
        op._dirty = False
    segs, crosses, axis_vec, ang_total = op._ghost_cache

    # ghost wires
    if segs:
        flat = []
        for a, b in segs:
            flat.append(a); flat.append(b)
        iops_draw.edges_3d(flat, role=Role.PREVIEW_LINE, context=context)

    # placeholder crosses for non-mesh clone children
    if crosses:
        iops_draw.points(crosses, role=Role.PREVIEW_POINT, context=context)

    # axis line through pivot
    max_r = 0.0
    for sub in op.subtree_data:
        root = sub[0][0]
        r = (root.matrix_world.translation - op.pivot_co).length
        if r > max_r: max_r = r
    if max_r < 1e-3:
        max_r = 1.0
    a_half = axis_vec * (max_r * 2.0)
    iops_draw.edges_3d([op.pivot_co - a_half, op.pivot_co + a_half],
                       role=Role.ACTIVE_LINE, context=context)

    # circle/arc in plane perpendicular to axis at radius max_r
    if max_r > 1e-3:
        steps = 64
        # build orthonormal frame
        up = axis_vec
        right = Vector((1,0,0)) if abs(up.x) < 0.9 else Vector((0,1,0))
        right = (right - up * right.dot(up)).normalized()
        fwd = up.cross(right)
        sweep = ang_total if op.arc_mode != ARC_FULL else 2 * math.pi
        ring = []
        for i in range(steps + 1):
            t = i / steps
            ang = op.start_offset + t * sweep
            p = op.pivot_co + (right * math.cos(ang) + fwd * math.sin(ang)) * max_r
            ring.append(p)
        # as line strip → pairs
        pairs = []
        for i in range(len(ring) - 1):
            pairs.append(ring[i]); pairs.append(ring[i+1])
        iops_draw.edges_3d(pairs, role=Role.PREVIEW_LINE, context=context)

    # pivot marker
    iops_draw.points([op.pivot_co], role=Role.PIVOT, context=context)
```

Then add registration of this handler in `invoke()` after `self._handle = safe_handler_add(... POST_PIXEL ...)`:

```python
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
```

And in `_cleanup()`:

```python
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None
```

- [ ] **Step 2: Smoke-check in Blender**

Run the operator interactively via blender-mcp:

```python
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(location=(0,0,0))
piv = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3,0,0))
src = bpy.context.active_object
piv.select_set(True); src.select_set(True)
bpy.context.view_layer.objects.active = piv
# Invoke (will require manual cancel via window — we just check no exception on invoke)
result = bpy.ops.iops.object_radial_array('INVOKE_DEFAULT')
print("invoke result:", result)
# Immediately cancel via the operator's modal handler is awkward headless;
# rely on visual confirmation: ask user to confirm ghosts + axis + circle appear.
```

User checkpoint: open Blender, run operator on a cube near origin + cube at (3,0,0) as pivot, confirm visually that ghost wires for 5 clones + axis line + circle + pivot marker appear.

- [ ] **Step 3: Commit**

```bash
git add operators/object_radial_array.py
git commit -m "feat(object_radial_array): GPU preview (ghosts + axis + arc + pivot)"
```

---

### Task 5: Modal key handling — toggles, axis, count, angle, numeric input

**Files:**
- Modify: `operators/object_radial_array.py`

- [ ] **Step 1: Expand `modal()` with the full key handler**

Replace the simplified key block in `modal()` (everything between the navigation pass-through and the final `return {"RUNNING_MODAL"}`) with:

```python
        # --- mode cycles ---
        if event.type == "P" and event.value == "PRESS":
            self.pivot_mode = _cycle(self.pivot_mode, PIVOT_CYCLE)
            pivot_co, pivot_obj, sources, end_target = _resolve_selection(context, self.pivot_mode)
            if sources:
                self.pivot_co = pivot_co
                self.pivot_obj = pivot_obj
                self.sources = sources
                self.end_target = end_target
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "I" and event.value == "PRESS":
            self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
            return {"RUNNING_MODAL"}

        if event.type == "A" and event.value == "PRESS":
            self.arc_mode = _cycle(self.arc_mode, ARC_CYCLE)
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- axis ---
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            self.axis_mode = {"X": AXIS_GLOBAL_X, "Y": AXIS_GLOBAL_Y, "Z": AXIS_GLOBAL_Z}[event.type]
            self.pending_normal_pick = False
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "L" and event.value == "PRESS":
            mapping = {AXIS_GLOBAL_X: AXIS_LOCAL_X, AXIS_GLOBAL_Y: AXIS_LOCAL_Y, AXIS_GLOBAL_Z: AXIS_LOCAL_Z,
                       AXIS_LOCAL_X:  AXIS_GLOBAL_X, AXIS_LOCAL_Y: AXIS_GLOBAL_Y, AXIS_LOCAL_Z: AXIS_GLOBAL_Z}
            self.axis_mode = mapping.get(self.axis_mode, AXIS_GLOBAL_Z)
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "V" and event.value == "PRESS":
            self.axis_mode = AXIS_VIEW
            self.pending_normal_pick = False
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "N" and event.value == "PRESS":
            self.pending_normal_pick = True
            self.report({"INFO"}, "Click a face to set rotation axis from its normal")
            return {"RUNNING_MODAL"}

        # --- normal pick via LMB while pending ---
        if self.pending_normal_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
            origin = region_2d_to_origin_3d(region, rv3d, mouse)
            direction = region_2d_to_vector_3d(region, rv3d, mouse)
            depsgraph = context.evaluated_depsgraph_get()
            hit, loc, normal, idx, obj, mat = context.scene.ray_cast(depsgraph, origin, direction)
            if hit:
                self._cached_axis_vec = (mat.to_3x3() @ normal).normalized()
                self.axis_mode = AXIS_NORMAL
                self._dirty = True
                self.report({"INFO"}, "Axis set from face normal")
            else:
                self.report({"WARNING"}, "No face hit")
            self.pending_normal_pick = False
            return {"RUNNING_MODAL"}

        # --- toggles ---
        if event.type == "R" and event.value == "PRESS":
            self.align_to_radius = not self.align_to_radius
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "O" and event.value == "PRESS":
            self.skip_first = not self.skip_first
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "E" and event.value == "PRESS":
            self.end_inclusive = not self.end_inclusive
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- count ---
        if event.type in {"NUMPAD_PLUS", "EQUAL", "WHEELUPMOUSE"} and event.value == "PRESS":
            step = 10 if event.ctrl else 1
            self.count = min(1024, self.count + step)
            self._dirty = True
            return {"RUNNING_MODAL"}
        if event.type in {"NUMPAD_MINUS", "MINUS", "WHEELDOWNMOUSE"} and event.value == "PRESS":
            step = 10 if event.ctrl else 1
            self.count = max(2, self.count - step)
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- numeric channel selection ---
        if event.type == "G" and event.value == "PRESS":
            self.numeric_channel = "ANGLE"
            self.numeric_string = ""
            self._angle_drag_start_x = event.mouse_region_x
            self._angle_drag_start_value = self.arc_angle
            return {"RUNNING_MODAL"}
        if event.type == "S" and event.value == "PRESS":
            self.start_offset_enabled = True
            self.numeric_channel = "OFFSET"
            self.numeric_string = ""
            return {"RUNNING_MODAL"}

        # angle drag in ANGLE channel
        if self.numeric_channel == "ANGLE" and event.type == "MOUSEMOVE":
            dx = event.mouse_region_x - getattr(self, "_angle_drag_start_x", event.mouse_region_x)
            ang = getattr(self, "_angle_drag_start_value", 0.0) + math.radians(dx * 0.5)
            if event.ctrl and event.shift:
                snap = math.radians(15.0); ang = round(ang / snap) * snap
            elif event.ctrl:
                snap = math.radians(5.0); ang = round(ang / snap) * snap
            self.arc_angle = ang
            self._dirty = True
            return {"RUNNING_MODAL"}

        # numeric digits
        if self.numeric_channel is not None and event.value == "PRESS":
            if event.type in {"ZERO","ONE","TWO","THREE","FOUR","FIVE","SIX","SEVEN","EIGHT","NINE"}:
                self.numeric_string += event.type.replace("ZERO","0").replace("ONE","1").replace("TWO","2").replace("THREE","3").replace("FOUR","4").replace("FIVE","5").replace("SIX","6").replace("SEVEN","7").replace("EIGHT","8").replace("NINE","9")
            elif event.type == "PERIOD":
                if "." not in self.numeric_string: self.numeric_string += "."
            elif event.type == "BACK_SPACE":
                self.numeric_string = self.numeric_string[:-1]
            elif event.type == "MINUS":
                # toggle sign
                if self.numeric_string.startswith("-"):
                    self.numeric_string = self.numeric_string[1:]
                else:
                    self.numeric_string = "-" + self.numeric_string
            else:
                pass
            try:
                val_deg = float(self.numeric_string) if self.numeric_string not in ("", "-", ".", "-.") else 0.0
                val_rad = math.radians(val_deg)
                if self.numeric_channel == "ANGLE":
                    self.arc_angle = val_rad
                elif self.numeric_channel == "OFFSET":
                    self.start_offset = val_rad
                self._dirty = True
            except ValueError:
                pass
            return {"RUNNING_MODAL"}
```

(The existing `LMB / Enter / Space` apply branch must remain after this block; ensure normal-pick LMB consumption above precedes the apply check — restructure the modal so the pending-pick LMB handler runs before the apply LMB handler.)

- [ ] **Step 2: Smoke-check via blender-mcp**

```python
# Just verify no syntax errors by reloading addon
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
print("reload OK")
```

User checkpoint: in Blender, invoke operator; press P, I, A, X/Y/Z, L, V, R, O, E, +/- and verify HUD reflects state changes and ghost preview updates.

- [ ] **Step 3: Commit**

```bash
git add operators/object_radial_array.py
git commit -m "feat(object_radial_array): full key handling (modes, axis, count, angle)"
```

---

### Task 6: Apply — materialize duplicates and instances

**Files:**
- Modify: `operators/object_radial_array.py`

- [ ] **Step 1: Add `_apply()` method**

Insert as a method on `IOPS_OT_Object_Radial_Array`:

```python
    def _apply(self, context):
        axis_vec = _resolve_axis(self, context)
        ang_total, step, n_clones = _compute_arc(self, axis_vec)
        if n_clones <= 0:
            return

        created_roots = []

        for subtree in self.subtree_data:
            root_obj = subtree[0][0]
            root_mw = root_obj.matrix_world.copy()

            # working collection
            try:
                base_coll = root_obj.users_collection[0]
            except IndexError:
                base_coll = context.scene.collection
            ra_name = f"_RadialArray_{root_obj.name}"
            ra_coll = bpy.data.collections.get(ra_name) or bpy.data.collections.new(ra_name)
            if ra_name not in {c.name for c in context.scene.collection.children_recursive}:
                context.scene.collection.children.link(ra_coll)

            for ci, angle in _iter_clone_angles(self.start_offset, step, n_clones):
                if self.skip_first and ci == 0:
                    continue

                M_root = _clone_matrix(self.pivot_co, axis_vec, angle,
                                       self.align_to_radius, root_mw)
                delta = M_root @ root_mw.inverted()

                # clone every member of subtree, preserving parent/child structure
                clone_map = {}
                for child_obj, _rel in subtree:
                    new = child_obj.copy()
                    if self.clone_mode == CLONE_DUP and child_obj.data is not None:
                        new.data = child_obj.data.copy()
                    # link to source's collection and to RA collection
                    try:
                        for c in child_obj.users_collection:
                            c.objects.link(new)
                    except RuntimeError:
                        pass
                    if new.name not in ra_coll.objects:
                        ra_coll.objects.link(new)
                    clone_map[child_obj] = new

                # rebuild parenting + apply final world matrices
                for child_obj, _rel in subtree:
                    new = clone_map[child_obj]
                    if child_obj.parent is not None and child_obj.parent in clone_map:
                        new.parent = clone_map[child_obj.parent]
                        new.matrix_parent_inverse = child_obj.matrix_parent_inverse.copy()
                    else:
                        new.parent = None
                    new.matrix_world = delta @ child_obj.matrix_world

                created_roots.append(clone_map[root_obj])

        # select results
        bpy.ops.object.select_all(action="DESELECT")
        for r in created_roots:
            r.select_set(True)
        if created_roots:
            context.view_layer.objects.active = created_roots[0]
```

- [ ] **Step 2: Wire apply into the existing apply branch in `modal()`**

Replace:

```python
        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._cleanup()
            return {"FINISHED"}
```

with:

```python
        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            # do not consume LMB if a normal pick is pending (handled above)
            self._apply(context)
            self._cleanup()
            return {"FINISHED"}
```

- [ ] **Step 3: Smoke-check via blender-mcp**

```python
import bpy, math
from mathutils import Vector
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(location=(0,0,0))
piv = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3,0,0))
src = bpy.context.active_object
piv.select_set(True); src.select_set(True)
bpy.context.view_layer.objects.active = piv

# call apply path directly via helper construction
from InteractionOps.operators.object_radial_array import (
    IOPS_OT_Object_Radial_Array, _resolve_selection, _subtree_roots_and_descendants,
    PIVOT_ACTIVE, CLONE_DUP, ARC_FULL, AXIS_GLOBAL_Z,
)

op = IOPS_OT_Object_Radial_Array()
op.pivot_mode = PIVOT_ACTIVE; op.clone_mode = CLONE_DUP; op.arc_mode = ARC_FULL
op.axis_mode = AXIS_GLOBAL_Z; op.align_to_radius = False; op.skip_first = False
op.end_inclusive = True; op.count = 4; op.arc_angle = 0.0; op.start_offset = 0.0
op._cached_axis_vec = Vector((0,0,1))
pc, po, srcs, et = _resolve_selection(bpy.context, PIVOT_ACTIVE)
op.pivot_co = pc; op.pivot_obj = po; op.sources = srcs; op.end_target = et
op.subtree_data = []
for root in srcs:
    inv = root.matrix_world.inverted()
    op.subtree_data.append([(root, inv @ root.matrix_world)])

n_before = len(bpy.data.objects)
op._apply(bpy.context)
n_after = len(bpy.data.objects)
print(f"created {n_after - n_before} objects")  # expect 3
assert n_after - n_before == 3
# verify positions ~ (0,3,0), (-3,0,0), (0,-3,0)
positions = sorted([tuple(round(c,2) for c in o.matrix_world.translation)
                    for o in bpy.data.objects if o.name.startswith("Cube.")])
print(positions)
```

Expected: 3 new objects created at the 3 non-source positions around origin at radius 3.

- [ ] **Step 4: Commit**

```bash
git add operators/object_radial_array.py
git commit -m "feat(object_radial_array): apply creates duplicates/instances with hierarchy"
```

---

### Task 7: HUD params + integration verification

**Files:**
- Modify: `operators/object_radial_array.py`

- [ ] **Step 1: Add HUDParam binding so the HUD shows live state**

In `_build_hud()`, before `return hud`, add a section with `HUDParam`s reflecting current state. Reference existing HUDParam usage in `mesh_straight_bevel.py` for the exact API. Add the call at end of `_build_hud`:

```python
    section = HUDSection("State", [
        HUDParam("Pivot",    lambda op=None: getattr(op, "pivot_mode", "—")),
        HUDParam("Clone",    lambda op=None: getattr(op, "clone_mode", "—")),
        HUDParam("Arc",      lambda op=None: getattr(op, "arc_mode", "—")),
        HUDParam("Axis",     lambda op=None: getattr(op, "axis_mode", "—")),
        HUDParam("Count",    lambda op=None: str(getattr(op, "count", "—"))),
        HUDParam("Angle°",   lambda op=None: f"{math.degrees(getattr(op, 'arc_angle', 0.0)):.1f}"),
        HUDParam("Offset°",  lambda op=None: f"{math.degrees(getattr(op, 'start_offset', 0.0)):.1f}"),
        HUDParam("Outward",  lambda op=None: "on" if getattr(op, "align_to_radius", False) else "off"),
        HUDParam("Skip 1st", lambda op=None: "on" if getattr(op, "skip_first", False) else "off"),
        HUDParam("End incl.", lambda op=None: "on" if getattr(op, "end_inclusive", False) else "off"),
    ])
    hud.add_section(section)
```

If the `HUDParam` signature in this codebase takes the operator differently (e.g., bound at draw time via `_last_event` style), match the pattern used in `mesh_straight_bevel.py` — open that file and copy the exact HUDParam construction style. **Do not invent a signature; copy from working code.**

Also pass `op` reference to HUD on each redraw: in `_draw_callback`, before `hud.draw(...)`, set `hud.op = op` (or similar — match `mesh_straight_bevel.py`).

- [ ] **Step 2: Verify HUD reflects state changes during modal**

User checkpoint in Blender: invoke operator, press P/I/A/X/Y/Z/R/+/- and visually confirm the HUD State section updates live.

- [ ] **Step 3: End-to-end test — hierarchy duplicate and linked instance**

```python
import bpy
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(location=(0,0,0))
piv = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(3,0,0))
parent = bpy.context.active_object
bpy.ops.mesh.primitive_cone_add(location=(3,0,1))
child = bpy.context.active_object
child.parent = parent

piv.select_set(True); parent.select_set(True); child.select_set(False)
bpy.context.view_layer.objects.active = piv

# Duplicate mode (default): expect each clone to have its own cone+cube and its own data
# Instance mode: clones share .data with originals
# Verified manually by invoking operator, toggling I, watching ghost, applying.
```

User checkpoint: confirm Duplicate creates independent meshes (`bpy.data.meshes` count grows by `(n_clones * n_meshes_in_subtree)`), Instance does not.

- [ ] **Step 4: Commit**

```bash
git add operators/object_radial_array.py
git commit -m "feat(object_radial_array): live HUDParams + end-to-end verification"
```

---

### Task 8: Keymap registration + final pass

**Files:**
- Modify: `__init__.py` (or wherever addon keymaps are registered — locate during this task)

- [ ] **Step 1: Locate keymap registration**

Run:

```bash
grep -rn "keymap_items.new\|km.keymap_items.new" __init__.py operators/hotkeys/ | head -20
```

Identify where addon-default keymaps are registered. If the addon uses JSON-defined hotkeys loaded via `IOPS_OT_LoadDefaultHotkeys`, add the entry to the matching JSON file (look for it in `operators/hotkeys/`). Otherwise add to the Python keymap registration block.

- [ ] **Step 2: Add a default binding (no shortcut by default — invocable from search menu and pie/IOPS menu)**

Decision: **do not assign a default key**. The operator is invocable via F3 search ("Radial Array"). Users can bind via the addon's hotkey system if desired. Document this in a one-line comment near the operator class:

```python
# No default key binding — invoke via F3 search or assign in keymap prefs.
```

- [ ] **Step 3: Final smoke test — disable/re-enable addon, run operator**

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
assert hasattr(bpy.ops.iops, "object_radial_array")
print("registration OK")
```

User checkpoint in Blender: full interactive run-through:
1. Cube at origin + 2 cubes selected → invoke → confirm preview → cycle modes → apply → result correct.
2. Parent+child hierarchy → invoke → apply Duplicate → confirm independent data; redo with Instance → confirm shared data.
3. Arc-2-points: 3 selected objects (active = pivot, two others) → arc mode `A` twice → confirm clones distribute between start and end.
4. Cancel path: invoke → Esc → confirm nothing was created.

- [ ] **Step 4: Commit**

```bash
git add __init__.py operators/object_radial_array.py
git commit -m "feat(object_radial_array): finalize registration + verified end-to-end"
```

---

## Self-Review Notes

- **Spec coverage:** Selection model (T2), clone types (T6), arc modes incl. 2-points (T3+T5), axis incl. local/view/normal-pick (T3+T5), count + tweaks incl. skip_first/end_inclusive/start_offset (T5), GPU preview from theme Roles (T4), HUD/Help (T1+T7), apply/cancel + edge cases handled in `_apply` and `_compute_arc` (T3+T6), file registration (T1+T8). Theme additions from spec resolved by reusing existing `Role.PREVIEW_LINE`/`ACTIVE_LINE`/`PIVOT`/`PREVIEW_POINT` — no new theme keys needed.
- **Out-of-scope items** explicitly omitted: geometry-nodes generator, on-curve distribution, nested radial arrays.
- **Known soft spot:** the exact `HUDParam` signature in this codebase isn't pinned in the plan (Task 7 Step 1) — that step explicitly says "copy from `mesh_straight_bevel.py`" rather than guessing. If the executor finds a mismatch, fix inline and re-commit; don't invent.
