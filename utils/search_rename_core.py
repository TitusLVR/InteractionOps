"""Pure name logic for Search & Replace rename (no bpy).

Mirrors the Search & Replace block of Total Commander's Multi-Rename
Tool. Plain search is case-insensitive, `|` separates several terms
(paired by position with the `|`-separated replacements, or all mapped
to a single replacement), `*` and `?` are wildcards. With `regex` the
search is a Python regular expression and `$1`..`$9` ($0 = whole match)
in the replacement insert groups; `subst` (regex only) replaces the
whole name with the expanded replacement when the pattern matches.

Blender's `.001` duplicate suffix plays the role of the file extension:
it is kept out of the search unless `include_suffix` ([E]) is set.
"""
import re

SUFFIX_RE = re.compile(r"^(.*?)(\.\d{3,})$", re.DOTALL)
WORD_START_RE = re.compile(r"(^|[\s_\-.])(\w)")
GROUP_REF_RE = re.compile(r"\$(\d)")

CASE_MODES = ("UNCHANGED", "LOWER", "UPPER", "FIRST", "WORDS")

HISTORY_LIMIT = 20


def split_suffix(name):
    """'Cube.001' -> ('Cube', '.001'); 'Cube' -> ('Cube', '')."""
    m = SUFFIX_RE.match(name)
    return (m.group(1), m.group(2)) if m else (name, "")


def wildcard_to_regex(term):
    """Escape a plain term, turning * and ? into their regex meaning."""
    return "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in term)


def expand_replacement(m, repl):
    """`repl` with $0..$9 replaced by the groups of match `m`; everything
    else (backslashes included) is literal."""
    def group(ref):
        try:
            return m.group(int(ref.group(1))) or ""
        except IndexError:
            raise ValueError(f"no group {ref.group(1)} in the pattern") from None

    return GROUP_REF_RE.sub(group, repl)


def change_case(text, case):
    if case == "LOWER":
        return text.lower()
    if case == "UPPER":
        return text.upper()
    if case == "FIRST":
        return text[:1].upper() + text[1:].lower()
    if case == "WORDS":
        return WORD_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text.lower())
    return text


def _replace_plain(text, search, replace, flags, count):
    terms = search.split("|")
    repls = replace.split("|")
    pairs = [(t, repls[0] if len(repls) == 1 else (repls[i] if i < len(repls) else ""))
             for i, t in enumerate(terms) if t]
    if not pairs:
        return text
    # One alternation so every term is replaced in a single pass:
    # swapping Left|Right -> Right|Left must not chain.
    pattern = re.compile("|".join(f"({wildcard_to_regex(t)})" for t, _ in pairs), flags)
    return pattern.sub(lambda m: pairs[m.lastindex - 1][1], text, count=count)


def _replace_regex(text, search, replace, flags, count, subst):
    try:
        pattern = re.compile(search, flags)
    except re.error as e:
        raise ValueError(f"invalid regular expression: {e}") from None
    if subst:
        m = pattern.search(text)
        return expand_replacement(m, replace) if m else text
    return pattern.sub(lambda m: expand_replacement(m, replace), text, count=count)


def rename(name, search, replace, *, case_sensitive=False, first_only=False,
           include_suffix=False, regex=False, subst=False, case="UNCHANGED"):
    """New name for `name`. Raises ValueError on an invalid regex."""
    base, suffix = (name, "") if include_suffix else split_suffix(name)
    if search:
        flags = 0 if case_sensitive else re.IGNORECASE
        count = 1 if first_only else 0
        if regex:
            base = _replace_regex(base, search, replace, flags, count, subst)
        else:
            base = _replace_plain(base, search, replace, flags, count)
    return change_case(base, case) + suffix


def push_history(history, value, limit=HISTORY_LIMIT):
    """Move `value` to the front of `history` (in place), capped at `limit`."""
    if not value:
        return
    if value in history:
        history.remove(value)
    history.insert(0, value)
    del history[limit:]
