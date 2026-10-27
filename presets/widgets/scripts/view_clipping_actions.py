# View clipping actions for the built-in view_clipping widget. Fired via
# iops.executor (script "view_clipping_actions.py") with self.args = action
# token (start_x10, start_d10, end_x10, end_d10, fit, reset).
#
# iops.executor runs this file via exec() inside a function scope, so
# file-level names (including imports) are invisible to nested scopes —
# keep all logic AND imports inside one def and pass self.args in.
def _clip(action):
    import bpy
    from mathutils import Vector

    sp = bpy.context.space_data
    if sp is None or sp.type != 'VIEW_3D':
        return
    if action == "start_x10":
        sp.clip_start = min(sp.clip_start * 10.0, sp.clip_end / 2.0)
    elif action == "start_d10":
        sp.clip_start = max(sp.clip_start / 10.0, 1e-5)
    elif action == "end_x10":
        sp.clip_end = min(sp.clip_end * 10.0, 1e8)
    elif action == "end_d10":
        sp.clip_end = max(sp.clip_end / 10.0, sp.clip_start * 10.0, 1.0)
    elif action == "reset":
        sp.clip_start = 0.01
        sp.clip_end = 1000.0
    elif action == "fit":
        ctx = bpy.context
        objs = ctx.selected_objects or ctx.visible_objects
        pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
        if not pts:
            return
        lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
        radius = max((hi - lo).length / 2.0, 1.0)
        # keep near/far ratio ~1e5-1e6 so the depth buffer stays usable
        sp.clip_start = min(max(radius / 1e5, 1e-4), 1.0)
        sp.clip_end = min(max(radius * 10.0, sp.clip_start * 1e4), 1e8)


_clip(self.args)
