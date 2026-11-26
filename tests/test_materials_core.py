from utils.materials_core import (
    Row, base_name, build_rows, format_assign_report, format_merge_report,
    format_skipped, freeze, gallery_columns, group_by_base, is_numbered,
    matches_search, next_material_name, page_slice, pick_original,
    plan_merge, plan_removal, plan_slot_collapse, remap_indices,
    split_numbered,
)


def test_split_numbered():
    assert split_numbered("Steel.001") == ("Steel", 1)
    assert split_numbered("Steel.1234") == ("Steel", 1234)
    assert split_numbered("Steel") == ("Steel", None)
    # fewer than 3 digits is part of the name
    assert split_numbered("Steel.01") == ("Steel.01", None)
    assert split_numbered("v1.5") == ("v1.5", None)
    # only the last suffix counts
    assert split_numbered("A.001.002") == ("A.001", 2)
    # a bare suffix is not a duplicate of an empty name
    assert split_numbered(".001") == (".001", None)


def test_base_and_is_numbered():
    assert base_name("Glass.010") == "Glass"
    assert is_numbered("Glass.010")
    assert not is_numbered("Glass")


def test_group_by_base_keeps_order():
    groups = group_by_base(["B.002", "A", "B", "A.001", "C.01"])
    assert groups == {"B": ["B.002", "B"], "A": ["A", "A.001"],
                      "C.01": ["C.01"]}


def test_pick_original_prefers_exact_base():
    assert pick_original("Steel", ["Steel.002", "Steel", "Steel.001"]) == "Steel"


def test_pick_original_lowest_number():
    assert pick_original("Steel", ["Steel.010", "Steel.002", "Steel.003"]) == "Steel.002"


def test_plan_merge_equivalent_and_different():
    names = ["Steel", "Steel.001", "Steel.002", "Wood"]
    fps = {"Steel": 1, "Steel.001": 1, "Steel.002": 2, "Wood": 3}
    (plan,) = plan_merge(names, fps)
    assert plan.base == "Steel"
    assert plan.original == "Steel"
    assert plan.merges == ["Steel.001"]
    assert plan.kept == ["Steel.002"]
    assert plan.rename is False


def test_plan_merge_force_merges_different():
    names = ["Steel", "Steel.001"]
    (plan,) = plan_merge(names, {"Steel": 1, "Steel.001": 2}, force=True)
    assert plan.merges == ["Steel.001"] and plan.kept == []


def test_plan_merge_missing_base_renames_lowest():
    names = ["Steel.003", "Steel.002"]
    (plan,) = plan_merge(names, {"Steel.003": 1, "Steel.002": 1})
    assert plan.original == "Steel.002"
    assert plan.merges == ["Steel.003"]
    assert plan.rename is True


def test_plan_merge_lone_numbered_is_renamed():
    (plan,) = plan_merge(["Paint.001"], {"Paint.001": 1})
    assert plan.original == "Paint.001" and plan.merges == []
    assert plan.rename is True


def test_plan_merge_rename_blocked_by_taken_name():
    (plan,) = plan_merge(["Paint.001"], {}, taken_names=["Paint"])
    assert plan.rename is False


def test_plan_merge_unknown_fingerprint_is_kept():
    (plan,) = plan_merge(["A", "A.001"], {"A": 1})
    assert plan.kept == ["A.001"]


def test_plan_merge_skips_groups_without_numbered_members():
    assert plan_merge(["A", "B"], {"A": 1, "B": 1}) == []


def test_plan_merge_only_base():
    names = ["A", "A.001", "B", "B.001"]
    fps = dict.fromkeys(names, 1)
    plans = plan_merge(names, fps, only_base="B")
    assert [p.base for p in plans] == ["B"]


def test_plan_slot_collapse_all_same():
    removed, remap = plan_slot_collapse(["M", "M", "M", "M"])
    assert removed == [1, 2, 3]
    assert remap == [0, 0, 0, 0]


def test_plan_slot_collapse_keeps_others_and_empties():
    removed, remap = plan_slot_collapse(["A", "B", "A"])
    assert removed == [2] and remap == [0, 1, 0]
    removed, remap = plan_slot_collapse([None, "A", None, "A", "B"])
    assert removed == [3]
    assert remap == [0, 1, 2, 1, 3]
    # empty slots never collapse into each other
    assert plan_slot_collapse([None, None]) == ([], [0, 1])
    assert plan_slot_collapse([]) == ([], [])


def test_remap_indices():
    _removed, remap = plan_slot_collapse(["A", "B", "A"])
    assert remap_indices([0, 1, 2, 2, 1], remap) == [0, 1, 0, 0, 1]
    # an index past the last slot follows the last slot
    assert remap_indices([3], remap) == [0]
    assert remap_indices([0, 5], []) == [0, 5]


