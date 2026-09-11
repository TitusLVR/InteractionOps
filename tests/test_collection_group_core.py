from utils.collection_group_core import base_key, group_duplicates


class TestBaseKey:
    def test_plain_name_is_its_own_key(self):
        assert base_key("box") == "box"

    def test_strips_blender_numeric_suffix(self):
        assert base_key("box.001") == "box"
        assert base_key("box.000") == "box"
        assert base_key("box.1234") == "box"

    def test_underscore_is_part_of_the_key(self):
        assert base_key("box_lid") == "box_lid"
        assert base_key("box_lid.001") == "box_lid"

    def test_dot_without_digits_is_kept(self):
        assert base_key("box.high") == "box.high"
        assert base_key("box.high.002") == "box.high"

    def test_bare_dot_suffix_edge_cases(self):
        assert base_key(".001") == ".001"
        assert base_key("box.") == "box."


class TestGroupDuplicates:
    def test_singletons_are_dropped(self):
        assert group_duplicates(["a", "b", "c"]) == {}

    def test_groups_copies_under_base_key(self):
        groups = group_duplicates(["box", "box.000", "box.001", "lamp"])
        assert groups == {"box": ["box", "box.000", "box.001"]}

    def test_preserves_input_order_and_keys_sorted(self):
        groups = group_duplicates(["z.001", "a", "z", "a.003"])
        assert list(groups) == ["a", "z"]
        assert groups["z"] == ["z.001", "z"]
