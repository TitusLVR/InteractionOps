import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ..utils.search_rename_core import push_history, rename

PREVIEW_ROWS = 12

# Session history for the two text fields, newest first (like the
# drop-down lists of Total Commander's Multi-Rename Tool).
_search_history = []
_replace_history = []


def _history_items(history, edit_text):
    needle = edit_text.lower()
    return [h for h in history if needle in h.lower()]


def _search_suggestions(self, context, edit_text):
    return _history_items(_search_history, edit_text)


def _replace_suggestions(self, context, edit_text):
    return _history_items(_replace_history, edit_text)


def _targets(context):
    """Selected objects, or the active one when nothing is selected.
    Linked (library) objects can't be renamed and are left out."""
    objs = list(context.selected_objects)
    if not objs and context.view_layer.objects.active is not None:
        objs = [context.view_layer.objects.active]
    return [o for o in objs if o.library is None]


class IOPS_OT_Object_Search_Rename(bpy.types.Operator):
    """Search & Replace in the names of the selected objects (or the active one),
like Total Commander's Multi-Rename Tool"""

    bl_idname = "iops.object_search_rename"
    bl_label = "Search & Replace"
    bl_options = {"REGISTER", "UNDO"}

    search_for: StringProperty(
        name="Search for",
        description="Text to find. | separates several terms, * and ? are wildcards",
        default="",
        search=_search_suggestions,
        search_options={"SUGGESTION"},
    )
    replace_with: StringProperty(
        name="Replace with",
        description=("Replacement. | separates replacements paired with the search terms; "
                     "with RegEx, $1..$9 insert groups"),
        default="",
        search=_replace_suggestions,
        search_options={"SUGGESTION"},
    )
    case_sensitive: BoolProperty(
        name="^",
        description="Case-sensitive search",
        default=False,
    )
    first_only: BoolProperty(
        name="1x",
        description="Replace only the first occurrence",
        default=False,
    )
    include_suffix: BoolProperty(
        name="[E]",
        description="Search the .001 duplicate suffix too (otherwise it is kept as is)",
        default=False,
    )
    use_regex: BoolProperty(
        name="RegEx",
        description="Search for is a regular expression",
        default=False,
    )
    use_subst: BoolProperty(
        name="Subst.",
        description="RegEx only: when the pattern matches, the whole name becomes Replace with",
        default=False,
    )
    case_mode: EnumProperty(
        name="Upper/lowercase",
        items=[
            ("UNCHANGED", "Unchanged", ""),
            ("LOWER", "lowercase", ""),
            ("UPPER", "UPPERCASE", ""),
            ("FIRST", "First letter uppercase", ""),
            ("WORDS", "First Letter Of Each Word Uppercase", ""),
        ],
        default="UNCHANGED",
    )

    @classmethod
    def poll(cls, context):
        return bool(_targets(context))

    def _new_name(self, name):
        return rename(
            name,
            self.search_for,
            self.replace_with,
            case_sensitive=self.case_sensitive,
            first_only=self.first_only,
            include_suffix=self.include_suffix,
            regex=self.use_regex,
            subst=self.use_subst,
            case=self.case_mode,
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        col = box.column(align=True)
        col.label(text="Search & Replace")
        col.activate_init = True
        col.prop(self, "search_for", text="Search for")
        col.prop(self, "replace_with", text="Replace with")
        row = box.row(align=True)
        row.prop(self, "case_sensitive")
        row.prop(self, "first_only")
        row.prop(self, "include_suffix")
        row.prop(self, "use_regex")
        sub = row.row(align=True)
        sub.enabled = self.use_regex
        sub.prop(self, "use_subst")

        box = layout.box()
        box.label(text="Upper/lowercase")
        box.prop(self, "case_mode", text="")

        objs = _targets(context)
        box = layout.box()
        col = box.column(align=True)
        try:
            pairs = [(o.name, self._new_name(o.name)) for o in objs]
        except ValueError as e:
            col.label(text=str(e), icon="ERROR")
            return
        changed = sum(1 for old, new in pairs if old != new)
        col.label(text=f"{changed} of {len(pairs)} will be renamed")
        for old, new in pairs[:PREVIEW_ROWS]:
            split = col.split(factor=0.5)
            split.label(text=old)
            split.label(text=new, icon="FORWARD" if new != old else "BLANK1")
        if len(pairs) > PREVIEW_ROWS:
            col.label(text=f"... {len(pairs) - PREVIEW_ROWS} more")

    def execute(self, context):
        objs = _targets(context)
        try:
            plan = [(o, self._new_name(o.name)) for o in objs]
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        push_history(_search_history, self.search_for)
        push_history(_replace_history, self.replace_with)

        empty = [o for o, new in plan if not new]
        plan = [(o, new) for o, new in plan if new and new != o.name]
        # Two passes: park every object on a unique temporary name first, so
        # renames inside the set (a -> b while b -> c) don't collide and pick
        # up .001 suffixes.
        for i, (o, _new) in enumerate(plan):
            o.name = f"iops_search_rename_tmp_{i}"
        for o, new in plan:
            o.name = new

        taken = sum(1 for o, new in plan if o.name != new)
        msg = f"Renamed {len(plan)} object(s)"
        if taken:
            msg += f", {taken} got a suffix (name taken)"
        if empty:
            msg += f", {len(empty)} skipped (empty name)"
        self.report({"WARNING"} if taken or empty else {"INFO"}, msg)
        return {"FINISHED"}
