import bpy


def edit_mode_switch(type):
    bpy.ops.mesh.select_mode(type=type)


def object_mode_switch(mode):
    bpy.ops.object.mode_set(mode=mode)


def cursor_origin():
    print("executed CURSOR ORIGIN")


def visual_origin():
    print("executed VISUAL ORIGIN")


def align_to_face():
    print("executed VISUAL ORIGIN")
