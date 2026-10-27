"""Sidebar (N-panel) of the visual widget editor.

A WindowManager PropertyGroup (`wm.iops_widget_editor`) mirrors the
selected element and the widget-level fields of the active edit session.
`sync_from_selection()` (called by editor.select / after_commit) fills it
under the `_SYNC` flag; every field's update callback writes ONE change
back through the EditorDoc (set_field / set_span / set_widget_field, or
one `commit` for a binding switch) and then `editor.after_commit()` —
same `_SYNC` guard pattern as prefs/widget_composer.py. A refused or
no-op write re-syncs the panel to the doc instead.

Field layout and the text formats live in the bpy-free editor_fields.
"""
import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup

from . import editor_fields as ef

_SYNC = False
# field name -> message for writes the panel refused (shown under the
# field; cleared by the next sync).
_errors = {}


def _editor():
    from . import editor
    return editor


def _composed():
    from ...widgets import composed
    return composed


def _session():
    return _editor().active()


def _selected():
    """(session, path, element) — element None when nothing selected."""
    s = _session()
    if s is None or s.doc.selection is None:
        return s, None, None
    return s, s.doc.selection, s.doc.get(s.doc.selection)


def _redraw():
    try:
        from . import state
        state.tag_redraw_all()
    except Exception:
        pass
    _redraw_sidebars()


def _redraw_sidebars():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in ("VIEW_3D", "IMAGE_EDITOR"):
                area.tag_redraw()


# ----------------------------------------------------------------------
# Dynamic enum items (cached: Blender needs the strings kept alive)
# ----------------------------------------------------------------------
_ITEM_CACHE = {}
_BINDING_LABELS = {
    "ATTRIBUTE": ("Mesh Attribute", "Attribute of the selected mesh "
                  "elements (Edit Mode)"),
    "PROP": ("RNA Prop", "Dotted RNA path resolved against the context"),
    "SWITCH": ("Switch", "Local widget switch (on/off state)"),
    "DATA": ("Scene Data", "Key in the per-scene widget data store"),
    "COLOR": ("Literal Color", "A fixed RGBA color"),
}
_DOMAIN_ITEMS = (
    ("POINT", "Vertex", "Attribute on the selected vertices"),
    ("EDGE", "Edge", "Attribute on the selected edges"),
    ("FACE", "Face", "Attribute on the selected faces"),
)
# Offered by the attribute field search next to the active mesh's own.
_COMMON_ATTRIBUTES = ("bevel_weight_edge", "crease_edge", "sharp_edge",
                      "uv_seam", "freestyle_edge", "bevel_weight_vert",
                      "crease_vert", "sharp_face", "freestyle_face")


def _items(kind, ids, labels=None):
    key = (kind, tuple(ids))
    cached = _ITEM_CACHE.get(key)
    if cached is None:
        cached = []
        for i in ids:
            name, desc = (labels or {}).get(i, (i.title(), ""))
            cached.append((i, name, desc))
        _ITEM_CACHE[key] = cached
    return cached


def _sel_type():
    _s, _p, el = _selected()
    return str(el.get("type", "")).upper() if el else ""


def _binding_items(self, context):
    ids = ef.bindings_for(_sel_type()) or ("PROP",)
    return _items("binding", ids, _BINDING_LABELS)


def _attribute_search(self, context, edit_text):
    names = list(_COMMON_ATTRIBUTES)
    ob = getattr(context, "active_object", None)
    if ob is not None and ob.type == "MESH":
        for a in ob.data.attributes:
            if (a.domain in ("POINT", "EDGE", "FACE")
                    and not a.name.startswith(".") and a.name != "position"
                    and a.name not in names):
                names.append(a.name)
    text = (edit_text or "").lower()
    return [n for n in names if text in n.lower()]


def _value_type_items(self, context):
    ids = ef.value_types_for(_sel_type()) or _composed().VALUE_TYPES
    return _items("value_type", ids)


_SELECTION_ITEMS = (
    ("ANY", "Any", "No selection condition"),
    ("verts", "Verts", "Visible when vertices are selected"),
    ("edges", "Edges", "Visible when edges are selected"),
    ("faces", "Faces", "Visible when faces are selected"),
    ("objects", "Objects", "Visible when objects are selected"),
)
_ROLE_ITEMS = (
    ("default", "Default", "Standard button colors"),
    ("error", "Error", "Destructive action (theme error color)"),
)


