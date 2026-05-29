# Z_OPS.py Operators Documentation

This document contains all the operator classes defined in the `z_ops.py` file of the InteractionOps Blender addon.

## Overview

The `z_ops.py` file contains 8 different operator classes that provide various mesh editing utilities, particularly focused on selection operations, edge manipulation, and face operations.

---

## Operator Classes

### 1. Z_OT_GrowLoop
- **Class Name**: `Z_OT_GrowLoop`
- **bl_idname**: `iops.z_grow_loop`
- **bl_label**: `Grow Loop`
- **Description**: Grows the current loop selection in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

### 2. Z_OT_ShrinkLoop
- **Class Name**: `Z_OT_ShrinkLoop`
- **bl_idname**: `iops.z_shrink_loop`
- **bl_label**: `Shrink Loop`
- **Description**: Shrinks the current loop selection in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

### 3. Z_OT_GrowRing
- **Class Name**: `Z_OT_GrowRing`
- **bl_idname**: `iops.z_grow_ring`
- **bl_label**: `Grow Ring`
- **Description**: Grows the current ring selection in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

### 4. Z_OT_ShrinkRing
- **Class Name**: `Z_OT_ShrinkRing`
- **bl_idname**: `iops.z_shrink_ring`
- **bl_label**: `Shrink Ring`
- **Description**: Shrinks the current ring selection in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

### 5. Z_OT_SelectBoundedLoop
- **Class Name**: `Z_OT_SelectBoundedLoop`
- **bl_idname**: `iops.z_select_bounded_loop`
- **bl_label**: `Select Bounded Loop`
- **Description**: Selects bounded loop selection in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

### 6. Z_OT_SelectBoundedRing
- **Class Name**: `Z_OT_SelectBoundedRing`
- **bl_idname**: `iops.z_select_bounded_ring`
- **bl_label**: `Select Bounded Ring`
- **Description**: Selects bounded ring selection in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

### 7. Z_OT_ContextDelete
- **Class Name**: `Z_OT_ContextDelete`
- **bl_idname**: `iops.z_delete_mode`
- **bl_label**: `Delete Selection`
- **Description**: Context-sensitive delete operation that works with different object types (MESH, CURVE, ARMATURE)
- **Poll Condition**: None (works in all contexts)
- **Options**: `REGISTER`, `UNDO`

**Special Features**:
- Automatically detects object type and applies appropriate delete operation
- For CURVE objects: Uses `curve.dissolve_verts()`
- For ARMATURE objects: Uses `armature.delete()`
- For MESH objects: Deletes based on current selection mode (VERT, EDGE, FACE)

### 8. Z_OT_EdgeEq
- **Class Name**: `Z_OT_EdgeEq`
- **bl_idname**: `iops.z_eq_edges`
- **bl_label**: `Equalize`
- **Description**: Equalize the selected contiguous edges
- **Poll Condition**: Requires active object in EDIT mode with edge selection mode only
- **Options**: `REGISTER`, `UNDO`

**Special Features**:
- Only works when mesh_select_mode is `(False, True, False)` (edge mode only)

### 9. Z_OT_EdgeLineUp
- **Class Name**: `Z_OT_EdgeLineUp`
- **bl_idname**: `iops.z_line_up_edges`
- **bl_label**: `Line Up`
- **Description**: Line up the selected contiguous edges
- **Poll Condition**: Requires active object in EDIT mode with edge selection mode only
- **Options**: `REGISTER`, `UNDO`

**Special Features**:
- Only works when mesh_select_mode is `(False, True, False)` (edge mode only)

### 10. Z_OT_EdgeConnect
- **Class Name**: `Z_OT_EdgeConnect`
- **bl_idname**: `iops.z_connect`
- **bl_label**: `Connect`
- **Description**: Connect the selected edges with advanced subdivide options
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

**Properties**:
- `use_subdivide_op` (BoolProperty): Use standard subdivide operator (default: False)
- `number_cuts` (IntProperty): Number of cuts (default: 1, range: 0-10000)
- `smoothness` (FloatProperty): Smoothness factor (default: 0.0, range: 0.0-1.0)
- `ngon` (BoolProperty): Create N-Gon - when disabled, newly created faces are limited to 3 and 4 sides (default: True)
- `quadcorner` (EnumProperty): How to subdivide quad corners - options: INNERVERT, PATH, STRAIGHT_CUT, FAN (default: FAN)
- `fractal` (FloatProperty): Fractal factor (default: 0.0, range: 0.0-1.0)
- `fractal_along_normal` (FloatProperty): Fractal along normal factor (default: 0.0, range: 0.0-1.0)
- `seed` (IntProperty): Random seed (default: 0, range: 0-255)

**Special Features**:
- Has a custom draw method for UI layout
- Can either use built-in subdivide operator or custom connect functionality
- Works primarily in edge selection mode

### 11. Z_OT_PutOn
- **Class Name**: `Z_OT_PutOn`
- **bl_idname**: `iops.z_put_on`
- **bl_label**: `Put On`
- **Description**: Places one face onto another face (requires exactly 2 selected faces with one being active)
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

**Properties**:
- `turn` (FloatProperty): Turn angle - turn by this angle after placing (range: -180.0 to 180.0, default: 0.0)

**Special Features**:
- Requires exactly 2 selected faces with one being the active face
- The operation places one face onto the other

### 12. Z_OT_Mirror
- **Class Name**: `Z_OT_Mirror`
- **bl_idname**: `iops.z_mirror`
- **bl_label**: `Mirror`
- **Description**: Mirror operation in edit mode
- **Poll Condition**: Requires active object in EDIT mode
- **Options**: `REGISTER`, `UNDO`

---

## Categories

### Selection Operations
- `Z_OT_GrowLoop` - Grow loop selection
- `Z_OT_ShrinkLoop` - Shrink loop selection
- `Z_OT_GrowRing` - Grow ring selection
- `Z_OT_ShrinkRing` - Shrink ring selection
- `Z_OT_SelectBoundedLoop` - Select bounded loop
- `Z_OT_SelectBoundedRing` - Select bounded ring

### Edge Operations
- `Z_OT_EdgeEq` - Equalize edges
- `Z_OT_EdgeLineUp` - Line up edges
- `Z_OT_EdgeConnect` - Connect edges with subdivide options

### Face Operations
- `Z_OT_PutOn` - Place one face onto another

### General Operations
- `Z_OT_ContextDelete` - Context-sensitive delete
- `Z_OT_Mirror` - Mirror geometry

---

## Usage Notes

1. Most operators require the active object to be in EDIT mode
2. Some operators have specific selection mode requirements (e.g., edge-only operations)
3. The `Z_OT_ContextDelete` operator is context-aware and works with different object types
4. The `Z_OT_EdgeConnect` operator provides both simple connection and advanced subdivide functionality
5. The `Z_OT_PutOn` operator has specific requirements (exactly 2 faces selected, one active)

## File Information
- **File**: `z_ops.py`
- **Total Classes**: 12 operator classes
- **Main Categories**: Selection, Edge Operations, Face Operations, General Operations
- **Dependencies**: bmesh, bpy, mathutils