from .functions import (
    no_operator,
    object_mode_switch,
    mesh_select_mode,
    cursor_origin_mesh,
    cursor_origin_selected,
    match_dimensions,
    mesh_selection_convert,
    z_connect,
    align_to_face,
    empty_to_cursor,
    view_selected_uv,
    uv_select_mode,
    uv_sync_toggle,
    set_display_mode,
    curve_subdivide,
    curve_spline_type,
)
import bpy

# QUERY: (type_area, type_object, mode_object, mode_mesh, op, event, flag_uv, mode_uv)

class IOPS_Dict:
    operators = {"F1", "F2", "F3", "F4", "F5", "ESC"}
    events = {"NONE", "ALT", "CTRL", "SHIFT", "ALT_CTRL", "ALT_SHIFT", "CTRL_SHIFT", "ALT_CTRL_SHIFT"}

    iops_dict = {
        "VIEW_3D": {
            "MESH": {
                "OBJECT": {
                    "F1": {
                        "NONE": lambda: mesh_select_mode("VERT"),
                        "ALT": lambda: mesh_selection_convert("VERT"),
                    },
                    "F2": {
                        "NONE": lambda: mesh_select_mode("EDGE"),
                        "ALT": lambda: mesh_selection_convert("EDGE"),
                    },
                    "F3": {
                        "NONE": lambda: mesh_select_mode("FACE"),
                        "ALT": lambda: mesh_selection_convert("FACE"),
                    },
                    "F4": {
                        "NONE": lambda: cursor_origin_mesh(),
                    },
                    "F5": {
                        "NONE": lambda: match_dimensions(),
                    },
                },
                "EDIT": {
                    "VERT": {
                        "F1": {
                            "NONE": lambda: bpy.ops.wm.call_menu(name="VIEW3D_MT_edit_mesh_vertices"),
                            "ALT": lambda: mesh_selection_convert("VERT"),
                        },
                        "F2": {
                            "NONE": lambda: mesh_select_mode("EDGE"),
                            "ALT": lambda: mesh_selection_convert("EDGE"),
                        },
                        "F3": {
                            "NONE": lambda: mesh_select_mode("FACE"),
                            "ALT": lambda: mesh_selection_convert("FACE"),
                        },
                        "F4": {
                            "NONE": lambda: cursor_origin_selected(),
                        },
                        "F5": {
                            "NONE": lambda: no_operator(),
                        },
                        "ESC": {
                            "NONE": lambda: object_mode_switch("OBJECT"),
                        },
                    },
                    "EDGE": {
                        "F1": {
                            "NONE": lambda: mesh_select_mode("VERT"),
                            "ALT": lambda: mesh_selection_convert("VERT"),
                        },
                        "F2": {
                            "NONE": lambda: bpy.ops.wm.call_menu(name="VIEW3D_MT_edit_mesh_edges"),
                            "ALT": lambda: mesh_selection_convert("EDGE"),
                        },
                        "F3": {
                            "NONE": lambda: mesh_select_mode("FACE"),
                            "ALT": lambda: mesh_selection_convert("FACE"),
                        },
                        "F4": {
                            "NONE": lambda: cursor_origin_selected(),
                        },
                        "F5": {
                            "NONE": lambda: z_connect(),
                        },
                        "ESC": {
                            "NONE": lambda: object_mode_switch("OBJECT"),
                        },
                    },
                    "FACE": {
                        "F1": {
                            "NONE": lambda: mesh_select_mode("VERT"),
                            "ALT": lambda: mesh_selection_convert("VERT"),
                        },
                        "F2": {
                            "NONE": lambda: mesh_select_mode("EDGE"),
                            "ALT": lambda: mesh_selection_convert("EDGE"),
                        },
                        "F3": {
                            "NONE": lambda: bpy.ops.wm.call_menu(name="VIEW3D_MT_edit_mesh_faces"),
                            "ALT": lambda: mesh_selection_convert("FACE"),
                        },
                        "F4": {
                            "NONE": lambda: cursor_origin_selected(),
                        },
                        "F5": {
                            "NONE": lambda: align_to_face(),
                        },
                        "ESC": {
                            "NONE": lambda: object_mode_switch("OBJECT"),
                        },
                    },
                },
            },
            "CURVE": {
                "OBJECT": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("EDIT"),
                    },
                    "F2": {
                        "NONE": lambda: no_operator(),
                    },
                    "F3": {
                        "NONE": lambda: no_operator(),
                    },
                    "F4": {
                        "NONE": lambda: bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN"),
                    },
                    "F5": {
                        "NONE": lambda: no_operator(),
                    },
                },
                "EDIT": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                    "F2": {
                        "NONE": lambda: curve_subdivide(),
                    },
                    "F3": {
                        "NONE": lambda: curve_spline_type(),
                    },
                    "F4": {
                        "NONE": lambda: cursor_origin_selected(),
                    },
                    "F5": {
                        "NONE": lambda: no_operator(),
                    },
                    "ESC": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                },
            },
            "SURFACE": {
                "F1": {
                    "NONE": lambda: no_operator(),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: no_operator(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
            },
            "META": {
                "F1": {
                    "NONE": lambda: object_mode_switch("EDIT"),
                },
                "F2": {
                    "NONE": lambda: object_mode_switch("EDIT"),
                },
                "F3": {
                    "NONE": lambda: object_mode_switch("EDIT"),
                },
                "ESC": {
                    "NONE": lambda: object_mode_switch("OBJECT"),
                },
            },
            "FONT": {
                "OBJECT": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("EDIT"),
                    },
                },
                "EDIT": {
                    "ESC": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                },
            },
            "ARMATURE": {
                "F1": {
                    "NONE": lambda: object_mode_switch("EDIT"),
                },
                "F2": {
                    "NONE": lambda: object_mode_switch("POSE"),
                },
                "F3": {
                    "NONE": lambda: bpy.ops.object.parent_set(type="BONE"),
                },
                "F4": {
                    "NONE": lambda: no_operator(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
                "ESC": {
                    "NONE": lambda: object_mode_switch("OBJECT"),
                },
            },
            "LATTICE": {
                "F1": {
                    "NONE": lambda: object_mode_switch("EDIT"),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: no_operator(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
                "ESC": {
                    "NONE": lambda: object_mode_switch("OBJECT"),
                },
            },
            "EMPTY": {
                "F1": {
                    "NONE": lambda: no_operator(),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: empty_to_cursor(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
            },
            "GPENCIL": {
                "EDIT_GPENCIL": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                    "F2": {
                        "NONE": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    },
                    "F3": {
                        "NONE": lambda: object_mode_switch("PAINT_GPENCIL"),
                    },
                    "F4": {
                        "NONE": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    },
                    "F5": {
                        "NONE": lambda: no_operator(),
                    },
                    "ESC": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                },
                "SCULPT_GPENCIL": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("EDIT_GPENCIL"),
                    },
                    "F2": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                    "F3": {
                        "NONE": lambda: object_mode_switch("PAINT_GPENCIL"),
                    },
                    "F4": {
                        "NONE": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    },
                    "F5": {
                        "NONE": lambda: no_operator(),
                    },
                    "ESC": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                },
                "PAINT_GPENCIL": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("EDIT_GPENCIL"),
                    },
                    "F2": {
                        "NONE": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    },
                    "F3": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                    "F4": {
                        "NONE": lambda: object_mode_switch("WEIGHT_GPENCIL"),
                    },
                    "F5": {
                        "NONE": lambda: no_operator(),
                    },
                    "ESC": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                },
                "WEIGHT_GPENCIL": {
                    "F1": {
                        "NONE": lambda: object_mode_switch("EDIT_GPENCIL"),
                    },
                    "F2": {
                        "NONE": lambda: object_mode_switch("SCULPT_GPENCIL"),
                    },
                    "F3": {
                        "NONE": lambda: object_mode_switch("PAINT_GPENCIL"),
                    },
                    "F4": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                    "F5": {
                        "NONE": lambda: no_operator(),
                    },
                    "ESC": {
                        "NONE": lambda: object_mode_switch("OBJECT"),
                    },
                },
            },
            "CAMERA": {
                "F1": {
                    "NONE": lambda: no_operator(),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: no_operator(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
            },
            "LIGHT": {
                "F1": {
                    "NONE": lambda: no_operator(),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: cursor_origin_mesh(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
            },
            "SPEAKER": {
                "F1": {
                    "NONE": lambda: no_operator(),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: no_operator(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
            },
            "LIGHT_PROBE": {
                "F1": {
                    "NONE": lambda: no_operator(),
                },
                "F2": {
                    "NONE": lambda: no_operator(),
                },
                "F3": {
                    "NONE": lambda: no_operator(),
                },
                "F4": {
                    "NONE": lambda: no_operator(),
                },
                "F5": {
                    "NONE": lambda: no_operator(),
                },
            },
        },
"IMAGE_EDITOR": {
            # Sync flag on
            True: {
                "VERT": {
                    "F1": {
                        "NONE": lambda: no_operator(),  
                    },
                    "F2": {
                        "NONE": lambda: mesh_select_mode("EDGE"),
                    },
                    "F3": {
                        "NONE": lambda: mesh_select_mode("FACE"),
                    },
                    "F4": {
                        "NONE": lambda: no_operator(),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                    "ESC": {
                        "NONE": lambda: bpy.ops.uv.snap_cursor(target="SELECTED"),
                    },
                },
                "EDGE": {
                    "F1": {
                        "NONE": lambda: mesh_select_mode("VERT"),
                    },
                    "F2": {
                        "NONE": lambda: no_operator(),
                    },
                    "F3": {
                        "NONE": lambda: mesh_select_mode("FACE"),
                    },
                    "F4": {
                        "NONE": lambda: no_operator(),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                    "ESC": {
                        "NONE": lambda: bpy.ops.uv.snap_cursor(target="SELECTED"),
                    },
                },
                "FACE": {
                    "F1": {
                        "NONE": lambda: mesh_select_mode("VERT"),
                    },
                    "F2": {
                        "NONE": lambda: mesh_select_mode("EDGE"),
                    },
                    "F3": {
                        "NONE": lambda: no_operator(),
                    },
                    "F4": {
                        "NONE": lambda: no_operator(),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                },
            },
            # Sync flag off
            False: {
                "UV_VERTEX": {
                    "F1": {
                        "NONE": lambda: view_selected_uv(),
                    },
                    "F2": {
                        "NONE": lambda: uv_select_mode("EDGE"),
                    },
                    "F3": {
                        "NONE": lambda: uv_select_mode("FACE"),
                    },
                    "F4": {
                        "NONE": lambda: uv_select_mode("ISLAND"),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                    "ESC": {
                        "NONE": lambda: bpy.ops.uv.snap_cursor(target="SELECTED"),
                    },
                },
                "UV_EDGE": {
                    "F1": {
                        "NONE": lambda: uv_select_mode("VERTEX"),
                    },
                    "F2": {
                        "NONE": lambda: view_selected_uv(),
                    },
                    "F3": {
                        "NONE": lambda: uv_select_mode("FACE"),
                    },
                    "F4": {
                        "NONE": lambda: uv_select_mode("ISLAND"),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                },
                "UV_FACE": {
                    "F1": {
                        "NONE": lambda: uv_select_mode("VERTEX"),
                    },
                    "F2": {
                        "NONE": lambda: uv_select_mode("EDGE"),
                    },
                    "F3": {
                        "NONE": lambda: view_selected_uv(),
                    },
                    "F4": { 
                        "NONE": lambda: uv_select_mode("ISLAND"),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                    "ESC": {
                        "NONE": lambda: bpy.ops.uv.snap_cursor(target="SELECTED"),
                    },
                },
                "UV_ISLAND": {
                    "F1": {
                        "NONE": lambda: uv_select_mode("VERTEX"),
                    },
                    "F2": {
                        "NONE": lambda: uv_select_mode("EDGE"),
                    },
                    "F3": {
                        "NONE": lambda: uv_select_mode("FACE"),
                    },
                    "F4": {
                        "NONE": lambda: view_selected_uv(),
                    },
                    "F5": {
                        "NONE": lambda: uv_sync_toggle(),
                    },
                    "ESC": {
                        "NONE": lambda: bpy.ops.uv.snap_cursor(target="SELECTED"),
                    },
                },
            },
        },
        "OUTLINER": {
            "F1": {
                "NONE": lambda: set_display_mode("VIEW_LAYER"),
            },
            "F2": {
                "NONE": lambda: no_operator(),
            },
            "F3": {
                "NONE": lambda: set_display_mode("LIBRARIES"),
            },
            "F4": {
                "NONE": lambda: set_display_mode("ORPHAN_DATA"),
            },
            "F5": {
                "NONE": lambda: no_operator(),
            },
            "ESC": {
                "NONE": lambda: no_operator(),
            },
        },
        "PREFERENCES": {
            "F1": {
                "NONE": lambda: bpy.ops.preferences.addon_show(module="InteractionOps"),
            },
            "F2": {
                "NONE": lambda: no_operator(),
            },
            "F3": {
                "NONE": lambda: no_operator(),
            },
            "F4": {
                "NONE": lambda: no_operator(),
            },
            "F5": {
                "NONE": lambda: no_operator(),
            },
            "ESC": {
                "NONE": lambda: no_operator(),
            },
        },
        "FILE_BROWSER": {
            "F1": {
                "NONE": lambda: no_operator(),
            },
            "F2": {
                "NONE": lambda: bpy.ops.file.rename(),
            },
            "F3": {
                "NONE": lambda: no_operator(),
            },
            "F4": {
                "NONE": lambda: no_operator(),
            },
            "F5": {
                "NONE": lambda: bpy.ops.file.refresh(),
            },
            "ESC": {
                "NONE": lambda: bpy.ops.file.cancel(),
            },
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
