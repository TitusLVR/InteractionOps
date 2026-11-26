"""Remap Materials: a two-column table, source material -> material it
changes to, applied at once.

All rows apply simultaneously from the original state: A -> B together with
B -> C turns A into B and B into C (not A into C), A -> B with B -> A swaps.
"""
import bpy

from ...utils import materials_core as core
from . import common, slots, state

_SCOPE_ITEMS = (
    ("SELECTED", "Selected Objects", "Slots of the selected objects (in Edit "
     "Mode: the objects being edited)"),
    ("SCENE", "Scene", "Slots of every object in the scene"),
    ("FILE", "File", "Every user of the material in the file"),
)

# visible table rows per page
LIST_ROWS = 8
THUMBNAIL_ROWS = 3
THUMBNAIL_MAX_UNITS = 3
# dialog width / popup width: two columns of ~24-character names with icons
# and pickers need ~22 units (about 7 px per character at 1.0 scale)
REMAP_WIDTH_FACTOR = 1.8


def scope_objects(context, scope):
    if scope == "SCENE":
        return list(context.scene.objects)
    return common.target_objects(context)


def scope_materials(context, scope):
    """Materials the table lists for `scope`, sorted by name."""
    if scope == "FILE":
        mats = list(bpy.data.materials)
    else:
        found = {}
        for obj in scope_objects(context, scope):
            for slot in getattr(obj, "material_slots", ()):
                if slot.material is not None:
                    found[slot.material.as_pointer()] = slot.material
        mats = list(found.values())
    return sorted(mats, key=lambda m: (m.name.lower(), m.name,
                                       common.material_key(m)[1]))


def build_rows(context, scope):
    """Fill the WindowManager table for `scope`; returns the row count."""
    rows = state.get_state(context).remap_rows
    rows.clear()
    for mat in scope_materials(context, scope):
        row = rows.add()
        row.source_name, row.source_library = common.material_key(mat)
    state.get_state(context).remap_page = 1
    state.get_state(context).remap_scope = scope
    return len(rows)


def row_source(row):
    return common.find_material(row.source_name, row.source_library)


def table_mapping(context):
    """{source material: target} for rows with a target that differs."""
    mapping = {}
    for row in state.get_state(context).remap_rows:
        src = row_source(row)
        if src is not None and row.target is not None and row.target != src:
            mapping[src] = row.target
    return mapping


def remap_in_objects(objects, mapping):
    """Switch slots holding a source to its target, every slot from its
    original value (simultaneous). Data-linked slots are handled once per
    data. Returns (objects changed, touched data list)."""
    seen_data = set()
    changed, touched = 0, {}
    for obj in objects:
        data = obj.data
        key = data.as_pointer()
        hit = False
        first_user = key not in seen_data
        seen_data.add(key)
        for slot in obj.material_slots:
            new = mapping.get(slot.material)
            if new is None:
                continue
            if slot.link == "DATA" and not first_user:
                hit = True
                continue
            slot.material = new
            hit = True
        if hit:
            changed += 1
            touched[key] = data
    return changed, list(touched.values())


def remap_file(mapping):
    """user_remap for local sources, all at once through placeholders.
    Returns (sources remapped, linked sources skipped)."""
    local = {s: t for s, t in mapping.items() if s.library is None}
    skipped = len(mapping) - len(local)
    holders = {}
    for src in local:
        holder = bpy.data.materials.new("iops remap placeholder")
        src.user_remap(holder)
        holders[holder] = local[src]
    for holder, target in holders.items():
        holder.user_remap(target)
        bpy.data.materials.remove(holder)
    return len(local), skipped


def _rebuild_on_scope(self, context):
    # only a real change: setting the same scope (e.g. as an operator
    # argument) must keep the picks
    if state.get_state(context).remap_scope != self.scope:
        build_rows(context, self.scope)


