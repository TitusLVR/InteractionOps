"""iOps Falloff tools: Move / Rotate / Scale the selection with a
Modo-style per-vertex falloff. All shared behaviour lives in
FalloffToolMixin; these classes only turn a mouse drag into an amount
and an amount into new coordinates."""
from __future__ import annotations

import math

import bpy
import numpy as np
from mathutils import Vector

from ...utils import falloff_core as fc
from .common import FalloffToolMixin


class IOPS_OT_mesh_falloff_move(FalloffToolMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_move"
    bl_label = "iOps Falloff Move"
    bl_description = ("Move the selection with a falloff (Linear / Radial / "
                      "Screen / Coplanar). Drag to move, drag handles to edit "
                      "the falloff")
    tool_label = "Move"
    undo_message = "Falloff Move"
    gizmo_kind = "MOVE"
    amount_label = "Offset"

    def _drag_begin(self, context, event):
        self._start_obj = self._mouse_to_plane_object(context, self._drag["start"])

    def _drag_amount(self, context, event):
        if self._start_obj is None:
            return np.zeros(3)
        cur = self._mouse_to_plane_object(context, (event.mouse_region_x, event.mouse_region_y))
        if cur is None:
            return np.zeros(3)
        d = cur - self._start_obj
        if event.shift:
            d *= 0.1
        # Axis → only that basis component; plane (Shift+axis) → drop the excluded one.
        d = Vector(self._constrain_object_vector(np.array(d[:], dtype=np.float64), self._axis))
        if event.ctrl:
            d = Vector([self._snap(c, 0.1) for c in d])
        return np.array(d[:], dtype=np.float64)

    def _amount_from_number(self, value):
        # Along the (first) constrained basis axis; basis X when unconstrained.
        letter = self._axis[0] if self._axis else "X"
        return np.array(self._basis_axis_vector(letter)[:], dtype=np.float64) * float(value)

    def _apply_amount(self, amount):
        return fc.apply_move(self._P0, self._W, amount)

    def _amount_text(self, amount):
        return "({:.3f}, {:.3f}, {:.3f})".format(*amount.tolist())


class IOPS_OT_mesh_falloff_rotate(FalloffToolMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_rotate"
    bl_label = "iOps Falloff Rotate"
    bl_description = ("Rotate the selection with a falloff (Linear / Radial / "
                      "Screen / Coplanar). Drag around the pivot to rotate; "
                      "X/Y/Z set the axis (view axis by default)")
    tool_label = "Rotate"
    undo_message = "Falloff Rotate"
    gizmo_kind = "ROTATE"
    amount_label = "Angle"

    def _mouse_angle(self, context, xy):
        p2 = self._pivot_region_2d(context)
        if p2 is None:
            return None
        return math.atan2(xy[1] - p2.y, xy[0] - p2.x)

    def _drag_begin(self, context, event):
        self._start_angle = self._mouse_angle(context, self._drag["start"])
        if self._start_angle is None:
            self._start_angle = 0.0
        self._prev_angle = self._start_angle
        self._accum = 0.0

    def _drag_amount(self, context, event):
        a = self._mouse_angle(context, (event.mouse_region_x, event.mouse_region_y))
        if a is not None:
            d = a - self._prev_angle
            while d > math.pi:
                d -= 2.0 * math.pi
            while d < -math.pi:
                d += 2.0 * math.pi
            self._prev_angle = a
            self._accum += d
        theta = self._accum
        if event.shift:
            theta *= 0.1
        if event.ctrl:
            theta = self._snap(theta, math.radians(5.0))
        return self._signed_for_axis(context, theta)

    def _signed_for_axis(self, context, theta):
        """Counter-clockwise on screen is positive about an axis pointing
        at the viewer; flip when the chosen object axis points away."""
        ax = self._axis_vector_object()
        if ax is None:
            return theta
        view = self._view_axis_object(self._rv3d)
        return theta if ax.dot(view) >= 0.0 else -theta

    def _rotation_axis(self):
        ax = self._axis_vector_object()
        return ax if ax is not None else self._view_axis_object(self._rv3d)

    def _amount_from_number(self, value):
        return math.radians(value)

    def _apply_amount(self, amount):
        axis = self._rotation_axis()
        return fc.apply_rotate(self._P0, self._W, self._pivot,
                               np.array(axis[:], dtype=np.float64), amount)

    def _amount_text(self, amount):
        return f"{math.degrees(amount):.2f}°"


class IOPS_OT_mesh_falloff_scale(FalloffToolMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_scale"
    bl_label = "iOps Falloff Scale"
    bl_description = ("Scale the selection about its centre with a falloff "
                      "(Linear / Radial / Screen / Coplanar). Drag away from "
                      "the pivot to grow; X/Y/Z constrain to one axis")
    tool_label = "Scale"
    undo_message = "Falloff Scale"
    gizmo_kind = "SCALE"
    amount_label = "Scale"

    def _drag_begin(self, context, event):
        p2 = self._pivot_region_2d(context)
        sx, sy = self._drag["start"]
        self._start_dist = max(1.0, math.hypot(sx - p2.x, sy - p2.y)) if p2 is not None else 1.0

    def _drag_amount(self, context, event):
        p2 = self._pivot_region_2d(context)
        if p2 is None:
            return np.ones(3)
        d = math.hypot(event.mouse_region_x - p2.x, event.mouse_region_y - p2.y)
        s = d / self._start_dist
        if event.shift:
            s = 1.0 + (s - 1.0) * 0.1
        if event.ctrl:
            s = max(0.0, self._snap(s, 0.1))
        return self._vector_for_axis(s)

    def _vector_for_axis(self, s):
        """Uniform when unconstrained; otherwise `s` on every allowed axis
        (one axis, or the two of a Shift+axis plane) and 1 elsewhere."""
        if self._axis is None:
            return np.full(3, float(s))
        mask = self._axis_mask(self._axis)
        return 1.0 + mask * (float(s) - 1.0)

    def _amount_from_number(self, value):
        return self._vector_for_axis(value)

    def _apply_amount(self, amount):
        return fc.apply_scale(self._P0, self._W, self._pivot, amount, basis=self._basis_R)

    def _amount_text(self, amount):
        a = amount.tolist()
        if abs(a[0] - a[1]) < 1e-9 and abs(a[1] - a[2]) < 1e-9:
            return f"{a[0]:.3f}"
        return "({:.3f}, {:.3f}, {:.3f})".format(*a)


classes = (
    IOPS_OT_mesh_falloff_move,
    IOPS_OT_mesh_falloff_rotate,
    IOPS_OT_mesh_falloff_scale,
)