# ----------------------------------------------------------------------
# Write-through (panel -> doc)
# ----------------------------------------------------------------------
def _upd(name):
    def update(self, context):
        if not _SYNC:
            _on_field(self, name)
    return update


def _done(changed):
    if changed:
        _editor().after_commit()
    else:
        sync_from_selection()
        _redraw_sidebars()


def _refuse(name, msg):
    _errors[name] = msg
    print(f"IOPS widget editor: {name}: {msg}")
    _redraw_sidebars()


# Number/color fields Blender updates continuously while dragged: their
# commits coalesce into one undo step per run (EditorDoc merge_key).
_DRAG_FIELDS = ("min", "max", "snap", "height", "color")


def _drag_key(path, name):
    return ("field", path, name)


def _text_or_none(text):
    text = str(text)
    return text if text.strip() else None


def _on_field(props, name):
    s = _session()
    if s is None:
        return
    if not _editor().can_edit():
        # An older draft is undecided: refuse the write (the doc is never
        # touched) and snap the field back to the doc value.
        sync_from_selection()
        _refuse(name, _editor().DRAFT_GATE_MSG)
        return
    _errors.pop(name, None)
    if name.startswith("w_"):
        _on_widget_field(s, props, name)
        return
    path = s.doc.selection
    el = s.doc.get(path) if path is not None else None
    if el is None:
        return
    rtype = str(el.get("type", "")).upper()
    doc = s.doc

    if name == "binding":
        _done(_set_binding(s, path, rtype, props))
        return
    if name in ("span", "span_min1"):
        top = path[1] is None
        v = int(getattr(props, name))
        key = _drag_key(path, "span")
        if v <= 0 and ef.span_min(top, rtype) == 0:
            _done(doc.set_field(path, "span", None, merge_key=key))
        else:
            _done(doc.set_span(path, max(1, v), merge_key=key))
        return
    if name.startswith("si_"):
        clause = ef.build_show_if(props.si_mode, props.si_object_type,
                                  props.si_selection, props.si_prop,
                                  props.si_switch, props.si_equals)
        _done(doc.set_field(path, "show_if", clause))
        return
    if name == "op_kwargs":
        val, err = ef.parse_kwargs(props.op_kwargs)
        if err:
            # Keep the typed text so it can be fixed; the doc is untouched.
            _refuse(name, err)
            return
        _done(doc.set_field(path, "op_kwargs", val or None))
        return

    if name in ("label", "fmt", "items_from", "unit"):
        value = _text_or_none(getattr(props, name))
    elif name in ("op", "prop", "data", "switch", "attribute"):
        value = getattr(props, name).strip()
    elif name in ("role", "value_type", "domain"):
        value = getattr(props, name)
    elif name in ("min", "max", "snap"):
        value = float(getattr(props, name))
    elif name == "values":
        value = ef.parse_numbers(props.values)
    elif name == "items":
        value = ef.parse_items(props.items)
    elif name == "labels":
        value = ef.parse_labels(props.labels) or None
    elif name == "color":
        value = [float(c) for c in props.color]
    elif name == "show_alpha":
        value = True if props.show_alpha else None
    elif name == "height":
        h = float(props.height)
        value = None if h <= 0.0 else max(_composed().MIN_SPACER_HEIGHT, h)
    else:
        return
    merge = _drag_key(path, name) if name in _DRAG_FIELDS else None
    _done(doc.set_field(path, name, value, merge_key=merge))


def _set_binding(s, path, rtype, props):
    binding = props.binding
    key = ef.BINDING_KEYS.get(binding)
    if key is None or binding not in ef.bindings_for(rtype):
        return False
    if key == "color":
        value = [float(c) for c in props.color]
    else:
        value = getattr(props, key).strip()

    def fn(_w):
        el = s.doc.get(path)
        return el is not None and ef.apply_binding(el, binding, value)

    # One undo step for the whole switch (drop old keys + set new one).
    return s.doc.commit(fn)


