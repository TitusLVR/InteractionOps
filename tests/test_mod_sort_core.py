from utils.mod_sort_core import parse_names, sort_rank, sorted_names


def R(*keys):
    return [(k, ()) for k in keys]


HEAD = [("NODES", ("Smooth by Angle",))] + R("MIRROR", "ARRAY")
TAIL = R("SIMPLE_DEFORM", "WEIGHTED_NORMAL", "TRIANGULATE")


class TestParseNames:
    def test_splits_trims_and_drops_empties(self):
        assert parse_names(" a, b ,,c ") == ("a", "b", "c")

    def test_empty(self):
        assert parse_names("") == ()


class TestSortRank:
    def test_head_items_rank_by_list_position(self):
        assert (sort_rank("MIRROR", "Mirror", HEAD, TAIL)
                < sort_rank("ARRAY", "Array", HEAD, TAIL))

    def test_tail_items_rank_by_list_position_after_middle(self):
        mid = sort_rank("BEVEL", "Bevel", HEAD, TAIL)
        assert sort_rank("ARRAY", "Array", HEAD, TAIL) < mid
        assert mid < sort_rank("SIMPLE_DEFORM", "SimpleDeform", HEAD, TAIL)
        assert (sort_rank("NODES", "Smooth by Angle", HEAD, TAIL)
                < sort_rank("MIRROR", "Mirror", HEAD, TAIL))

    def test_unlisted_types_share_the_middle_rank(self):
        assert (sort_rank("BEVEL", "Bevel", HEAD, TAIL)
                == sort_rank("BOOLEAN", "Boolean", HEAD, TAIL))

    def test_names_restrict_the_type_case_insensitive(self):
        head = [("BEVEL", ("final", "chamfer"))]
        assert sort_rank("BEVEL", "Bevel FINAL", head, []) == 0
        assert sort_rank("BEVEL", "My Chamfer", head, []) == 0
        assert sort_rank("BEVEL", "Bevel", head, []) == 500
        assert sort_rank("BOOLEAN", "final", head, []) == 500

    def test_nodes_rule_without_names_catches_every_gn_modifier(self):
        assert sort_rank("NODES", "Anything", [], R("NODES")) == 1000

    def test_first_matching_rule_wins(self):
        head = [("BEVEL", ("keep",)), ("BEVEL", ())]
        assert sort_rank("BEVEL", "Bevel keep", head, []) == 0
        assert sort_rank("BEVEL", "Bevel", head, []) == 1

    def test_head_rule_beats_tail_rule(self):
        assert sort_rank("BEVEL", "x", R("BEVEL"), [("BEVEL", ("x",))]) == 0


class TestSortedNames:
    def test_moves_head_and_tail_keeps_middle_order(self):
        stack = [("Tri", "TRIANGULATE"), ("Bool", "BOOLEAN"),
                 ("Mir", "MIRROR"), ("Bev", "BEVEL"), ("Arr", "ARRAY")]
        assert sorted_names(stack, HEAD, TAIL) == [
            "Mir", "Arr", "Bool", "Bev", "Tri"]

    def test_equal_ranks_are_stable(self):
        stack = [("A", "BEVEL"), ("B", "BEVEL"), ("M2", "MIRROR"),
                 ("M1", "MIRROR")]
        assert sorted_names(stack, HEAD, TAIL) == ["M2", "M1", "A", "B"]

    def test_named_bevel_goes_to_the_bottom_plain_bevel_stays(self):
        stack = [("Bevel Final", "BEVEL"), ("Bool", "BOOLEAN"),
                 ("Bevel", "BEVEL")]
        assert sorted_names(stack, [], [("BEVEL", ("final",))]) == [
            "Bool", "Bevel", "Bevel Final"]

    def test_optional_match_text_is_searched_instead_of_name(self):
        stack = [("GeometryNodes", "NODES", "GeometryNodes | Smooth by Angle"),
                 ("Bevel", "BEVEL")]
        assert sorted_names(stack, HEAD, []) == ["GeometryNodes", "Bevel"]

    def test_empty_lists_leave_stack_untouched(self):
        stack = [("Tri", "TRIANGULATE"), ("Mir", "MIRROR")]
        assert sorted_names(stack, [], []) == ["Tri", "Mir"]
