import sys
from unittest.mock import MagicMock

# Mock bpy / gpu / blf so pure-Python modules can import without Blender.
for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils",
             "gpu", "gpu.shader", "gpu.state", "gpu.types",
             "gpu_extras", "gpu_extras.batch", "blf", "mathutils"):
    sys.modules.setdefault(name, MagicMock())
