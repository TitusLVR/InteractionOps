"""Material assignment of the iOps Materials panel.

`assign_material()` takes an explicit material and target list so the
asset shelf and the eyedropper of later stages can reuse it; the operators
only gather targets from the context and report.
"""
from collections import namedtuple

import bmesh
import bpy

from ...utils import materials_core as core
from . import common, state

AssignResult = namedtuple("AssignResult", "objects faces skipped")
# objects: objects that got the material
# faces:   faces assigned (None for whole-object assignment)
# skipped: {label: count}

NO_FACES = "no selected faces"


def _unique_by_data(objects):
    """[(data, [objects using it])] in first-seen order."""
    order, users = [], {}
    for obj in objects:
        data = obj.data
        key = data.as_pointer()
        if key not in users:
            users[key] = (data, [])
            order.append(key)
        users[key][1].append(obj)
    return [users[k] for k in order]


def _reset_indices(data):
    """All face / spline material indices to 0."""
    if isinstance(data, bpy.types.Mesh):
        if data.is_editmode:
            bm = bmesh.from_edit_mesh(data)
            for f in bm.faces:
                f.material_index = 0
            bmesh.update_edit_mesh(data, loop_triangles=False,
                                   destructive=False)
        elif data.polygons:
            data.polygons.foreach_set("material_index",
                                      [0] * len(data.polygons))
            data.update()
    elif isinstance(data, bpy.types.Curve):
        for spline in getattr(data, "splines", ()):
            spline.material_index = 0


def assign_whole(objects, mat):
    """Every object ends up with exactly `mat` on all faces: its slots
    collapse to one slot holding it. Shared data is processed once.
    `objects` must be compatible. Returns the number of objects."""
    count = 0
    for data, users in _unique_by_data(objects):
        data.materials.clear()
        data.materials.append(mat)
        _reset_indices(data)
        for obj in users:
            slots = obj.material_slots
            if slots and slots[0].link == "OBJECT":
                slots[0].material = mat
            count += 1
    return count


def _slot_index(obj, mat):
    for i, slot in enumerate(obj.material_slots):
        if slot.material == mat:
            return i
    return -1


def _face_selection(data):
    if data.is_editmode:
        return [f.select for f in bmesh.from_edit_mesh(data).faces]
    sel = [False] * len(data.polygons)
    if sel:
        data.polygons.foreach_get("select", sel)
    return sel


def _reusable_empty_slot(obj, data, sel=None):
    """First empty (data-linked) slot no face outside `sel` (default: the
    face selection) uses, else -1. Reusing it keeps face assignment from
    piling up slots."""
    empties = [i for i, m in enumerate(data.materials) if m is None
               and obj.material_slots[i].link == "DATA"]
    if not empties:
        return -1
    from .slots import get_indices
    idx = get_indices(data)
    if sel is None:
        sel = _face_selection(data)
    taken = {i for i, s in zip(idx, sel) if not s}
    for i in empties:
        if i not in taken:
            return i
    return -1


def _selected_faces(data):
    if data.is_editmode:
        bm = bmesh.from_edit_mesh(data)
        return sum(1 for f in bm.faces if f.select)
    sel = [False] * len(data.polygons)
    if sel:
        data.polygons.foreach_get("select", sel)
    return sum(sel)


def _set_selected_indices(data, index):
    if data.is_editmode:
        bm = bmesh.from_edit_mesh(data)
        for f in bm.faces:
            if f.select:
                f.material_index = index
        bmesh.update_edit_mesh(data, loop_triangles=False, destructive=False)
        return
    n = len(data.polygons)
    sel = [False] * n
    idx = [0] * n
    data.polygons.foreach_get("select", sel)
    data.polygons.foreach_get("material_index", idx)
    for i in range(n):
        if sel[i]:
            idx[i] = index
    data.polygons.foreach_set("material_index", idx)
    data.update()


def assign_faces(objects, mat):
    """Selected faces of the mesh objects get `mat` (existing slot reused,
    else one appended). Edit Mode meshes use their bmesh selection, others
    the stored face selection. Returns (objects, faces, skipped); nothing
    changes when no face is selected anywhere. `objects` must be
    compatible."""
    skipped = {}
    plan = []
    for data, users in _unique_by_data(objects):
        if not isinstance(data, bpy.types.Mesh):
            label = common.type_label(users[0])
            skipped[label] = skipped.get(label, 0) + len(users)
            continue
        n = _selected_faces(data)
        if n == 0:
            skipped[NO_FACES] = skipped.get(NO_FACES, 0) + len(users)
            continue
        plan.append((data, users, n))
    objects_done = faces = 0
    for data, users, n in plan:
        obj = users[0]
        index = _slot_index(obj, mat)
        if index < 0:
            index = _reusable_empty_slot(obj, data)
            if index >= 0:
                data.materials[index] = mat
            else:
                data.materials.append(mat)
                index = len(data.materials) - 1
        _set_selected_indices(data, index)
        objects_done += len(users)
        faces += n
    return objects_done, faces, skipped


