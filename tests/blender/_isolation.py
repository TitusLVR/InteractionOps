"""Guard for headless Blender test scripts: refuse to run against the real user resources.

Enabling and disabling the add-on writes into the user folders: iOps saves its preferences on
unregister into the user scripts folder (``bpy.utils.script_path_user()``, which
``BLENDER_USER_SCRIPTS`` moves on its own), and the preferences add-on operators re-sync extension
wheels in the user extensions folder. A test run must therefore use throw-away folders for all of
them:

    BLENDER_USER_RESOURCES=<a folder under the temp dir> blender --background --factory-startup ...

``BLENDER_USER_SCRIPTS`` / ``BLENDER_USER_EXTENSIONS``, when set, must point under the temp dir too.
Set ``IOPS_TEST_ALLOW_USER_RESOURCES=1`` to run against non-temp folders on purpose.
"""

import os
import sys
import tempfile

OPT_IN = "IOPS_TEST_ALLOW_USER_RESOURCES"


def _is_under(path, root):
    path = os.path.normcase(os.path.realpath(path))
    root = os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:          # different drives
        return False


def unsafe_folders(folders, root):
    """[(label, path)] of `folders` ({label: path or None}) not under `root`; None paths are skipped
    (Blender has no such folder)."""
    return [(label, path) for label, path in folders.items()
            if path is not None and not _is_under(path, root)]


def user_folders(bpy):
    """The user folders a test run may write into: resources, scripts, extensions."""
    folders = {"user resources": bpy.utils.resource_path("USER"),
               "user scripts": bpy.utils.script_path_user()}
    try:
        folders["user extensions"] = bpy.utils.user_resource("EXTENSIONS")
    except (TypeError, ValueError):     # a Blender without extensions
        pass
    return folders


def require_isolated_user_resources():
    """Exit (code 1) before anything is enabled unless Blender's user resource, scripts and
    extensions folders all lie under the system temp dir or the opt-in variable is set."""
    import bpy
    if os.environ.get(OPT_IN) == "1":
        return
    bad = unsafe_folders(user_folders(bpy), tempfile.gettempdir())
    if not bad:
        return
    listing = ", ".join(f"{label} {path!r}" for label, path in bad)
    print(f"ABORT: {listing} not under the temp dir {tempfile.gettempdir()!r}. This test enables / "
          f"disables the add-on, which writes there. Set BLENDER_USER_RESOURCES (and "
          f"BLENDER_USER_SCRIPTS / BLENDER_USER_EXTENSIONS if you set them) to scratch folders "
          f"under the temp dir (or {OPT_IN}=1 to override).", flush=True)
    sys.exit(1)
