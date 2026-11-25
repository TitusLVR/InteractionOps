import os
import re

from ui.iops_pie_groups import (EXTRA_COLUMNS, PIE_GROUPS, SLOTS,
                                VERTEX_COLOR, groups_for_mode)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIAGONALS = {"TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT"}


def _entries():
    for mode, table in PIE_GROUPS.items():
        for slot, (_title, rows) in table.items():
            if rows == VERTEX_COLOR:
                continue
            for row in rows:
                for entry in row:
                    yield mode, slot, entry


def _source_idnames():
    found = set()
    pattern = re.compile(r'bl_idname\s*=\s*"([^"]+)"')
    for sub in ("operators", "ui"):
        for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, sub)):
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                        found.update(pattern.findall(f.read()))
    return found


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_slots_order():
    assert SLOTS == ("LEFT", "RIGHT", "BOTTOM", "TOP",
                     "TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT")


def test_slot_names_valid():
    for table in PIE_GROUPS.values():
        for slot in table:
            assert slot in SLOTS or slot in EXTRA_COLUMNS


def test_overlays_column_on_top_in_both_modes():
    src = _read(os.path.join("ui", "iops_pie_menu.py"))
    for mode in ("OBJECT", "EDIT_MESH"):
        title, rows = PIE_GROUPS[mode]["TOP_FAR_RIGHT"]
        assert title == "Overlays"
        assert rows[-2][0][0] == "iops.mesh_zfight_overlay"
        assert rows[-1][0][0] == "iops.mesh_hidden_faces_overlay"
    assert '"TOP_RIGHT", "TOP_FAR_RIGHT")' in src
    assert ('"iops.mesh_hidden_faces_overlay": ("hidden_faces_rays", '
            '"hidden_faces_in_front")') in src
    assert '"iops.mesh_zfight_overlay": ("zfight_in_front",)' in src
    assert ('"iops.mesh_hidden_faces_overlay": '
            '"iops.mesh_hidden_faces_select"') in src
    idnames = _source_idnames()
    for name in ("nonplanar", "zfight", "hidden_faces"):
        assert f"iops.mesh_{name}_select" in idnames
        overlay = _read(os.path.join("operators", f"mesh_{name}_overlay.py"))
        assert "event.shift" not in overlay
    prefs_src = _read(os.path.join("prefs", "addon_preferences.py"))
    for name in ("zfight_in_front", "hidden_faces_in_front"):
        assert f"{name}: BoolProperty(" in prefs_src
        assert f'"{name}": safe("{name}",' in _read(
            os.path.join("prefs", "iops_prefs.py"))
        assert f'("{name}",' in _read(os.path.join(
            "operators", "preferences", "io_addon_preferences.py"))


def test_diagonals_short():
    for table in PIE_GROUPS.values():
        for slot, (_title, rows) in table.items():
            if slot in _DIAGONALS and rows != VERTEX_COLOR:
                assert len(rows) <= 5, slot


def test_only_iops_operators():
    for _mode, _slot, (idname, _text, _props) in _entries():
        assert idname.startswith("iops."), idname


def test_vertex_color_bottom_in_both_modes():
    for mode in ("OBJECT", "EDIT_MESH"):
        assert PIE_GROUPS[mode]["BOTTOM"] == ("Vertex Color", VERTEX_COLOR)


def test_idnames_exist_in_source():
    known = _source_idnames()
    missing = sorted({e[0] for _m, _s, e in _entries()} - known)
    assert missing == []


def test_groups_for_mode():
    assert groups_for_mode("EDIT_MESH") is PIE_GROUPS["EDIT_MESH"]
    assert groups_for_mode("OBJECT") is PIE_GROUPS["OBJECT"]
    assert groups_for_mode("EDIT_CURVE") is PIE_GROUPS["OBJECT"]


def test_external_hotkey():
    from prefs.hotkeys_default import keys_default
    rows = [k for k in keys_default if k[0] == "iops.call_pie_external"]
    assert rows == [("iops.call_pie_external", "ACCENT_GRAVE", "PRESS",
                     True, False, False, False)]


def test_external_pie_guards_addons():
    assert 'addons["' not in _read(os.path.join("ui", "iops_pie_external.py"))


def test_main_pie_has_no_external_ops():
    src = _read(os.path.join("ui", "iops_pie_menu.py"))
    for needle in ("bmax.", "bmoi3d.", "b2ruvl.", "mesh.optiloops", "B2RUVL"):
        assert needle not in src, needle


def test_modifiers_group_in_both_modes():
    for mode in ("OBJECT", "EDIT_MESH"):
        title, rows = PIE_GROUPS[mode]["TOP_LEFT"]
        assert title == "Modifiers"
        idnames = {e[0] for row in rows for e in row}
        assert "iops.modifier_easy_shwarp" in idnames
        assert "iops.mod_cleanup" in idnames


def test_assets_group_in_both_modes():
    for mode in ("OBJECT", "EDIT_MESH"):
        titles = [g[0] for g in PIE_GROUPS[mode].values()]
        assert "Assets & Files" in titles