def assign_face(obj, face_index, mat):
    """Give polygon `face_index` of mesh object `obj` the material `mat`
    (Object or Edit Mode): its existing slot, else an empty slot no other
    face uses, else a new slot. Returns None on success or a reason."""
    reason = common.skip_reason(obj)
    if reason is not None:
        return reason
    data = obj.data
    if not isinstance(data, bpy.types.Mesh):
        return common.type_label(obj)
    count = (len(bmesh.from_edit_mesh(data).faces) if data.is_editmode
             else len(data.polygons))
    if not 0 <= face_index < count:
        return "no face"
    index = _slot_index(obj, mat)
    if index < 0:
        only = [i == face_index for i in range(count)]
        index = _reusable_empty_slot(obj, data, only)
        if index >= 0:
            data.materials[index] = mat
        else:
            data.materials.append(mat)
            index = len(data.materials) - 1
    if data.is_editmode:
        bm = bmesh.from_edit_mesh(data)
        bm.faces.ensure_lookup_table()
        bm.faces[face_index].material_index = index
        bmesh.update_edit_mesh(data, loop_triangles=False, destructive=False)
    else:
        data.polygons[face_index].material_index = index
        data.update()
    return None


def assign_material(mat, objects, mode="OBJECT"):
    """Assign `mat` to `objects` ("OBJECT": whole object, "FACES": selected
    faces). Incompatible objects are skipped and counted."""
    good, skipped = common.split_compatible(objects)
    if mode == "FACES":
        done, faces, more = assign_faces(good, mat)
        for label, n in more.items():
            skipped[label] = skipped.get(label, 0) + n
        return AssignResult(done, faces, skipped)
    return AssignResult(assign_whole(good, mat), None, skipped)


def ensure_principled(mat):
    """Give `mat` a node tree with a Principled BSDF into a Material Output
    (when it has none)."""
    if mat.node_tree is None:
        try:
            mat.use_nodes = True
        except (AttributeError, TypeError):
            pass
    tree = mat.node_tree
    if tree is None:
        return
    nodes = tree.nodes
    if any(n.bl_idname == "ShaderNodeBsdfPrincipled" for n in nodes):
        return
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300.0, 0.0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0.0, 0.0)
    tree.links.new(bsdf.outputs[0], out.inputs[0])


def _report_result(op, mat, result):
    if result.objects == 0:
        if result.faces is not None and result.skipped.get(NO_FACES):
            op.report({"WARNING"}, "No faces selected")
        else:
            tail = core.format_skipped(result.skipped)
            op.report({"WARNING"},
                      f"Nothing can take {mat.name}" + (f": {tail}" if tail
                                                        else ""))
        return False
    op.report({"INFO"}, core.format_assign_report(
        mat.name, result.objects, result.skipped, faces=result.faces))
    return True


def assign_poll(context):
    return context.mode == "OBJECT" or common.in_edit_mode(context)


_MODE_ITEMS = (
    ("OBJECT", "Whole Object", "The objects get only this material, on all "
     "faces"),
    ("FACES", "Selected Faces", "The selected faces get this material"),
)


class IOPS_OT_MaterialAssign(bpy.types.Operator):
    """Click: assign to the selected objects (whole object).
Alt+click: assign to the selected faces.
Ctrl+click: only make it the panel's active material"""

    bl_idname = "iops.material_assign"
    bl_label = "Assign Material"
    bl_options = {"REGISTER", "UNDO"}

    material: bpy.props.StringProperty(name="Material")
    library: bpy.props.StringProperty(name="Library")
    mode: bpy.props.EnumProperty(name="Assign To", items=_MODE_ITEMS,
                                 default="OBJECT")

    @classmethod
    def poll(cls, context):
        return assign_poll(context)

    def invoke(self, context, event):
        if event.ctrl:
            mat = common.find_material(self.material, self.library)
            if mat is not None:
                state.set_active(mat, context)
                common.tag_redraw(context)
            # UI-only change: no undo step
            return {"CANCELLED"}
        if event.alt:
            self.mode = "FACES"
        return self.execute(context)

    def execute(self, context):
        mat = common.find_material(self.material, self.library)
        if mat is None:
            self.report({"WARNING"}, f"Material {self.material!r} not found")
            return {"CANCELLED"}
        state.set_active(mat, context)
        result = assign_material(mat, common.target_objects(context),
                                 self.mode)
        state.invalidate_sources()
        common.tag_redraw(context)
        if not _report_result(self, mat, result):
            return {"CANCELLED"}
        return {"FINISHED"}