def test_plan_slot_collapse_drop_empty():
    # [M, M, <empty>, M(was M.001), Other] -> [M, Other]
    removed, remap = plan_slot_collapse(["M", "M", None, "M", "O"],
                                        drop_empty=True)
    assert removed == [1, 2, 3]
    assert remap == [0, 0, 0, 0, 1]
    # only empty slots: all go, faces to 0
    assert plan_slot_collapse([None, None], drop_empty=True) == ([0, 1], [0, 0])


def test_plan_removal():
    # remove slots 0 and 2 of 4; faces of removed slots go to new slot 0
    assert plan_removal(4, [0, 2]) == [0, 0, 0, 1]
    assert plan_removal(3, [1], {1: 2}) == [0, 1, 1]
    assert plan_removal(2, []) == [0, 1]


def test_merge_report_parts():
    plans = plan_merge(["M", "M.001"], {"M": 1, "M.001": 1})
    assert format_merge_report(plans, collapsed=3, empty_removed=1) == \
        "Merged 1 duplicate, collapsed 3 slots, removed 1 empty slot"
    # merge switched off: only the slot parts
    assert format_merge_report(None, collapsed=0, empty_removed=2) == \
        "Collapsed 0 slots, removed 2 empty slots"
    assert format_merge_report(None, collapsed=2) == "Collapsed 2 slots"
    assert format_merge_report(plans, slot_skipped={"object-linked slots": 1}) == \
        "Merged 1 duplicate, slots left on 1 object (1 object-linked slots)"
    assert format_merge_report(None) == "Nothing to do"


def test_plan_slot_collapse_empty_only():
    removed, remap = plan_slot_collapse(["A", None, "A", None],
                                        drop_empty=True, collapse_repeats=False)
    assert removed == [1, 3] and remap == [0, 0, 1, 0]


def test_matches_search():
    assert matches_search("", "anything")
    assert matches_search("ste", "Steel")
    assert matches_search("STE dark", "Steel Dark")
    assert not matches_search("ste wood", "Steel")
    # tokens may match different names
    assert matches_search("steel 001", "Steel", "Steel.001")


def _entries(*items):
    """(name, in_source) or (name, in_source, lib) -> build_rows entries."""
    out = []
    for it in items:
        name, src = it[0], it[1]
        lib = it[2] if len(it) > 2 else ""
        out.append(((name, lib), name, lib, src))
    return out


def test_build_rows_unstacked():
    entries = _entries(("A", True), ("A.001", True), ("B", False))
    rows = build_rows(entries, stack=False)
    assert [r.display for r in rows] == ["A", "A.001"]
    assert all(r.count == 1 for r in rows)


def test_build_rows_stacked_groups_and_counts():
    entries = _entries(("A", True), ("A.001", False), ("A.002", False),
                       ("B", True))
    rows = build_rows(entries, stack=True)
    assert rows == [
        Row(("A", ""), "A", 3, "A",
            (("A", ""), ("A.001", ""), ("A.002", ""))),
        Row(("B", ""), "B", 1, "B", (("B", ""),)),
    ]


def test_build_rows_group_shown_when_any_member_in_source():
    # only the duplicate is used in the scene; the row still stands for the
    # original
    entries = _entries(("A", False), ("A.001", True))
    (row,) = build_rows(entries, stack=True)
    assert row.key == ("A", "") and row.count == 2


def test_build_rows_missing_base_uses_lowest_number():
    entries = _entries(("A.002", True), ("A.005", True))
    (row,) = build_rows(entries, stack=True)
    assert row.key == ("A.002", "") and row.display == "A"


def test_build_rows_library_groups_apart():
    entries = _entries(("A", True), ("A", True, "//lib.blend"),
                       ("A.001", True, "//lib.blend"))
    rows = build_rows(entries, stack=True)
    assert [(r.key, r.count) for r in rows] == [
        (("A", ""), 1), (("A", "//lib.blend"), 2)]


def test_build_rows_search_on_member_names():
    entries = _entries(("A", True), ("A.001", True), ("B", True))
    assert [r.display for r in build_rows(entries, "001", True)] == ["A"]
    assert build_rows(entries, "001", False)[0].display == "A.001"


def test_build_rows_order_follows_original_position():
    entries = _entries(("B.001", True), ("A", True), ("B", True))
    assert [r.display for r in build_rows(entries)] == ["A", "B"]


def test_next_material_name():
    assert next_material_name([]) == "Material"
    assert next_material_name(["Material"]) == "Material 2"
    assert next_material_name(["Material", "Material 2"]) == "Material 3"
    assert next_material_name(["Material.001"]) == "Material"


def test_freeze():
    assert freeze(0.1234567891) == 0.123457
    assert freeze(-0.0000001) == 0.0
    assert freeze([1.0, (2.0, 3)]) == (1.0, (2.0, 3))
    assert freeze({"b": 1, "a": 2.0}) == (("a", 2.0), ("b", 1))
    assert freeze({"Y", "X"}) == ("X", "Y")
    assert freeze(True) is True
    assert freeze(None) is None
    hash(freeze([[1.0], {"k": [2.0]}]))