def _on_widget_field(s, props, name):
    composed = _composed()
    doc = s.doc
    if name == "w_name":
        new = composed.sanitize_name(props.w_name)
        if not new:
            sync_from_selection()
            _refuse(name, "the widget name can't be empty")
            return
        _done(doc.set_widget_field("name", new))
    elif name == "w_title":
        _done(doc.set_widget_field("title", _text_or_none(props.w_title)))
    elif name == "w_width":
        w = float(props.w_width)
        _done(doc.set_widget_field(
            "width", None if w <= 0.0 else max(composed.MIN_WIDGET_WIDTH, w),
            merge_key=_drag_key(None, "w_width")))
    elif name in ("w_space_view3d", "w_space_image"):
        spaces = [sp for sp, on in (("VIEW_3D", props.w_space_view3d),
                                    ("IMAGE_EDITOR", props.w_space_image))
                  if on]
        if not spaces:
            sync_from_selection()
            _refuse("w_space", "a widget needs at least one editor")
            return
        _done(doc.set_widget_field("space", spaces))
    elif name == "w_switches":
        _done(doc.set_widget_field("switches",
                                   ef.parse_switches(props.w_switches)))


# ----------------------------------------------------------------------
# Doc -> panel
# ----------------------------------------------------------------------
def _put(props, name, value):
    try:
        setattr(props, name, value)
    except (TypeError, ValueError, AttributeError):
        pass


_DEFAULT_VALUE_TYPE = {"SLIDER": "FLOAT", "PRESETS": "FLOAT",
                       "INPUT": "STRING", "BUTTONS": "FLOAT"}


def _effective_span(s, path, el):
    if path[1] is None and el.get("type") != "FLIPBOX" \
            and el.get("span") is None:
        return 0
    from . import editor_model
    bounds = editor_model.span_bounds(s.doc.wdef.get("rows", []), path)
    return bounds[1] if bounds else int(el.get("span") or 0)


def sync_from_selection():
    """Fill the panel props from the selected element and the widget def
    (no writes back: runs under _SYNC)."""
    global _SYNC
    s = _session()
    if s is None:
        return
    try:
        props = bpy.context.window_manager.iops_widget_editor
    except AttributeError:
        return
    _errors.clear()
    _SYNC = True
    try:
        path = s.doc.selection
        el = s.doc.get(path) if path is not None else None
        if el is not None:
            _sync_element(s, props, path, el)
        _sync_widget(props, s.doc.wdef)
    finally:
        _SYNC = False
    _redraw_sidebars()


def _sync_element(s, props, path, el):
    rtype = str(el.get("type", "")).upper()
    binding = ef.binding_of(el)
    for key in ("label", "op", "prop", "data", "switch", "attribute", "fmt",
                "items_from", "unit"):
        _put(props, key, str(el.get(key, "") or ""))
    _put(props, "op_kwargs", ef.format_kwargs(el.get("op_kwargs")))
    _put(props, "role", el.get("role", "default"))
    if binding:
        _put(props, "binding", binding)
    _put(props, "domain", str(el.get("domain", "EDGE")).upper())
    vts = ef.value_types_for(rtype)
    vt = str(el.get("value_type", "")).upper()
    if vts:
        _put(props, "value_type",
             vt if vt in vts else _DEFAULT_VALUE_TYPE.get(rtype, vts[0]))
    for key, default in (("min", 0.0), ("max", 1.0)):
        try:
            _put(props, key, float(el.get(key, default)))
        except (TypeError, ValueError):
            _put(props, key, default)
    try:
        _put(props, "snap", float(el.get("snap", 0.0)))
    except (TypeError, ValueError):
        _put(props, "snap", 0.0)
    _put(props, "values", ef.format_numbers(el.get("values")))
    _put(props, "items", ef.format_items(el.get("items")))
    _put(props, "labels", ef.format_labels(el.get("labels")))
    color = el.get("color")
    if not (isinstance(color, (list, tuple)) and len(color) == 4):
        color = (1.0, 1.0, 1.0, 1.0)
    _put(props, "color", [float(c) for c in color])
    _put(props, "show_alpha", bool(el.get("show_alpha", False)))
    try:
        _put(props, "height", float(el.get("height", 0.0)))
    except (TypeError, ValueError):
        _put(props, "height", 0.0)
    span = _effective_span(s, path, el)
    _put(props, "span", span)
    _put(props, "span_min1", max(1, span))
    for key, val in ef.show_if_fields(el.get("show_if")).items():
        if key == "si_selection":
            val = val or "ANY"
        _put(props, key, val)


def _sync_widget(props, wdef):
    _put(props, "w_name", str(wdef.get("name", "")))
    _put(props, "w_title", str(wdef.get("title", "") or ""))
    try:
        _put(props, "w_width", float(wdef.get("width") or 0.0))
    except (TypeError, ValueError):
        _put(props, "w_width", 0.0)
    spaces = _composed().clean_spaces(wdef.get("space"))
    _put(props, "w_space_view3d", "VIEW_3D" in spaces)
    _put(props, "w_space_image", "IMAGE_EDITOR" in spaces)
    _put(props, "w_switches", ef.format_switches(wdef.get("switches")))