class IOPS_OT_MaterialNew(bpy.types.Operator):
    """New node material (Principled BSDF), made the panel's active material.
Shift+click: also assign it to the selected objects.
Shift+Alt+click: also assign it to the selected faces"""

    bl_idname = "iops.material_new"
    bl_label = "New Material"
    bl_options = {"REGISTER", "UNDO"}

    assign: bpy.props.BoolProperty(
        name="Assign", description="Assign the new material to the "
        "selection", default=False)
    mode: bpy.props.EnumProperty(name="Assign To", items=_MODE_ITEMS,
                                 default="OBJECT")

    def invoke(self, context, event):
        if event.shift:
            self.assign = True
            if event.alt:
                self.mode = "FACES"
        return self.execute(context)

    def execute(self, context):
        taken = [m.name for m in bpy.data.materials if m.library is None]
        mat = bpy.data.materials.new(core.next_material_name(taken))
        ensure_principled(mat)
        state.set_active(mat, context)
        state.invalidate_sources()
        common.tag_redraw(context)
        if not self.assign or not assign_poll(context):
            self.report({"INFO"}, f"Created {mat.name}")
            return {"FINISHED"}
        result = assign_material(mat, common.target_objects(context),
                                 self.mode)
        if result.objects == 0:
            # the material stays; say why nothing got it
            _report_result(self, mat, result)
            return {"FINISHED"}
        self.report({"INFO"}, f"Created {mat.name}. " + core.format_assign_report(
            mat.name, result.objects, result.skipped, faces=result.faces))
        return {"FINISHED"}


def _face_selected_in_edit(obj, face_index):
    """True when `obj` is a mesh in Edit Mode and that face is selected."""
    data = getattr(obj, "data", None)
    if not isinstance(data, bpy.types.Mesh) or not data.is_editmode:
        return False
    bm = bmesh.from_edit_mesh(data)
    if not 0 <= face_index < len(bm.faces):
        return False
    bm.faces.ensure_lookup_table()
    return bm.faces[face_index].select


class IOPS_OT_MaterialAssignDrop(bpy.types.Operator):
    """Assign a material to one object (whole object), or to one face of
    it: what dropping a material from the iOps shelf onto the viewport
    does. In Edit Mode a drop on a selected face goes to the whole face
    selection"""

    bl_idname = "iops.material_assign_drop"
    bl_label = "Drop Material"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    material: bpy.props.StringProperty(name="Material")
    library: bpy.props.StringProperty(name="Library")
    object: bpy.props.StringProperty(name="Object")
    face: bpy.props.IntProperty(
        name="Face", description="Polygon index; -1: the whole object",
        default=-1, min=-1)

    @classmethod
    def poll(cls, context):
        return assign_poll(context)

    def execute(self, context):
        mat = common.find_material(self.material, self.library)
        obj = bpy.data.objects.get(self.object)
        if mat is None or obj is None:
            self.report({"WARNING"}, "Material or object not found")
            return {"CANCELLED"}
        state.set_active(mat, context)
        if self.face < 0:
            result = assign_material(mat, [obj], "OBJECT")
            state.invalidate_sources()
            if not _report_result(self, mat, result):
                return {"CANCELLED"}
            return {"FINISHED"}
        if _face_selected_in_edit(obj, self.face):
            # Edit Mode shows the selection: a drop on a selected face means
            # the selection, on an unselected face just that face
            result = assign_material(mat, common.target_objects(context),
                                     "FACES")
            state.invalidate_sources()
            if not _report_result(self, mat, result):
                return {"CANCELLED"}
            return {"FINISHED"}
        reason = assign_face(obj, self.face, mat)
        state.invalidate_sources()
        if reason is not None:
            self.report({"WARNING"}, f"{obj.name} cannot take {mat.name} "
                                     f"({reason})")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Assigned {mat.name} to 1 face on {obj.name}")
        return {"FINISHED"}
