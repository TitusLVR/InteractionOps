"""Theme presets — save / load / list `.itheme` files.

Storage: `bpy.utils.script_path_user()/presets/IOPS/themes/*.itheme`

Each `.itheme` file is a JSON dump of the writable properties on
`IOPS_Theme`. UI-only toggles (the collapsible `show_*` booleans and the
`theme_preset` selector itself) are skipped so saved themes are pure
style data.

On register, three bundled presets are written into the themes folder if
they don't already exist: Default (current values), Dark, High Contrast.
"""
from __future__ import annotations

import json
import os
from typing import Any

import bpy


_ITHEME_EXT = ".itheme"
# Property names we never serialize: UI accordion booleans and the
# preset-selector itself (which would re-trigger its own update callback
# on load and cause infinite recursion). The Island palette belongs to
# Visual UV prefs and is intentionally excluded from theme presets.
_SKIP_PROPS = {"rna_type", "theme_preset"}
_SKIP_PREFIXES = ("show_", "island_palette_")

# Path to the read-only themes shipped inside the addon. The user's
# write-target (where Save As stores files) lives under
# `bpy.utils.script_path_user()` — see `user_themes_folder()`.
_BUNDLED_THEMES_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "presets", "themes",
))


def user_themes_folder() -> str:
    """Writable location for user-saved themes."""
    return os.path.join(bpy.utils.script_path_user(),
                        "presets", "IOPS", "themes")


def bundled_themes_folder() -> str:
    """Read-only location of the themes shipped with the addon."""
    return _BUNDLED_THEMES_DIR


# Back-compat shim: any code calling themes_folder() lands on the user
# folder (Save As / Delete / Open Folder all target user-writable space).
def themes_folder() -> str:
    return user_themes_folder()


def _get_theme(context):
    try:
        return context.preferences.addons["InteractionOps"].preferences.iops_theme
    except (KeyError, AttributeError):
        return None


def serialize_theme(theme) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for prop in theme.bl_rna.properties:
        name = prop.identifier
        if name in _SKIP_PROPS:
            continue
        if name.startswith(_SKIP_PREFIXES):
            continue
        if prop.is_readonly:
            continue
        try:
            val = getattr(theme, name)
        except AttributeError:
            continue
        if hasattr(val, "__len__") and not isinstance(val, str):
            val = list(val)
        data[name] = val
    return data


def apply_theme_dict(theme, data: dict[str, Any]) -> int:
    """Write `data` onto `theme`. Returns count of applied props."""
    applied = 0
    for k, v in data.items():
        if k in _SKIP_PROPS or k.startswith("show_"):
            continue
        if not hasattr(theme, k):
            continue
        try:
            current = getattr(theme, k)
            if hasattr(current, "__len__") and not isinstance(current, str):
                setattr(theme, k, tuple(v))
            else:
                setattr(theme, k, v)
            applied += 1
        except (TypeError, ValueError, AttributeError) as e:
            print(f"IOPS theme: skipped '{k}' — {e}")
    return applied


