"""Apply real spawn plans to real node trees and assert the resulting links.

Run: blender --background --factory-startup --python tools/verify_node_pie_applier.py
(with BLENDER_USER_SCRIPTS pointing at a scripts dir whose addons/ contains
this repo as 'InteractionOps', same as tests/smoke_register.py).

The pure planner is covered by pytest; the *applier* is not, and cannot be —
it edits `bpy` data. That is exactly where the identity bug lived that turned
the whole splice feature into a no-op for every graph (`link.from_node is
active` is never True: bpy_struct attribute access returns a fresh wrapper
each time). This script closes that gap. Exits non-zero on failure —
deliberate, because an uncaught exception from a --python script still
leaves Blender exiting 0, which would make it useless as a gate.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

bpy.ops.preferences.addon_enable(module="InteractionOps")

from InteractionOps.operators.node_pie import ops, store  # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


def link_rows(ntree):
    """Every link as (from node, from socket, to node, to socket) names."""
    return sorted(
        (link.from_node.name, link.from_socket.name,
         link.to_node.name, link.to_socket.name)
        for link in ntree.links
    )


def dump(label, ntree):
    print(f"  {label}:")
    for row in link_rows(ntree):
        print(f"    {row[0]}.{row[1]:<10} -> {row[2]}.{row[3]}")


def build_tree(downstream_x_name="MathX"):
    """Separate XYZ whose X and Y outputs each feed a Math node."""
    ntree = bpy.data.node_groups.new("IOPS_ApplierProbe", "GeometryNodeTree")
    sep = ntree.nodes.new("ShaderNodeSeparateXYZ")
    sep.name = "Sep"
    sep.location = (0.0, 0.0)
    math_x = ntree.nodes.new("ShaderNodeMath")
    math_x.name = downstream_x_name
    math_x.location = (900.0, 0.0)
    math_y = ntree.nodes.new("ShaderNodeMath")
    math_y.name = "MathY"
    math_y.location = (900.0, -300.0)
    ntree.links.new(sep.outputs[0], math_x.inputs[0])   # X
    ntree.links.new(sep.outputs[1], math_y.inputs[0])   # Y
    ntree.nodes.active = sep
    return ntree, sep, math_x, math_y


def spawn(ntree, active, idname, entry=None):
    """The shipped code path, minus the operator context."""
    new = ntree.nodes.new(idname)
    plan = ops.plan_for(ntree, active, new, entry or {})
    ops.apply_plan(ntree, plan, active, new)
    return new, plan


CURSOR = (321.0, 654.0)


def spawn_via_gate(ntree, idname, entry=None):
    """`IOPS_OT_NodeSpawnConnected.execute`, minus the operator context.

    Unlike `spawn()` above, this does not take `active` as a plain
    argument — it resolves it through `store.active_if_selected`, the exact
    gate `execute()` uses. That is the thing under test: a node can still be
    `ntree.nodes.active` after a deselect-all, and this must treat that the
    same way `execute()` does, i.e. as no active node at all.
    """
    active = store.active_if_selected(ntree.nodes)
    new = ntree.nodes.new(idname)
    if active is None:
        new.location = CURSOR
    else:
        plan = ops.plan_for(ntree, active, new, entry or {})
        ops.apply_plan(ntree, plan, active, new)
    for node in ntree.nodes:
        node.select = False
    new.select = True
    ntree.nodes.active = new
    return new


# --- case 1: splice off one output of a two-output node -------------------
print("case 1: spawn a Clamp off Separate XYZ's X output")
ntree, sep, math_x, math_y = build_tree()
dump("before", ntree)
clamp, plan = spawn(ntree, sep, "ShaderNodeClamp")
clamp.name = "Clamp"
dump("after", ntree)
print(f"  plan.location={plan.location} plan.links_to_remove="
      f"{len(plan.links_to_remove)} warning={plan.warning!r}")
print(f"  clamp.location={tuple(clamp.location)}")

rows = link_rows(ntree)
check("X is spliced through the new node: Sep.X -> Clamp.Value",
      ("Sep", "X", "Clamp", "Value") in rows)
check("X is spliced through the new node: Clamp.Result -> MathX.Value",
      ("Clamp", "Result", "MathX", "Value") in rows)
check("the direct Sep.X -> MathX link is gone",
      ("Sep", "X", "MathX", "Value") not in rows)
check("the sibling output's link is untouched: Sep.Y -> MathY.Value",
      ("Sep", "Y", "MathY", "Value") in rows)
check("no links beyond those three", len(rows) == 3, f"{len(rows)} links")
check("the new node lands midway between Sep and MathX",
      tuple(clamp.location) == (450.0, 0.0), str(tuple(clamp.location)))
check("every link Blender kept is valid", all(link.is_valid for link in ntree.links))
bpy.data.node_groups.remove(ntree)

# --- case 2: a downstream node the user named 'NEW' ----------------------
print("case 2: the downstream node is literally named 'NEW'")
ntree, sep, math_x, math_y = build_tree(downstream_x_name="NEW")
dump("before", ntree)
clamp, plan = spawn(ntree, sep, "ShaderNodeClamp")
clamp.name = "Clamp"
dump("after", ntree)
rows = link_rows(ntree)
check("the active node still feeds the spawned node",
      ("Sep", "X", "Clamp", "Value") in rows)
check("the spawned node feeds the node named NEW",
      ("Clamp", "Result", "NEW", "Value") in rows)
check("the spawned node is not linked to itself",
      not any(r[0] == "Clamp" and r[2] == "Clamp" for r in rows))
check("the sibling output's link is untouched", ("Sep", "Y", "MathY", "Value") in rows)
check("no links beyond those three", len(rows) == 3, f"{len(rows)} links")
bpy.data.node_groups.remove(ntree)

# --- case 3: nothing to splice through leaves the graph alone ------------
# Attribute Statistic takes a GEOMETRY input but has only VALUE/VECTOR
# outputs, so it can be wired to the cube yet has nothing to carry the
# cube's geometry on to the Join. The link must survive untouched.
print("case 3: the spawned node has no output the downstream link can use")
ntree = bpy.data.node_groups.new("IOPS_ApplierProbe3", "GeometryNodeTree")
cube = ntree.nodes.new("GeometryNodeMeshCube")
cube.name = "Cube"
cube.location = (0.0, 0.0)
join = ntree.nodes.new("GeometryNodeJoinGeometry")
join.name = "Join"
join.location = (900.0, 0.0)
ntree.links.new(cube.outputs[0], join.inputs[0])
before = link_rows(ntree)
dump("before", ntree)
stat, plan = spawn(ntree, cube, "GeometryNodeAttributeStatistic")
stat.name = "Stat"
dump("after", ntree)
rows = link_rows(ntree)
print(f"  warning={plan.warning!r}")
check("the existing downstream link survives",
      all(row in rows for row in before), str(before))
check("the new node is still wired to the active one",
      ("Cube", "Mesh", "Stat", "Geometry") in rows)
check("the plan warns about the node it could not splice to",
      bool(plan.warning) and "Join" in plan.warning, repr(plan.warning))
check("nothing was removed", plan.links_to_remove == ())
bpy.data.node_groups.remove(ntree)

# --- case 4: plain spawn, no downstream ----------------------------------
print("case 4: plain spawn with nothing downstream")
ntree = bpy.data.node_groups.new("IOPS_ApplierProbe2", "GeometryNodeTree")
cube = ntree.nodes.new("GeometryNodeMeshCube")
cube.name = "Cube"
cube.location = (0.0, 0.0)
set_pos, plan = spawn(ntree, cube, "GeometryNodeSetPosition")
set_pos.name = "SetPos"
rows = link_rows(ntree)
dump("after", ntree)
check("the new node is wired to the active one",
      ("Cube", "Mesh", "SetPos", "Geometry") in rows)
check("the new node sits at the plain offset",
      tuple(set_pos.location) == (cube.location[0] + cube.width + 40.0, 0.0),
      str(tuple(set_pos.location)))
bpy.data.node_groups.remove(ntree)

# --- case 5: active survives a deselect, but nothing is selected --------
# Reproduces the reported bug: Select All > None leaves `nodes.active`
# pointing at the last active node (Blender never clears it). The pie, and
# this spawn, must treat that as no active node at all.
print("case 5: deselect-all leaves a stale active node — must fall back")
ntree, sep, math_x, math_y = build_tree()
sep.select = True
ntree.nodes.active = sep
for node in ntree.nodes:
    node.select = False
before = link_rows(ntree)
clamp = spawn_via_gate(ntree, "ShaderNodeClamp")
clamp.name = "Clamp"
dump("after", ntree)
rows = link_rows(ntree)
check("no link was created off the stale active node",
      rows == before, f"{rows} vs {before}")
check("the new node landed at the 2D cursor, not beside the stale active node",
      tuple(clamp.location) == CURSOR, str(tuple(clamp.location)))
bpy.data.node_groups.remove(ntree)

# --- case 6: chaining is intact — a fresh spawn is active AND selected ----
print("case 6: chaining — a freshly spawned node is active+selected for the next spawn")
ntree = bpy.data.node_groups.new("IOPS_ApplierProbeChain", "GeometryNodeTree")
root = ntree.nodes.new("ShaderNodeValue")
root.name = "Root"
root.location = (0.0, 0.0)
root.select = True
ntree.nodes.active = root
first = spawn_via_gate(ntree, "ShaderNodeMath")
first.name = "Math1"
# Check this before the second spawn: that spawn deselects everything else
# as a side effect, which would make this check trivially pass no matter
# what and defeat the point of checking it here.
check("the freshly spawned node is itself active+selected, so the *next* "
      "spawn's gate resolves it as active rather than falling back",
      first.select and ntree.nodes.active == first and not root.select,
      f"first.select={first.select} root.select={root.select} "
      f"active={ntree.nodes.active}")
second = spawn_via_gate(ntree, "ShaderNodeMath")
second.name = "Math2"
dump("after", ntree)
rows = link_rows(ntree)
check("root fed the first spawned node", ("Root", "Value", "Math1", "Value") in rows, str(rows))
check("the first spawned node fed the second — chaining intact",
      ("Math1", "Value", "Math2", "Value") in rows, str(rows))
bpy.data.node_groups.remove(ntree)

if FAILURES:
    print("node pie applier FAILED:", file=sys.stderr)
    for entry in FAILURES:
        print(f"  {entry}", file=sys.stderr)
    sys.exit(1)

print("node pie applier OK")