def test_format_skipped():
    assert format_skipped({}) == ""
    assert format_skipped({"Empty": 0}) == ""
    assert format_skipped({"Empty": 1}) == "1 skipped (Empty)"
    assert format_skipped({"Empty": 2, "Camera": 1}) == \
        "3 skipped (2 Empty, 1 Camera)"


def test_format_assign_report():
    assert format_assign_report("Steel", 2, {"Empty": 1}) == \
        "Assigned Steel to 2 objects, 1 skipped (Empty)"
    assert format_assign_report("Steel", 1, {}) == "Assigned Steel to 1 object"
    assert format_assign_report("Steel", 2, {}, faces=12) == \
        "Assigned Steel to 12 faces on 2 objects"


def test_format_merge_report():
    plans = plan_merge(["A", "A.001", "A.002", "B.001"],
                       {"A": 1, "A.001": 1, "A.002": 2, "B.001": 1})
    assert format_merge_report(plans, linked_skipped=2) == \
        "Merged 1 duplicate, renamed 1, kept 1 different (A.002), skipped 2 linked"
    assert format_merge_report([]) == "Merged 0 duplicates"


def test_gallery_columns():
    # the popup at its default 12 units keeps 2 columns at the default size 4
    assert gallery_columns(12, 4) == 2
    assert gallery_columns(14, 4) == 2
    assert gallery_columns(30, 4) == 6
    assert gallery_columns(2, 8) == 1


def test_page_slice():
    assert page_slice(10, 4, 0) == (0, 4, 0, 3)
    assert page_slice(10, 4, 2) == (8, 10, 2, 3)
    assert page_slice(10, 4, 9) == (8, 10, 2, 3)
    assert page_slice(0, 4, 0) == (0, 0, 0, 1)
    assert page_slice(5, 0, 0) == (0, 1, 0, 5)


# ----------------------------------------------------------------------
# stage 2: asset libraries
# ----------------------------------------------------------------------
from utils.materials_core import (  # noqa: E402
    asset_source_key, find_library_by_path, library_name_for_folder,
    normalize_path, path_in_library, same_path, shelf_preview_size,
)


def test_normalize_path_windows():
    assert normalize_path("C:/Lib/Mats/") == "c:\\lib\\mats"
    assert normalize_path("C:\\Lib\\x\\..\\Mats") == "c:\\lib\\mats"
    assert normalize_path("C:\\") == "c:\\"
    assert normalize_path("") == ""


def test_normalize_path_posix():
    assert normalize_path("/lib/mats/") == "/lib/mats"
    assert normalize_path("/lib/x/../Mats") == "/lib/Mats"
    assert normalize_path("/") == "/"


def test_path_in_library():
    assert path_in_library("C:/Lib/Mats/metal/steel.blend", "C:\\lib\\mats")
    assert path_in_library("C:/Lib/Mats", "C:/Lib/Mats/")
    # a sibling folder sharing a prefix is not inside
    assert not path_in_library("C:/Lib/Mats2/a.blend", "C:/Lib/Mats")
    assert not path_in_library("C:/Other/a.blend", "C:/Lib/Mats")
    assert path_in_library("/srv/lib/a.blend", "/srv/lib")
    assert not path_in_library("/srv/library/a.blend", "/srv/lib")
    assert not path_in_library("", "/srv/lib")
    assert not path_in_library("/srv/lib/a.blend", "")


def test_same_path():
    assert same_path("C:/A/b.blend", "c:\\a\\B.blend")
    assert not same_path("", "")
    assert not same_path("/a/b.blend", "/a/B.blend")


def test_asset_source_key_ignores_spelling_of_the_path():
    assert asset_source_key("C:/Lib/m.blend", "Steel") == \
        asset_source_key("c:\\lib\\M.blend", "Steel")
    assert asset_source_key("C:/Lib/m.blend", "Steel") != \
        asset_source_key("C:/Lib/m.blend", "Steel.001")


def test_library_name_for_folder():
    assert library_name_for_folder("C:/Assets/Materials/", []) == "Materials"
    assert library_name_for_folder("C:\\Assets\\Metal", ["Metal"]) == "Metal 2"
    assert library_name_for_folder("C:/", []) == "Materials"
    assert library_name_for_folder("", []) == "Materials"


def test_find_library_by_path():
    libs = [("User Library", "C:/Users/me/Assets"), ("Mats", "D:/Mats")]
    assert find_library_by_path(libs, "d:\\mats\\") == "Mats"
    assert find_library_by_path(libs, "D:/Other") is None


def test_shelf_preview_size():
    assert shelf_preview_size(4) == 80
    assert shelf_preview_size(0) == 16
    assert shelf_preview_size(20) == 256


def test_list_rows():
    from utils.materials_core import list_rows
    assert list_rows(3, 8) == 3
    assert list_rows(0, 8) == 1
    assert list_rows(20, 8) == 8
