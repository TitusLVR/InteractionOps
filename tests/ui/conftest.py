import sys
import importlib.util
from pathlib import Path

# When pytest loads tests/ui/__init__.py as the 'ui' package (due to
# --import-mode=importlib + testpaths=tests), it shadows the real ui/ package
# at the project root.  Re-point sys.modules['ui'] to the real package so that
# "from ui.draw.theme import ..." resolves correctly inside tests.
_project_root = Path(__file__).parents[2]
_real_ui_path = _project_root / "ui" / "__init__.py"

spec = importlib.util.spec_from_file_location(
    "ui",
    _real_ui_path,
    submodule_search_locations=[str(_project_root / "ui")],
)
_real_ui = importlib.util.module_from_spec(spec)
sys.modules["ui"] = _real_ui
spec.loader.exec_module(_real_ui)
