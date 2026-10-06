from utils.boolean_links_core import (
    boolean_operands, boolean_users, mirror_objects, local_view_of,
)


class Obj:
    def __init__(self, name, modifiers=()):
        self.name = name
        self.modifiers = list(modifiers)

    def __repr__(self):
        return f"Obj({self.name})"


class Coll:
    def __init__(self, *objs):
        self.all_objects = list(objs)


class Mod:
    def __init__(self, type, object=None, operand_type="OBJECT",
                 collection=None, mirror_object=None):
        self.type = type
        self.object = object
        self.operand_type = operand_type
        self.collection = collection
        self.mirror_object = mirror_object


class Space:
    def __init__(self, type="VIEW_3D", local_view=None):
        self.type = type
        self.local_view = local_view


# --- boolean_operands -------------------------------------------------

def test_operands_object_mode():
    cutter = Obj("cutter")
    host = Obj("host", [Mod("BOOLEAN", object=cutter)])
    assert boolean_operands([host]) == [cutter]


def test_operands_collection_mode_expands_members():
    a, b = Obj("a"), Obj("b")
    host = Obj("host", [Mod("BOOLEAN", operand_type="COLLECTION",
                            collection=Coll(a, b))])
    assert boolean_operands([host]) == [a, b]


def test_operands_skip_empty_and_non_boolean():
    host = Obj("host", [Mod("BOOLEAN", object=None),
                        Mod("BOOLEAN", operand_type="COLLECTION",
                            collection=None),
                        Mod("MIRROR", mirror_object=Obj("m"))])
    assert boolean_operands([host]) == []


def test_operands_dedup_and_order_across_sources():
    c1, c2 = Obj("c1"), Obj("c2")
    h1 = Obj("h1", [Mod("BOOLEAN", object=c1), Mod("BOOLEAN", object=c2)])
    h2 = Obj("h2", [Mod("BOOLEAN", object=c1)])
    assert boolean_operands([h1, h2]) == [c1, c2]


def test_operands_exclude_sources_themselves():
    c = Obj("c")
    h = Obj("h", [Mod("BOOLEAN", object=c)])
    # c cuts h and h cuts c: neither source is returned as its own result
    c.modifiers.append(Mod("BOOLEAN", object=h))
    assert boolean_operands([h, c]) == []


# --- boolean_users ----------------------------------------------------

def test_users_by_object_operand():
    cutter = Obj("cutter")
    host = Obj("host", [Mod("BOOLEAN", object=cutter)])
    other = Obj("other", [Mod("BOOLEAN", object=Obj("x"))])
    assert boolean_users([host, other, cutter], [cutter]) == [host]


def test_users_by_collection_operand():
    cutter = Obj("cutter")
    host = Obj("host", [Mod("BOOLEAN", operand_type="COLLECTION",
                            collection=Coll(Obj("a"), cutter))])
    assert boolean_users([host, cutter], [cutter]) == [host]


def test_users_multiple_targets_dedup_and_exclude_targets():
    c1, c2 = Obj("c1"), Obj("c2")
    host = Obj("host", [Mod("BOOLEAN", object=c1), Mod("BOOLEAN", object=c2)])
    # c2 also cuts c1 — c2 is a target, so it must not be returned
    c2.modifiers.append(Mod("BOOLEAN", object=c1))
    assert boolean_users([host, c1, c2], [c1, c2]) == [host]


def test_users_ignores_non_mesh_like_objects_without_modifiers():
    class Bare:
        name = "bare"
    cutter = Obj("cutter")
    assert boolean_users([Bare(), cutter], [cutter]) == []


# --- mirror_objects ---------------------------------------------------

def test_mirror_objects_collects_dedup_skips_none():
    e = Obj("empty")
    h1 = Obj("h1", [Mod("MIRROR", mirror_object=e), Mod("MIRROR")])
    h2 = Obj("h2", [Mod("MIRROR", mirror_object=e),
                    Mod("BOOLEAN", object=Obj("c"))])
    assert mirror_objects([h1, h2]) == [e]


# --- local_view_of ----------------------------------------------------

def test_local_view_of_returns_space_only_in_local_view():
    assert local_view_of(None) is None
    assert local_view_of(Space("VIEW_3D", local_view=None)) is None
    assert local_view_of(Space("OUTLINER", local_view=object())) is None
    lv = Space("VIEW_3D", local_view=object())
    assert local_view_of(lv) is lv
