import bpy

def get_addon(addon, debug=False):
    import addon_utils

    # look for addon by name and find folder name and path
    # Note, this will also find addons that aren't registered!

    for mod in addon_utils.modules():
        name = mod.bl_info["name"]
        version = mod.bl_info.get("version", None)
        foldername = mod.__name__
        path = mod.__file__
        enabled = addon_utils.check(foldername)[1]

        if name == addon:
            return enabled, foldername, version, path

    return False, None, None, None