import bpy
import numpy
from mathutils import Vector
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)
from bpy.props import BoolProperty

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw.theme import get_theme
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState, handle_hud_toggle


_BBOX_EDGES_8 = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)
_BBOX_EDGES_32 = (
    (0, 1), (1, 2), (2, 3), (0, 3),
    (4, 5), (5, 6), (6, 7), (4, 7),
    (0, 4), (1, 5), (3, 7), (2, 6),
    (8, 10), (9, 11),
    (12, 14), (13, 15),
    (16, 17), (8, 12),
    (10, 14), (18, 19),
    (11, 15), (16, 19),
    (17, 18), (9, 13),
    (20, 23), (20, 21),
    (20, 27), (20, 25),
    (20, 31), (20, 29),
)


class IOPS_OT_VisualOrigin(bpy.types.Operator):
    """Visual origin placing helper tool"""

    bl_idname = "iops.object_visual_origin"
    bl_label = "Visual origin"
    bl_options = {"REGISTER", "UNDO"}

    mouse_pos = (0, 0)
    cursor = []
    result = False
    result_obj = None
    vp_objs = []
    vp_group = None

    pos_batch = []
    pos_batch_3d = []

    batch_idx = None
    target = (0, 0)
    target_3d = None

    vp_handlers = []

    hold_cursor: BoolProperty(
        name="Hold cursor",
        description="Hold cursor location and rotation",
        default=True,
    )

    offset_instances: BoolProperty(
        name="Offset instances",
        description="Compensate linked duplicates (objects sharing mesh data) so they don't jump when origin changes",
        default=False,
    )

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and context.view_layer.objects.active.type == "MESH"
            and context.view_layer.objects.selected[:] != []
        )

    def _build_hud(self, context):
        verbosity = get_theme(context).hud.verbosity
        hud = HUDOverlay("visual_origin", verbosity=verbosity)
        hud.add_section(HUDSection("Visual Origin", [
            HUDItem("World space group",         "F1",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Local space for active",    "F2",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("World space for active",    "F3",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Origin → World center",     "W",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Selected → World center",   "M",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Pick active object",        "Shift+LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Offset instances",          "I",         ItemState.ON if self.offset_instances else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Confirm",                   "LMB/Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                    "Esc/RMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        hud.bind_region(context.region)
        return hud

    def _sync_hud(self):
        if getattr(self, "hud", None) is None:
            return
        self.hud.set_state("I", ItemState.ON if self.offset_instances else ItemState.OFF)

    def _draw_hud(self, context):
        if getattr(self, "hud", None) is None:
            return
        self.hud.draw(context, getattr(self, "_last_event", None))

    def _draw_cage_lines(self, context):
        coords3d = self.pos_batch_3d
        if not coords3d:
            return
        n = len(coords3d)
        if n == 8:
            edges = _BBOX_EDGES_8
        elif n >= 32:
            edges = _BBOX_EDGES_32
        else:
            return
        flat = []
        for a, b in edges:
            if a < n and b < n:
                flat.append(coords3d[a])
                flat.append(coords3d[b])
        if not flat:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.edges_3d(flat, role=Role.LINE, context=context)

    def _draw_cage_points(self, context):
        if not self.pos_batch_3d:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.points(list(self.pos_batch_3d), role=Role.POINT, context=context)

    def _draw_active_point(self, context):
        if self.target_3d is None:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.points([self.target_3d], role=Role.CLOSEST_POINT, context=context)

    def get_mesh_instances(self, context, selected_objs):
        selected_set = set(selected_objs)
        selected_meshes = set(ob.data for ob in selected_objs if ob.type == "MESH")
        instances = []
        for ob in bpy.data.objects:
            if ob.type == "MESH" and ob not in selected_set and ob.data in selected_meshes:
                instances.append(ob)
        return instances

    def record_instance_refs(self, instances):
        ref_positions = {}
        for inst in instances:
            if len(inst.data.vertices) > 0:
                ref_positions[inst] = (
                    inst.matrix_world @ inst.data.vertices[0].co.copy()
                )
        return ref_positions

    def compensate_instances(self, instances, ref_positions):
        for inst in instances:
            if inst in ref_positions and len(inst.data.vertices) > 0:
                old_world_pos = ref_positions[inst]
                new_world_pos = inst.matrix_world @ inst.data.vertices[0].co
                shift = new_world_pos - old_world_pos
                if inst.parent:
                    parent_inv = inst.parent.matrix_world.inverted()
                    shift = parent_inv.to_3x3() @ shift
                inst.location -= shift

    def place_origin(self, context):
        objs = list(context.view_layer.objects.selected)
        pos = self.pos_batch_3d[self.batch_idx]
        context.scene.cursor.location = pos

        instances = []
        ref_positions = {}
        if self.offset_instances:
            instances = self.get_mesh_instances(context, objs)
            ref_positions = self.record_instance_refs(instances)

        for ob in objs:
            context.view_layer.objects.active = ob
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

        if self.offset_instances:
            self.compensate_instances(instances, ref_positions)

    def move_selected_to_world(self, context):
        objs = context.view_layer.objects.selected
        for ob in objs:
            ob.location = (0, 0, 0)

    def origin_to_world(self, context):
        objs = list(context.view_layer.objects.selected)
        context.scene.cursor.location = (0, 0, 0)
        context.scene.cursor.rotation_euler = (0, 0, 0)

        instances = []
        ref_positions = {}
        if self.offset_instances:
            instances = self.get_mesh_instances(context, objs)
            ref_positions = self.record_instance_refs(instances)

        for ob in objs:
            context.view_layer.objects.active = ob
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

        if self.offset_instances:
            self.compensate_instances(instances, ref_positions)

    def calc_distance(self, context):
        # Re-project bbox to 2D each call. Without this, viewport navigation
        # leaves pos_batch stale and the highlighted point drifts from where
        # the cursor actually is.
        self.object_bbox(context)
        mouse_pos = self.mouse_pos
        pos_batch = self.pos_batch
        if len(pos_batch) != 0:
            act_dist = numpy.linalg.norm(pos_batch[0] - Vector(mouse_pos))
            act_id = 0
            counter = 1
            itertargets = iter(self.pos_batch)
            next(itertargets)
            for pos in itertargets:
                dist = numpy.linalg.norm(pos - Vector(mouse_pos))
                if dist < act_dist:
                    act_id = counter
                    act_dist = dist
                counter += 1
            self.batch_idx = act_id
            self.target = pos_batch[act_id]
            self.target_3d = self.pos_batch_3d[act_id] if act_id < len(self.pos_batch_3d) else None

    def getActiveFromSelected(self, context):
        selected_objects = []
        active_object = None
        for ob in context.view_layer.objects.selected:
            if ob.type == "MESH":
                selected_objects.append(ob)
        for ob in selected_objects:
            if ob == context.view_layer.objects.active:
                active_object = ob

        return active_object, selected_objects

    def orphan_data_purge(self, context):
        for block in bpy.data.meshes:
            if block.users == 0:
                bpy.data.meshes.remove(block)
        for block in bpy.data.materials:
            if block.users == 0:
                bpy.data.materials.remove(block)
        for block in bpy.data.textures:
            if block.users == 0:
                bpy.data.textures.remove(block)
        for block in bpy.data.images:
            if block.users == 0:
                bpy.data.images.remove(block)

    def getBBOX_from_selected(self, context):
        sel_objs = []
        for ob in context.view_layer.objects.selected:
            if ob.type == "MESH":
                sel_objs.append(ob)
        dups = []
        for ob in sel_objs:
            matrix = ob.matrix_world
            dup_mesh = ob.data.copy()
            dup_obj = bpy.data.objects.new("iops_dups", dup_mesh)
            dup_obj.matrix_world = matrix
            context.scene.collection.objects.link(dup_obj)
            dups.append(dup_obj)
        for ob in sel_objs:
            ob.select_set(False)
        for ob in dups:
            ob.select_set(True)
        context.view_layer.objects.active = dups[-1]
        view = bpy.context.space_data
        if view.local_view:
            bpy.ops.view3d.localview(frame_selected=False)
        if len(dups) != 1:
            bpy.ops.object.join()
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        else:
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        dup = context.view_layer.objects.active
        dup_bounds = dup.bound_box
        bbox_verts = []
        for v in dup_bounds:
            bbox_verts.append(Vector(v))

        bpy.data.objects.remove(dup, do_unlink=True, do_id_user=True, do_ui_user=True)

        mesh = bpy.data.meshes.new("iops_bbox_mesh")
        mesh.from_pydata(bbox_verts, [], [])
        bbox = bpy.data.objects.new("iops_bbox", mesh)
        context.scene.collection.objects.link(bbox)

        for ob in sel_objs:
            ob.select_set(True)
        context.view_layer.objects.active = sel_objs[-1]

        if self.vp_group is None:
            self.result = True
            self.result_obj = bbox
            self.vp_group = bbox

    def active_to_world(self, context):
        sel_objs = []
        for ob in context.view_layer.objects.selected:
            if ob.type == "MESH":
                sel_objs.append(ob)

        obj = context.view_layer.objects.active
        matrix = obj.matrix_world
        dup_mesh = obj.data.copy()
        dup_obj = bpy.data.objects.new("iops_dups", dup_mesh)
        dup_obj.matrix_world = matrix
        context.scene.collection.objects.link(dup_obj)
        for ob in sel_objs:
            ob.select_set(False)
        dup_obj.select_set(True)
        context.view_layer.objects.active = dup_obj
        view = bpy.context.space_data
        if view.local_view:
            bpy.ops.view3d.localview(frame_selected=False)
        bpy.ops.object.transform_apply(
            location=True, rotation=True, scale=True, properties=True
        )

        dup_bounds = dup_obj.bound_box
        bbox_verts = []
        for v in dup_bounds:
            bbox_verts.append(Vector(v))
        bpy.data.objects.remove(
            dup_obj, do_unlink=True, do_id_user=True, do_ui_user=True
        )

        mesh = bpy.data.meshes.new("iops_bbox_mesh")
        mesh.from_pydata(bbox_verts, [], [])
        bbox = bpy.data.objects.new("iops_bbox", mesh)
        context.scene.collection.objects.link(bbox)
        for ob in sel_objs:
            ob.select_set(True)
        context.view_layer.objects.active = obj
        if self.vp_group is None:
            self.result = True
            self.result_obj = bbox
            self.vp_group = bbox

    def scene_ray_cast(self, context):
        from ..utils.picking import raycast_from_mouse
        result, _location, _normal, _idx, obj, _mat = raycast_from_mouse(
            context, self.mouse_pos)
        if result and obj in self.vp_objs:
            context.view_layer.objects.active = obj
            self.result_obj = obj
        return result, obj

    def object_bbox(self, context):
        region = context.region
        rv3d = context.region_data
        obj = self.result_obj

        bbox_batch = []
        bbox_batch_3d = []
        if obj is not None:
            matrix = obj.matrix_world
            matrix_trans = matrix.transposed()
            bbox = obj.bound_box
            bbox_verts_3d = []
            if len(bbox) != 0:
                bbox_edges = (
                    (0, 1), (1, 2), (2, 3), (0, 3),
                    (4, 5), (5, 6), (6, 7), (4, 7),
                    (0, 4), (1, 5), (2, 6), (3, 7),
                    (0, 6),
                )
                bbox_subd_edges = (
                    (8, 10), (9, 11),
                    (12, 14), (13, 15),
                    (16, 17), (8, 12),
                    (10, 14), (18, 19),
                    (11, 15), (16, 19),
                    (17, 18), (9, 13),
                )

                for v in bbox:
                    pos = Vector(v) @ matrix_trans
                    bbox_verts_3d.append(pos)

                for e in bbox_edges:
                    v1 = Vector(bbox[e[0]])
                    v2 = Vector(bbox[e[1]])
                    vertmid = (v1 + v2) / 2
                    pos = Vector(vertmid) @ matrix_trans
                    bbox_verts_3d.append(pos)

                for e in bbox_subd_edges:
                    v1 = Vector(bbox_verts_3d[e[0]])
                    v2 = Vector(bbox_verts_3d[e[1]])
                    vertmid = (v1 + v2) / 2
                    pos = Vector(vertmid)
                    bbox_verts_3d.append(pos)

                for v in bbox_verts_3d:
                    pos3D = v
                    pos2D = location_3d_to_region_2d(region, rv3d, pos3D, default=None)
                    if pos2D is None:
                        pos2D = Vector((0, 0))
                    bbox_batch_3d.append(pos3D)
                    bbox_batch.append(pos2D)

            self.pos_batch = bbox_batch
            self.pos_batch_3d = bbox_batch_3d
            return [bbox_batch, bbox_batch_3d]
        else:
            self.pos_batch = []
            self.pos_batch_3d = []
            return [bbox_batch, bbox_batch]

    def clear_draw_handlers(self):
        for handler in self.vp_handlers:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")

    def execute(self, context):
        self.place_origin(context)
        if self.vp_group is not None:
            bpy.data.objects.remove(
                self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
            )
            self.vp_group = None
        try:
            self.clear_draw_handlers()
        except ValueError:
            pass
        self.orphan_data_purge(context)
        return {"FINISHED"}

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event
        if handle_hud_toggle(getattr(self, "_hud", None) or getattr(self, "hud", None), context, event):
            return {'RUNNING_MODAL'}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        elif event.shift:
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                self.mouse_pos = event.mouse_region_x, event.mouse_region_y
                self.scene_ray_cast(context)
                self.object_bbox(context)
                self.calc_distance(context)
                if self.vp_group is not None:
                    bpy.data.objects.remove(
                        self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                    )
                    self.vp_group = None
                    self.orphan_data_purge(context)
        elif event.type == "F3" and event.value == "PRESS":
            if self.vp_group is not None:
                bpy.data.objects.remove(
                    self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                )
                self.vp_group = None
                self.orphan_data_purge(context)
            if self.vp_group is None:
                self.active_to_world(context)
                self.object_bbox(context)
                self.calc_distance(context)

        elif event.type == "F1" and event.value == "PRESS":
            if self.vp_group is not None:
                bpy.data.objects.remove(
                    self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                )
                self.vp_group = None
                self.orphan_data_purge(context)
            if self.vp_group is None:
                self.getBBOX_from_selected(context)
                self.object_bbox(context)
                self.calc_distance(context)
                self.orphan_data_purge(context)

        elif event.type == "F2" and event.value == "PRESS":
            self.result_obj, self.vp_objs = self.getActiveFromSelected(context)
            self.object_bbox(context)
            self.calc_distance(context)
            if self.vp_group is not None:
                bpy.data.objects.remove(
                    self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                )
                self.vp_group = None
                self.orphan_data_purge(context)

        elif event.type == "W" and event.value == "PRESS":
            self.origin_to_world(context)
            if self.vp_group is not None:
                bpy.data.objects.remove(
                    self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                )
            self.vp_group = None
            self.clear_draw_handlers()
            self.orphan_data_purge(context)
            return {"FINISHED"}

        elif event.type == "M" and event.value == "PRESS":
            self.move_selected_to_world(context)
            if self.vp_group is not None:
                bpy.data.objects.remove(
                    self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                )
            self.vp_group = None
            self.clear_draw_handlers()
            self.orphan_data_purge(context)
            return {"FINISHED"}

        elif event.type == "I" and event.value == "PRESS":
            self.offset_instances = not self.offset_instances
            self._sync_hud()

        elif event.type == "MOUSEMOVE":
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            self.calc_distance(context)

        elif event.type in {"LEFTMOUSE", "SPACE"}:
            self.execute(context)
            if self.hold_cursor:
                context.scene.cursor.location = self.cursor[0]
                context.scene.cursor.rotation_euler = self.cursor[1]
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self.mouse_pos = [0, 0]
            self.result = False
            self.result_obj = None
            if self.vp_group:
                bpy.data.objects.remove(
                    self.vp_group, do_unlink=True, do_id_user=True, do_ui_user=True
                )
            self.clear_draw_handlers()
            self.orphan_data_purge(context)
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.space_data.type != "VIEW_3D":
            self.report({"WARNING"}, "Active space must be a View3d")
            return {"CANCELLED"}

        self.cursor = [
            context.scene.cursor.location.copy(),
            context.scene.cursor.rotation_euler.copy(),
        ]
        self.mouse_pos = event.mouse_region_x, event.mouse_region_y
        self.result_obj, self.vp_objs = self.getActiveFromSelected(context)
        self.object_bbox(context)
        self.calc_distance(context)

        self.hud = self._build_hud(context)
        self._last_event = event

        self._handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        self._handle_bbox_lines = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cage_lines, (context,), "WINDOW", "POST_VIEW"
        )
        self._handle_bbox_points = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cage_points, (context,), "WINDOW", "POST_VIEW"
        )
        self._handle_bbox_act_point = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_active_point, (context,), "WINDOW", "POST_VIEW"
        )
        self.vp_handlers = [
            self._handle_iops_text,
            self._handle_bbox_lines,
            self._handle_bbox_points,
            self._handle_bbox_act_point,
        ]
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
