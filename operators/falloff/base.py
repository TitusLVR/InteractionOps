"""Shared operator base for falloff operations: field-stack snapshot, redo,
and the Blender-style modal.

`FalloffOpMixin` knows nothing about the operation itself. A subclass turns
the mouse / typed number into its own amount properties (`_begin`,
`_update_amount`) and the amount into positions (`_apply`). Everything else
(domain, weights, stack snapshot for F9, copy-back, curve / invert keys,
axis keys, status line, cancel, cleanup) lives here so later operations
(extrude, inset, bevel) can reuse it.

All maths are world space: `P0` / `N` come from `domain.collect_domain`.
"""
from __future__ import annotations

import traceback

import numpy as np
from bpy.props import CollectionProperty, FloatVectorProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ...utils import falloff_core as fc
from ..mesh_shear import DIGIT_TYPES
from . import draw
from .domain import (auto_pivot, basis_matrix, collect_domain, finish_domain,
                     write_back)
from .fields import edit_mesh_poll, ensure_field
from .props import IOPS_FalloffField, active_field, copy_stack, stack_to_list

AXIS_KEYS = ("X", "Y", "Z")
PASS_THROUGH_PREFIXES = ("WHEEL", "NDOF", "TRACKPAD")
PASS_THROUGH_TYPES = {"MIDDLEMOUSE", "MOUSEROTATE", "MOUSESMARTZOOM", "MOUSEPAN"}
MODIFIER_KEYS = {"LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL"}
COPY_BACK_KEYS = ("blend", "strength", "curve", "invert", "enabled")
# Shift: the drag / amount moves this much slower (operators and handles)
PRECISE_FACTOR = 0.1


# ------------------------------------------------------------------ draw hooks
# The scene's fields are drawn while the operator runs, whatever the active
# tool. A drawing failure must never stop the operation.

def draw_begin(op):
    try:
        draw.op_begin(op)
    except Exception:
        traceback.print_exc()


def draw_end(op):
    try:
        draw.op_end(op)
    except Exception:
        traceback.print_exc()


# ------------------------------------------------------------------ helpers

def resolve_pivot(context, domain) -> np.ndarray:
    settings = context.scene.IOPS.falloff
    if settings.use_custom_pivot:
        return np.array(settings.pivot[:], dtype=np.float64)
    return np.asarray(auto_pivot(context, domain), dtype=np.float64)


def toggle_axis(current, key, plane):
    """X/Y/Z → that axis; with `plane`, the plane of the other two. The same
    combination again clears the constraint (None)."""
    new = "".join(a for a in AXIS_KEYS if a != key) if plane else key
    return None if current == new else new


def axis_mask(letters) -> np.ndarray:
    """(3,) 1/0 mask of the allowed basis axes; all ones when unconstrained."""
    if not letters:
        return np.ones(3, dtype=np.float64)
    return np.array([1.0 if a in letters else 0.0 for a in AXIS_KEYS])


def snap(value, step):
    return round(value / step) * step


