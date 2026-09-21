import json

from utils import node_pie_rules as nr


def _entry(idname):
    return {"node": idname}


def test_slot_labels_are_pie_draw_order():
    assert nr.SLOT_LABELS == ("W", "E", "S", "N", "NW", "NE", "SW", "SE")


def test_normalise_pads_short_slot_lists_to_eight():
    slots = nr.normalise_rule({"slots": [_entry("A"), _entry("B")]})
    assert len(slots) == nr.SLOT_COUNT
    assert slots[0] == {"node": "A"}
    assert slots[2:] == [None] * 6


def test_normalise_truncates_overlong_slot_lists():
    slots = nr.normalise_rule({"slots": [_entry("A")] * 12})
    assert len(slots) == nr.SLOT_COUNT


def test_normalise_drops_entries_without_a_node_field():
    slots = nr.normalise_rule({"slots": [{"text": "oops"}, _entry("B")]})
    assert slots[0] is None
    assert slots[1] == {"node": "B"}


def test_user_rule_replaces_shipped_rule_wholesale():
    defaults = {"GeometryNodeMeshCube": {"slots": [_entry("A"), _entry("B")]}}
    user = {"GeometryNodeMeshCube": {"slots": [_entry("Z")]}}
    merged = nr.merge(defaults, user)
    slots = nr.get_entries(merged, "GeometryNodeMeshCube")
    assert slots[0] == {"node": "Z"}
    assert slots[1] is None


def test_user_may_add_rules_for_unknown_node_types():
    merged = nr.merge({}, {"GeometryNodeFooBar": {"slots": [_entry("Z")]}})
    assert nr.get_entries(merged, "GeometryNodeFooBar")[0] == {"node": "Z"}


def test_empty_slot_list_forces_the_fallback():
    merged = nr.merge({"X": {"slots": [_entry("A")]}}, {"X": {"slots": []}})
    assert nr.get_entries(merged, "X") is None


def test_unknown_node_type_returns_none():
    assert nr.get_entries({}, "GeometryNodeNope") is None


def test_load_document_applies_user_rules_over_defaults():
    defaults = {"X": {"slots": [_entry("A")]}}
    text = json.dumps({"version": nr.SCHEMA_VERSION, "tree_type": "GeometryNodeTree",
                       "rules": {"X": {"slots": [_entry("Z")]}}})
    rules, warnings = nr.load_document(text, defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "Z"}
    assert warnings == []


def test_load_document_reports_a_newer_schema_but_still_loads():
    defaults = {}
    text = json.dumps({"version": nr.SCHEMA_VERSION + 5,
                       "rules": {"X": {"slots": [_entry("Z")]}}})
    rules, warnings = nr.load_document(text, defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "Z"}
    assert any("version" in w for w in warnings)


def test_malformed_json_degrades_to_defaults_with_a_warning():
    defaults = {"X": {"slots": [_entry("A")]}}
    rules, warnings = nr.load_document("{not json", defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "A"}
    assert warnings


def test_empty_file_degrades_to_defaults_without_crashing():
    defaults = {"X": {"slots": [_entry("A")]}}
    rules, warnings = nr.load_document("   ", defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "A"}
    assert warnings == []


def test_non_dict_document_degrades_to_defaults():
    defaults = {"X": {"slots": [_entry("A")]}}
    rules, warnings = nr.load_document("[1, 2, 3]", defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "A"}
    assert warnings


def test_defaults_cover_both_tree_types():
    assert nr.DEFAULTS["GeometryNodeTree"]
    assert nr.DEFAULTS["ShaderNodeTree"]


def test_every_default_rule_normalises_to_eight_slots():
    for tree_type, rules in nr.DEFAULTS.items():
        for node_idname, rule in rules.items():
            slots = nr.normalise_rule(rule)
            assert len(slots) == nr.SLOT_COUNT, (tree_type, node_idname)
            assert any(slots), (tree_type, node_idname)


def test_fallback_rules_offer_the_search_slot():
    for tree_type, rules in nr.DEFAULTS.items():
        slots = nr.normalise_rule(rules[nr.FALLBACK_KEY])
        assert any(s and s["node"] == "__search__" for s in slots), tree_type


def test_shader_only_nodes_are_absent_from_geometry_defaults():
    shader_only = {"ShaderNodeTexCoord", "ShaderNodeBsdfPrincipled",
                   "ShaderNodeOutputMaterial", "ShaderNodeMixShader",
                   "ShaderNodeAddShader", "ShaderNodeBump",
                   "ShaderNodeDisplacement", "ShaderNodeNormalMap"}
    for node_idname, rule in nr.DEFAULTS["GeometryNodeTree"].items():
        for slot in nr.normalise_rule(rule):
            if slot:
                assert slot["node"] not in shader_only, node_idname


def test_geometry_only_nodes_are_absent_from_shader_defaults():
    for node_idname, rule in nr.DEFAULTS["ShaderNodeTree"].items():
        for slot in nr.normalise_rule(rule):
            if slot and slot["node"].startswith("GeometryNode"):
                raise AssertionError(f"{node_idname} offers {slot['node']}")


