import pytest

from utils.selection_sets_core import (
    ATTR_PREFIX, MAX_NAME_LEN,
    make_attr_name, parse_attr_name, sanitize_set_name, unique_name,
    group_sets, merge_membership, diff_membership,
)


def test_make_parse_roundtrip():
    attr = make_attr_name("V", "bolts")
    assert attr == ".iops_ss_V_bolts"
    assert parse_attr_name(attr) == ("V", "bolts")


def test_parse_name_with_underscores():
    assert parse_attr_name(".iops_ss_F_door_handle_top") == ("F", "door_handle_top")


def test_parse_rejects_foreign_attrs():
    assert parse_attr_name("crease") is None
    assert parse_attr_name(".hidden_other") is None
    assert parse_attr_name(".iops_ss_X_bad_domain") is None
    assert parse_attr_name(".iops_ss_V_") is None  # empty name


def test_sanitize_strips_and_collapses():
    assert sanitize_set_name("  my   set  ") == "my set"


def test_sanitize_empty_falls_back():
    assert sanitize_set_name("   ") == "Set"


def test_sanitize_truncates():
    assert len(sanitize_set_name("x" * 200)) == MAX_NAME_LEN


def test_sanitize_truncates_cyrillic_by_utf8_bytes():
    # Cyrillic chars are 2 bytes each in UTF-8, so the byte cap bites well
    # before the character cap would.
    result = sanitize_set_name("б" * 200)
    assert len(result.encode("utf-8")) <= MAX_NAME_LEN
    assert len(result) < MAX_NAME_LEN


def test_unique_name_no_clash():
    assert unique_name("Set", []) == "Set"


def test_unique_name_suffixes():
    assert unique_name("Set", ["Set"]) == "Set.001"
    assert unique_name("Set", ["Set", "Set.001"]) == "Set.002"


def test_group_sets_flags_ordered():
    names = [
        make_attr_name("F", "hinges"),
        make_attr_name("V", "hinges"),
        make_attr_name("E", "panel"),
        "crease",  # foreign, ignored
    ]
    assert group_sets(names) == {"hinges": "VF", "panel": "E"}


def test_merge_membership():
    a = {"V": {1, 2}, "E": {5}}
    b = {"V": {2, 3}, "F": {7}}
    assert merge_membership([a, b]) == {"V": {1, 2, 3}, "E": {5}, "F": {7}}


def test_diff_membership_symmetric():
    a = {"V": {1, 2}, "E": {5}}
    b = {"V": {2, 3}}
    assert diff_membership(a, b) == {"V": {1, 3}, "E": {5}}
