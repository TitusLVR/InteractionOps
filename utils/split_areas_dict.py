split_areas_dict = {
    "Empty": {
        "type": "EMPTY",
        "ui": "EMPTY",
        "icon": "NONE",
        "num": 0
        },
    "3D Viewport": {
        "type": "VIEW_3D",
        "ui": "VIEW_3D",
        "icon": "VIEW3D",
        "num": 1
        },
    "Image Editor": {
        "type": "IMAGE_EDITOR",
        "ui": "IMAGE_EDITOR",
        "icon": "IMAGE",
        "num": 2,
    },
    "UV Editor": {
        "type": "IMAGE_EDITOR",
        "ui": "UV",
        "icon": "UV",
        "num": 3
                  },
    "Shader Editor": {
        "type": "NODE_EDITOR",
        "ui": "ShaderNodeTree",
        "icon": "NODE_MATERIAL",
        "num": 4,
    },
    "Compositor": {
        "type": "NODE_EDITOR",
        "ui": "CompositorNodeTree",
        "icon": "NODE_COMPOSITING",
        "num": 5,
    },
    "Texture Node Editor": {
        "type": "NODE_EDITOR",
        "ui": "TextureNodeTree",
        "icon": "NODE_TEXTURE",
        "num": 6,
    },
    "Video Sequencer": {
        "type": "SEQUENCE_EDITOR",
        "ui": "SEQUENCE_EDITOR",
        "icon": "SEQUENCE",
        "num": 7,
    },
    "Movie Clip Editor": {
        "type": "CLIP_EDITOR",
        "ui": "CLIP_EDITOR",
        "icon": "TRACKER",
        "num": 8,
    },
    "Dope Sheet": {
        "type": "DOPESHEET_EDITOR",
        "ui": "DOPESHEET",
        "icon": "ACTION",
        "num": 9,
    },
    "Timeline": {
        "type": "DOPESHEET_EDITOR",
        "ui": "TIMELINE",
        "icon": "TIME",
        "num": 10,
    },
    "Graph Editor": {
        "type": "GRAPH_EDITOR",
        "ui": "FCURVES",
        "icon": "GRAPH",
        "num": 11,
    },
    "Drivers": {
        "type": "GRAPH_EDITOR",
        "ui": "DRIVERS",
        "icon": "DRIVER",
        "num": 12,
    },
    "Nonlinear Animation": {
        "type": "NLA_EDITOR",
        "ui": "NLA_EDITOR",
        "icon": "NLA",
        "num": 13,
    },
    "Text Editor": {
        "type": "TEXT_EDITOR",
        "ui": "TEXT_EDITOR",
        "icon": "TEXT",
        "num": 14,
    },
    "Python Console": {
        "type": "CONSOLE",
        "ui": "CONSOLE",
        "icon": "CONSOLE",
        "num": 15,
    },
    "Info": {"type": "INFO",
             "ui": "INFO",
             "icon": "INFO",
             "num": 16},
    "Outliner": {
        "type": "OUTLINER",
        "ui": "OUTLINER",
        "icon": "OUTLINER",
        "num": 17,
    },
    "Properties": {
        "type": "PROPERTIES",
        "ui": "PROPERTIES",
        "icon": "PROPERTIES",
        "num": 18,
    },
    "File Browser": {
        "type": "FILE_BROWSER",
        "ui": "FILES",
        "icon": "FILEBROWSER",
        "num": 19,
    },
    "Preferences": {
        "type": "PREFERENCES",
        "ui": "PREFERENCES",
        "icon": "PREFERENCES",
        "num": 20,
    },
    "Geometry Nodes": {
        "type": "NODE_EDITOR",
        "ui": "GeometryNodeTree",
        "icon": "NODETREE",
        "num": 21,
    },
    "Spreadsheet": {
        "type": "SPREADSHEET",
        "ui": "SPREADSHEET",
        "icon": "SPREADSHEET",
        "num": 22,
    },
    "Asset Manager": {
        "type": "FILE_BROWSER",
        "ui": "ASSETS",
        "icon": "ASSET_MANAGER",
        "num": 23,
    },
}

split_areas_list = [
    (v["ui"], k, "", v["icon"], v["num"]) for k, v in split_areas_dict.items()
]

split_areas_position_list = [
    ("LEFT", "LEFT", "", "", 0),
    ("RIGHT", "RIGHT", "", "", 1),
    ("TOP", "TOP", "", "", 2),
    ("BOTTOM", "BOTTOM", "", "", 3),
]
