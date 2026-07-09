"""Pure-logic tests for widgets/scene_store.py — the per-.blend widget
data store. No bpy: the module is getattr-only, so fake RNA collections
(name-keyed, add/remove/clear) stand in for the real thing."""
import importlib
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

scene_store = importlib.import_module("widgets.scene_store")


# ----------------------------------------------------------------------
# Fakes emulating RNA CollectionProperty behavior
# ----------------------------------------------------------------------
class FakeCollection:
    def __init__(self, factory):
        self._items = []
        self._factory = factory

    def get(self, name):
        return next((it for it in self._items if it.name == name), None)

    def add(self):
        it = self._factory()
        self._items.append(it)
        return it

    def remove(self, index):
        self._items.pop(index)

    def clear(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class FakeEntry:
    def __init__(self):
        self.name = ""
        self.value = ""


class FakeBlock:
    def __init__(self):
        self.name = ""
        self.entries = FakeCollection(FakeEntry)


class FakeIOPS:
    def __init__(self):
        self.widget_data = FakeCollection(FakeBlock)


class FakeScene:
    def __init__(self):
        self.IOPS = FakeIOPS()


class FakeContext:
    def __init__(self):
        self.scene = FakeScene()


class BareContext:
    """Context whose scene has no IOPS (addon half-registered)."""
    def __init__(self):
        self.scene = object()


# ----------------------------------------------------------------------
# get / set_value
# ----------------------------------------------------------------------
def test_get_missing_returns_default():
    ctx = FakeContext()
    assert scene_store.get(ctx, "w", "k") is None
    assert scene_store.get(ctx, "w", "k", default="d") == "d"


def test_set_then_get_roundtrip():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "k", "hello")
    assert scene_store.get(ctx, "w", "k") == "hello"


def test_set_coerces_to_str():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "n", 42)
    assert scene_store.get(ctx, "w", "n") == "42"


def test_set_overwrites_existing_entry_no_duplicates():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "k", "a")
    scene_store.set_value(ctx, "w", "k", "b")
    assert scene_store.get(ctx, "w", "k") == "b"
    block = ctx.scene.IOPS.widget_data.get("w")
    assert len(block.entries) == 1


def test_widgets_do_not_collide():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w1", "k", "a")
    scene_store.set_value(ctx, "w2", "k", "b")
    assert scene_store.get(ctx, "w1", "k") == "a"
    assert scene_store.get(ctx, "w2", "k") == "b"


def test_missing_store_degrades():
    ctx = BareContext()
    scene_store.set_value(ctx, "w", "k", "x")   # no-op, no raise
    assert scene_store.get(ctx, "w", "k", default="d") == "d"


# ----------------------------------------------------------------------
# delete / purge
# ----------------------------------------------------------------------
def test_delete_entry():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "k", "x")
    assert scene_store.delete(ctx, "w", "k") is True
    assert scene_store.get(ctx, "w", "k") is None
    assert scene_store.delete(ctx, "w", "k") is False
    assert scene_store.delete(ctx, "nope", "k") is False


def test_purge_one_widget():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w1", "k", "a")
    scene_store.set_value(ctx, "w2", "k", "b")
    assert scene_store.purge(ctx, "w1") == 1
    assert scene_store.get(ctx, "w1", "k") is None
    assert scene_store.get(ctx, "w2", "k") == "b"
    assert scene_store.purge(ctx, "w1") == 0


def test_purge_all():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w1", "k", "a")
    scene_store.set_value(ctx, "w2", "k", "b")
    assert scene_store.purge(ctx) == 2
    assert len(ctx.scene.IOPS.widget_data) == 0


def test_purge_missing_store_returns_zero():
    assert scene_store.purge(BareContext()) == 0


# ----------------------------------------------------------------------
# Adapters
# ----------------------------------------------------------------------
import math
import pytest


def test_value_adapter_string_roundtrip():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "note", "STRING")
    assert ad["get"](ctx) == ("", False)          # unset -> default, enabled
    ad["set"](ctx, "hello")
    assert ad["get"](ctx) == ("hello", False)


def test_value_adapter_int():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "n", "INT")
    assert ad["get"](ctx) == (0, False)
    ad["set"](ctx, 3)
    assert ad["get"](ctx) == (3, False)
    assert scene_store.get(ctx, "w", "n") == "3"  # stored as string


def test_value_adapter_float():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "f", "FLOAT")
    ad["set"](ctx, 1.5)
    assert ad["get"](ctx) == (1.5, False)


def test_value_adapter_degrees_stores_radians():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "a", "DEGREES")
    ad["set"](ctx, 90.0)                           # author space: degrees
    stored = float(scene_store.get(ctx, "w", "a"))
    assert stored == pytest.approx(math.pi / 2)    # storage space: radians
    value, mixed = ad["get"](ctx)
    assert value == pytest.approx(90.0)            # back to degrees
    assert mixed is False


def test_value_adapter_enum_behaves_as_string():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "e", "ENUM")
    ad["set"](ctx, "OPTION_A")
    assert ad["get"](ctx) == ("OPTION_A", False)


def test_value_adapter_unparseable_returns_default():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "n", "garbage")
    ad = scene_store.store_value_adapter("w", "n", "INT")
    assert ad["get"](ctx) == (0, False)


def test_value_adapter_missing_store_disabled():
    ctx = BareContext()
    ad = scene_store.store_value_adapter("w", "k", "STRING")
    assert ad["get"](ctx) == (None, False)         # disabled
    ad["set"](ctx, "x")                            # no-op, no raise


def test_bool_adapter():
    ctx = FakeContext()
    ad = scene_store.store_bool_adapter("w", "flag")
    assert ad["get"](ctx) == (False, False)        # unset -> False, enabled
    ad["set"](ctx, True)
    assert ad["get"](ctx) == (True, False)
    assert scene_store.get(ctx, "w", "flag") == "1"
    ad["set"](ctx, False)
    assert ad["get"](ctx) == (False, False)
    assert scene_store.get(ctx, "w", "flag") == "0"


def test_bool_adapter_missing_store_disabled():
    assert scene_store.store_bool_adapter("w", "k")["get"](BareContext()) \
        == (None, False)
