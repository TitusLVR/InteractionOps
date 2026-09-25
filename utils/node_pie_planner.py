"""Pure spawn planning for the node-editor pie (no bpy) so pytest can cover it.

Everything that can be wrong — which sockets to link, what to splice, where to
put the node — is decided here over plain dataclasses. The bpy side in
`operators/node_pie/ops.py` only applies the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Socket types Blender implicitly converts between. Anything outside this set
# links only to its own type. Values are `NodeSocket.type` enum identifiers.
IMPLICIT_GROUP = frozenset(
    {"VALUE", "INT", "BOOLEAN", "VECTOR", "ROTATION", "RGBA"}
)


@dataclass(frozen=True)
class NodeRef:
    """A node a plan refers to that has no name yet, or must not be named.

    `links_to_add` mixes references to the spawned node, the active node and
    arbitrary *existing* nodes addressed by name. Using reserved strings for
    the first two (`"NEW"` / `"ACTIVE"`) collided with real node names — node
    names are user-editable, so a node actually called `NEW` resolved to the
    spawned node and the applier severed the user's link and self-linked the
    new node. These singletons cannot collide: a plain `str` in a plan always
    means "the existing node with this name", and nothing else.
    """
    kind: str

    def __repr__(self):  # keeps test failures readable
        return f"<{self.kind}>"


#: The node the pie was opened on.
ACTIVE = NodeRef("active")
#: The node about to be spawned.
NEW = NodeRef("new")


@dataclass(frozen=True)
class SocketDesc:
    """One socket, stripped to what planning needs."""
    name: str
    type: str
    index: int
    enabled: bool = True
    hide: bool = False


@dataclass(frozen=True)
class NodeDesc:
    """One node, stripped to what planning needs."""
    bl_idname: str
    location: tuple[float, float] = (0.0, 0.0)
    width: float = 140.0
    inputs: tuple[SocketDesc, ...] = field(default_factory=tuple)
    outputs: tuple[SocketDesc, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LinkDesc:
    """One existing link, addressed by node + socket index."""
    from_node: str
    from_socket: int
    to_node: str
    to_socket: int
    to_socket_type: str
    to_node_location: tuple[float, float] = (0.0, 0.0)


def is_compatible(a: str, b: str) -> bool:
    """True when a link between socket types `a` and `b` is meaningful."""
    if a == b:
        return True
    return a in IMPLICIT_GROUP and b in IMPLICIT_GROUP


def _usable(sockets):
    return [s for s in sockets if s.enabled and not s.hide]


def pick_source(node: NodeDesc, from_socket: str | int | None) -> SocketDesc | None:
    """Output socket to link from.

    `from_socket` (a rule entry's optional override) may be a socket name or an
    index; an override that does not resolve falls back to the default pick
    rather than failing, so a rule written against another Blender version
    still spawns something useful.
    """
    usable = _usable(node.outputs)
    if not usable:
        return None
    if from_socket is not None:
        for s in usable:
            if s.name == from_socket or s.index == from_socket:
                return s
    return usable[0]


def pick_target(node: NodeDesc, source_type: str) -> SocketDesc | None:
    """First input on the spawned node that `source_type` can meaningfully feed."""
    for s in _usable(node.inputs):
        if is_compatible(source_type, s.type):
            return s
    return None


#: Horizontal gap between the active node's right edge and the new node.
#: Node dimensions are (0, 0) until Blender draws them, so measured layout is
#: impossible; this fixed offset is applied from the active node's right edge
#: because `width` is the only reliable size available at creation time.
SPAWN_GAP = 40.0
#: Extra clearance required before a spliced node is placed midway.
SPLICE_CLEARANCE = 80.0


@dataclass(frozen=True)
class SpawnPlan:
    """Everything the bpy side needs to apply, and nothing it must decide.

    Each `links_to_add` entry is `(from_ref, from_index, to_ref, to_index)`,
    where a ref is either the `ACTIVE`/`NEW` singleton or the name of an
    existing node.
    """
    location: tuple[float, float]
    links_to_add: tuple[tuple[NodeRef | str, int, NodeRef | str, int], ...] = ()
    links_to_remove: tuple[LinkDesc, ...] = ()
    warning: str | None = None


def _splice_output(new: NodeDesc, to_socket_type: str) -> SocketDesc | None:
    """Output socket to splice the downstream link through.

    Prioritizes exact type match, then compatible types, else None.
    """
    usable = _usable(new.outputs)
    if not usable:
        return None
    for s in usable:
        if s.type == to_socket_type:
            return s
    for s in usable:
        if is_compatible(s.type, to_socket_type):
            return s
    return None


def plan_spawn(active: NodeDesc, new: NodeDesc,
               downstream: tuple[LinkDesc, ...] = (),
               from_socket: str | int | None = None) -> SpawnPlan:
    """Decide where the new node goes and how it is wired.

    `downstream` is every existing link leaving the active node; only those
    leaving the chosen source socket are spliced. The node is always placed,
    even when nothing can be linked — a pie press that produces no node at all
    reads as a dead key.
    """
    plain = (active.location[0] + active.width + SPAWN_GAP, active.location[1])

    source = pick_source(active, from_socket)
    if source is None:
        return SpawnPlan(plain, warning="active node has no output to link from")

    target = pick_target(new, source.type)
    if target is None:
        return SpawnPlan(
            plain,
            warning=f"{new.bl_idname} has no compatible input for {source.type}",
        )

    spliced = tuple(link for link in downstream if link.from_socket == source.index)

    links = [(ACTIVE, source.index, NEW, target.index)]
    links_to_remove = []
    splice_warnings = []

    for link in spliced:
        out = _splice_output(new, link.to_socket_type)
        if out is not None:
            links.append((NEW, out.index, link.to_node, link.to_socket))
            links_to_remove.append(link)
        else:
            splice_warnings.append(link.to_node)

    location = plain
    if spliced:
        nearest = min(link.to_node_location[0] for link in spliced)
        needed = active.location[0] + active.width + new.width + SPLICE_CLEARANCE
        if nearest >= needed:
            location = ((active.location[0] + nearest) / 2.0, active.location[1])

    warning = None
    if splice_warnings:
        # De-duplicate node names while preserving order
        seen = set()
        unique_nodes = []
        for node_name in splice_warnings:
            if node_name not in seen:
                seen.add(node_name)
                unique_nodes.append(node_name)
        warning = f"cannot splice to {', '.join(unique_nodes)}: no compatible output"

    return SpawnPlan(location, tuple(links), tuple(links_to_remove), warning)