def _write_atomic(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def list_theme_files() -> list[str]:
    """Union of bundled and user `.itheme` files (by filename). User
    files override bundled ones with the same name."""
    seen: dict[str, bool] = {}
    for folder in (bundled_themes_folder(), user_themes_folder()):
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.endswith(_ITHEME_EXT) and os.path.isfile(os.path.join(folder, f)):
                seen[f] = True
    return sorted(seen)


def resolve_theme_path(name: str) -> str | None:
    """Find the on-disk path for a preset name. User folder takes
    precedence over the bundled folder."""
    fn = name + _ITHEME_EXT
    for folder in (user_themes_folder(), bundled_themes_folder()):
        p = os.path.join(folder, fn)
        if os.path.isfile(p):
            return p
    return None


# --- Enum items callback (must keep strings alive in module scope) ---------

_ENUM_ITEMS_CACHE: list[tuple[str, str, str]] = []


def theme_preset_items(self, context):
    """Items callback for the `theme_preset` EnumProperty."""
    global _ENUM_ITEMS_CACHE
    files = list_theme_files()
    if not files:
        _ENUM_ITEMS_CACHE = [("__none__", "(no presets)", "")]
        return _ENUM_ITEMS_CACHE
    items = []
    for fn in files:
        name = fn[: -len(_ITHEME_EXT)]
        items.append((name, name, f"Apply theme '{name}'"))
    _ENUM_ITEMS_CACHE = items
    return _ENUM_ITEMS_CACHE


def theme_preset_get(self):
    """Getter for the `theme_preset` enum — resolve the persisted name string
    to its index in the current items list. Returns 0 (first item) if the
    stored preset no longer exists, so a deleted preset degrades gracefully."""
    name = getattr(self, "theme_preset_name", "")
    if not name:
        return 0
    items = theme_preset_items(self, None)
    for i, it in enumerate(items):
        if it[0] == name:
            return i
    return 0


def theme_preset_set(self, value):
    """Setter for the `theme_preset` enum — translate the index back to a
    name and store it in the persisted `theme_preset_name` string. The
    EnumProperty's `update` callback fires afterwards and applies the preset."""
    items = theme_preset_items(self, None)
    if 0 <= value < len(items):
        self.theme_preset_name = items[value][0]


def theme_preset_update(self, context):
    """Update callback — apply the selected preset."""
    name = getattr(self, "theme_preset", "")
    if not name or name == "__none__":
        return
    path = resolve_theme_path(name)
    if path is None:
        print(f"IOPS theme: preset '{name}' not found in user or bundled folder")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"IOPS theme: failed to load '{path}': {e}")
        return
    if not isinstance(data, dict):
        print(f"IOPS theme: invalid file format: {path}")
        return
    n = apply_theme_dict(self, data)
    print(f"IOPS theme: applied '{name}' ({n} props)")
    # Persist the selection immediately through the IOPS prefs JSON
    # (iops_prefs_user.json) so the last active preset survives reload
    # and restart even when userpref.blend is never saved. Lazy import
    # avoids a module-init cycle with io_addon_preferences.
    try:
        from .io_addon_preferences import save_iops_preferences
        save_iops_preferences()
    except Exception as e:
        print(f"IOPS theme: failed to persist preset selection: {e}")


# --- Bundled defaults ------------------------------------------------------


