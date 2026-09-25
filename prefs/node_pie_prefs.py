"""Node Editor Pie rollout (Preferences tab): edit which nodes each pie slot spawns.

Slot edits go straight into the in-memory store (so the next pie open shows
them). Save writes only the rules that differ from the shipped defaults to
scripts/presets/IOPS/node_pies/<tree>.json, so an addon update can still
reach every node type the user never touched.
Per-slot `props`/`inputs` are shown read-only — they are JSON-only in v1.
"""
import bpy

from ..operators.node_pie import catalog, store
from ..utils import node_pie_rules as nr

#: Numpad key -> pie direction. The grid is labelled the way the keys sit
#: under the hand (Slot 7/8/9, 4/6, 1/2/3), matching the Shading Pie
#: Layout; the compass names survive only as `nr.SLOT_LABELS`, which is
#: what actually orders the `slots` list.
NUMPAD_LABELS = {7: "NW", 8: "N", 9: "NE", 4: "W", 6: "E",
                 1: "SW", 2: "S", 3: "SE"}


def _rules(prefs):
    return dict(store.rules_for(prefs.node_pie_tree_type))


def _rules_to_save(tree_type, rules):
    """Only the entries that actually differ from the shipped defaults.

    `rules` is defaults ∪ user (see store.rules_for/merge) — writing it
    wholesale would freeze every shipped rule the user never touched into
    their file forever, permanently cutting those node types off from
    future addon updates. Slots are compared normalised so a rule that
    merely round-tripped through the UI unchanged is not written; a rule
    the user emptied to "slots": [] (see IOPS_OT_NodePieRemoveRule) DOES
    differ from its shipped default and is kept.
    """
    defaults = nr.DEFAULTS.get(tree_type, {})
    out = {}
    for key, rule in rules.items():
        shipped = defaults.get(key)
        if shipped is not None and nr.normalise_rule(rule) == nr.normalise_rule(shipped):
            continue
        out[key] = rule
    return out


def _rule_label(key):
    """Friendly display name for a rule key (a node `bl_idname`, or the
    fallback sentinel, which has no node type behind it)."""
    if key == nr.FALLBACK_KEY:
        return "Fallback (no matching rule)"
    return store.label_for(key)


def _current_rule_key(prefs):
    rules = _rules(prefs)
    key = prefs.node_pie_rule_name
    if key in rules:
        return key
    return nr.FALLBACK_KEY


def _write_entry(prefs, index, entry):
    """Replace slot `index` of the rule currently being edited."""
    tree_type = prefs.node_pie_tree_type
    rules = _rules(prefs)
    key = _current_rule_key(prefs)
    slots = nr.normalise_rule(rules.get(key, {}))
    slots[index] = entry
    rules[key] = {"slots": slots}
    store.set_rules(tree_type, rules)


def _write_slot(prefs, index, node_idname):
    _write_entry(prefs, index, {"node": node_idname} if node_idname else None)


# --- slot proxy properties ------------------------------------------------
# `layout.prop()` needs a real property to bind to, but a node-pie slot is
# not addon state: it is an entry in the rule JSON, per tree type and per
# node type. So the preferences carry SLOT_COUNT Bool/String properties
# whose get/set read and write the current rule's slot through the store —
# same get/set-backed-property technique as `theme_preset` /
# `theme_preset_name` in prefs/theme.py, for the same reason (the real
# state lives somewhere Blender cannot store for us).
#
# Getters run inside draw callbacks, so they must never raise: every one of
# them degrades to "empty slot" when there is no rule selected, the selected
# rule has been removed, or the tree type changed under them. Setters are
# a no-op on an empty slot rather than inventing an entry with no `node`.


def _slot_entry(prefs, index):
    """The current rule's slot `index`, or None. Never raises."""
    try:
        slots = nr.normalise_rule(_rules(prefs).get(_current_rule_key(prefs), {}))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if 0 <= index < len(slots):
        return slots[index]
    return None


def slot_enable_get(prefs, index):
    entry = _slot_entry(prefs, index)
    if entry is None:
        # An empty slot has nothing to switch off, and reading it as enabled
        # keeps its cell expanded so the node picker stays reachable.
        return True
    return nr.is_enabled(entry)


def slot_enable_set(prefs, index, value):
    entry = _slot_entry(prefs, index)
    if entry is None:
        return
    updated = dict(entry)
    if value:
        # Drop the key rather than writing `true`: an untouched entry then
        # still compares equal to its shipped default and stays out of the
        # saved file (see _rules_to_save).
        updated.pop("enabled", None)
    else:
        updated["enabled"] = False
    _write_entry(prefs, index, updated)


def slot_name_get(prefs, index):
    entry = _slot_entry(prefs, index)
    if entry is None:
        return ""
    text = entry.get("text")
    return text if isinstance(text, str) else ""