# --- untrusted optional fields -------------------------------------------
# These are hand-edited JSON fields that reach code assuming a type: `text`
# and `icon` go into UILayout.operator() (TypeError inside a draw callback on
# a non-string), `props`/`inputs` are .items()-ed by the spawn operator
# (AttributeError out of execute() on a non-dict).


def test_non_string_text_is_dropped_but_the_slot_survives():
    slots = nr.normalise_rule({"slots": [{"node": "A", "text": 42}]})
    assert slots[0] == {"node": "A"}


def test_non_string_icon_is_dropped_but_the_slot_survives():
    slots = nr.normalise_rule({"slots": [{"node": "A", "icon": ["X"]}]})
    assert slots[0] == {"node": "A"}


def test_non_dict_props_is_dropped_but_the_slot_survives():
    slots = nr.normalise_rule({"slots": [{"node": "A", "props": "MULTIPLY"}]})
    assert slots[0] == {"node": "A"}


def test_non_dict_inputs_is_dropped_but_the_slot_survives():
    slots = nr.normalise_rule({"slots": [{"node": "A", "inputs": [1, 2]}]})
    assert slots[0] == {"node": "A"}


def test_well_typed_optional_fields_are_kept():
    entry = {"node": "A", "text": "T", "icon": "VIEWZOOM",
             "props": {"operation": "MULTIPLY"}, "inputs": {"1": 2.0}}
    assert nr.normalise_rule({"slots": [entry]})[0] == entry


def test_unknown_fields_pass_through_untouched():
    """Only the fields with a known consumer are type-checked."""
    slots = nr.normalise_rule({"slots": [{"node": "A", "from_socket": 1,
                                          "future_field": {"x": 1}}]})
    assert slots[0]["from_socket"] == 1
    assert slots[0]["future_field"] == {"x": 1}


def test_normalise_does_not_mutate_the_source_entry():
    """The shipped DEFAULTS tables are normalised on every pie draw."""
    entry = {"node": "A", "text": 42}
    nr.normalise_rule({"slots": [entry]})
    assert entry == {"node": "A", "text": 42}


def test_normalise_entry_rejects_non_dicts_and_missing_node():
    assert nr.normalise_entry(None) is None
    assert nr.normalise_entry("GeometryNodeMeshCube") is None
    assert nr.normalise_entry({"text": "oops"}) is None
    assert nr.normalise_entry({"node": 7}) is None


# --- the optional `enabled` flag -----------------------------------------
# A slot switched off in the preferences keeps its entry (node, label,
# props, inputs) and only stops being offered. Absent means enabled, so
# presets written before the field existed load unchanged.


def test_enabled_absent_means_the_slot_is_enabled():
    entry = nr.normalise_rule({"slots": [_entry("A")]})[0]
    assert entry == {"node": "A"}
    assert nr.is_enabled(entry) is True


def test_enabled_false_is_kept_and_disables_the_slot():
    entry = nr.normalise_rule({"slots": [{"node": "A", "enabled": False}]})[0]
    assert entry == {"node": "A", "enabled": False}
    assert nr.is_enabled(entry) is False


def test_enabled_true_is_kept_and_leaves_the_slot_enabled():
    entry = nr.normalise_rule({"slots": [{"node": "A", "enabled": True}]})[0]
    assert entry == {"node": "A", "enabled": True}
    assert nr.is_enabled(entry) is True


def test_non_bool_enabled_is_dropped_but_the_slot_survives():
    entry = nr.normalise_rule({"slots": [{"node": "A", "enabled": "no",
                                          "text": "T"}]})[0]
    assert entry == {"node": "A", "text": "T"}
    assert nr.is_enabled(entry) is True


def test_is_enabled_reads_a_raw_non_bool_as_enabled():
    """Same degrade-to-enabled rule before normalisation as after."""
    assert nr.is_enabled({"node": "A", "enabled": "no"}) is True
    assert nr.is_enabled({"node": "A", "enabled": 0}) is True


def test_is_enabled_says_no_for_an_empty_slot():
    assert nr.is_enabled(None) is False
    assert nr.is_enabled("GeometryNodeMeshCube") is False


def test_disabling_a_slot_keeps_the_rest_of_the_entry():
    entry = {"node": "A", "text": "T", "icon": "VIEWZOOM",
             "props": {"operation": "MULTIPLY"}, "inputs": {"1": 2.0},
             "enabled": False}
    assert nr.normalise_rule({"slots": [entry]})[0] == entry


def test_a_disabled_rule_differs_from_the_same_rule_enabled():
    """What makes a disabled-only edit worth saving (see _rules_to_save)."""
    shipped = {"slots": [_entry("A")]}
    edited = {"slots": [{"node": "A", "enabled": False}]}
    assert nr.normalise_rule(edited) != nr.normalise_rule(shipped)
