"""Parse an operator-call string from prefs into (idname, props).

Custom Edit-Pie slots accept either a bare operator idname
(``uv.pin``) or Python call syntax with keyword literals
(``uv.pin(clear=False)``). Pure Python — no bpy, unit-testable
standalone. Nothing is executed: the string is parsed with ``ast`` and
keyword values go through ``ast.literal_eval``, so only literal
bools/numbers/strings/tuples pass.
"""
from __future__ import annotations

import ast
import re
from typing import Optional, Tuple

# bpy.ops idnames are exactly <module>.<op>, both plain identifiers.
_IDNAME_RE = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")


def parse_operator_call(text: str) -> Optional[Tuple[str, dict]]:
    """``"uv.pin(clear=False)"`` → ``("uv.pin", {"clear": False})``;
    ``"uv.pin"`` → ``("uv.pin", {})``. None for anything else —
    positional args, non-literal values, statements, wrong idname shape.
    """
    text = text.strip()
    if not text:
        return None
    if _IDNAME_RE.match(text):
        return text, {}
    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Call) or node.args:
        return None
    func = node.func
    if (not isinstance(func, ast.Attribute)
            or not isinstance(func.value, ast.Name)):
        return None
    idname = f"{func.value.id}.{func.attr}"
    props = {}
    for kw in node.keywords:
        if kw.arg is None:  # **kwargs
            return None
        try:
            props[kw.arg] = ast.literal_eval(kw.value)
        except ValueError:
            return None
    return idname, props
