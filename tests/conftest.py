import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock bpy / gpu / blf so pure-Python modules can import without Blender.
for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils",
             "gpu", "gpu.shader", "gpu.state", "gpu.types",
             "gpu_extras", "gpu_extras.batch", "blf", "mathutils"):
    sys.modules.setdefault(name, MagicMock())

# ---------------------------------------------------------------------------
# Prevent pytest from trying to execute the addon root __init__.py as a
# test-package initialiser.  The addon root has __init__.py with relative
# imports that only work inside Blender; pytest 9 + --import-mode=importlib
# would otherwise call Package.setup() → importtestmodule(__init__.py) and
# fail with "attempted relative import with no known parent package".
# ---------------------------------------------------------------------------
_ADDON_ROOT = Path(__file__).parents[1]

# ---------------------------------------------------------------------------
# Monkey-patch Package.setup() so it skips the addon root __init__.py.
# pytest 9 + --import-mode=importlib creates a Package node for any directory
# that has __init__.py.  The addon root __init__.py uses relative imports and
# cannot be imported outside Blender.  We replace setup() with a no-op for
# the addon root node only.
# ---------------------------------------------------------------------------
import _pytest.python as _pytest_python

_original_package_setup = _pytest_python.Package.setup


def _patched_package_setup(self):
    if self.path == _ADDON_ROOT:
        return  # skip — addon __init__.py cannot be imported outside Blender
    _original_package_setup(self)


_pytest_python.Package.setup = _patched_package_setup