def _bundled_overrides() -> dict[str, dict[str, Any]]:
    """VS-Code-style bundled presets. Each is a diff over the addon's
    current state (which on first run equals the PropertyGroup defaults
    captured as `Default.itheme`)."""
    return {
        # VS Code "Dark+": calm grey panel, teal headers, blue glyphs.
        "Dark+": {
            "panel_bg_color":           [0.117, 0.117, 0.117, 0.85],
            "color_hud_header":         [0.306, 0.788, 0.690, 1.00],  # #4EC9B0
            "color_hud_key":            [0.337, 0.612, 0.839, 1.00],  # #569CD6
            "color_hud_active_value":   [0.337, 0.612, 0.839, 1.00],
            "color_hud_label":          [0.831, 0.831, 0.831, 1.00],  # #D4D4D4
            "color_hud_label_inactive": [0.502, 0.502, 0.502, 0.90],  # #808080
            "color_hud_stats_error":    [0.949, 0.294, 0.294, 1.00],  # #F14C4C
        },
        # VS Code "Light+": white panel, dark text, blue glyphs, teal headers.
        "Light+": {
            "panel_bg_color":           [1.000, 1.000, 1.000, 0.90],
            "color_hud_header":         [0.149, 0.498, 0.600, 1.00],  # #267F99
            "color_hud_key":            [0.000, 0.000, 1.000, 1.00],  # #0000FF
            "color_hud_active_value":   [0.000, 0.000, 1.000, 1.00],
            "color_hud_label":          [0.000, 0.000, 0.000, 1.00],
            "color_hud_label_inactive": [0.467, 0.467, 0.467, 0.90],  # #777
            "color_hud_stats_error":    [0.639, 0.082, 0.082, 1.00],  # #A31515
        },
        # Monokai: dark warm panel, pink headers, yellow glyphs, cream label.
        "Monokai": {
            "panel_bg_color":           [0.153, 0.157, 0.133, 0.95],  # #272822
            "color_hud_header":         [0.976, 0.149, 0.447, 1.00],  # #F92672
            "color_hud_key":            [0.902, 0.859, 0.455, 1.00],  # #E6DB74
            "color_hud_active_value":   [0.902, 0.859, 0.455, 1.00],
            "color_hud_label":          [0.973, 0.973, 0.949, 1.00],  # #F8F8F2
            "color_hud_label_inactive": [0.459, 0.443, 0.369, 0.90],  # #75715E
            "color_hud_stats_error":    [0.976, 0.149, 0.447, 1.00],
        },
        # Blender Default: colors sourced from Blender 4.x UI theme so
        # the HUD blends with the rest of the app.
        #   panel       ← wcol_tooltip.inner       (#1D1D1D)
        #   header/act  ← v3d.object_active        (#FFA028 orange)
        #   glyph/value ← wcol_state.inner_key     (#B3AE36 keyframe)
        #   label       ← wcol_text.text_sel       (#FFFFFF)
        #   label inact ← wcol_text.text           (#E6E6E6)
        "Blender Default": {
            "panel_bg_color":           [0.114, 0.114, 0.114, 0.95],
            "color_hud_header":         [1.000, 0.627, 0.157, 1.00],
            "color_hud_key":            [0.702, 0.682, 0.212, 1.00],
            "color_hud_active_value":   [0.702, 0.682, 0.212, 1.00],
            "color_hud_label":          [1.000, 1.000, 1.000, 1.00],
            "color_hud_label_inactive": [0.902, 0.902, 0.902, 0.85],
            "color_hud_stats_error":    [0.949, 0.294, 0.294, 1.00],
        },
        # Solarized Dark: muted teal panel, cyan headers, yellow glyphs.
        "Solarized Dark": {
            "panel_bg_color":           [0.000, 0.169, 0.212, 0.95],  # #002B36
            "color_hud_header":         [0.149, 0.545, 0.824, 1.00],  # #268BD2
            "color_hud_key":            [0.710, 0.537, 0.000, 1.00],  # #B58900
            "color_hud_active_value":   [0.710, 0.537, 0.000, 1.00],
            "color_hud_label":          [0.514, 0.580, 0.588, 1.00],  # #839496
            "color_hud_label_inactive": [0.345, 0.431, 0.459, 0.90],  # #586E75
            "color_hud_stats_error":    [0.863, 0.196, 0.184, 1.00],  # #DC322F
        },
    }


# Legacy presets that were shipped earlier but are now superseded by
# the VS-style bundle. Delete them on register so the dropdown stays
# tidy. (User-created themes are never touched.)
_LEGACY_PRESETS = ("Dark", "High Contrast")


def ensure_default_presets() -> None:
    """Legacy hook — bundled themes now ship inside the addon (read-only)
    under `InteractionOps/presets/themes/`, so we no longer need to seed
    the user folder. Kept as a no-op for compatibility and to clean up
    legacy presets that were previously written into the user folder
    under names we no longer ship."""
    user = user_themes_folder()
    for legacy in _LEGACY_PRESETS:
        p = os.path.join(user, legacy + _ITHEME_EXT)
        if os.path.isfile(p):
            try:
                os.remove(p)
                print(f"IOPS theme: removed legacy preset {p}")
            except Exception as e:
                print(f"IOPS theme: failed to remove legacy {p}: {e}")


# --- Operators -------------------------------------------------------------