def slot_name_set(prefs, index, value):
    entry = _slot_entry(prefs, index)
    if entry is None:
        return
    updated = dict(entry)
    if value:
        updated["text"] = value
    else:
        # Empty means "use the node's own friendly name".
        updated.pop("text", None)
    _write_entry(prefs, index, updated)


class IOPS_OT_NodePieSetSlot(bpy.types.Operator):
    """Set the node this pie slot spawns"""

    bl_idname = "iops.node_pie_set_slot"
    bl_label = "Set Slot"
    bl_property = "node_type"

    slot_index: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    node_type: bpy.props.EnumProperty(
        name="Node",
        items=lambda self, context: catalog.items(
            context.preferences.addons["InteractionOps"].preferences.node_pie_tree_type
        ),
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        _write_slot(prefs, self.slot_index, self.node_type)
        return {'FINISHED'}


class IOPS_OT_NodePieClearSlot(bpy.types.Operator):
    """Empty this pie slot"""

    bl_idname = "iops.node_pie_clear_slot"
    bl_label = "Clear Slot"

    slot_index: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        _write_slot(prefs, self.slot_index, "")
        return {'FINISHED'}


class IOPS_OT_NodePieSave(bpy.types.Operator):
    """Write these rules to the user preset file"""

    bl_idname = "iops.node_pie_save"
    bl_label = "Save"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        tree_type = prefs.node_pie_tree_type
        full = store.rules_for(tree_type)
        to_save = _rules_to_save(tree_type, full)
        try:
            path = store.save(tree_type, to_save)
        except (RuntimeError, OSError) as exc:
            # store.save() raises RuntimeError when Blender reports no user
            # scripts path — nothing to write to — and can also raise a
            # plain OSError from os.makedirs()/open() (read-only filesystem,
            # permission denied, disk full). This operator is invoked from
            # the preferences UI, so neither may propagate out of execute()
            # (that would print a traceback to the user's console).
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        # store.save() caches exactly what it wrote (`to_save`, the diff-only
        # subset) — restore the full defaults ∪ user view in memory so the
        # in-session pie and this tab are unaffected by what got persisted.
        store.set_rules(tree_type, full)
        self.report({'INFO'}, f"Saved {path}")
        return {'FINISHED'}


class IOPS_OT_NodePieReload(bpy.types.Operator):
    """Re-read the user preset file, discarding unsaved edits"""

    bl_idname = "iops.node_pie_reload"
    bl_label = "Reload"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        store.reload(prefs.node_pie_tree_type)
        return {'FINISHED'}


class IOPS_OT_NodePieResetRule(bpy.types.Operator):
    """Drop this rule back to the shipped default"""

    bl_idname = "iops.node_pie_reset_rule"
    bl_label = "Reset Rule"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        tree_type = prefs.node_pie_tree_type
        rules = _rules(prefs)
        key = _current_rule_key(prefs)
        shipped = nr.DEFAULTS.get(tree_type, {}).get(key)
        if shipped is None:
            rules.pop(key, None)
            # No shipped default for this key — same situation
            # IOPS_OT_NodePieRemoveRule handles, so agree with it: point
            # the selector back at the fallback rather than leaving it on
            # a key that no longer exists in `rules`.
            prefs.node_pie_rule_name = nr.FALLBACK_KEY
        else:
            rules[key] = shipped
        store.set_rules(tree_type, rules)
        return {'FINISHED'}


class IOPS_OT_NodePieResetAll(bpy.types.Operator):
    """Drop every rule for this tree type back to the shipped defaults"""

    bl_idname = "iops.node_pie_reset_all"
    bl_label = "Reset All"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        tree_type = prefs.node_pie_tree_type
        store.set_rules(tree_type, dict(nr.DEFAULTS.get(tree_type, {})))
        return {'FINISHED'}


class IOPS_OT_NodePieAddRule(bpy.types.Operator):
    """Start a rule for another node type"""

    bl_idname = "iops.node_pie_add_rule"
    bl_label = "Add Rule"
    bl_property = "node_type"

    node_type: bpy.props.EnumProperty(
        name="Node",
        items=lambda self, context: catalog.items(
            context.preferences.addons["InteractionOps"].preferences.node_pie_tree_type
        ),
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        rules = _rules(prefs)
        rules.setdefault(self.node_type, {"slots": [None] * nr.SLOT_COUNT})
        store.set_rules(prefs.node_pie_tree_type, rules)
        prefs.node_pie_rule_name = self.node_type
        return {'FINISHED'}


class IOPS_OT_NodePieRemoveRule(bpy.types.Operator):
    """Make this node type fall back to the generic pie (Reset Rule restores its shipped default instead)"""

    bl_idname = "iops.node_pie_remove_rule"
    bl_label = "Remove Rule"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        tree_type = prefs.node_pie_tree_type
        rules = _rules(prefs)
        key = _current_rule_key(prefs)
        if key != nr.FALLBACK_KEY:
            # Popping the key would only remove it from the merged
            # (defaults ∪ user) dict in memory — on the next load it is
            # re-merged over the shipped defaults and the "removed" rule
            # comes back. "slots": [] is a real, persistable value: it
            # already means "force the fallback pie for this node type"
            # (see nr.get_entries), and it survives save/load.
            rules[key] = {"slots": []}
            prefs.node_pie_rule_name = nr.FALLBACK_KEY
            store.set_rules(tree_type, rules)
        return {'FINISHED'}


def draw_node_pie_tab(prefs, layout, context):
    layout.row(align=True).prop(prefs, "node_pie_tree_type", expand=True)

    rules = _rules(prefs)
    key = _current_rule_key(prefs)

    row = layout.row(align=True)
    row.label(text=f"Rule: {_rule_label(key)}", icon='NODE')
    if key != nr.FALLBACK_KEY:
        # The one place the technical id survives, dimmed, so hand-editing
        # the JSON is still discoverable — same technique as the slot rows'
        # props/inputs summary below.
        sub = row.row()
        sub.enabled = False
        sub.label(text=f"·  {key}")
    row.operator("iops.node_pie_add_rule", text="", icon='ADD')
    row.operator("iops.node_pie_remove_rule", text="", icon='REMOVE')

    keys = sorted(k for k in rules if k != nr.FALLBACK_KEY)
    grid = layout.box().grid_flow(columns=3, even_columns=True)
    for name in [nr.FALLBACK_KEY] + keys:
        op_row = grid.row()
        op_row.alert = (name == key)
        op_row.operator("iops.node_pie_pick_rule", text=_rule_label(name)).rule_name = name

    box = layout.box()
    slots = nr.normalise_rule(rules.get(key, {}))

    def draw_pie_slot(parent, numpad):
        # Cells are numbered like the numpad (and like the Shading Pie
        # Layout above), but the slot index comes from SLOT_LABELS via
        # NUMPAD_LABELS rather than a second hardcoded index table, so a
        # change to the pie draw order is automatically followed.
        index = nr.SLOT_LABELS.index(NUMPAD_LABELS[numpad])
        slot = slots[index]
        sub = parent.box().column(align=True)
        sub.prop(prefs, f"node_pie_slot_{index}_enable",
                 text=f"Slot {numpad}", toggle=True)
        if not getattr(prefs, f"node_pie_slot_{index}_enable"):
            # Collapsed to the toggle: the entry is kept, the pie draws a
            # separator in this position until it is switched back on.
            return
        sub.prop(prefs, f"node_pie_slot_{index}_name", text="",
                 placeholder="custom label")
        # The picker button names what the slot holds — the node, not the
        # custom label, which now has its own field above it. `__search__`
        # is a sentinel, not a node type, so label_for() would print it raw.
        if not slot:
            text = "—"
        elif slot["node"] == "__search__":
            text = "Node Search"
        else:
            text = store.label_for(slot["node"])
        btn_row = sub.row(align=True)
        btn_row.operator("iops.node_pie_set_slot", text=text).slot_index = index
        btn_row.operator("iops.node_pie_clear_slot", text="", icon='X') \
            .slot_index = index
        if slot and (slot.get("props") or slot.get("inputs")):
            preset = slot.get("props") or slot.get("inputs")
            info = sub.row()
            info.enabled = False
            info.label(text=", ".join(f"{k}={v}" for k, v in preset.items()))

    row = box.row(align=True)
    for numpad in (7, 8, 9):
        draw_pie_slot(row, numpad)
    row = box.row(align=True)
    draw_pie_slot(row, 4)
    row.box().column(align=True).label(text=" ")
    draw_pie_slot(row, 6)
    row = box.row(align=True)
    for numpad in (1, 2, 3):
        draw_pie_slot(row, numpad)

    row = layout.row(align=True)
    row.operator("iops.node_pie_save", icon='FILE_TICK')
    row.operator("iops.node_pie_reload", icon='FILE_REFRESH')
    row.operator("iops.node_pie_reset_rule", icon='LOOP_BACK')
    row.operator("iops.node_pie_reset_all", icon='TRASH')


class IOPS_OT_NodePiePickRule(bpy.types.Operator):
    """Edit this rule"""

    bl_idname = "iops.node_pie_pick_rule"
    bl_label = "Pick Rule"

    rule_name: bpy.props.StringProperty(default=nr.FALLBACK_KEY)

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        prefs.node_pie_rule_name = self.rule_name
        return {'FINISHED'}


classes = (
    IOPS_OT_NodePieSetSlot,
    IOPS_OT_NodePieClearSlot,
    IOPS_OT_NodePieSave,
    IOPS_OT_NodePieReload,
    IOPS_OT_NodePieResetRule,
    IOPS_OT_NodePieResetAll,
    IOPS_OT_NodePieAddRule,
    IOPS_OT_NodePieRemoveRule,
    IOPS_OT_NodePiePickRule,
)