class IOPS_OT_MaterialsRemap(bpy.types.Operator):
    """Remap materials in a two-column table: each material on the left
    changes to the one picked on the right, all at once"""

    bl_idname = "iops.materials_remap"
    bl_label = "Remap Materials"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(name="In", items=_SCOPE_ITEMS,
                                  default="SELECTED", update=_rebuild_on_scope)
    collapse_slots: bpy.props.BoolProperty(
        name="Collapse Duplicate Slots", description="Afterwards, slots "
        "holding the same material collapse into the first one",
        default=True)
    remove_empty: bpy.props.BoolProperty(
        name="Remove Empty Slots", description="Afterwards, remove every "
        "empty slot; its faces move to the first remaining slot",
        default=False)

    def invoke(self, context, event):
        if not build_rows(context, self.scope):
            self.report({"INFO"}, "No materials to remap here")
            return {"CANCELLED"}
        width = int(common.popup_width_px(context) * REMAP_WIDTH_FACTOR)
        return context.window_manager.invoke_props_dialog(
            self, width=width, confirm_text="Remap")

    def cancel(self, context):
        state.get_state(context).remap_rows.clear()

    def draw(self, context):
        draw_table(self.layout, context, self)

    def execute(self, context):
        st = state.get_state(context)
        if not st.remap_rows:
            self.report({"INFO"}, "No materials to remap here")
            return {"CANCELLED"}
        mapping = table_mapping(context)
        if not mapping:
            self.report({"INFO"}, "No material picked on the right")
            st.remap_rows.clear()
            return {"CANCELLED"}
        skipped = {}
        if self.scope == "FILE":
            using = {}
            for obj in bpy.data.objects:
                if obj.data is not None and any(
                        s.material in mapping for s in
                        getattr(obj, "material_slots", ())):
                    using[obj] = obj.data
            done, linked = remap_file(mapping)
            if linked:
                skipped["linked material"] = linked
            objects = len(using)
            touched = list({d.as_pointer(): d for d in using.values()}.values())
        else:
            good, skipped = common.split_compatible(
                scope_objects(context, self.scope))
            objects, touched = remap_in_objects(good, mapping)
            done = len(mapping)
        repeats = empties = None
        slot_skipped = {}
        if self.collapse_slots or self.remove_empty:
            r, e, slot_skipped = slots.cleanup_many(
                touched, self.collapse_slots, self.remove_empty)
            repeats = r if self.collapse_slots else None
            empties = e if self.remove_empty else None
        st.remap_rows.clear()
        state.invalidate_sources()
        common.tag_redraw(context)
        text = (f"Remapped {core.plural(done, 'material')} on "
                f"{core.plural(objects, 'object')}")
        tail = core.format_merge_report(None, 0, repeats, empties,
                                        slot_skipped)
        if tail != "Nothing to do":
            text += ", " + tail[0].lower() + tail[1:]
        more = core.format_skipped(skipped)
        self.report({"INFO"}, f"{text}, {more}" if more else text)
        return {"FINISHED"}


def draw_table(layout, context, op):
    st = state.get_state(context)
    prefs = common.addon_prefs(context)
    layout.prop(op, "scope", expand=True)
    row = layout.row(align=True)
    row.prop(st, "remap_view", expand=True)
    rows = st.remap_rows
    thumbs = st.remap_view == "THUMBNAILS"
    per_page = THUMBNAIL_ROWS if thumbs else LIST_ROWS
    start, stop, page, pages = core.page_slice(len(rows), per_page,
                                               st.remap_page - 1)
    head = layout.split(factor=0.5)
    head.label(text="Material")
    head.label(text="Changes To")
    box = layout.column(align=True)
    size = min(prefs.materials_thumbnail_size, THUMBNAIL_MAX_UNITS)
    for row in rows[start:stop]:
        src = row_source(row)
        name = row.source_name if src is None else src.name
        changed = row.target is not None and row.target != src
        split = box.split(factor=0.5, align=True)
        left = split.column(align=True) if thumbs else split.row(align=True)
        right = split.column(align=True)
        if thumbs:
            left.template_icon(icon_value=layout.icon(src) if src else 0,
                               scale=size)
            line = left.row(align=True)
            line.label(text=name)
            if changed:
                line.label(text="", icon="FORWARD")
            if row.target is not None:
                right.template_icon(icon_value=layout.icon(row.target),
                                    scale=size)
            else:
                blank = right.column()
                blank.scale_y = size
                blank.label(text="Unchanged")
            right.prop(row, "target", text="")
            box.separator(factor=0.5)
        else:
            left.label(text=name,
                       icon_value=layout.icon(src) if src else 0)
            if changed:
                left.label(text="", icon="FORWARD")
            right.prop(row, "target", text="")
    if pages > 1:
        nav = layout.row(align=True)
        nav.prop(st, "remap_page", text=f"Page (of {pages})")
        if page + 1 != st.remap_page:
            nav.label(text=f"Showing {page + 1}")
    layout.separator()
    layout.prop(op, "collapse_slots")
    layout.prop(op, "remove_empty")
