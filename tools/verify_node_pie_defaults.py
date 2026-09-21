"""Assert every shipped node-pie default is creatable in its tree type.

Run: blender --background --factory-startup --python tools/verify_node_pie_defaults.py
Prints every id that cannot be created to stderr and calls sys.exit(1).
This is deliberate rather than relying on an uncaught exception: in
Blender's background mode, an unhandled Python exception from a --python
script prints a traceback but Blender still exits 0, which would make this
script useless as a CI gate. On success it prints `node pie defaults OK`
and exits 0.
Must be run whenever an id is added to utils/node_pie_rules.py — poll() lies,
so creation is the only honest check.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import node_pie_rules as nr  # noqa: E402

bad = []
for tree_type, rules in nr.DEFAULTS.items():
    scratch = bpy.data.node_groups.new("IOPS_VerifyDefaults", tree_type)
    try:
        for node_idname, rule in rules.items():
            for index, slot in enumerate(nr.normalise_rule(rule)):
                if not slot or slot["node"] == "__search__":
                    continue
                try:
                    node = scratch.nodes.new(slot["node"])
                    scratch.nodes.remove(node)
                except (RuntimeError, TypeError) as exc:
                    bad.append(
                        f"{tree_type}/{node_idname} slot "
                        f"{nr.SLOT_LABELS[index]}: {slot['node']} ({exc})"
                    )
    finally:
        bpy.data.node_groups.remove(scratch)

if bad:
    print("invalid default node ids:", file=sys.stderr)
    for entry in bad:
        print(f"  {entry}", file=sys.stderr)
    sys.exit(1)

print("node pie defaults OK")
