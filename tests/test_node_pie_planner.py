from utils import node_pie_planner as pl


def test_exact_types_are_compatible_with_themselves():
    for t in ("GEOMETRY", "SHADER", "OBJECT", "COLLECTION", "MATERIAL",
              "IMAGE", "STRING", "MENU", "TEXTURE", "MATRIX"):
        assert pl.is_compatible(t, t)


def test_exact_only_types_do_not_cross_link():
    assert not pl.is_compatible("GEOMETRY", "SHADER")
    assert not pl.is_compatible("SHADER", "VALUE")
    assert not pl.is_compatible("OBJECT", "COLLECTION")


def test_implicit_group_is_mutually_compatible():
    group = ("VALUE", "INT", "BOOLEAN", "VECTOR", "ROTATION", "RGBA")
    for a in group:
        for b in group:
            assert pl.is_compatible(a, b), (a, b)


def test_implicit_group_does_not_reach_exact_only_types():
    assert not pl.is_compatible("VALUE", "GEOMETRY")
    assert not pl.is_compatible("RGBA", "SHADER")


def test_unknown_socket_type_is_only_self_compatible():
    assert pl.is_compatible("CUSTOM", "CUSTOM")
    assert not pl.is_compatible("CUSTOM", "VALUE")


def _geo_node(idname="GeometryNodeSetPosition"):
    return pl.NodeDesc(
        bl_idname=idname,
        inputs=(
            pl.SocketDesc("Geometry", "GEOMETRY", 0),
            pl.SocketDesc("Selection", "BOOLEAN", 1),
            pl.SocketDesc("Position", "VECTOR", 2),
            pl.SocketDesc("Offset", "VECTOR", 3),
        ),
        outputs=(pl.SocketDesc("Geometry", "GEOMETRY", 0),),
    )


def test_pick_source_defaults_to_first_visible_output():
    node = pl.NodeDesc(
        "GeometryNodeRaycast",
        outputs=(
            pl.SocketDesc("Is Hit", "BOOLEAN", 0, enabled=False),
            pl.SocketDesc("Hit Position", "VECTOR", 1),
        ),
    )
    assert pl.pick_source(node, None).name == "Hit Position"


def test_pick_source_skips_hidden_outputs():
    node = pl.NodeDesc(
        "N",
        outputs=(
            pl.SocketDesc("A", "VALUE", 0, hide=True),
            pl.SocketDesc("B", "VALUE", 1),
        ),
    )
    assert pl.pick_source(node, None).name == "B"


def test_pick_source_honours_from_socket_by_name_and_index():
    node = pl.NodeDesc(
        "N",
        outputs=(pl.SocketDesc("A", "VALUE", 0), pl.SocketDesc("B", "VECTOR", 1)),
    )
    assert pl.pick_source(node, "B").index == 1
    assert pl.pick_source(node, 1).index == 1


def test_pick_source_falls_back_when_from_socket_is_unknown():
    node = pl.NodeDesc("N", outputs=(pl.SocketDesc("A", "VALUE", 0),))
    assert pl.pick_source(node, "Nope").name == "A"


def test_pick_source_returns_none_without_usable_outputs():
    assert pl.pick_source(pl.NodeDesc("N"), None) is None


def test_pick_target_takes_first_compatible_input():
    assert pl.pick_target(_geo_node(), "GEOMETRY").index == 0
    assert pl.pick_target(_geo_node(), "VECTOR").index == 1  # BOOLEAN, implicit


def test_pick_target_skips_disabled_inputs():
    node = pl.NodeDesc(
        "N",
        inputs=(
            pl.SocketDesc("A", "GEOMETRY", 0, enabled=False),
            pl.SocketDesc("B", "GEOMETRY", 1),
        ),
    )
    assert pl.pick_target(node, "GEOMETRY").index == 1


def test_pick_target_returns_none_when_nothing_is_compatible():
    assert pl.pick_target(_geo_node(), "SHADER") is None


GAP = 40.0


def test_plain_spawn_places_right_of_active_and_links_once():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0), width=140.0,
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    plan = pl.plan_spawn(active, _geo_node(), downstream=())
    assert plan.location == (180.0, 0.0)
    assert plan.links_to_add == ((pl.ACTIVE, 0, pl.NEW, 0),)
    assert plan.links_to_remove == ()
    assert plan.warning is None


