"""The headless-test guard (tests/blender/_isolation.py) checks every user folder a run writes to."""
import importlib.util
import os
import tempfile
from types import SimpleNamespace

import pytest

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender", "_isolation.py")
_spec = importlib.util.spec_from_file_location("_isolation", _PATH)
iso = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iso)

TMP = tempfile.gettempdir()
SAFE = os.path.join(TMP, "iops_res")
REAL = os.path.abspath(os.sep + "not_temp_user_config")


def _bpy(resources, scripts, extensions="missing"):
    def user_resource(kind):
        if extensions == "missing":
            raise TypeError(kind)
        return extensions
    return SimpleNamespace(utils=SimpleNamespace(
        resource_path=lambda kind: resources,
        script_path_user=lambda: scripts,
        user_resource=user_resource))


def test_all_under_temp_is_safe():
    folders = iso.user_folders(_bpy(SAFE, os.path.join(SAFE, "scripts"), os.path.join(SAFE, "ext")))
    assert iso.unsafe_folders(folders, TMP) == []


def test_scripts_folder_elsewhere_is_caught():
    folders = iso.user_folders(_bpy(SAFE, REAL, os.path.join(SAFE, "ext")))
    assert iso.unsafe_folders(folders, TMP) == [("user scripts", REAL)]


def test_extensions_folder_elsewhere_is_caught():
    folders = iso.user_folders(_bpy(SAFE, os.path.join(SAFE, "scripts"), REAL))
    assert iso.unsafe_folders(folders, TMP) == [("user extensions", REAL)]


def test_missing_folders_are_skipped():
    folders = iso.user_folders(_bpy(SAFE, None))
    assert "user extensions" not in folders
    assert iso.unsafe_folders(folders, TMP) == []


def test_guard_exits_unless_opted_in(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "bpy", _bpy(SAFE, REAL))
    monkeypatch.delenv(iso.OPT_IN, raising=False)
    with pytest.raises(SystemExit):
        iso.require_isolated_user_resources()
    monkeypatch.setenv(iso.OPT_IN, "1")
    iso.require_isolated_user_resources()