class IOPS_OT_ThemeSaveAs(bpy.types.Operator):
    bl_idname = "iops.theme_save_as"
    bl_label = "Save Theme As..."
    bl_description = "Save current theme to a new .itheme preset file"
    bl_options = {"REGISTER"}

    name: bpy.props.StringProperty(name="Preset name", default="My Theme")
    overwrite: bpy.props.BoolProperty(
        name="Overwrite if exists", default=False,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "overwrite")
        path = os.path.join(themes_folder(), (self.name or "?") + _ITHEME_EXT)
        layout.label(text=path, icon="FILE_FOLDER")

    def execute(self, context):
        theme = _get_theme(context)
        if theme is None:
            self.report({"ERROR"}, "Theme prefs not available")
            return {"CANCELLED"}
        clean = self.name.strip()
        if not clean:
            self.report({"ERROR"}, "Preset name is empty")
            return {"CANCELLED"}
        # Strip illegal filename chars conservatively.
        for ch in '<>:"/\\|?*':
            clean = clean.replace(ch, "_")
        path = os.path.join(themes_folder(), clean + _ITHEME_EXT)
        if os.path.exists(path) and not self.overwrite:
            self.report({"ERROR"},
                        f"'{clean}{_ITHEME_EXT}' exists — tick Overwrite")
            return {"CANCELLED"}
        try:
            _write_atomic(path, serialize_theme(theme))
        except Exception as e:
            self.report({"ERROR"}, f"Save failed: {e}")
            return {"CANCELLED"}
        # Make the new preset visible in the dropdown and select it.
        theme_preset_items(theme, context)
        try:
            theme.theme_preset = clean
        except (AttributeError, TypeError):
            pass
        self.report({"INFO"}, f"Saved theme to {path}")
        return {"FINISHED"}


class IOPS_OT_ThemeSave(bpy.types.Operator):
    bl_idname = "iops.theme_save"
    bl_label = "Save Current Theme"
    bl_description = ("Save current values onto the selected preset "
                      "(writes to the user folder, overriding a bundled "
                      "preset of the same name)")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        theme = _get_theme(context)
        if theme is None:
            return False
        return getattr(theme, "theme_preset", "") not in ("", "__none__")

    def execute(self, context):
        theme = _get_theme(context)
        if theme is None:
            self.report({"ERROR"}, "Theme prefs not available")
            return {"CANCELLED"}
        name = theme.theme_preset
        path = os.path.join(user_themes_folder(), name + _ITHEME_EXT)
        try:
            _write_atomic(path, serialize_theme(theme))
        except Exception as e:
            self.report({"ERROR"}, f"Save failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Saved theme '{name}' to {path}")
        return {"FINISHED"}


class IOPS_OT_ThemeDelete(bpy.types.Operator):
    bl_idname = "iops.theme_delete"
    bl_label = "Delete Theme Preset"
    bl_description = "Delete the currently selected .itheme preset file"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        theme = _get_theme(context)
        if theme is None:
            return False
        return getattr(theme, "theme_preset", "") not in ("", "__none__")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        theme = _get_theme(context)
        if theme is None:
            return {"CANCELLED"}
        name = theme.theme_preset
        user_path = os.path.join(user_themes_folder(), name + _ITHEME_EXT)
        if not os.path.isfile(user_path):
            bundled = os.path.join(bundled_themes_folder(),
                                   name + _ITHEME_EXT)
            if os.path.isfile(bundled):
                self.report({"WARNING"},
                            f"'{name}' is a bundled preset and cannot be "
                            f"deleted. Save a user version with the same "
                            f"name to override it instead.")
                return {"CANCELLED"}
            self.report({"ERROR"}, f"Preset not found: {name}")
            return {"CANCELLED"}
        try:
            os.remove(user_path)
        except Exception as e:
            self.report({"ERROR"}, f"Delete failed: {e}")
            return {"CANCELLED"}
        theme_preset_items(theme, context)
        self.report({"INFO"}, f"Deleted {user_path}")
        return {"FINISHED"}


class IOPS_OT_ThemeOpenFolder(bpy.types.Operator):
    bl_idname = "iops.theme_open_folder"
    bl_label = "Open Themes Folder"
    bl_description = "Open the themes folder in your OS file manager"
    bl_options = {"REGISTER"}

    def execute(self, context):
        folder = themes_folder()
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


classes = (
    IOPS_OT_ThemeSaveAs,
    IOPS_OT_ThemeSave,
    IOPS_OT_ThemeDelete,
    IOPS_OT_ThemeOpenFolder,
)
