"""The keys a modal handles, read from its source, and the key words of a help legend: for
tests/blender/test_hud_more_options.py. Pure Python (no bpy).

``handled_events`` finds every string compared with ``event.type`` (also ``evt.type``, or a local name bound to
it), directly or through a module-level collection (``event.type in TYPING_KEYS``); tests whose branch only
returns PASS_THROUGH are left out. Keys handled elsewhere (a shared helper module)
are not seen: the case's own ``keys`` list covers those.
"""
import ast
import re

# Event types that are never help lines: mouse motion, timers, navigation and the overlay keys (H, /).
IGNORED = {
    "MOUSEMOVE", "INBETWEEN_MOUSEMOVE", "TIMER", "TIMER_REPORT", "TIMERREGION", "MIDDLEMOUSE", "TRACKPADPAN",
    "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM", "WINDOW_DEACTIVATE", "H", "SLASH", "NONE",
}
EVENT_NAMES = ("event", "evt")

_DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")
_DIGIT_WORDS = {"Digits", "Numbers", "0-9", "0 - 9", "Number Keys"}
_NAMED = {
    "RET": {"Enter"}, "NUMPAD_ENTER": {"Enter"}, "SPACE": {"Space"}, "ESC": {"Esc"}, "TAB": {"Tab"},
    "LEFTMOUSE": {"LMB"}, "RIGHTMOUSE": {"RMB"}, "BACK_SPACE": {"Backspace"}, "DEL": {"Delete"},
    "WHEELUPMOUSE": {"Wheel"}, "WHEELDOWNMOUSE": {"Wheel"},
    "MINUS": {"-", "Minus"}, "NUMPAD_MINUS": {"-", "Minus"},
    "PLUS": {"+", "Plus"}, "NUMPAD_PLUS": {"+", "Plus"}, "EQUAL": {"+", "Plus", "="},
    "PERIOD": {".", "Period"}, "NUMPAD_PERIOD": {".", "Period"}, "COMMA": {",", "Comma"},
    "LEFT_SHIFT": {"Shift"}, "RIGHT_SHIFT": {"Shift"}, "LEFT_CTRL": {"Ctrl"}, "RIGHT_CTRL": {"Ctrl"},
    "LEFT_ALT": {"Alt"}, "RIGHT_ALT": {"Alt"}, "OSKEY": {"OS Key"},
    "UP_ARROW": {"Up", "Arrows", "Up Arrow"}, "DOWN_ARROW": {"Down", "Arrows", "Down Arrow"},
    "LEFT_ARROW": {"Left", "Arrows", "Left Arrow"}, "RIGHT_ARROW": {"Right", "Arrows", "Right Arrow"},
    "LEFT_BRACKET": {"["}, "RIGHT_BRACKET": {"]"},
    "PAGE_UP": {"Page Up"}, "PAGE_DOWN": {"Page Down"}, "HOME": {"Home"}, "END": {"End"},
}


def aliases(event_type):
    """The help words that name ``event_type`` (any one of them in the help counts)."""
    if event_type in _NAMED:
        return set(_NAMED[event_type])
    if event_type in _DIGITS:
        return {str(_DIGITS.index(event_type))} | _DIGIT_WORDS
    if event_type.startswith("NUMPAD_") and event_type[7:].isdigit():
        return {event_type[7:]} | _DIGIT_WORDS
    return {event_type}             # letters, F1 .. F12


def _is_event(text):
    return bool(text) and text.replace("_", "").isalnum() and text.upper() == text and not text.isdigit()


def _strings(node):
    return {sub.value for sub in ast.walk(node) if isinstance(sub, ast.Constant) and isinstance(sub.value, str)}


def _keys(node):
    """The strings of a collection; of a dict only its keys (``{"ONE": "VERT"}`` maps a key to a value)."""
    if isinstance(node, ast.Dict):
        return set().union(*(_strings(k) for k in node.keys if k is not None)) if node.keys else set()
    return _strings(node)


def _is_event_type(node, aliases_=()):
    if isinstance(node, ast.Name):
        return node.id in aliases_
    return (isinstance(node, ast.Attribute) and node.attr == "type" and isinstance(node.value, ast.Name)
            and node.value.id in EVENT_NAMES)


def _type_aliases(tree):
    """Local names bound to the event type: ``et = event.type``, ``et, ev = event.type, event.value``."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            pairs = [(target, node.value)]
            if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                pairs = list(zip(target.elts, node.value.elts))
            for t, v in pairs:
                if isinstance(t, ast.Name) and _is_event_type(v):
                    names.add(t.id)
    return names


def handled_events(path, class_name=None):
    """Every event type compared with ``<event>.type`` in the module at ``path``; only in the class ``class_name``
    when given (a base class from another module: that module's other operators are not this one's keys)."""
    with open(path, encoding="utf-8") as fh:
        module = ast.parse(fh.read())
    tree = module
    if class_name is not None:
        tree = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    consts = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Set, ast.Tuple, ast.List, ast.Dict)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = _keys(node.value)
    # tests of `if ...: return {"PASS_THROUGH"}`: keys handed to Blender (navigation, sidebar), not the modal's own
    passed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and len(node.body) == 1 and isinstance(node.body[0], ast.Return)                 and node.body[0].value is not None and "PASS_THROUGH" in _strings(node.body[0].value):
            passed.update(id(sub) for sub in ast.walk(node.test))
    alias_names = _type_aliases(tree)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or id(node) in passed:
            continue
        sides = [node.left, *node.comparators]
        if not any(_is_event_type(side, alias_names) for side in sides):
            continue
        for side in sides:
            if isinstance(side, ast.Name) and side.id in alias_names:
                continue
            if isinstance(side, ast.Name) and side.id in consts:
                found.update(consts[side.id])
            found.update(_keys(side) if isinstance(side, ast.Dict) else _strings(side))
    return {t for t in found if _is_event(t) and t not in IGNORED and not t.startswith("NDOF")}


def help_words(key_texts):
    """The words of help key texts: "Shift + D / Ctrl + D" gives Shift, D, Ctrl, and the whole texts too."""
    words = set()
    for text in key_texts:
        text = text.strip()
        words.add(text)
        for part in text.split(" / "):
            part = part.strip()
            words.add(part)
            for piece in part.split(" + "):
                words.add(piece.strip())
                words.update(piece.split())
            for low, high in re.findall(r"(\d)\s*(?:-|to)\s*(\d)", part):    # "Numpad 1 - 9", "0 to 9"
                words.update(str(d) for d in range(int(low), int(high) + 1))
    return words


def missing_keys(sources, key_texts, ignore=()):
    """Event types handled in ``sources`` that no help key names. A source is a module path, or a pair (module path,
    class name) to read only that class."""
    if isinstance(sources, str):
        sources = [sources]
    handled = set()
    for source in sources:
        handled |= handled_events(*source) if isinstance(source, tuple) else handled_events(source)
    words = help_words(key_texts)
    return sorted(t for t in handled - set(ignore) if not (aliases(t) & words))
