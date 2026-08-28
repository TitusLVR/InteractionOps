import pytest

from utils.op_call import parse_operator_call


class TestParseOperatorCall:
    def test_bare_idname(self):
        assert parse_operator_call("uv.pin") == ("uv.pin", {})

    def test_call_with_bool(self):
        assert parse_operator_call("uv.pin(clear=False)") == (
            "uv.pin", {"clear": False})

    def test_call_with_multiple_kwargs(self):
        idname, props = parse_operator_call(
            "mesh.inset(thickness=0.05, use_individual=True, mode='FACE')")
        assert idname == "mesh.inset"
        assert props == {"thickness": 0.05, "use_individual": True,
                         "mode": "FACE"}

    def test_negative_number(self):
        assert parse_operator_call("transform.translate(value=-1.5)") == (
            "transform.translate", {"value": -1.5})

    def test_tuple_value(self):
        idname, props = parse_operator_call(
            "transform.translate(value=(0, 0, 1.0))")
        assert props == {"value": (0, 0, 1.0)}

    def test_whitespace_tolerated(self):
        assert parse_operator_call("  uv.pin( clear = True )  ") == (
            "uv.pin", {"clear": True})

    def test_empty_parens(self):
        assert parse_operator_call("uv.pin()") == ("uv.pin", {})

    def test_nested_idname(self):
        # Some idnames have deeper paths in call syntax only via getattr
        # chains: object.mode_set is the normal two-part form.
        assert parse_operator_call("object.mode_set(mode='EDIT')") == (
            "object.mode_set", {"mode": "EDIT"})

    # --- rejects ---

    def test_positional_args_rejected(self):
        assert parse_operator_call("uv.pin(False)") is None

    def test_non_literal_value_rejected(self):
        assert parse_operator_call("uv.pin(clear=bpy.context)") is None

    def test_garbage_rejected(self):
        assert parse_operator_call("not an operator!!") is None

    def test_empty_string_rejected(self):
        assert parse_operator_call("") is None
        assert parse_operator_call("   ") is None

    def test_missing_dot_rejected(self):
        assert parse_operator_call("uvpin(clear=False)") is None
        assert parse_operator_call("uvpin") is None

    def test_statement_rejected(self):
        assert parse_operator_call("import os") is None

    def test_call_on_non_attribute_rejected(self):
        assert parse_operator_call("pin(clear=False)") is None

    def test_three_part_idname_rejected(self):
        # bpy.ops idnames are exactly module.op
        assert parse_operator_call("bpy.ops.uv.pin()") is None
