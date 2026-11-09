import os
import bmesh
import bpy
from math import radians
from ..utils.functions import with_progress


def get_smooth_by_angle_node_group():
    """Return the essentials 'Smooth by Angle' node group, linking it once
    if it is not in the file yet.

    bpy.ops.object.shade_auto_smooth resolves the node group through the
    asset system on every call, which stalls for seconds in files with
    linked libraries — so we fetch the group directly instead.
    """
    for ng in bpy.data.node_groups:
        if (
            ng.name == "Smooth by Angle"
            and ng.library
            and "geometry_nodes_essentials" in ng.library.filepath
        ):
            return ng

    path = os.path.join(
        bpy.utils.system_resource("DATAFILES"),
        "assets",
        "nodes",
        "geometry_nodes_essentials.blend",
    )
    with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
        data_to.node_groups = [
            name for name in data_from.node_groups if name == "Smooth by Angle"
        ]
    return data_to.node_groups[0] if data_to.node_groups else None


class IOPS_OT_AutoSmooth(bpy.types.Operator):
    bl_idname = "iops.object_auto_smooth"
    bl_description = "Add Auto Smooth to selected objects"
    bl_label = "Add Auto Smooth"
    bl_options = {"REGISTER", "UNDO"}

    angle: bpy.props.FloatProperty(
        name="Smooth Angle",
        description="Smooth Angle",
        default=30.0,
        min=0.0,
        max=180.0,
    )

    @classmethod
    def poll(self, context):
        # True if any of the selected objects are meshes
        return any(obj.type == "MESH" for obj in bpy.context.selected_objects)

    def execute(self, context):
        # Get all mesh objects
        meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
        if not meshes:
            return {"FINISHED"}
        
        angle_rad = radians(self.angle)
        
        # Track and handle edit mode
        # Store original mode states and active object
        original_active = context.active_object
        objects_in_edit_mode = []
        
        # Check which objects are in edit mode and exit temporarily
        for obj in meshes:
            if obj.mode == 'EDIT':
                objects_in_edit_mode.append(obj)
                # Exit edit mode for this object
                with context.temp_override(object=obj):
                    bpy.ops.object.mode_set(mode='OBJECT')
        
        try:
            node_group = get_smooth_by_angle_node_group()
            if node_group is None:
                self.report({"ERROR"}, "Smooth by Angle node group not found")
                return {"CANCELLED"}

            angle_socket = next(
                (
                    item.identifier
                    for item in node_group.interface.items_tree
                    if item.item_type == "SOCKET"
                    and item.in_out == "INPUT"
                    and item.name == "Angle"
                ),
                None,
            )

            for mesh in with_progress(meshes, prefix="Adding Auto Smooth"):
                # First delete all modifiers with names containing "Auto Smooth" or "Smooth by Angle"
                for mod in [
                    mod
                    for mod in mesh.modifiers
                    if mod.type == "NODES"
                    and ("Auto Smooth" in mod.name or "Smooth by Angle" in mod.name)
                ]:
                    mesh.modifiers.remove(mod)

                # Shade smooth the mesh data
                mesh.data.polygons.foreach_set(
                    "use_smooth", [True] * len(mesh.data.polygons)
                )
                mesh.data.update()

                # Add the modifier directly and move it to the top of the stack
                mod = mesh.modifiers.new("Smooth by Angle", "NODES")
                mod.node_group = node_group
                if angle_socket:
                    getattr(mod.properties.inputs, angle_socket).value = angle_rad
                if len(mesh.modifiers) > 1:
                    mesh.modifiers.move(len(mesh.modifiers) - 1, 0)
        
        finally:
            # Restore edit mode for objects that were in edit mode
            for obj in objects_in_edit_mode:
                if obj and obj.name in context.scene.objects:
                    # Only restore if object still exists and is still selected
                    if obj in context.selected_objects:
                        with context.temp_override(object=obj):
                            bpy.ops.object.mode_set(mode='EDIT')
            
            # Restore original active object if it still exists
            if original_active and original_active.name in context.scene.objects:
                context.view_layer.objects.active = original_active

        return {"FINISHED"}


class IOPS_OT_ClearCustomNormals(bpy.types.Operator):
    bl_idname = "iops.object_clear_normals"
    bl_description = "Remove custom normals from selected objects"
    bl_label = "Clear Custom Normals"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        # True if any of the selected objects are meshes and have custom normals (obj.data.has_custom_normals)
        return any(
            obj.type == "MESH" and getattr(obj.data, "has_custom_normals", False)
            for obj in bpy.context.selected_objects
        )

    def execute(self, context):
        count = 1
        for obj in bpy.context.selected_objects:
            print(
                f"Clearing custom normals from {obj.name}, {count} of {len(bpy.context.selected_objects)}"
            )
            count += 1
            with bpy.context.temp_override(object=obj):
                if obj.type == "MESH":
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
        return {"FINISHED"}


