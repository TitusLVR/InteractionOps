from collections import defaultdict
from .functions import *


class IOPS_State():

    operators = {"F1", "F2", "F3", "F4", "F5"}

    iops_dict = defaultdict(lambda: "Operator not defined.")
    iops_dict = {
        "VIEW_3D": {
            "MESH": {
                "OBJECT": {
                    "F1": lambda: mesh_select_mode("VERT"),
                    "F2": lambda: mesh_select_mode("EDGE"),
                    "F3": lambda: mesh_select_mode("FACE"),
                    "F4": lambda: cursor_origin(),
                    "F5": lambda: visual_origin(),
                },
                "EDIT_MESH": {
                    "VERT": {
                        "F1": lambda: object_mode_switch("OBJECT"),
                        "F2": lambda: mesh_select_mode("EDGE"),
                        "F3": lambda: mesh_select_mode("FACE"),
                        "F4": lambda: cursor_origin(),
                        "F5": lambda: None,
                    },
                    "EDGE": {
                        "F1": lambda: mesh_select_mode("VERT"),
                        "F2": lambda: object_mode_switch("OBJECT"),
                        "F3": lambda: mesh_select_mode("FACE"),
                        "F4": lambda: cursor_origin(),
                        "F5": lambda: None,
                    },
                    "FACE": {
                        "F1": lambda: mesh_select_mode("VERT"),
                        "F2": lambda: mesh_select_mode("EDGE"),
                        "F3": lambda: object_mode_switch("OBJECT"),
                        "F4": lambda: cursor_origin(),
                        "F5": lambda: align_to_face(),
                    },
                },
            },
            "CURVE": {
                "OBJECT": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: None,
                    "F3": lambda: None,
                    "F4": lambda: cursor_origin(),
                    "F5": lambda: None,
                },
                "EDIT_CURVE": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: None,
                    "F3": lambda: None,
                    "F4": lambda: cursor_origin(),
                    "F5": lambda: None,
                },
            },
            "SURFACE": {
            },
            "META": {
            },
            "FONT": {
            },
            "ARMATURE": {
            },
            "LATTICE": {
            },
            "EMPTY": {
            },
            "GPENCIL": {
                "EDIT_GPENCIL": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    "F3": lambda: object_mode_switch("PAINT_GPENCIL"),
                    "F4": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    "F5": lambda: None,
                },
                "SCULPT_GPENCIL": {
                    "F1": lambda: object_mode_switch("EDIT_GPENCIL"),
                    "F2": lambda: object_mode_switch("OBJECT"),
                    "F3": lambda: object_mode_switch("PAINT_GPENCIL"),
                    "F4": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    "F5": lambda: None,
                },
                "PAINT_GPENCIL": {
                    "F1": lambda: object_mode_switch("EDIT_GPENCIL"),
                    "F2": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    "F3": lambda: object_mode_switch("OBJECT"),
                    "F4": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    "F5": lambda: None,
                },
                "WEIGHT_GPENCIL": {
                    "F1": lambda: object_mode_switch("EDIT_GPENCIL"),
                    "F2": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    "F3": lambda: object_mode_switch("PAINT_GPENCIL"),
                    "F4": lambda: object_mode_switch("OBJECT"),
                    "F5": lambda: None,
                },
            },
            "CAMERA": {
            },
            "LIGHT": {
            },
            "SPEAKER": {
            },
            "LIGHT_PROBE": {
            },
        },
        "IMAGE_EDITOR": {
            # Sync flag on
            True: {
                "VERT": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: mesh_select_mode("EDGE"),
                    "F3": lambda: mesh_select_mode("FACE"),
                    "F4": lambda: None,
                    "F5": lambda: None,
                },
                "EDGE": {
                    "F1": lambda: mesh_select_mode("VERT"),
                    "F2": lambda: object_mode_switch("OBJECT"),
                    "F3": lambda: mesh_select_mode("FACE"),
                    "F4": lambda: None,
                    "F5": lambda: None,
                },
                "FACE": {
                    "F1": lambda: mesh_select_mode("VERT"),
                    "F2": lambda: mesh_select_mode("EDGE"),
                    "F3": lambda: object_mode_switch("OBJECT"),
                    "F4": lambda: None,
                    "F5": lambda: None,
                },
            },
            # Sync flag off
            False: {
                "VERTEX": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: None,
                },
                "EDGE": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: None,
                },
                "FACE": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: None,
                },
                "ISLAND": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: None,
                },
            },

        },
        "OUTLINER": {

        },
    }

# areas = {"EMPTY",
#         "VIEW_3D",
#         "IMAGE_EDITOR",
#         "NODE_EDITOR",
#         "SEQUENCE_EDITOR",
#         "CLIP_EDITOR",
#         "DOPESHEET_EDITOR",
#         "GRAPH_EDITOR",
#         "NLA_EDITOR",
#         "TEXT_EDITOR",
#         "CONSOLE",
#         "INFO",
#         "TOPBAR",
#         "STATUSBAR",
#         "OUTLINER",
#         "PROPERTIES",
#         "FILE_BROWSER",
#         "PREFERENCES"
#         }

# types = {"MESH",
#         "CURVE",
#         "SURFACE",
#         "META",
#         "FONT",
#         "ARMATURE",
#         "LATTICE",
#         "EMPTY",
#         "GPENCIL",
#         "CAMERA",
#         "LIGHT",
#         "SPEAKER",
#         "LIGHT_PROBE"
#         }

# modes = {"EDIT_MESH",
#         "EDIT_CURVE",
#         "EDIT_SURFACE",
#         "EDIT_TEXT",
#         "EDIT_ARMATURE",
#         "EDIT_METABALL",
#         "EDIT_LATTICE",
#         "POSE",
#         "SCULPT",
#         "PAINT_WEIGHT",
#         "PAINT_VERTEX",
#         "PAINT_TEXTURE",
#         "PARTICLE",
#         "OBJECT",
#         "PAINT_GPENCIL",
#         "EDIT_GPENCIL",
#         "SCULPT_GPENCIL",
#         "WEIGHT_GPENCIL"
#         }

# submodes_uv = {"VERTEX",
#                 "EDGE",
#                 "FACE",
#                 "ISLAND"
#                 }

# submodes_mesh = {"VERT",
#                 "EDGE",
#                 "FACE"
#                 }