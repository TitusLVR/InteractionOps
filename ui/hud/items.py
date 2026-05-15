from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ItemState(Enum):
    ON = "on"
    OFF = "off"
    DISABLED = "disabled"


@dataclass
class HUDItem:
    label: str
    key: str
    state: ItemState = ItemState.OFF


@dataclass
class HUDSection:
    title: str
    items: list[HUDItem] = field(default_factory=list)
