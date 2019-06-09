from collections import defaultdict
from .functions import *


def get_path(root, path):
   
    # current = root
    # for node in path:
    #     current = current.get(node)
    #     if current is None:
    #         raise KeyError("Cannot find specified path %s" % path)
    return path


class IOPS_State():

    areas = {"EMPTY",
             "VIEW_3D",
             "IMAGE_EDITOR",
             "NODE_EDITOR",
             "SEQUENCE_EDITOR",
             "CLIP_EDITOR",
             "DOPESHEET_EDITOR",
             "GRAPH_EDITOR",
             "NLA_EDITOR",
             "TEXT_EDITOR",
             "CONSOLE",
             "INFO",
             "TOPBAR",
             "STATUSBAR",
             "OUTLINER",
             "PROPERTIES",
             "FILE_BROWSER",
             "PREFERENCES"
             }

    types = {"MESH",
             "CURVE",
             "SURFACE",
             "META",
             "FONT",
             "ARMATURE",
             "LATTICE",
             "EMPTY",
             "GPENCIL",
             "CAMERA",
             "LIGHT",
             "SPEAKER",
             "LIGHT_PROBE"
             }

    modes = {"EDIT_MESH",
             "EDIT_CURVE",
             "EDIT_SURFACE",
             "EDIT_TEXT",
             "EDIT_ARMATURE",
             "EDIT_METABALL",
             "EDIT_LATTICE",
             "POSE",
             "SCULPT",
             "PAINT_WEIGHT",
             "PAINT_VERTEX",
             "PAINT_TEXTURE",
             "PARTICLE",
             "OBJECT",
             "PAINT_GPENCIL",
             "EDIT_GPENCIL",
             "SCULPT_GPENCIL",
             "WEIGHT_GPENCIL"
             }

    submodes_uv = {"VERTEX",
                   "EDGE",
                   "FACE",
                   "ISLAND"
                   }

    submodes_mesh = {"VERT",
                     "EDGE",
                     "FACE"
                     }

    operators = {"F1", "F2", "F3", "F4", "F5"}

    # CURRENT SUPPORT
    mesh_dict = defaultdict(lambda: "Operator not defined.")
    curve_dict = defaultdict(lambda: "Operator not defined.")
    empty_dict = defaultdict(lambda: "Operator not defined.")
    font_dict = defaultdict(lambda: "Operator not defined.")
    gpencil_dict = defaultdict(lambda: "Operator not defined.")
    light_dict = defaultdict(lambda: "Operator not defined.")

    # FUTURE SUPPORT
    meta_dict = defaultdict(lambda: "Operator not defined.")
    armature_dict = defaultdict(lambda: "Operator not defined.")
    lattice_dict = defaultdict(lambda: "Operator not defined.")
    camera_dict = defaultdict(lambda: "Operator not defined.")
    speaker_dict = defaultdict(lambda: "Operator not defined.")
    light_probe_dict = defaultdict(lambda: "Operator not defined.")

    # # MESH DICTIONARY

    # mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F1"] = lambda: edit_mode_switch("VERT")  # Switch to VERTEX
    # mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F2"] = lambda: edit_mode_switch("EDGE")  # Switch to EDGE
    # mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F3"] = lambda: edit_mode_switch("FACE")  # Switch to FACE
    # mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F4"] = lambda: cursor_origin()  # Move to cursor
    # mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F5"] = lambda: visual_origin()  # Visual origin

    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F1"] = lambda: object_mode_switch("OBJECT")  # Switch to OBJECT
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F2"] = lambda: edit_mode_switch("EDGE")   # Switch to EDGE
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F3"] = lambda: edit_mode_switch("FACE")   # Switch to FACE
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F4"] = lambda: cursor_origin()   # Cursor/Origin
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F5"] = None  # ???

    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F1"] = ()  # Switch to VERTEX
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F2"] = lambda: object_mode_switch("OBJECT")  # Switch to OBJECT
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F3"] = ()  # Switch to FACE
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F4"] = lambda: cursor_origin()  # Cursor/Origin
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F5"] = None  # ???

    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F1"] = ()  # Switch to VERTEX
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F2"] = ()  # Switch to EDGE
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F3"] = lambda: object_mode_switch("OBJECT")  # Switch to OBJECT
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F4"] = lambda: cursor_origin()  # Cursor/Origin
    # mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F5"] = ()  # Align to face normal

    # # CURVE DICTIONARY

    # curve_dict["VIEW_3D"]["CURVE"]["OBJECT"]["F1"] = ()  # Switch to EDIT
    # curve_dict["VIEW_3D"]["CURVE"]["OBJECT"]["F2"] = ()  #
    # curve_dict["VIEW_3D"]["CURVE"]["OBJECT"]["F3"] = ()  #
    # curve_dict["VIEW_3D"]["CURVE"]["OBJECT"]["F4"] = ()  #
    # curve_dict["VIEW_3D"]["CURVE"]["OBJECT"]["F5"] = ()  #

    # curve_dict["VIEW_3D"]["CURVE"]["EDIT_CURVE"]["F1"] = ()  # Switch to OBJECT
    # curve_dict["VIEW_3D"]["CURVE"]["EDIT_CURVE"]["F2"] = ()  #
    # curve_dict["VIEW_3D"]["CURVE"]["EDIT_CURVE"]["F3"] = ()  #
    # curve_dict["VIEW_3D"]["CURVE"]["EDIT_CURVE"]["F4"] = ()  #
    # curve_dict["VIEW_3D"]["CURVE"]["EDIT_CURVE"]["F5"] = ()  #

    # # EMPTY DICTIONARY

    # empty_dict["VIEW_3D"]["EMPTY"]["F1"] = ()  # ???
    # empty_dict["VIEW_3D"]["EMPTY"]["F2"] = ()  # ???
    # empty_dict["VIEW_3D"]["EMPTY"]["F3"] = ()  # ???
    # empty_dict["VIEW_3D"]["EMPTY"]["F4"] = ()  # Move to Cursor
    # empty_dict["VIEW_3D"]["EMPTY"]["F5"] = ()  # ???

    # # FONT DICTIONARY

    # empty_dict["VIEW_3D"]["FONT"]["F1"] = ()  # Edit text
    # empty_dict["VIEW_3D"]["FONT"]["F2"] = ()  # ???
    # empty_dict["VIEW_3D"]["FONT"]["F3"] = ()  # ???
    # empty_dict["VIEW_3D"]["FONT"]["F4"] = ()  # Move to Cursor
    # empty_dict["VIEW_3D"]["FONT"]["F5"] = ()  # ???

    # empty_dict["VIEW_3D"]["FONT"]["EDIT_TEXT"]["F1"] = ()  # Switch to OBJECT
    # empty_dict["VIEW_3D"]["FONT"]["EDIT_TEXT"]["F2"] = ()  # ???
    # empty_dict["VIEW_3D"]["FONT"]["EDIT_TEXT"]["F3"] = ()  # ???
    # empty_dict["VIEW_3D"]["FONT"]["EDIT_TEXT"]["F4"] = ()  # ???
    # empty_dict["VIEW_3D"]["FONT"]["EDIT_TEXT"]["F5"] = ()  # ???


