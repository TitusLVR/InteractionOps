import bpy
import itertools


keyconfigs = bpy.context.window_manager.keyconfigs

for kc in keyconfigs:
    for kms in kc.keymaps:
        print("START CLEAN UP ->", kms.name)
        km_items = kms.keymap_items
        duplicates = tuple(
            b for a, b in itertools.combinations(km_items, 2) if a.compare(b)
        )

        for dupe in duplicates:
            try:
                print("Deleting...", dupe.name, dupe.idname, sep=" | ")
                km_items.remove(dupe)
            except ReferenceError:
                print("Moving on... ReferenceError!")