# ----------------------------------------------------------------------
# Property group
# ----------------------------------------------------------------------
class IOPS_WidgetEditorProps(PropertyGroup):
    # -- selected element ---------------------------------------------
    label: StringProperty(name="Label", update=_upd("label"))
    op: StringProperty(name="Operator",
                       description="Operator idname, e.g. iops.executor",
                       update=_upd("op"))
    op_kwargs: StringProperty(
        name="Arguments",
        description='Operator keyword arguments as JSON, e.g. '
                    '{"script": "..."}',
        update=_upd("op_kwargs"))
    role: EnumProperty(name="Role", items=_ROLE_ITEMS, default="default",
                       update=_upd("role"))
    binding: EnumProperty(name="Binding", items=_binding_items,
                          description="What this control reads and writes",
                          update=_upd("binding"))
    prop: StringProperty(name="Prop",
                         description="Dotted RNA path, e.g. "
                                     "tool_settings.use_snap",
                         update=_upd("prop"))
    data: StringProperty(name="Data Key",
                         description="Key in the per-scene widget data store",
                         update=_upd("data"))
    switch: StringProperty(name="Switch", description="Local switch name",
                           update=_upd("switch"))
    attribute: StringProperty(
        name="Attribute",
        description="Mesh attribute name, e.g. bevel_weight_edge "
                    "(created on the first non-zero write)",
        search=_attribute_search, search_options={"SUGGESTION"},
        update=_upd("attribute"))
    domain: EnumProperty(name="Domain", items=_DOMAIN_ITEMS, default="EDGE",
                         update=_upd("domain"))
    value_type: EnumProperty(name="Value Type", items=_value_type_items,
                             update=_upd("value_type"))
    min: FloatProperty(name="Min", default=0.0, update=_upd("min"))
    max: FloatProperty(name="Max", default=1.0, update=_upd("max"))
    snap: FloatProperty(name="Snap", default=0.0, min=0.0, precision=3,
                        description="Snap increment (Ctrl = smooth); "
                                    "0 disables snapping",
                        update=_upd("snap"))
    fmt: StringProperty(name="Format",
                        description="Python format string, e.g. {:.2f}",
                        update=_upd("fmt"))
    values: StringProperty(name="Values",
                           description="Comma-separated numbers",
                           update=_upd("values"))
    items: StringProperty(name="Items",
                          description="Comma-separated enum items, "
                                      "ID or ID:Label",
                          update=_upd("items"))
    labels: StringProperty(name="Labels",
                           description="Item labels as ID=Label; ID2=Label",
                           update=_upd("labels"))
    items_from: StringProperty(name="Items From",
                               description="Registered live items provider",
                               update=_upd("items_from"))
    unit: StringProperty(name="Unit", description="Suffix after the value "
                                                  "(empty = default)",
                         update=_upd("unit"))
    color: FloatVectorProperty(name="Color", size=4, subtype="COLOR",
                               min=0.0, max=1.0,
                               default=(1.0, 1.0, 1.0, 1.0),
                               update=_upd("color"))
    show_alpha: BoolProperty(name="Show Alpha", update=_upd("show_alpha"))
    span: IntProperty(name="Span", min=0, max=12,
                      description="Width in twelfths (0 = full width, "
                                  "top-level rows only)",
                      update=_upd("span"))
    # Same field for elements whose span can't be unset (ROW cells and
    # top-level flipboxes): the slider never offers 0.
    span_min1: IntProperty(name="Span", min=1, max=12, default=1,
                           description="Width in twelfths",
                           update=_upd("span_min1"))
    height: FloatProperty(name="Height", min=0.0, default=0.0,
                          description="Spacer height in px (0 = default)",
                          update=_upd("height"))
    # -- show_if (empty = absent) -------------------------------------
    si_mode: StringProperty(name="Mode",
                            description="Comma-separated context modes, "
                                        "e.g. EDIT_MESH, OBJECT",
                            update=_upd("si_mode"))
    si_object_type: StringProperty(name="Object Type",
                                   description="Comma-separated object "
                                               "types, e.g. MESH, CURVE",
                                   update=_upd("si_object_type"))
    si_selection: EnumProperty(name="Selection", items=_SELECTION_ITEMS,
                               default="ANY", update=_upd("si_selection"))
    si_prop: StringProperty(name="Prop", description="RNA path; visible "
                                                     "when truthy / equal",
                            update=_upd("si_prop"))
    si_switch: StringProperty(name="Switch", description="Switch name; "
                                                         "visible when on "
                                                         "/ equal",
                              update=_upd("si_switch"))
    si_equals: StringProperty(name="Equals",
                              description="Compare prop/switch to this "
                                          "(JSON literal or plain text)",
                              update=_upd("si_equals"))
    # -- widget --------------------------------------------------------
    w_name: StringProperty(name="Name", description="Widget name (file "
                                                    "name; Save renames)",
                           update=_upd("w_name"))
    w_title: StringProperty(name="Title", update=_upd("w_title"))
    w_width: FloatProperty(name="Width", min=0.0, default=0.0,
                           description="Minimum content width in px "
                                       "(0 = auto-fit). Also set by "
                                       "dragging the panel's right edge",
                           update=_upd("w_width"))
    w_space_view3d: BoolProperty(name="3D Viewport", default=True,
                                 update=_upd("w_space_view3d"))
    w_space_image: BoolProperty(name="Image Editor", default=False,
                                update=_upd("w_space_image"))
    w_switches: StringProperty(name="Switches",
                               description="Switch defaults as "
                                           "name=1, other=0",
                               update=_upd("w_switches"))


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------
class _SessionOp:
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _session() is not None


