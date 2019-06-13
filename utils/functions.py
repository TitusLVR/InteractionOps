import bpy


def get_iop(dictionary, query):
    current = dictionary
    for key in query:
        next_ = current.get(key)
        if next_ is None:
            continue
        current = next_
        if not isinstance(current, dict):
            return current
    raise KeyError("Invalid query from Blender!")


def uv_select_mode(mode):
    bpy.context.tool_settings.uv_select_mode = mode


def uv_sync_toggle():
    flag = bpy.context.tool_settings.use_uv_select_sync
    bpy.context.tool_settings.use_uv_select_sync = not flag


def mesh_select_mode(type):
    if bpy.context.mode == "OBJECT":
        object_mode_switch("EDIT")
    bpy.ops.mesh.select_mode(type=type)


def object_mode_switch(mode):
    bpy.ops.object.mode_set(mode=mode)


def cursor_origin():
    print("executed CURSOR ORIGIN")


def visual_origin():
    print("executed VISUAL ORIGIN")


def align_to_face():
    print("executed VISUAL ORIGIN")
