from ui.hud.items import HUDItem, HUDSection, ItemState


def test_item_defaults():
    item = HUDItem(label="Lock", key="X")
    assert item.state is ItemState.OFF


def test_section_holds_items_in_order():
    a = HUDItem("A", "A")
    b = HUDItem("B", "B")
    s = HUDSection("modes", [a, b])
    assert s.items == [a, b]
    assert s.title == "modes"


def test_state_transitions():
    item = HUDItem("Snap", "S", state=ItemState.ON)
    assert item.state is ItemState.ON
    item.state = ItemState.DISABLED
    assert item.state is ItemState.DISABLED