class IOPS_OT_widget_editor_save(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_save"
    bl_label = "Save Widget"
    bl_description = "Validate and write the widget JSON, then leave edit mode"

    def execute(self, context):
        ok, msg = _editor().save()
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class IOPS_OT_widget_editor_save_duplicate(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_save_duplicate"
    bl_label = "Save Duplicate"
    bl_description = ("Write the edited widget as a new widget (unique "
                      "name), leave the original unchanged and leave "
                      "edit mode")

    def execute(self, context):
        ok, msg = _editor().save_duplicate()
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class IOPS_OT_widget_editor_cancel(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_cancel"
    bl_label = "Cancel Editing"
    bl_description = ("Discard every change since edit mode was entered "
                      "(a never-saved new widget is removed)")

    def execute(self, context):
        _editor().cancel()
        return {"FINISHED"}


def _key_action(action):
    from .events import IOPS_OT_widget_editor_key
    return IOPS_OT_widget_editor_key.run(action)


class IOPS_OT_widget_editor_undo(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_undo"
    bl_label = "Undo Widget Edit"
    bl_description = "Undo the last widget edit"

    @classmethod
    def poll(cls, context):
        s = _session()
        return s is not None and s.doc.can_undo and _editor().can_edit()

    def execute(self, context):
        _key_action("UNDO")
        return {"FINISHED"}


class IOPS_OT_widget_editor_redo(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_redo"
    bl_label = "Redo Widget Edit"
    bl_description = "Redo the last undone widget edit"

    @classmethod
    def poll(cls, context):
        s = _session()
        return s is not None and s.doc.can_redo and _editor().can_edit()

    def execute(self, context):
        _key_action("REDO")
        return {"FINISHED"}


class IOPS_OT_widget_editor_delete(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_delete"
    bl_label = "Delete Element"
    bl_description = "Delete the selected element"

    @classmethod
    def poll(cls, context):
        s = _session()
        return (s is not None and s.doc.selection is not None
                and _editor().can_edit())

    def execute(self, context):
        _key_action("DELETE")
        return {"FINISHED"}


class IOPS_OT_widget_editor_duplicate(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_duplicate"
    bl_label = "Duplicate Element"
    bl_description = ("Duplicate the selected element (a cell to its "
                      "right, a row below it)")

    @classmethod
    def poll(cls, context):
        s = _session()
        return (s is not None and s.doc.selection is not None
                and _editor().can_edit())

    def execute(self, context):
        if not _key_action("DUPLICATE"):
            self.report({"WARNING"}, "No room in the row for a copy")
            return {"CANCELLED"}
        return {"FINISHED"}


class IOPS_OT_widget_editor_resume_draft(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_resume_draft"
    bl_label = "Resume Draft"
    bl_description = ("Load the unsaved draft left by an earlier edit "
                      "session (undoable)")

    @classmethod
    def poll(cls, context):
        s = _session()
        return s is not None and s.draft_available

    def execute(self, context):
        if not _editor().resume_draft():
            self.report({"WARNING"}, "The draft could not be loaded")
            return {"CANCELLED"}
        return {"FINISHED"}


class IOPS_OT_widget_editor_discard_draft(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_discard_draft"
    bl_label = "Discard Draft"
    bl_description = "Delete the unsaved draft and keep the saved widget"

    @classmethod
    def poll(cls, context):
        s = _session()
        return s is not None and s.draft_available

    def execute(self, context):
        _editor().discard_draft()
        _redraw_sidebars()
        return {"FINISHED"}


# Operator search items, built lazily once per edit session.
_OP_CACHE = {"session": None, "items": []}


def _operator_items(self, context):
    s = _session()
    key = id(s) if s is not None else None
    if _OP_CACHE["session"] != key or not _OP_CACHE["items"]:
        idnames = []
        for mod in dir(bpy.ops):
            if mod.startswith("_"):
                continue
            try:
                names = dir(getattr(bpy.ops, mod))
            except Exception:
                continue
            idnames.extend(f"{mod}.{n}" for n in names
                           if not n.startswith("_"))
        idnames.sort()
        _OP_CACHE["items"] = [(i, i, "") for i in idnames]
        _OP_CACHE["session"] = key
    return _OP_CACHE["items"]


class IOPS_OT_widget_editor_pick_operator(_SessionOp, Operator):
    bl_idname = "iops.widget_editor_pick_operator"
    bl_label = "Pick Operator"
    bl_description = "Search all operators and set the element's operator"
    bl_property = "op_enum"

    op_enum: EnumProperty(name="Operator", items=_operator_items)

    @classmethod
    def poll(cls, context):
        return (_sel_type() in ("BUTTON", "SWATCH")
                and _editor().can_edit())

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        s, path, el = _selected()
        if el is None or not self.op_enum or not _editor().can_edit():
            return {"CANCELLED"}
        _done(s.doc.set_field(path, "op", self.op_enum))
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------
_FIELD_TEXT = {"op_kwargs": "Arguments", "items_from": "Items From"}


def _draw_field(col, props, name, el):
    if name == "op":
        row = col.row(align=True)
        row.prop(props, "op")
        row.operator("iops.widget_editor_pick_operator", text="",
                     icon="VIEWZOOM")
    elif name == "color":
        col.prop(props, "color")
    else:
        col.prop(props, name)
    err = _errors.get(name)
    if err:
        sub = col.row()
        sub.alert = True
        sub.label(text=err, icon="ERROR")


def _draw_selected(layout, s, props):
    box = layout.box()
    path = s.doc.selection
    el = s.doc.get(path) if path is not None else None
    if el is None:
        box.label(text="Selected: nothing (click an element)",
                  icon="RESTRICT_SELECT_OFF")
        return
    rtype = str(el.get("type", "")).upper()
    r, c = path
    where = f"row {r + 1}" if c is None else f"row {r + 1}, cell {c + 1}"
    box.label(text=f"Selected: {rtype.title()}  ({where})",
              icon="RESTRICT_SELECT_OFF")
    # Cached per doc revision (editor.rebuild_preview / select) — the
    # draw runs on every redraw and must not validate.
    if rtype != "ROW" and path in s.incomplete:
        warn = box.row()
        warn.alert = True
        warn.label(text="Incomplete: needs a binding / operator",
                   icon="ERROR")
    col = box.column()
    if rtype == "ROW":
        col.label(text="Row container: select a cell to edit it.")
    for name in ef.fields_for(el):
        _draw_field(col, props, name, el)
    top = c is None
    if ef.has_span(top, rtype):
        if ef.span_min(top, rtype) == 0:
            col.prop(props, "span", text="Span (0 = full)")
        else:
            col.prop(props, "span_min1", text="Span")
    sub = box.box()
    sub.label(text="Show If", icon="HIDE_OFF")
    sc = sub.column()
    for name in ("si_mode", "si_object_type", "si_selection", "si_prop",
                 "si_switch", "si_equals"):
        sc.prop(props, name)


def _draw_widget(layout, s, props):
    box = layout.box()
    box.label(text="Widget", icon="MENU_PANEL")
    col = box.column()
    for name in ("w_name", "w_title", "w_width"):
        _draw_field(col, props, name, None)
    row = col.row(align=True)
    row.prop(props, "w_space_view3d", toggle=True)
    row.prop(props, "w_space_image", toggle=True)
    err = _errors.get("w_space")
    if err:
        sub = col.row()
        sub.alert = True
        sub.label(text=err, icon="ERROR")
    _draw_field(col, props, "w_switches", None)


def draw_editor(layout, context):
    s = _session()
    if s is None:
        return
    props = context.window_manager.iops_widget_editor
    if s.draft_available:
        # Edits are refused until the draft is decided (editor.can_edit):
        # make that impossible to miss.
        box = layout.box()
        box.alert = True
        box.label(text="An unsaved draft of this widget exists",
                  icon="FILE_BACKUP")
        box.label(text=_editor().DRAFT_GATE_MSG + " — edits are blocked",
                  icon="ERROR")
        row = box.row(align=True)
        row.scale_y = 1.4
        row.operator("iops.widget_editor_resume_draft", text="Resume",
                     icon="RECOVER_LAST")
        row.operator("iops.widget_editor_discard_draft", text="Discard",
                     icon="TRASH")
    if s.load_problems:
        box = layout.box()
        box.alert = True
        box.label(text="Loaded with problems (Save keeps a .bak):",
                  icon="ERROR")
        for msg in s.load_problems[:6]:
            box.label(text=str(msg))
        if len(s.load_problems) > 6:
            box.label(text=f"... {len(s.load_problems) - 6} more")

    # Greyed out while a draft is undecided (the write path refuses too).
    body = layout.column()
    body.enabled = _editor().can_edit()
    _draw_selected(body, s, props)
    _draw_widget(body, s, props)

    row = layout.row(align=True)
    row.operator("iops.widget_editor_undo", text="Undo", icon="LOOP_BACK")
    row.operator("iops.widget_editor_redo", text="Redo",
                 icon="LOOP_FORWARDS")
    row.operator("iops.widget_editor_duplicate", text="Duplicate",
                 icon="DUPLICATE")
    row.operator("iops.widget_editor_delete", text="Delete", icon="X")

    bad = s.incomplete
    if bad:
        warn = layout.row()
        warn.alert = True
        warn.label(text=f"{len(bad)} incomplete element(s) block Save",
                   icon="ERROR")
    row = layout.row(align=True)
    row.scale_y = 1.3
    row.operator("iops.widget_editor_save", text="Save", icon="CHECKMARK")
    row.operator("iops.widget_editor_save_duplicate", text="Save Duplicate",
                 icon="DUPLICATE")
    row.operator("iops.widget_editor_cancel",
                 text="Cancel (delete new)" if s.is_new else "Cancel",
                 icon="CANCEL")
    op = layout.operator("iops.widget_edit", text="Open JSON",
                         icon="FILE_TEXT")
    op.name = s.name


class _EditorPanel:
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_label = "Widget Editor"

    @classmethod
    def poll(cls, context):
        return _session() is not None

    def draw(self, context):
        draw_editor(self.layout, context)


class IOPS_PT_widget_editor_view3d(_EditorPanel, Panel):
    bl_idname = "IOPS_PT_widget_editor_view3d"
    bl_space_type = "VIEW_3D"


class IOPS_PT_widget_editor_image(_EditorPanel, Panel):
    bl_idname = "IOPS_PT_widget_editor_image"
    bl_space_type = "IMAGE_EDITOR"


def register_props():
    bpy.types.WindowManager.iops_widget_editor = bpy.props.PointerProperty(
        type=IOPS_WidgetEditorProps)


def unregister_props():
    try:
        del bpy.types.WindowManager.iops_widget_editor
    except AttributeError:
        pass
    _ITEM_CACHE.clear()
    _OP_CACHE["items"] = []
    _OP_CACHE["session"] = None


classes = (
    IOPS_WidgetEditorProps,
    IOPS_OT_widget_editor_save,
    IOPS_OT_widget_editor_save_duplicate,
    IOPS_OT_widget_editor_cancel,
    IOPS_OT_widget_editor_undo,
    IOPS_OT_widget_editor_redo,
    IOPS_OT_widget_editor_delete,
    IOPS_OT_widget_editor_duplicate,
    IOPS_OT_widget_editor_resume_draft,
    IOPS_OT_widget_editor_discard_draft,
    IOPS_OT_widget_editor_pick_operator,
    IOPS_PT_widget_editor_view3d,
    IOPS_PT_widget_editor_image,
)
