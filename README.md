<a href="https://imgur.com/bUoowcQ"><img src="https://i.imgur.com/bUoowcQ.png" title="iOps" /></a>

# InteractionOps (iOps)

A Blender addon that boosts day-to-day interactivity by mapping a large set of context-aware operators onto a small number of functional buttons (F1–F5 + ESC), wrapped in a unified themed UI with on-canvas HUD and Help overlays.

- **Target:** Blender 5.0+ (see `bl_info` in [`__init__.py`](__init__.py))
- **Version:** 7.7.7
- **License:** see [`license`](license)
- **Issues:** https://github.com/TitusLVR/InteractionOps/issues

## Features

### Modal operators (mesh / object / UV)
- **Cursor Bisect** ([`operators/mesh_cursor_bisect.py`](operators/mesh_cursor_bisect.py)) — cursor-driven bisect with snap, **Inset (V)** and **Bevel (B)** snap-point modes for parallel/dual cuts.
- **UV Shortest Mark** ([`operators/mesh_uv_shortest_mark.py`](operators/mesh_uv_shortest_mark.py)) — interactive seam/sharp marking via Dijkstra / A* / BFS / Edge-Loop, with waypoint system, direction lock, path smoother, and curvature bias. Heavy lifting in a Rust extension ([`rust/mesh_uv_shortest_mark_lib`](rust/mesh_uv_shortest_mark_lib/)).
- **Drag Snap** (mesh / UV / cursor variants), **Quick Snap**, **Quick Connect**, **Straight Bevel**, **Shear**, **Visual UV**, **Visual Origin**, **Three-Point Rotation**, **Align Origin To Normal**, **Align Object To Face**, **Align Between Two**, **Drop It**, **KitBash Grid**, **Mesh To Grid**, **Mesh → Tris → Quads**, **Copy Edges Length / Angle**, **Cursor Rotate**, **UV Channel Hop**, and more.
- All modal operators share the **unified HUD / Help overlay** (live parameters in the corner, key legend toggled with `H` by default).

### Pies & panels
- **Pie menus:** main, edit, split, assets — see [`ui/iops_pie_*.py`](ui/).
- **Floating panels:** Transform Manager, Transform Pivot/Snap, Data, Collection Append, Vertex Color, Object Color, Material Override, Modifier Window — see [`ui/`](ui/).
- **Asset management** (catalogs, marking, search, library switching, thumbnail rendering) — [`operators/assets_management.py`](operators/assets_management.py), [`operators/render_asset_thumbnail.py`](operators/render_asset_thumbnail.py).
- **Executor** — run user Python snippets from a managed list ([`operators/executor.py`](operators/executor.py)).

### Themed UI
- All cosmetic prefs are unified under a single **`IOPS_Theme`** datablock ([`prefs/theme.py`](prefs/theme.py)). Operators pull colors/sizes via `get_theme()` instead of individual prefs.
- Theme roles: **Point / Line / Text** (5 states each), Widgets, Axis, Handle/Pivot/BBox/Cursor, Island palette (8 colors), HUD/Help spacing & columns.
- Theme tab in addon preferences uses collapsible groups and a side-by-side color table.
- **Theme presets** in [`presets/themes/`](presets/themes/): Blender Default, Default, Dark+, Light+, Monokai, Solarized Dark. Save/Load/Delete via the Theme tab.
- Live **Theme Preview** operator renders sample primitives in the active 3D viewport with a Stop button to dismiss.

### HUD / Help split
- **HUD** = live parameter readout (values, snapping state, active mode flags) drawn near the cursor or in a fixed corner.
- **Help** = per-operator key legend in a screen corner, toggled by a unified key (default `H`), with widest-key column alignment for stable layout.
- Implementations: [`ui/hud/`](ui/hud/), [`ui/draw/`](ui/draw/).

### F-key dispatch
- `F1`–`F5` + `ESC` are routed through [`operators/modes.py`](operators/modes.py) and [`operators/iops.py`](operators/iops.py), invoking different operators depending on edit mode, selection, and area context.

### Rust extensions
- Performance-critical path-finding lives in a `pyo3` extension. See [`rust/README.md`](rust/README.md) for the build/deploy workflow.

## Install

1. Download or clone this repo into your Blender `scripts/addons/` directory as a folder named `InteractionOps`.
2. In Blender: *Edit → Preferences → Add-ons → Install from Disk…* (or enable it directly if already on disk).
3. Open the **iOps** preferences tab to set hotkeys, theme, and per-operator options.

> If you want the Rust-backed shortest-path algorithms, also build the Rust crates — see [`rust/README.md`](rust/README.md). The Python side falls back gracefully when the `.pyd` is missing.

## Layout

```
InteractionOps/
├── __init__.py            # registration, bl_info, class list
├── operators/             # modal operators + helpers
│   └── *.pyd              # compiled Rust extensions (gitignored builds)
├── ui/
│   ├── draw/              # shared draw primitives, handlers, state
│   ├── hud/               # HUD + Help overlay
│   └── iops_*.py          # panels, pies
├── prefs/
│   ├── theme.py           # IOPS_Theme datablock + roles
│   ├── addon_preferences.py
│   ├── addon_properties.py
│   └── hotkeys_default.py
├── presets/themes/        # .itheme presets
├── resources/
├── rust/                  # Cargo workspace for .pyd extensions
└── docs/superpowers/      # design specs & implementation plans
```

## Design docs

Active specs and plans live under [`docs/superpowers/`](docs/superpowers/). See [`docs/superpowers/STATUS.md`](docs/superpowers/STATUS.md) for current implementation status of each.

## Documentation

User docs are built from [`docs/`](docs/) with MkDocs Material and deployed via GitHub Actions to GitHub Pages:

**https://tituslvr.github.io/InteractionOps/**

Local preview:

```sh
pip install -r requirements-docs.txt
mkdocs serve
```

Legacy Sphinx docs (predate the unified-UI / HUD split / theme refactor): https://interactionops-docs.readthedocs.io/en/latest/index.html

## Community

BlenderArtists thread: https://blenderartists.org/t/interactionops-iops/

## Authors

- Cyrill Vitkovskiy — https://www.artstation.com/furash
- Titus Lavrov — https://www.artstation.com/tituslvr · https://gumroad.com/titus
- Aleksey

## Special thanks

- Author of qBlocker — https://gumroad.com/sanislovart
- jayanamgames — https://www.youtube.com/user/jayanamgames