def test_spawn_without_compatible_input_still_places_and_warns():
    active = pl.NodeDesc("ShaderNodeBsdfPrincipled", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("BSDF", "SHADER", 0),))
    plan = pl.plan_spawn(active, _geo_node(), downstream=())
    assert plan.links_to_add == ()
    assert plan.location == (180.0, 0.0)
    assert "no compatible input" in plan.warning


def test_splice_rewires_every_downstream_consumer():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (900.0, 0.0)),
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Output", 0, "GEOMETRY", (1200.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert (pl.ACTIVE, 0, pl.NEW, 0) in plan.links_to_add
    assert (pl.NEW, 0, "Join", 0) in plan.links_to_add
    assert (pl.NEW, 0, "Output", 0) in plan.links_to_add
    assert set(plan.links_to_remove) == set(downstream)


def test_splice_places_midway_when_there_is_room():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0), width=140.0,
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (900.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert plan.location == (450.0, 0.0)


def test_splice_uses_plain_offset_when_downstream_is_close():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0), width=140.0,
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (200.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert plan.location == (180.0, 0.0)


def test_splice_picks_output_matching_the_downstream_socket_type():
    active = pl.NodeDesc("A", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Out", "VALUE", 0),))
    new = pl.NodeDesc(
        "ShaderNodeSeparateXYZ",
        inputs=(pl.SocketDesc("Vector", "VECTOR", 0),),
        outputs=(pl.SocketDesc("X", "VALUE", 0), pl.SocketDesc("Y", "VALUE", 1)),
    )
    downstream = (pl.LinkDesc("A", 0, "Math", 1, "VALUE", (900.0, 0.0)),)
    plan = pl.plan_spawn(active, new, downstream=downstream)
    assert (pl.NEW, 0, "Math", 1) in plan.links_to_add


def test_plan_without_usable_output_on_active_still_places_the_node():
    active = pl.NodeDesc("GeometryNodeGroupOutput", location=(0.0, 0.0))
    plan = pl.plan_spawn(active, _geo_node(), downstream=())
    assert plan.links_to_add == ()
    assert plan.location == (180.0, 0.0)
    assert "no output" in plan.warning


def test_splice_with_no_usable_outputs_on_new_preserves_downstream():
    """Splicing with a node that has no usable outputs preserves existing links."""
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    new = pl.NodeDesc("GeometryNodeGroupOutput",
                      inputs=(pl.SocketDesc("Geometry", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (900.0, 0.0)),
    )
    plan = pl.plan_spawn(active, new, downstream=downstream)
    assert (pl.ACTIVE, 0, pl.NEW, 0) in plan.links_to_add
    assert plan.links_to_remove == ()
    assert "cannot splice to Join" in plan.warning


def test_splice_picks_compatible_output_when_exact_match_unavailable():
    """Splicing picks a compatible output when exact type is unavailable.

    The new node has multiple outputs: first is GEOMETRY (not compatible with INT),
    second is VALUE (compatible via implicit group). Must pick the second.
    The old buggy code would fall back to usable[0] (GEOMETRY), producing a type
    mismatch; the fixed code checks is_compatible and picks the VALUE output.
    """
    active = pl.NodeDesc("A", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Out", "VALUE", 0),))
    new = pl.NodeDesc(
        "ShaderNodeSeparateXYZ",
        inputs=(pl.SocketDesc("Vector", "VECTOR", 0),),
        outputs=(
            pl.SocketDesc("Geo", "GEOMETRY", 0),
            pl.SocketDesc("X", "VALUE", 1),
        ),
    )
    downstream = (pl.LinkDesc("A", 0, "Math2", 1, "INT", (900.0, 0.0)),)
    plan = pl.plan_spawn(active, new, downstream=downstream)
    assert (pl.NEW, 1, "Math2", 1) in plan.links_to_add
    assert downstream[0] in plan.links_to_remove


def test_splice_leaves_incompatible_link_in_place():
    """Splicing leaves a link alone when no compatible output exists."""
    active = pl.NodeDesc("A", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Out", "VALUE", 0),))
    new = pl.NodeDesc(
        "N",
        inputs=(pl.SocketDesc("Value", "VALUE", 0),),
        outputs=(pl.SocketDesc("Geo", "GEOMETRY", 0),),
    )
    downstream = (pl.LinkDesc("A", 0, "Output", 0, "SHADER", (900.0, 0.0)),)
    plan = pl.plan_spawn(active, new, downstream=downstream)
    assert (pl.ACTIVE, 0, pl.NEW, 0) in plan.links_to_add
    assert plan.links_to_remove == ()
    assert "cannot splice to Output" in plan.warning


def test_node_named_new_is_not_mistaken_for_the_spawned_node():
    """A user-named node can never collide with the ACTIVE/NEW references.

    Node names are user-editable. When these were the reserved strings
    "NEW"/"ACTIVE", a downstream node actually called `NEW` resolved to the
    node being spawned: the applier removed the user's link, self-linked the
    new node and clobbered the intended active->new link.
    """
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "NEW", 0, "GEOMETRY", (900.0, 0.0)),
        pl.LinkDesc("GeometryNodeMeshCube", 0, "ACTIVE", 1, "GEOMETRY", (900.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert (pl.ACTIVE, 0, pl.NEW, 0) in plan.links_to_add
    assert (pl.NEW, 0, "NEW", 0) in plan.links_to_add
    assert (pl.NEW, 0, "ACTIVE", 1) in plan.links_to_add
    # The refs standing for the spawned/active node are not strings at all,
    # so no node-name lookup can ever produce one.
    assert not isinstance(pl.NEW, str)
    assert not isinstance(pl.ACTIVE, str)
    assert pl.NEW != "NEW" and pl.ACTIVE != "ACTIVE"


def _two_output_node():
    """A node whose two outputs each feed something — Separate XYZ, in effect."""
    return pl.NodeDesc(
        "ShaderNodeSeparateXYZ", location=(0.0, 0.0), width=140.0,
        outputs=(pl.SocketDesc("X", "VALUE", 0), pl.SocketDesc("Y", "VALUE", 1)),
    )


def test_only_links_on_the_chosen_source_socket_are_spliced():
    """A spawn off one output must not disturb another output's link.

    The `link.from_socket == source.index` filter is the safety property
    here; a fixture whose downstream links all sit on socket 0 never
    exercises it.
    """
    active = _two_output_node()
    on_x = pl.LinkDesc("Sep", 0, "MathX", 0, "VALUE", (900.0, 0.0))
    on_y = pl.LinkDesc("Sep", 1, "MathY", 0, "VALUE", (900.0, -200.0))
    new = pl.NodeDesc(
        "ShaderNodeClamp", width=140.0,
        inputs=(pl.SocketDesc("Value", "VALUE", 0),),
        outputs=(pl.SocketDesc("Result", "VALUE", 0),),
    )

    plan = pl.plan_spawn(active, new, downstream=(on_x, on_y), from_socket=0)
    assert (pl.ACTIVE, 0, pl.NEW, 0) in plan.links_to_add
    assert (pl.NEW, 0, "MathX", 0) in plan.links_to_add
    assert plan.links_to_remove == (on_x,)
    # The Y link is neither rewired nor removed.
    assert on_y not in plan.links_to_remove
    assert not any(ref == "MathY" for _, _, ref, _ in plan.links_to_add)

    # And spawning off Y leaves the X link alone, symmetrically.
    plan_y = pl.plan_spawn(active, new, downstream=(on_x, on_y), from_socket=1)
    assert (pl.ACTIVE, 1, pl.NEW, 0) in plan_y.links_to_add
    assert (pl.NEW, 0, "MathY", 0) in plan_y.links_to_add
    assert plan_y.links_to_remove == (on_y,)


def test_splice_warning_names_each_blocked_node_once():
    """Two links into the same node must not repeat its name in the warning.

    Only reachable now that `_downstream` actually returns links; before the
    identity fix it never had more than zero to de-duplicate.
    """
    active = pl.NodeDesc("A", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Out", "VALUE", 0),))
    new = pl.NodeDesc(
        "N",
        inputs=(pl.SocketDesc("Value", "VALUE", 0),),
        outputs=(pl.SocketDesc("Geo", "GEOMETRY", 0),),
    )
    downstream = (
        pl.LinkDesc("A", 0, "Output", 0, "SHADER", (900.0, 0.0)),
        pl.LinkDesc("A", 0, "Output", 1, "SHADER", (900.0, 0.0)),
        pl.LinkDesc("A", 0, "Other", 0, "SHADER", (900.0, 0.0)),
    )
    plan = pl.plan_spawn(active, new, downstream=downstream)
    assert plan.warning.count("Output") == 1
    assert plan.warning == "cannot splice to Output, Other: no compatible output"
    assert plan.links_to_remove == ()