mesh_dict_v2 = {
    "VIEW_3D": {
        "MESH": {
            "OBJECT": {
                "F1": lambda: edit_mode_switch("VERT"),
                "F2": lambda: edit_mode_switch("EDGE"),
                "F3": lambda: edit_mode_switch("FACE"),
                "F4": lambda: cursor_origin(),
                "F5": lambda: visual_origin(),
            },
            "EDIT_MESH": {
                "VERT": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: edit_mode_switch("EDGE"),
                    "F3": lambda: edit_mode_switch("FACE"),
                    "F4": lambda: cursor_origin(),
                    "F5": None,
                },
                "EDGE": {
                    "F1": lambda: edit_mode_switch("VERT"),
                    "F2": lambda: object_mode_switch("OBJECT"),
                    "F3": lambda: edit_mode_switch("FACE"),
                    "F4": lambda: cursor_origin(),
                    "F5": None,
                },
                "FACE": {
                    "F1": lambda: edit_mode_switch("VERT"),
                    "F2": lambda: edit_mode_switch("EDGE"),
                    "F3": lambda: object_mode_switch("OBJECT"),
                    "F4": lambda: cursor_origin(),
                    "F5": lambda: align_to_face(),
                },
            },
        },
        "CURVE": {
            "OBJECT": {
                "F1": lambda: object_mode_switch("OBJECT"),
                "F2": lambda: edit_mode_switch("EDGE"),
                "F3": lambda: edit_mode_switch("FACE"),
                "F4": lambda: cursor_origin(),
                "F5": None,
            },
            "EDIT_CURVE": {
                "F1": lambda: object_mode_switch("OBJECT"),
                "F2": lambda: edit_mode_switch("EDGE"),
                "F3": lambda: edit_mode_switch("FACE"),
                "F4": lambda: cursor_origin(),
                "F5": None,
            },
        },
    },
}
