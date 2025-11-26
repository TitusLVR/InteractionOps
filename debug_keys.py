import bpy

def debug_keyconfigs():
    wm = bpy.context.window_manager
    print("-" * 30)
    print(f"Active Keyconfig: {wm.keyconfigs.active.name}")
    
    configs = [
        ("Active", wm.keyconfigs.active),
        ("User", wm.keyconfigs.user),
        ("Addon", wm.keyconfigs.addon),
    ]
    
    for name, config in configs:
        print(f"\nChecking {name} config ({config.name})...")
        count = 0
        for km in config.keymaps:
            for kmi in km.keymap_items:
                if kmi.idname.startswith("iops."):
                    count += 1
                    if count <= 5: # Print first 5 found
                        print(f"  Found: {kmi.idname} in {km.name} (Active: {kmi.active})")
        print(f"Total 'iops' items in {name}: {count}")

debug_keyconfigs()