def get_auto_smooth_modifiers(obj):
    """Geometry Nodes 'Smooth by Angle' / 'Auto Smooth' modifiers on ``obj``."""
    return [
        mod
        for mod in obj.modifiers
        if mod.type == "NODES"
        and (
            "Auto Smooth" in mod.name
            or "Smooth by Angle" in mod.name
            or (
                mod.node_group is not None
                and mod.node_group.name.startswith(("Smooth by Angle", "Auto Smooth"))
            )
        )
    ]


def _is_linked(obj):
    return obj.library is not None or (
        obj.data is not None and getattr(obj.data, "library", None) is not None
    )


_SHADE_TYPES = {"MESH", "CURVE", "SURFACE"}


def _mesh_bm(context, obj):
    """BMesh for ``obj``: the live edit-mesh in Edit Mode, else a fresh copy."""
    if context.mode == "EDIT_MESH":
        return bmesh.from_edit_mesh(obj.data), True
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm, False


def _mesh_bm_commit(obj, bm, is_edit):
    if is_edit:
        bmesh.update_edit_mesh(obj.data)
    else:
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()


class IOPS_OT_Object_Shade(bpy.types.Operator):
    bl_idname = "iops.object_shade"
    bl_label = "Shade"
    bl_options = {"REGISTER", "UNDO"}

    shade_type: bpy.props.EnumProperty(
        name="Shade",
        items=[
            ("SMOOTH", "Smooth", "Shade smooth, keep Auto Smooth modifiers"),
            ("FLAT", "Flat", "Shade flat and remove Auto Smooth modifiers"),
        ],
        default="SMOOTH",
    )
    include_children: bpy.props.BoolProperty(
        name="Include Children",
        description="Also shade all children of the selected objects",
        default=False,
    )

    sharpen: bpy.props.BoolProperty(
        name="Mark Sharp",
        description="Mark edges sharp where the face angle exceeds Angle",
        default=False,
    )
    sharp_angle: bpy.props.FloatProperty(name="Angle", default=20.0, min=0.0, max=180.0)
    sharpen_additively: bpy.props.BoolProperty(
        name="Additive",
        description="Keep existing sharp edges instead of replacing them",
        default=True,
    )

    clear: bpy.props.BoolProperty(
        name="Clear Edge Data",
        description="Clear sharps, bevel weights, creases and seams",
        default=False,
    )
    clear_sharps: bpy.props.BoolProperty(name="Sharps", default=True)
    clear_bweights: bpy.props.BoolProperty(name="BWeights", default=True)
    clear_creases: bpy.props.BoolProperty(name="Creases", default=True)
    clear_seams: bpy.props.BoolProperty(name="Seams", default=True)
    avoid_clearing_subd_creases: bpy.props.BoolProperty(
        name="Keep SubD Creases",
        description="Keep creases on objects with a Subdivision modifier using creases",
        default=True,
    )

    @classmethod
    def description(cls, context, properties):
        if properties.shade_type == "FLAT":
            desc = (
                "Shade Flat (removes Auto Smooth modifiers)\n"
                "ALT: Clear sharps, bevel weights, creases and seams"
            )
        else:
            desc = (
                "Shade Smooth (keeps Auto Smooth modifiers)\n"
                "ALT: Mark edges sharp by face angle"
            )
        desc += "\nSHIFT: Include children"
        if context and context.mode == "EDIT_MESH":
            desc += "\nEdit Mode: edge operations affect selected edges only"
        return desc

    @classmethod
    def poll(cls, context):
        if context.mode == "EDIT_MESH":
            return True
        return context.mode == "OBJECT" and any(
            obj.type in _SHADE_TYPES for obj in context.selected_objects
        )

    def invoke(self, context, event):
        if self.shade_type == "SMOOTH":
            self.sharpen = event.alt
        else:
            self.clear = event.alt
        self.include_children = event.shift
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.row(align=True).prop(self, "shade_type", expand=True)
        if self.shade_type == "SMOOTH":
            row = col.row(align=True)
            row.prop(self, "sharpen", toggle=True)
            sub = row.row(align=True)
            sub.active = self.sharpen
            sub.prop(self, "sharpen_additively", text="", icon="ADD")
            sub.prop(self, "sharp_angle")
        else:
            col.prop(self, "clear", toggle=True)
            row = col.row(align=True)
            row.active = self.clear
            row.prop(self, "clear_sharps", toggle=True)
            row.prop(self, "clear_bweights", toggle=True)
            row.prop(self, "clear_creases", toggle=True)
            row.prop(self, "clear_seams", toggle=True)
            sub = col.row(align=True)
            sub.active = self.clear and self.clear_creases
            sub.prop(self, "avoid_clearing_subd_creases", toggle=True)
        if context.mode == "OBJECT":
            col.separator()
            col.prop(self, "include_children", toggle=True)

    def _gather_objects(self, context):
        selected = [
            obj
            for obj in context.selected_objects
            if obj.type in _SHADE_TYPES and not _is_linked(obj)
        ]
        if not self.include_children:
            return selected
        scene_objects = context.scene.objects
        result = list(selected)
        for obj in selected:
            for child in obj.children_recursive:
                if (
                    child.type in _SHADE_TYPES
                    and not _is_linked(child)
                    and child.name in scene_objects
                    and child not in result
                ):
                    result.append(child)
        return result

    def execute(self, context):
        smooth = self.shade_type == "SMOOTH"
        is_edit = context.mode == "EDIT_MESH"

        if is_edit:
            if smooth:
                bpy.ops.mesh.faces_shade_smooth()
            else:
                bpy.ops.mesh.faces_shade_flat()
            objects = [o for o in context.objects_in_mode if o.type == "MESH"]
        else:
            objects = self._gather_objects(context)

        removed = 0
        done_data = set()
        for obj in objects:
            if not is_edit and not smooth:
                for mod in get_auto_smooth_modifiers(obj):
                    obj.modifiers.remove(mod)
                    removed += 1
            if obj.data.name_full in done_data:
                continue
            done_data.add(obj.data.name_full)

            if not is_edit:
                if obj.type == "MESH":
                    if smooth:
                        obj.data.shade_smooth()
                    else:
                        obj.data.shade_flat()
                    obj.data.update()
                else:
                    for spline in obj.data.splines:
                        spline.use_smooth = smooth
                    obj.data.update_tag()

            if obj.type != "MESH":
                continue
            if smooth and self.sharpen:
                self._set_sharp_edges(context, obj)
            elif not smooth and self.clear:
                self._clear_edge_data(context, obj)

        space = context.space_data
        if smooth and self.sharpen and space is not None and space.type == "VIEW_3D":
            space.overlay.show_edge_sharp = True

        msg = f"{len(objects)} object(s) shaded {'smooth' if smooth else 'flat'}"
        if removed:
            msg += f", {removed} Auto Smooth modifier(s) removed"
        if smooth and self.sharpen:
            msg += f", sharp edges marked at {self.sharp_angle:g} deg"
        elif not smooth and self.clear:
            msg += ", edge data cleared"
        self.report({"INFO"}, msg)
        return {"FINISHED"}

    def _set_sharp_edges(self, context, obj):
        bm, is_edit = _mesh_bm(context, obj)
        bm.normal_update()
        angle = radians(self.sharp_angle)
        for e in bm.edges:
            if is_edit and not e.select:
                continue
            is_sharp = len(e.link_faces) == 2 and e.calc_face_angle(0.0) > angle
            if is_sharp:
                e.smooth = False
            elif not self.sharpen_additively:
                e.smooth = True
        _mesh_bm_commit(obj, bm, is_edit)

    def _clear_edge_data(self, context, obj):
        keep_creases = self.avoid_clearing_subd_creases and any(
            mod.type == "SUBSURF" and mod.use_creases for mod in obj.modifiers
        )
        bm, is_edit = _mesh_bm(context, obj)
        floats = bm.edges.layers.float
        bw = floats.get("bevel_weight_edge") if self.clear_bweights else None
        cr = floats.get("crease_edge") if self.clear_creases and not keep_creases else None
        for e in bm.edges:
            if is_edit and not e.select:
                continue
            if self.clear_sharps:
                e.smooth = True
            if self.clear_seams:
                e.seam = False
            if bw is not None:
                e[bw] = 0.0
            if cr is not None:
                e[cr] = 0.0
        _mesh_bm_commit(obj, bm, is_edit)


class IOPS_OT_Object_Auto_Smooth_Toggle(bpy.types.Operator):
    """Toggle Auto Smooth on selected meshes.
Removes it when the active object has it, otherwise adds it"""

    bl_idname = "iops.object_auto_smooth_toggle"
    bl_label = "Toggle Auto Smooth"
    bl_options = {"REGISTER", "UNDO"}

    angle: bpy.props.FloatProperty(
        name="Smooth Angle",
        description="Angle used when Auto Smooth is added",
        default=30.0,
        min=0.0,
        max=180.0,
    )

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"} and any(
            obj.type == "MESH" for obj in context.selected_objects
        )

    def execute(self, context):
        active = context.active_object
        meshes = [
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj.library is None
        ]
        reference = active if active in meshes else meshes[0]

        if get_auto_smooth_modifiers(reference):
            removed = 0
            for obj in meshes:
                for mod in get_auto_smooth_modifiers(obj):
                    obj.modifiers.remove(mod)
                    removed += 1
            self.report({"INFO"}, f"Auto Smooth removed ({removed} modifier(s))")
            return {"FINISHED"}

        return bpy.ops.iops.object_auto_smooth(angle=self.angle)