class FalloffOpMixin:
    """Mixin for `bpy.types.Operator` subclasses. Subclass contract:

    - `op_label` ("Move"), `snap_step`, `allow_planes`, `use_axis_keys`,
      `free_axis_label` (status text when no axis is set)
    - `_apply(P0, W, N)` -> new world positions, from the amount props
    - `_begin(context, event)` -> capture drag start, reset the amount
    - `_update_amount(context, event)` -> mouse / axis / typed -> amount props
    - `_amount_text()` and `draw_amount(layout)`
    """

    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    op_prefix = "Falloff"   # "Field" for the topology / slide operations
    op_label = "Falloff"
    snap_step = 0.1
    allow_planes = False
    use_axis_keys = True
    free_axis_label = "Free"
    _transient = ()        # subclass attributes dropped on finish

    stack: CollectionProperty(type=IOPS_FalloffField, options={"SKIP_SAVE"})
    pivot: FloatVectorProperty(
        name="Pivot", size=3, subtype="TRANSLATION", options={"SKIP_SAVE"},
        description="Pivot used by the operation (world space)")

    @classmethod
    def poll(cls, context):
        return edit_mesh_poll(context)

    # -------------------------------------------------------------- hooks

    def _apply(self, P0, W, N):
        raise NotImplementedError

    def _begin(self, context, event):
        raise NotImplementedError

    def _update_amount(self, context, event):
        raise NotImplementedError

    def _amount_text(self):
        return ""

    def _resolve_unset(self, context, domain):
        """`execute` without the modal: fill amount-side properties the
        caller did not set from the scene (as `pivot` is)."""

    def draw_amount(self, layout):
        pass

    def _extra_key(self, context, event):
        """Operation-specific modal key (pressed, not handled by the base).
        Return True when handled; the result is then recomputed."""
        return False

    # -------------------------------------------------------------- redo / script

    def execute(self, context):
        domain = collect_domain(context)
        if domain is None:
            self.report({"WARNING"}, f"{self.op_prefix} {self.op_label}: no visible vertices")
            return {"CANCELLED"}
        settings = context.scene.IOPS.falloff
        try:
            if len(self.stack) == 0:
                copy_stack(settings.fields, self.stack)
            if not self.properties.is_property_set("pivot"):
                self.pivot = tuple(resolve_pivot(context, domain))
            self._resolve_unset(context, domain)
            W = fc.stack_weights(domain.P, stack_to_list(self.stack))
            write_back(domain, self._apply(domain.P, W, domain.N))
        finally:
            finish_domain(domain)
        self._copy_back(settings)
        return {"FINISHED"}

    def _copy_back(self, settings):
        """Redo-panel edits of blend / strength / curve / invert / enabled go
        back onto the scene fields (matched by position)."""
        if len(self.stack) != len(settings.fields):
            return
        for src, dst in zip(self.stack, settings.fields):
            for k in COPY_BACK_KEYS:
                v = getattr(src, k)
                if getattr(dst, k) != v:
                    setattr(dst, k, v)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        self.draw_amount(layout)
        layout.prop(self, "pivot")
        for f in self.stack:
            box = layout.box()
            box.label(text=f.name)
            box.prop(f, "enabled")
            col = box.column()
            col.active = f.enabled
            col.prop(f, "blend")
            col.prop(f, "strength")
            col.prop(f, "curve")
            col.prop(f, "invert")

    # -------------------------------------------------------------- modal

    def invoke(self, context, event):
        if context.region_data is None:
            self.report({"WARNING"}, f"{self.op_prefix} {self.op_label}: run from a 3D viewport")
            return {"CANCELLED"}
        settings = context.scene.IOPS.falloff
        if not len(settings.fields):
            ensure_field(context)
        domain = collect_domain(context)
        if domain is None:
            self.report({"WARNING"}, f"{self.op_prefix} {self.op_label}: no visible vertices")
            return {"CANCELLED"}
        copy_stack(settings.fields, self.stack)
        self._influence0 = [(f.curve, f.invert) for f in settings.fields]
        if not self.properties.is_property_set("pivot"):
            self.pivot = tuple(resolve_pivot(context, domain))
        self._domain = domain
        self._R = np.asarray(basis_matrix(context, domain), dtype=np.float64)
        self._P0 = domain.P.copy()
        self._N = domain.N.copy()
        self._W = None
        self._recompute_weights()
        self._region = context.region
        self._rv3d = context.region_data
        self._axis = None
        self._input = ""
        self._start_xy = (event.mouse_region_x, event.mouse_region_y)
        self._begin(context, event)
        draw_begin(self)
        self._set_status(context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            self._revert_influence(context)
            self._finish(context)
            self.report({"WARNING"}, f"{self.op_prefix} {self.op_label}: mesh data became invalid")
            return {"CANCELLED"}
        except Exception:
            self._revert_mesh()
            self._revert_influence(context)
            self._finish(context)
            raise

    def cancel(self, context):
        """Blender removed the modal (file load, window closed): what Esc
        does, each step on its own so one failure does not skip the rest."""
        for step in (self._revert_mesh,
                     lambda: self._revert_influence(context),
                     lambda: self._finish(context)):
            try:
                step()
            except Exception:
                traceback.print_exc()

    def _modal(self, context, event):
        et = event.type
        if et in PASS_THROUGH_TYPES or et.startswith(PASS_THROUGH_PREFIXES):
            return {"PASS_THROUGH"}
        if context.area:
            context.area.tag_redraw()

        if et == "MOUSEMOVE" or et in MODIFIER_KEYS:
            self._live(context, event)
            return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if et in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"}:
            self._finish(context)
            return {"FINISHED"}
        if et in {"RIGHTMOUSE", "ESC"}:
            write_back(self._domain, self._P0)
            self._revert_influence(context)
            self._finish(context)
            return {"CANCELLED"}

        if et in DIGIT_TYPES:
            self._input += DIGIT_TYPES[et]
        elif et in {"PERIOD", "NUMPAD_PERIOD"}:
            if "." not in self._input:
                self._input += "."
        elif et in {"MINUS", "NUMPAD_MINUS"}:
            self._input = (self._input[1:] if self._input.startswith("-")
                           else "-" + self._input)
        elif et == "BACK_SPACE":
            self._input = self._input[:-1]
        elif et in AXIS_KEYS and self.use_axis_keys:
            self._axis = toggle_axis(self._axis, et, event.shift and self.allow_planes)
        elif et in {"LEFT_BRACKET", "RIGHT_BRACKET"}:
            self._step_curve(context, 1 if et == "RIGHT_BRACKET" else -1)
        elif et == "I" and event.shift:
            self._toggle_invert(context)
        elif not self._extra_key(context, event):
            return {"RUNNING_MODAL"}
        self._live(context, event)
        return {"RUNNING_MODAL"}

    def _live(self, context, event):
        self._update_amount(context, event)
        write_back(self._domain, self._apply(self._P0, self._W, self._N))
        self._set_status(context)

    def _revert_mesh(self):
        """Best effort: put the geometry back to its state at invoke."""
        try:
            write_back(self._domain, self._P0)
        except Exception:
            pass

    def _revert_influence(self, context):
        """Undo `[` / `]` / Shift+I edits made on the scene fields."""
        saved = getattr(self, "_influence0", None)
        if saved is None:
            return
        try:
            fields = context.scene.IOPS.falloff.fields
            # a field added / removed meanwhile: positions no longer match,
            # so on purpose nothing is reverted
            if len(fields) == len(saved):
                for f, (curve, invert) in zip(fields, saved):
                    f.curve = curve
                    f.invert = invert
        except (AttributeError, ReferenceError):
            pass

    def _finish(self, context):
        self._influence0 = None
        draw_end(self)
        try:
            context.workspace.status_text_set(None)
        except (AttributeError, ReferenceError):
            pass
        domain = getattr(self, "_domain", None)
        if domain is not None:
            finish_domain(domain)
        self._domain = None
        self._P0 = self._N = self._W = None
        self._R = None
        self._region = self._rv3d = None
        for name in self._transient:
            setattr(self, name, None)

    # -------------------------------------------------------------- field keys

    def _recompute_weights(self):
        self._W = fc.stack_weights(self._P0, stack_to_list(self.stack))

    def _active_pair(self, context):
        """(scene field, snapshot field) of the active index, or None."""
        settings = context.scene.IOPS.falloff
        f = active_field(settings)
        i = settings.active_index
        if f is None or i >= len(self.stack):
            return None
        return f, self.stack[i]

    def _step_curve(self, context, step):
        pair = self._active_pair(context)
        if pair is None:
            return
        shapes = fc.SHAPES
        new = shapes[(shapes.index(pair[0].curve) + step) % len(shapes)]
        for f in pair:
            f.curve = new
        self._recompute_weights()

    def _toggle_invert(self, context):
        pair = self._active_pair(context)
        if pair is None:
            return
        new = not pair[0].invert
        for f in pair:
            f.invert = new
        self._recompute_weights()

    # -------------------------------------------------------------- amount helpers

    def _typed_value(self):
        """The typed number, or None when the buffer is empty or not (yet) a
        number ("-", ".")."""
        if not self._input:
            return None
        try:
            return float(self._input)
        except ValueError:
            return None

    def _mouse_xy(self, event):
        return (event.mouse_region_x, event.mouse_region_y)

    def _pivot_vec(self):
        return Vector(self.pivot[:])

    def _pivot_2d(self):
        """Pivot projected to region pixels, or None behind the view."""
        return view3d_utils.location_3d_to_region_2d(
            self._region, self._rv3d, self._pivot_vec())

    def _mouse_on_view_plane(self, xy):
        """Region px -> world point on the view plane through the pivot."""
        p = view3d_utils.region_2d_to_location_3d(
            self._region, self._rv3d, xy, self._pivot_vec())
        return None if p is None else np.array(p[:], dtype=np.float64)

    def _world_per_px(self):
        """World length of one pixel at the pivot (along view right); a
        fraction of the domain size when the view cannot measure it."""
        px = draw.world_per_px(self._region, self._rv3d, self.pivot[:])
        if px <= 0.0:
            P = self._P0
            diag = float(np.linalg.norm(P.max(axis=0) - P.min(axis=0)))
            return max(diag, 1.0) * 0.002
        return px

    def _view_axis(self) -> np.ndarray:
        """World unit vector from the scene toward the viewer."""
        v = self._rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        return np.array(v.normalized()[:], dtype=np.float64)

    def _basis_axis(self, letter) -> np.ndarray:
        return self._R[:, AXIS_KEYS.index(letter)].copy()

    def _constrained_axis(self):
        """Single world axis of the constraint: the basis axis, or for a plane
        the axis perpendicular to it. None when unconstrained."""
        if self._axis is None:
            return None
        if len(self._axis) == 1:
            return self._basis_axis(self._axis)
        return self._basis_axis(next(a for a in AXIS_KEYS if a not in self._axis))

    def _constrain(self, d) -> np.ndarray:
        """Project a world vector onto the allowed basis axes."""
        d = np.asarray(d, dtype=np.float64)
        if not self._axis:
            return d
        return self._R @ ((self._R.T @ d) * axis_mask(self._axis))

    # -------------------------------------------------------------- status

    def _status_text(self, context):
        f = active_field(context.scene.IOPS.falloff)
        name, curve = (f.name, f.curve.replace("_", " ").title()) if f else ("-", "-")
        amount = self._amount_text()
        if self._input:
            amount += f" [{self._input}]"
        axis = self._axis or self.free_axis_label
        return (f"{self.op_prefix} {self.op_label} | Axis {axis} | {amount} | {name} Curve: {curve}"
                " — LMB/Enter confirm, Esc cancel")

    def _set_status(self, context):
        context.workspace.status_text_set(self._status_text(context))
