"""The case record of tests/blender/test_hud_more_options.py; the ``hud_cases_*.py`` files import it from here."""
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HudCase:
    name: str                       # the operator's name, for the report
    module: str                     # e.g. "operators.mesh_uv_stripe" (below the addon package)
    cls: str                        # the operator class name
    always: set                     # rows shown with More Options off in the default state
    keys: list                      # every key the modal handles, as written in the help (a key or one " / " part)
    tab_rows: set | None = None     # rows shown only under More Options; None: the operator has no Tab section
    also: list = field(default_factory=list)   # [(state changes, row shown by them with More Options off)]
    state: dict = field(default_factory=dict)  # instance attributes the getters read (beyond the RNA defaults)
    build: Callable[[Any], None] | None = None  # builds the overlays; default op._build_overlays(None)
    ignore_events: set = field(default_factory=set)   # handled event types deliberately not in the help (say why)
    hud: str = "_hud"
    help: str = "_help"
