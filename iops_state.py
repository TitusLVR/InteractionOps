from collections import defaultdict

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

    operators = {'F1','F2','F3','F4','F5'}


    mesh_dict = defaultdict(lambda: "Operator not defined.")
    
    mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F1"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F2"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F3"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F4"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["OBJECT"]["F5"] = ""

    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F1"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F2"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F3"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F4"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["VERT"]["F5"] = ""

    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F1"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F2"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F3"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F4"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["EDGE"]["F5"] = ""

    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F1"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F2"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F3"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F4"] = ""
    mesh_dict["VIEW_3D"]["MESH"]["EDIT_MESH"]["FACE"]["F5"] = ""
