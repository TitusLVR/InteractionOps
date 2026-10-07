"""Pure ordering logic for the modifier stack sorter (no bpy).

The user keeps two ordered lists in preferences: rules for modifiers
that belong at the TOP of a stack and rules for the BOTTOM. A rule is
(modifier type key, names) where `names` is a tuple of case-insensitive
name substrings: empty = every modifier of that type, otherwise only
those whose name contains one of them. Anything unmatched stays in the
middle with its current relative order. When several rules match one
modifier the first one in the list wins. A rule may carry an optional
third field, the pin flag: a tail rule with it set pins its modifiers to
the end of the stack (Blender's use_pin_to_last); see `desired_pins`.
"""

MIDDLE_RANK = 500
TAIL_BASE = 1000


def parse_names(text):
    """'a, b ,,c' -> ('a', 'b', 'c')"""
    return tuple(p.strip() for p in text.split(",") if p.strip())


def rule_pin(rule):
    """The optional pin flag of a rule (False when absent)."""
    return bool(rule[2]) if len(rule) > 2 else False


def rule_matches(rule, type_key, name):
    rule_type, names = rule[0], rule[1]
    if type_key != rule_type:
        return False
    if not names:
        return True
    lname = name.lower()
    return any(n.lower() in lname for n in names)


def _first_match(rules, type_key, name):
    for i, rule in enumerate(rules):
        if rule_matches(rule, type_key, name):
            return i
    return None


def sort_rank(type_key, name, head, tail):
    """Rank of one modifier: head rule position, MIDDLE_RANK when no rule
    matches, TAIL_BASE + tail rule position. Head rules win over tail."""
    i = _first_match(head, type_key, name)
    if i is not None:
        return i
    i = _first_match(tail, type_key, name)
    if i is not None:
        return TAIL_BASE + i
    return MIDDLE_RANK


def sorted_names(stack, head, tail):
    """`stack` = [(modifier name, type key[, match text])] in current
    order; returns the names in sorted order (stable: equal ranks keep
    relative order). The optional match text is what name rules are
    searched in instead of the name itself."""
    head = list(head)
    tail = list(tail)

    def rank(e):
        text = e[2] if len(e) > 2 else e[0]
        return sort_rank(e[1], text, head, tail)

    return [e[0] for e in sorted(stack, key=rank)]


def desired_pins(stack, head, tail):
    """Pin-to-last state the rules ask for, per modifier name: True for a
    modifier caught by a tail rule with the pin flag, False for one caught
    by any other rule (so the sort can place it), None when no rule
    matches (left as it is). `stack` as in `sorted_names`."""
    head = list(head)
    tail = list(tail)
    out = {}
    for e in stack:
        text = e[2] if len(e) > 2 else e[0]
        if _first_match(head, e[1], text) is not None:
            out[e[0]] = False
            continue
        i = _first_match(tail, e[1], text)
        out[e[0]] = None if i is None else rule_pin(tail[i])
    return out


def base_name_candidates(name):
    """Names a duplicate datablock may be a copy of, most specific first:
    everything before the last '.', then before the one before, ...
    'Smooth by Angle.001' -> ['Smooth by Angle'];
    'a.b.001' -> ['a.b', 'a']; 'plain' -> []."""
    out = []
    while "." in name:
        name = name.rsplit(".", 1)[0]
        if name:
            out.append(name)
    return out
