import pytest

from utils.search_rename_core import push_history, rename


class TestPlain:
    def test_replaces_every_occurrence_ignoring_case(self):
        assert rename("Wall_wall_WALL", "wall", "Fence") == "Fence_Fence_Fence"

    def test_case_sensitive(self):
        assert rename("Wall_wall", "wall", "x", case_sensitive=True) == "Wall_x"

    def test_first_only(self):
        assert rename("a_a_a", "a", "b", first_only=True) == "b_a_a"

    def test_empty_search_leaves_name(self):
        assert rename("Cube", "", "x") == "Cube"

    def test_empty_replace_deletes(self):
        assert rename("SM_Cube", "SM_", "") == "Cube"

    def test_regex_chars_are_literal(self):
        assert rename("a.b(c)", ".b(", "-") == "a-c)"


class TestMultiple:
    def test_pairs_terms_by_position(self):
        assert rename("äöü", "ä|ö|ü", "ae|oe|ue") == "aeoeue"

    def test_single_replacement_for_all_terms(self):
        assert rename("L_arm_R_leg", "L_|R_", "") == "arm_leg"

    def test_swap_is_simultaneous(self):
        assert rename("Left_Right", "Left|Right", "Right|Left") == "Right_Left"

    def test_missing_replacements_delete(self):
        assert rename("a_b_c", "a|b|c", "x|y") == "x_y_"


class TestWildcards:
    def test_star(self):
        assert rename("Cube_tmp_v2", "_tmp*", "") == "Cube"

    def test_question_mark(self):
        assert rename("lod0_lod1", "lod?", "L") == "L_L"


class TestSuffix:
    def test_suffix_kept_out_of_search_by_default(self):
        assert rename("Cube.001", "0", "X") == "Cube.001"

    def test_suffix_searched_with_e(self):
        assert rename("Cube.001", ".001", "", include_suffix=True) == "Cube"

    def test_suffix_survives_base_rename(self):
        assert rename("Cube.012", "Cube", "Box") == "Box.012"


class TestRegex:
    def test_groups(self):
        assert rename("wall_01", r"(\w+)_(\d+)", "$2_$1", regex=True) == "01_wall"

    def test_pipe_is_alternation(self):
        assert rename("cat_dog", "cat|dog", "pet", regex=True) == "pet_pet"

    def test_first_only(self):
        assert rename("a1a2", r"\d", "#", regex=True, first_only=True) == "a#a2"

    def test_backslash_in_replacement_is_literal(self):
        assert rename("a", "a", r"\n", regex=True) == r"\n"

    def test_invalid_pattern_raises(self):
        with pytest.raises(ValueError):
            rename("a", "(", "", regex=True)

    def test_subst_replaces_whole_name(self):
        assert rename("SM_Rock_big", "Rock", "Stone", regex=True, subst=True) == "Stone"

    def test_subst_expands_groups(self):
        assert rename("SM_Rock_big", r"_(\w+?)_", "$1", regex=True, subst=True) == "Rock"

    def test_subst_without_match_leaves_name(self):
        assert rename("Cube", "Rock", "Stone", regex=True, subst=True) == "Cube"

    def test_subst_ignored_without_regex(self):
        assert rename("SM_Rock", "Rock", "Stone", subst=True) == "SM_Stone"


class TestCase:
    def test_lower(self):
        assert rename("Wall_A", "", "", case="LOWER") == "wall_a"

    def test_upper(self):
        assert rename("Wall_a", "", "", case="UPPER") == "WALL_A"

    def test_first_letter(self):
        assert rename("wALL_DOOR", "", "", case="FIRST") == "Wall_door"

    def test_each_word(self):
        assert rename("big wall_DOOR-frame.left", "", "", case="WORDS") == "Big Wall_Door-Frame.Left"

    def test_applied_after_replace(self):
        assert rename("sm_rock", "sm_", "prop_", case="UPPER") == "PROP_ROCK"


class TestHistory:
    def test_newest_first_without_duplicates(self):
        h = ["b", "a"]
        push_history(h, "a")
        assert h == ["a", "b"]

    def test_capped(self):
        h = [str(i) for i in range(5)]
        push_history(h, "x", limit=5)
        assert h == ["x", "0", "1", "2", "3"]

    def test_empty_not_stored(self):
        h = ["a"]
        push_history(h, "")
        assert h == ["a"]
