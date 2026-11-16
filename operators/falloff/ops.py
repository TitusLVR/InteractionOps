"""Falloff Move / Rotate / Scale / Normal Offset.

Each operator only maps the mouse (or a typed number) to its amount
properties and the amount to positions; the stack snapshot, redo, modal keys
and cleanup come from `FalloffOpMixin`. Amounts are world space so `execute`
(F9 / scripts) replays exactly what the modal showed.
"""
from __future__ import annotations

import math

import bpy
import numpy as np
from bpy.props import FloatProperty, FloatVectorProperty

from ...utils import falloff_core as fc
from .base import PRECISE_FACTOR, FalloffOpMixin, axis_mask, snap
from .domain import basis_matrix

_IDENTITY9 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _wrap_pi(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def _f3(v):
    return tuple(float(x) for x in v)


class IOPS_OT_mesh_falloff_move(FalloffOpMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_move"
    bl_label = "iOps Falloff Move"
    bl_description = "Move the selection, weighted by the scene's falloff fields"
    op_label = "Move"
    allow_planes = True
    snap_step = 0.1
    _transient = ("_start",)

    value: FloatVectorProperty(name="Move", size=3, subtype="TRANSLATION",
                               options={"SKIP_SAVE"},
                               description="World-space offset at full weight")

    def _apply(self, P0, W, N):
        return fc.apply_move(P0, W, self.value)

    def _begin(self, context, event):
        self._start = self._mouse_on_view_plane(self._start_xy)
        self.value = (0.0, 0.0, 0.0)

    def _update_amount(self, context, event):
        typed = self._typed_value()
        if typed is not None:
            # along the (first) constrained basis axis; basis X when free
            letter = self._axis[0] if self._axis else "X"
            self.value = _f3(self._basis_axis(letter) * typed)
            return
        cur = self._mouse_on_view_plane(self._mouse_xy(event))
        if cur is None or self._start is None:
            return
        d = cur - self._start
        if event.shift:
            d = d * PRECISE_FACTOR
        d = self._constrain(d)
        if event.ctrl:
            # snap the basis components, not the world ones
            db = np.array([snap(c, self.snap_step) for c in self._R.T @ d])
            d = self._R @ db
        self.value = _f3(d)

    def _amount_text(self):
        return "({:.3f}, {:.3f}, {:.3f})".format(*self.value)

    def draw_amount(self, layout):
        layout.prop(self, "value")


class IOPS_OT_mesh_falloff_rotate(FalloffOpMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_rotate"
    bl_label = "iOps Falloff Rotate"
    bl_description = ("Rotate the selection about the pivot, weighted by the "
                      "scene's falloff fields (view axis unless X/Y/Z is set)")
    op_label = "Rotate"
    snap_step = math.radians(5.0)
    free_axis_label = "View"

    angle: FloatProperty(name="Angle", subtype="ANGLE", options={"SKIP_SAVE"},
                         description="Angle at full weight")
    axis: FloatVectorProperty(name="Axis", size=3, subtype="XYZ",
                              default=(0.0, 0.0, 1.0), options={"SKIP_SAVE"},
                              description="World-space rotation axis")

    def _apply(self, P0, W, N):
        return fc.apply_rotate(P0, W, self.pivot, self.axis, self.angle)

    def _mouse_angle(self, xy):
        p2 = self._pivot_2d()
        if p2 is None:
            return None
        return math.atan2(xy[1] - p2.y, xy[0] - p2.x)

    def _begin(self, context, event):
        a = self._mouse_angle(self._start_xy)
        self._prev_angle = 0.0 if a is None else a
        self._accum = 0.0
        self.angle = 0.0
        self.axis = _f3(self._view_axis())

    def _update_amount(self, context, event):
        a = self._mouse_angle(self._mouse_xy(event))
        if a is not None:
            self._accum += _wrap_pi(a - self._prev_angle)
            self._prev_angle = a
        ax = self._constrained_axis()
        view = self._view_axis()
        self.axis = _f3(ax if ax is not None else view)
        typed = self._typed_value()
        if typed is not None:
            self.angle = math.radians(typed)
            return
        theta = self._accum
        if event.shift:
            theta *= PRECISE_FACTOR
        if event.ctrl:
            theta = snap(theta, self.snap_step)
        # counter-clockwise on screen is positive about an axis toward the
        # viewer; flip when the chosen axis points away
        if ax is not None and float(ax @ view) < 0.0:
            theta = -theta
        self.angle = theta

    def _amount_text(self):
        return f"{math.degrees(self.angle):.2f}°"

    def draw_amount(self, layout):
        layout.prop(self, "angle")
        layout.prop(self, "axis")


class IOPS_OT_mesh_falloff_scale(FalloffOpMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_scale"
    bl_label = "iOps Falloff Scale"
    bl_description = ("Scale the selection about the pivot, weighted by the "
                      "scene's falloff fields")
    op_label = "Scale"
    allow_planes = True
    snap_step = 0.1

    factor: FloatVectorProperty(name="Scale", size=3, default=(1.0, 1.0, 1.0),
                                options={"SKIP_SAVE"},
                                description="Scale along the orientation axes at full weight")
    orient: FloatVectorProperty(name="Orientation", size=9, default=_IDENTITY9,
                                options={"SKIP_SAVE"},
                                description="World-space axes of the scale, "
                                            "columns X, Y, Z flattened")

    def _orient_matrix(self):
        # orient[0:3] is the X column, [3:6] Y, [6:9] Z
        return np.array(self.orient[:], dtype=np.float64).reshape(3, 3).T

    def _resolve_unset(self, context, domain):
        # a scripted call without `orient` scales along the Basis axes
        if not self.properties.is_property_set("orient"):
            R = np.asarray(basis_matrix(context, domain), dtype=np.float64)
            self.orient = tuple(float(x) for x in R.T.reshape(9))

    def _apply(self, P0, W, N):
        return fc.apply_scale(P0, W, self.pivot, self.factor, basis=self._orient_matrix())

    def _begin(self, context, event):
        p2 = self._pivot_2d()
        sx, sy = self._start_xy
        self._start_dist = (max(1.0, math.hypot(sx - p2.x, sy - p2.y))
                            if p2 is not None else 1.0)
        self.factor = (1.0, 1.0, 1.0)
        self.orient = tuple(float(x) for x in self._R.T.reshape(9))

    def _vector_for_axis(self, s):
        """Uniform when free; `s` on the allowed axes, 1 elsewhere."""
        return _f3(1.0 + axis_mask(self._axis) * (float(s) - 1.0))

    def _update_amount(self, context, event):
        typed = self._typed_value()
        if typed is not None:
            self.factor = self._vector_for_axis(typed)
            return
        p2 = self._pivot_2d()
        if p2 is None:
            return
        x, y = self._mouse_xy(event)
        s = math.hypot(x - p2.x, y - p2.y) / self._start_dist
        if event.shift:
            s = 1.0 + (s - 1.0) * PRECISE_FACTOR
        if event.ctrl:
            s = max(0.0, snap(s, self.snap_step))
        self.factor = self._vector_for_axis(s)

    def _amount_text(self):
        a = self.factor
        if abs(a[0] - a[1]) < 1e-9 and abs(a[1] - a[2]) < 1e-9:
            return f"{a[0]:.3f}"
        return "({:.3f}, {:.3f}, {:.3f})".format(*a)

    def draw_amount(self, layout):
        layout.prop(self, "factor")


class IOPS_OT_mesh_falloff_normal_offset(FalloffOpMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_normal_offset"
    bl_label = "iOps Falloff Normal Offset"
    bl_description = ("Push the selection along its vertex normals, weighted "
                      "by the scene's falloff fields")
    op_label = "Normal Offset"
    snap_step = 0.1
    use_axis_keys = False
    free_axis_label = "Normal"

    distance: FloatProperty(name="Distance", subtype="DISTANCE", options={"SKIP_SAVE"},
                            description="Offset along the normal at full weight")

    def _apply(self, P0, W, N):
        return fc.apply_normal_offset(P0, W, N, self.distance)

    def _begin(self, context, event):
        p2 = self._pivot_2d()
        sx, sy = self._start_xy
        self._start_dist = math.hypot(sx - p2.x, sy - p2.y) if p2 is not None else None
        self.distance = 0.0

    def _update_amount(self, context, event):
        typed = self._typed_value()
        if typed is not None:
            self.distance = typed
            return
        p2 = self._pivot_2d()
        if p2 is None or self._start_dist is None:
            return
        x, y = self._mouse_xy(event)
        # signed change of the mouse's distance from the pivot, in world units
        d = (math.hypot(x - p2.x, y - p2.y) - self._start_dist) * self._world_per_px()
        if event.shift:
            d *= PRECISE_FACTOR
        if event.ctrl:
            d = snap(d, self.snap_step)
        self.distance = d

    def _amount_text(self):
        return f"{self.distance:.3f}"

    def draw_amount(self, layout):
        layout.prop(self, "distance")


classes = (
    IOPS_OT_mesh_falloff_move,
    IOPS_OT_mesh_falloff_rotate,
    IOPS_OT_mesh_falloff_scale,
    IOPS_OT_mesh_falloff_normal_offset,
)
