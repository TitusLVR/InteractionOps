import json
import os

from utils.library_core import (
    CatalogEntry,
    asset_cache_key,
    catalog_is_stale,
    find_master_in_entries,
    load_catalog_file,
    log_tail,
    normalize_path,
    result_data,
    save_catalog_file,
    thumbnail_filename,
    valid_master_file,
)


class FakeStat:
    def __init__(self, mtime, size):
        self.st_mtime = mtime
        self.st_size = size


def test_normalize_path_empty():
    assert normalize_path("") == ""
    assert normalize_path(None) == ""


def test_normalize_path_normalizes(tmp_path):
    messy = str(tmp_path) + os.sep + "a" + os.sep + ".." + os.sep + "b.blend"
    assert normalize_path(messy) == os.path.normpath(str(tmp_path) + os.sep + "b.blend")


def test_valid_master_file(tmp_path):
    blend = tmp_path / "Master_Library.blend"
    blend.write_bytes(b"")
    assert valid_master_file(str(blend))
    assert not valid_master_file(str(tmp_path / "missing.blend"))
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    assert not valid_master_file(str(txt))
    assert not valid_master_file("")


def test_find_master_single_known_filename(tmp_path):
    (tmp_path / "Master_Library.blend").write_bytes(b"")
    result = find_master_in_entries([("Anything", str(tmp_path))])
    assert os.path.basename(result) == "Master_Library.blend"


def test_find_master_ambiguous_returns_empty(tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    (d1 / "Master_Library.blend").write_bytes(b"")
    (d2 / "Master_Kitbash.blend").write_bytes(b"")
    result = find_master_in_entries([("A", str(d1)), ("B", str(d2))])
    assert result == ""


def test_find_master_single_blend_in_keyword_library(tmp_path):
    (tmp_path / "parts.blend").write_bytes(b"")
    assert find_master_in_entries([("My Kitbash", str(tmp_path))]) != ""
    assert find_master_in_entries([("Unrelated", str(tmp_path))]) == ""


def test_cache_key_stable_and_distinct():
    key1 = asset_cache_key("C:/lib/master.blend", "Bolt", "OBJECT")
    key2 = asset_cache_key("C:/lib/master.blend", "Bolt", "OBJECT")
    key3 = asset_cache_key("C:/lib/master.blend", "Bolt", "MATERIAL")
    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 40
    assert thumbnail_filename("C:/lib/master.blend", "Bolt") == key1 + ".png"


def test_catalog_roundtrip(tmp_path):
    path = str(tmp_path / "cache" / "catalog.json")
    entries = [
        CatalogEntry(asset_name="A", library_path="m.blend", id_type="OBJECT",
                     data_collection="objects", subtype="MESH",
                     category="GEOMETRY", thumbnail_path=""),
    ]
    save_catalog_file(path, "m.blend", 12.5, 999, entries)
    data = load_catalog_file(path)
    assert data["master_file"] == "m.blend"
    assert data["master_mtime"] == 12.5
    assert data["master_size"] == 999
    assert len(data["assets"]) == 1
    assert isinstance(data["assets"][0], CatalogEntry)
    assert data["assets"][0].asset_name == "A"


def test_load_catalog_missing_and_corrupt(tmp_path):
    missing = load_catalog_file(str(tmp_path / "nope.json"))
    assert missing["assets"] == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_catalog_file(str(bad))["assets"] == []
    notdict = tmp_path / "list.json"
    notdict.write_text("[1, 2]")
    assert load_catalog_file(str(notdict))["assets"] == []


def test_catalog_is_stale():
    stat = FakeStat(100.0, 50)
    assert catalog_is_stale(stat, 100.0, 50, has_assets=False)
    assert not catalog_is_stale(stat, 100.0, 50, has_assets=True)
    assert catalog_is_stale(stat, 99.0, 50, has_assets=True)
    assert catalog_is_stale(stat, 100.0, 51, has_assets=True)


def test_result_data_and_log_tail(tmp_path):
    good = tmp_path / "r.json"
    good.write_text(json.dumps({"ok": True}))
    assert result_data(str(good)) == {"ok": True}
    assert result_data(str(tmp_path / "missing.json")) == {}
    log = tmp_path / "w.log"
    log.write_text("\n".join("line%d" % i for i in range(20)))
    tail = log_tail(str(log), line_count=3)
    assert tail.splitlines() == ["line17", "line18", "line19"]
    assert log_tail(str(tmp_path / "missing.log")) == ""
