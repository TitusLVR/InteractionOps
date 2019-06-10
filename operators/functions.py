import bpy


def get_path(root, path):
    # current = root
    # for node in path:
    #     current = current.get(node)
    #     if current is None:
    #         raise KeyError("Cannot find specified path %s" % path)
    return path


def uv_select_mode(mode):
    bpy.context.tool_settings.uv_select_mode = mode


def uv_sync_toggle():
    flag = bpy.context.tool_settings.use_uv_select_sync
    bpy.context.tool_settings.use_uv_select_sync = not flag


def mesh_select_mode(type):
    bpy.ops.mesh.select_mode(type=type)


def object_mode_switch(mode):
    bpy.ops.object.mode_set(mode=mode)


def cursor_origin():
    print("executed CURSOR ORIGIN")


def visual_origin():
    print("executed VISUAL ORIGIN")


def align_to_face():
    print("executed VISUAL ORIGIN")
