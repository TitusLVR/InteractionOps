from utils.renamed_idnames import (
    RENAMED_IDNAMES,
    migrate_idname,
    migrate_key_rows,
    migrate_operator_call,
)


def _row(idname, key="F19", ctrl=False):
    return [idname, key, "PRESS", ctrl, False, False, False]


class TestMigrateKeyRows:
    def test_old_idname_carries_its_binding_to_the_new_one(self):
        rows = [_row("iops.mesh_smart_inset", "I", ctrl=True)]
        assert migrate_key_rows(rows) == [_row("iops.mesh_inset", "I", ctrl=True)]

    def test_both_renamed_operators(self):
        rows = [_row("iops.mesh_smart_inset", "I"), _row("iops.mesh_smart_edge_slide", "E")]
        assert migrate_key_rows(rows) == [_row("iops.mesh_inset", "I"), _row("iops.mesh_edge_slide", "E")]

    def test_new_idname_wins_and_old_is_dropped(self):
        rows = [_row("iops.mesh_smart_inset", "I"), _row("iops.mesh_inset", "J")]
        assert migrate_key_rows(rows) == [_row("iops.mesh_inset", "J")]

    def test_new_idname_wins_when_it_comes_first(self):
        rows = [_row("iops.mesh_edge_slide", "J"), _row("iops.mesh_smart_edge_slide", "E")]
        assert migrate_key_rows(rows) == [_row("iops.mesh_edge_slide", "J")]

    def test_other_rows_untouched_and_order_kept(self):
        rows = [_row("iops.mesh_shear", "S"), _row("iops.mesh_smart_inset", "I"), _row("iops.function_f1", "F1")]
        assert migrate_key_rows(rows) == [
            _row("iops.mesh_shear", "S"), _row("iops.mesh_inset", "I"), _row("iops.function_f1", "F1"),
        ]

    def test_input_not_changed_and_rows_copied(self):
        rows = [_row("iops.mesh_smart_inset"), _row("iops.mesh_shear")]
        before = [list(r) for r in rows]
        out = migrate_key_rows(rows)
        assert rows == before
        assert out[1] is not rows[1]

    def test_tuples_become_lists(self):
        assert migrate_key_rows([("iops.mesh_smart_inset", "I", "PRESS", False, False, False, False)]) == [
            _row("iops.mesh_inset", "I"),
        ]

    def test_malformed_rows_pass_through(self):
        rows = [[], "junk", _row("iops.mesh_smart_inset")]
        assert migrate_key_rows(rows) == [[], "junk", _row("iops.mesh_inset")]

    def test_empty(self):
        assert migrate_key_rows([]) == []


class TestMigrateIdname:
    def test_renamed(self):
        for old, new in RENAMED_IDNAMES.items():
            assert migrate_idname(old) == new

    def test_unchanged(self):
        assert migrate_idname("iops.mesh_shear") == "iops.mesh_shear"
        assert migrate_idname("DEFAULT") == "DEFAULT"
        assert migrate_idname(["not", "hashable"]) == ["not", "hashable"]


class TestMigrateOperatorCall:
    def test_bare_idname(self):
        assert migrate_operator_call("iops.mesh_smart_inset") == "iops.mesh_inset"

    def test_call_with_kwargs(self):
        assert migrate_operator_call("iops.mesh_smart_edge_slide(width=0.1)") == "iops.mesh_edge_slide(width=0.1)"

    def test_longer_idname_with_the_old_prefix_untouched(self):
        assert migrate_operator_call("iops.mesh_smart_inset_x") == "iops.mesh_smart_inset_x"

    def test_other_text_untouched(self):
        assert migrate_operator_call("uv.pin(clear=False)") == "uv.pin(clear=False)"
        assert migrate_operator_call("") == ""
        assert migrate_operator_call(None) is None
