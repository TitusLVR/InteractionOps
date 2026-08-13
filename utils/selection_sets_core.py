"""Pure helpers for iOps Selection Sets — no bpy imports.

Edit-mode selection sets persist as hidden int attributes on the mesh, one
attribute per set per domain:

    .iops_ss_<D>_<name>      D in {V, E, F}

The leading dot hides the attribute from the Attributes panel; the domain
letter keeps names unique across domains (Mesh attribute names share one
namespace); the set's select mode is derived from which domain attributes
exist. Membership lives on the elements themselves, so sets survive undo,
file save and topology edits (deleted elements simply leave the set).
"""

ATTR_PREFIX = ".iops_ss_"
DOMAINS = ("V", "E", "F")
# Blender attribute names cap at 64 bytes; leave room for the prefix,
# domain letter and a ".001" dedup suffix.
MAX_NAME_LEN = 48


def make_attr_name(domain, name):
    return f"{ATTR_PREFIX}{domain}_{name}"


def parse_attr_name(attr):
    """(domain, set_name) for our attributes, None for anything else."""
    if not attr.startswith(ATTR_PREFIX):
        return None
    rest = attr[len(ATTR_PREFIX):]
    if len(rest) < 3 or rest[0] not in DOMAINS or rest[1] != "_":
        return None
    name = rest[2:]
    if not name:
        return None
    return rest[0], name


def sanitize_set_name(name):
    clean = " ".join(str(name).split())
    if not clean:
        clean = "Set"
    # Blender attribute names cap at 64 BYTES, not characters — truncate by
    # UTF-8 byte length so multi-byte names (Cyrillic, etc.) round-trip
    # through layers.get() instead of silently truncating inside Blender.
    while len(clean.encode("utf-8")) > MAX_NAME_LEN:
        clean = clean[:-1]
    return clean


def unique_name(name, existing):
    """Blender-style dedup: 'Set' -> 'Set.001' -> 'Set.002' ..."""
    taken = set(existing)
    if name not in taken:
        return name
    i = 1
    while f"{name}.{i:03d}" in taken:
        i += 1
    return f"{name}.{i:03d}"


def group_sets(attr_names):
    """{set_name: flags} from a flat list of attribute names.

    Flags are a subset of "VEF", always in that order.
    """
    sets = {}
    for attr in attr_names:
        parsed = parse_attr_name(attr)
        if parsed is None:
            continue
        domain, name = parsed
        sets.setdefault(name, set()).add(domain)
    return {n: "".join(d for d in DOMAINS if d in doms)
            for n, doms in sets.items()}


def merge_membership(memberships):
    """Union of {domain: set(indices)} dicts."""
    out = {}
    for m in memberships:
        for domain, indices in m.items():
            out.setdefault(domain, set()).update(indices)
    return out


def diff_membership(a, b):
    """Per-domain symmetric difference of {domain: set(indices)} dicts.

    Domains present in only one side pass through unchanged; empty
    results are dropped.
    """
    out = {}
    for domain in set(a) | set(b):
        d = a.get(domain, set()) ^ b.get(domain, set())
        if d:
            out[domain] = d
    return out
