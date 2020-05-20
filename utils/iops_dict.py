from collections import defaultdict
from .functions import *
import bpy


class IOPS_Dict():

    operators = {"F1", "F2", "F3", "F4", "F5", "ESC"}

    iops_dict = {
        "VIEW_3D": {
            "MESH": {
                "OBJECT": {
                    "F1": lambda: mesh_select_mode("VERT"),
                    "F2": lambda: mesh_select_mode("EDGE"),
                    "F3": lambda: mesh_select_mode("FACE"),
                    "F4": lambda: cursor_origin_mesh(),
                    "F5": lambda: match_dimensions(),
                },
                "EDIT": {
                    "VERT": {
                        "F1": lambda: bpy.ops.wm.call_menu(name="VIEW3D_MT_edit_mesh_vertices"),
                        "F2": lambda: mesh_select_mode("EDGE"),
                        "F3": lambda: mesh_select_mode("FACE"),
                        "F4": lambda: cursor_origin_selected(),
                        "F5": lambda: no_operator(),
                        "ESC": lambda: object_mode_switch("OBJECT"),
                    },
                    "EDGE": {
                        "F1": lambda: mesh_select_mode("VERT"),
                        "F2": lambda: bpy.ops.wm.call_menu(name="VIEW3D_MT_edit_mesh_edges"),
                        "F3": lambda: mesh_select_mode("FACE"),
                        "F4": lambda: cursor_origin_selected(),
                        "F5": lambda: z_connect(),
                        "ESC": lambda: object_mode_switch("OBJECT"),
                    },
                    "FACE": {
                        "F1": lambda: mesh_select_mode("VERT"),
                        "F2": lambda: mesh_select_mode("EDGE"),
                        "F3": lambda: bpy.ops.wm.call_menu(name="VIEW3D_MT_edit_mesh_faces"),
                        "F4": lambda: cursor_origin_selected(),
                        "F5": lambda: align_to_face(),
                        "ESC": lambda: object_mode_switch("OBJECT"),
                    },
                },
            },
            "CURVE": {
                "OBJECT": {
                    "F1": lambda: object_mode_switch("EDIT"),
                    "F2": lambda: no_operator(),
                    "F3": lambda: no_operator(),
                    "F4": lambda: cursor_origin_selected(),
                    "F5": lambda: no_operator(),
                },
                "EDIT": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: curve_subdivide(),
                    "F3": lambda: curve_spline_type(),
                    "F4": lambda: cursor_origin_selected(),
                    "F5": lambda: no_operator(),
                    "ESC": lambda: object_mode_switch("OBJECT"),
                },
            },
            "SURFACE": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
            "META": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
            "FONT": {
                "OBJECT":{
                    "F1": lambda: object_mode_switch("EDIT"),
                    },
                "EDIT":{
                    "ESC": lambda: object_mode_switch("OBJECT")
                    }
            },
            "ARMATURE": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
            "LATTICE": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
                "ESC": lambda: object_mode_switch("OBJECT"),
            },
            "EMPTY": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: empty_to_cursor(),
                "F5": lambda: no_operator(),
            },
            "GPENCIL": {
                "EDIT_GPENCIL": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    "F3": lambda: object_mode_switch("PAINT_GPENCIL"),
                    "F4": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    "F5": lambda: no_operator(),
                    "ESC": lambda: object_mode_switch("OBJECT"),
                },
                "SCULPT_GPENCIL": {
                    "F1": lambda: object_mode_switch("EDIT_GPENCIL"),
                    "F2": lambda: object_mode_switch("OBJECT"),
                    "F3": lambda: object_mode_switch("PAINT_GPENCIL"),
                    "F4": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    "F5": lambda: no_operator(),
                    "ESC": lambda: object_mode_switch("OBJECT"),
                },
                "PAINT_GPENCIL": {
                    "F1": lambda: object_mode_switch("EDIT_GPENCIL"),
                    "F2": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    "F3": lambda: object_mode_switch("OBJECT"),
                    "F4": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    "F5": lambda: no_operator(),
                    "ESC": lambda: object_mode_switch("OBJECT"),
                },
                "WEIGHT_GPENCIL": {
                    "F1": lambda: object_mode_switch("EDIT_GPENCIL"),
                    "F2": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    "F3": lambda: object_mode_switch("PAINT_GPENCIL"),
                    "F4": lambda: object_mode_switch("OBJECT"),
                    "F5": lambda: no_operator(),
                    "ESC": lambda: object_mode_switch("OBJECT"),
                },
            },
            "CAMERA": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
            "LIGHT": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
            "SPEAKER": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
            "LIGHT_PROBE": {
                "F1": lambda: no_operator(),
                "F2": lambda: no_operator(),
                "F3": lambda: no_operator(),
                "F4": lambda: no_operator(),
                "F5": lambda: no_operator(),
            },
        },
        "IMAGE_EDITOR": {
            # Sync flag on
            True: {
                "VERT": {
                    "F1": lambda: object_mode_switch("OBJECT"),
                    "F2": lambda: mesh_select_mode("EDGE"),
                    "F3": lambda: mesh_select_mode("FACE"),
                    "F4": lambda: no_operator(),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
                "EDGE": {
                    "F1": lambda: mesh_select_mode("VERT"),
                    "F2": lambda: object_mode_switch("OBJECT"),
                    "F3": lambda: mesh_select_mode("FACE"),
                    "F4": lambda: no_operator(),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
                "FACE": {
                    "F1": lambda: mesh_select_mode("VERT"),
                    "F2": lambda: mesh_select_mode("EDGE"),
                    "F3": lambda: object_mode_switch("OBJECT"),
                    "F4": lambda: no_operator(),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
            },
            # Sync flag off
            False: {
                "VERTEX": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
                "EDGE": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
                "FACE": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
                "ISLAND": {
                    "F1": lambda: uv_select_mode("VERTEX"),
                    "F2": lambda: uv_select_mode("EDGE"),
                    "F3": lambda: uv_select_mode("FACE"),
                    "F4": lambda: uv_select_mode("ISLAND"),
                    "F5": lambda: uv_sync_toggle(),
                    "ESC": lambda: bpy.ops.uv.snap_cursor(target='SELECTED'),
                },
            },

        },
        "OUTLINER": {
            "F1": lambda: set_display_mode('VIEW_LAYER'),
            "F2": lambda: no_operator(),
            "F3": lambda: set_display_mode('LIBRARIES'),
            "F4": lambda: set_display_mode('ORPHAN_DATA'),
            "F5": lambda: no_operator(),
            "ESC": lambda: no_operator(),
        },

        "PREFERENCES": {
            "F1": lambda: no_operator(),
            "F2": lambda: no_operator(),
            "F3": lambda: no_operator(),
            "F4": lambda: no_operator(),
            "F5": lambda: no_operator(),
            "ESC": lambda: no_operator(),
        },

        "FILE_BROWSER": {
            "F1": lambda: no_operator(),
            "F2": lambda: bpy.ops.file.rename(),
            "F3": lambda: no_operator(),
            "F4": lambda: no_operator(),
            "F5": lambda: bpy.ops.file.refresh(),
            "ESC": lambda: bpy.ops.file.cancel(),
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
