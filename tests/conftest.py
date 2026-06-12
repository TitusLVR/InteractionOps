import os
import sys

# Make `import utils.alignment_fit` resolve from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The repo root is a Blender addon: its __init__.py imports `bpy` (only
# available inside Blender). pytest would otherwise build a `Package` collector
# for the rootdir and import that __init__.py during setup, breaking these
# pure-NumPy unit tests. Collect the rootdir as a plain directory instead so
# the addon __init__.py is never imported.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest_collect_directory(path, parent):
    # pytest.Dir is the public home since pytest 8; older pytest kept it in
    # _pytest.python.
    try:
        from pytest import Dir
    except ImportError:
        from _pytest.python import Dir

    if str(path) == _REPO_ROOT:
        return Dir.from_parent(parent, path=path)
    return None
