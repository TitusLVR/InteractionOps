import bpy
import re
from bpy.props import (
    IntProperty,
    StringProperty,
    BoolProperty,
)

class IOPS_OT_Object_Name_From_Active(bpy.types.Operator):
    """Rename Object as Active ObjectName"""

    bl_idname = "iops.object_name_from_active"
    bl_label = "IOPS Object Name From Active"
    bl_options = {"REGISTER", "UNDO"}

    new_name: StringProperty(
        name="New Name",
        default="",
    )

    active_name: StringProperty(
        name="Active Name",
        default="",
    )

    pattern: StringProperty(
        name="Pattern",
        description="""Naming Syntaxis:
    [N] - Name
    [C] - Counter
    [T] - Object Type
    [COL] - Collection Name
    """,
        default="[N]_[C]",
    )

    use_distance: BoolProperty(
        name="By Distance",
        description="Rename Selected Objects Based on Distance to Active Object",
        default=True,
    )

    counter_digits: IntProperty(
        name="Counter Digits",
        description="Number Of Digits For Counter",
        default=2,
        min=2,
        max=10,
    )

    counter_shift: BoolProperty(
        name="+1",
        description="+1 shift for counter, useful when we need to rename active object too",
        default=True,
    )

    rename_active: BoolProperty(
        name="Rename Active", description="Rename active also", default=True
    )

    rename_mesh_data: BoolProperty(
        name="Rename Mesh Data", description="Rename Mesh Data", default=True
    )

    rename_mesh_data_single: BoolProperty(
        name="Rename Mesh Data",
        description="Rename mesh data when only one object is selected",
        default=False,
    )

    trim_prefix: IntProperty(
        name="Prefix",
        description="Number Of Digits for Prefix trim",
        default=0,
        min=0,
        max=100,
    )

    trim_suffix: IntProperty(
        name="Suffix",
        description="Number Of Digits for Suffix trim",
        default=0,
        min=0,
        max=100,
    )
    use_trim: BoolProperty(
        name="Trim", description="Trim Name Prefix/Suffix", default=False
    )
    rename_linked: BoolProperty(
        name="Rename Linked",
        description="Rename Linked Objects",
        default=False,
    )

    copy_to_clipboard: BoolProperty(
        name="Copy to Clipboard",
        description="Copy the active object name to the clipboard",
        default=True,
    )

    def invoke(self, context, event):
        active = context.view_layer.objects.active
        if active is None:
            # No active object (e.g. collections picked in the outliner) -
            # fall back to the last selected object and make it active.
            selected = context.selected_objects
            if not selected:
                self.report({"ERROR"}, "Nothing selected.")
                return {"CANCELLED"}
            active = selected[-1]
            context.view_layer.objects.active = active
        self.active_name = active.name
        self.new_name = self.active_name
        return self.execute(context)

    def execute(self, context):
        Objects = context.selected_objects
        if len(Objects) == 1:
            if self.copy_to_clipboard:
                context.window_manager.clipboard = self.active_name            
            if self.rename_mesh_data_single and Objects[0].type == "MESH":
                Objects[0].data.name = Objects[0].name
            return {"FINISHED"}
        else:
            if self.pattern:
                active = context.view_layer.objects.active
                if active is None:
                    selected = context.selected_objects
                    if not selected:
                        self.report({"ERROR"}, "Nothing selected.")
                        return {"CANCELLED"}
                    active = selected[-1]
                    context.view_layer.objects.active = active
                if self.active_name != active.name:
                    active.name = self.active_name
                # Trim string
                if self.use_trim:
                    name = self.active_name
                    if self.trim_suffix == 0:
                        self.new_name = name[(self.trim_prefix) :]
                    else:
                        self.new_name = name[(self.trim_prefix) : -(self.trim_suffix)]
                else:
                    self.trim_suffix = self.trim_prefix = 0

                digit = "{0:0>" + str(self.counter_digits) + "}"
                Objects = context.selected_objects
                if self.use_distance:
                    al = active.location
                    Objects.sort(key=lambda obj: (obj.location - al).length_squared)
                # Check active
                if self.rename_active:
                    to_rename = [ob.name for ob in Objects]
                else:
                    to_rename = [ob.name for ob in Objects if ob is not active]
                if self.rename_linked and active.children_recursive:
                    to_rename.extend(child.name for child in active.children_recursive)
                    # children may already be selected - dedup, keep first order
                    to_rename = list(dict.fromkeys(to_rename))

                # Split the pattern once; tokens get filled per object below.
                tokens = re.split(r"(\[\w+\])", self.pattern)
                want_name = "[N]" in tokens
                want_counter = "[C]" in tokens
                want_type = "[T]" in tokens
                per_collection = "[COL]" in tokens

                # Build an object -> collection-names map once (O(M) instead of
                # O(objects x collections) from a per-object lookup).
                col_map = {}
                if per_collection:
                    for col in bpy.data.collections:
                        for ob in col.objects:
                            col_map.setdefault(ob.name, []).append(col.name)

                # counter - per-collection when [COL] is used, otherwise global
                start = 1 if self.counter_shift else 0
                counters = {}

                for name in to_rename:
                    o = bpy.data.objects[name]
                    col_names = "_".join(col_map.get(name, ())) if per_collection else ""
                    # Separate counter per collection group so each collection
                    # gets its own 01..0N sequence instead of a shared global one.
                    key = col_names if per_collection else ""
                    counter = counters.get(key, start)
                    parts = tokens[:]
                    for i, p in enumerate(parts):
                        if want_name and p == "[N]":
                            parts[i] = self.new_name
                        elif want_counter and p == "[C]":
                            parts[i] = digit.format(counter)
                        elif want_type and p == "[T]":
                            parts[i] = o.type.lower()
                        elif per_collection and p == "[COL]":
                            parts[i] = col_names
                    o.name = "".join(parts)
                    # Rename object mesh data
                    if self.rename_mesh_data and o.type == "MESH":
                        o.data.name = o.name
                    counters[key] = counter + 1
            else:
                self.report({"ERROR"}, "Please fill the pattern field")
            return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        selected_count = len(context.selected_objects)

        if selected_count == 1:
            # Simple: one object
            col = layout.column(align=True)
            col.prop(self, "copy_to_clipboard", text="Copy Name to Clipboard")
            col.prop(self, "rename_mesh_data_single", text="Rename Mesh Data to Object Name")
        else:
            # Full: multiple objects
            col = layout.column(align=True)
            row = col.row()
            row.enabled = False
            row.prop(self, "active_name", text="Active")
            col.prop(self, "new_name", text="New Name")
            col.separator()
            row = col.row(align=True)
            row.prop(self, "use_trim", toggle=True)
            sub = row.row(align=True)
            sub.enabled = self.use_trim
            sub.prop(self, "trim_prefix", text="Prefix")
            sub.prop(self, "trim_suffix", text="Suffix")
            layout.separator()

            col = layout.column(align=True)
            col.prop(self, "pattern", text="Pattern")
            row = col.row(align=True)
            row.label(text="Counter Digits")
            row.prop(self, "counter_digits", text="")
            row.prop(self, "counter_shift", text="+1 Shift")
            layout.separator()

            col = layout.column(align=True)
            col.prop(self, "copy_to_clipboard", text="Copy Name to Clipboard")
            col.prop(self, "rename_active", text="Include Active Object")
            col.prop(self, "use_distance", text="Sort by Distance to Active")
            col.prop(self, "rename_mesh_data", text="Object's Mesh Data")
            col.prop(self, "rename_linked", text="Linked Objects")  
