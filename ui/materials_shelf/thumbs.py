"""GPU textures from material previews for the iOps shelf.

- A texture is made lazily, only for drawn cells, at most MAX_NEW_PER_DRAW
  per redraw, from the preview's pixels (reading them never renders: an ID
  preview's pixels are only what Blender already rendered).
- A material without a rendered preview is queued; a timer asks Blender to
  render it with ID.asset_generate_preview(), which schedules a background
  job in a UI session (never from the draw callback). One request at a
  time and never while a preview job runs, see _tick().
- The timer also re-reads the pixels of recently drawn materials every
  CHECK_INTERVAL seconds and drops a texture whose preview changed (a
  finished render job, an edited material), so the next draw rebuilds it.
- Everything is freed on unregister and on file load.
"""
import time

import bpy
import numpy as np
from bpy.app.handlers import persistent

from ...operators.materials import common

MAX_NEW_PER_DRAW = 6
REQUEST_COOLDOWN = 5.0  # seconds before a preview is asked for again
CHECK_INTERVAL = 0.5
RECENT = 2.0            # seconds a drawn material counts as visible

_TEX = {}               # key -> (texture, checksum)
_SEEN = {}              # key -> last draw time
_PENDING = set()        # keys waiting for a preview render
_REQUESTED = {}         # key -> request time (no repeat for 5 s)
_BUDGET = {"left": MAX_NEW_PER_DRAW}


def _pixels(mat):
    """(w, h, float32 RGBA array) of the material's rendered preview, or
    None when it has none yet."""
    prv = mat.preview
    if prv is None:
        return None
    w, h = prv.image_size
    if w <= 0 or h <= 0:
        return None
    px = np.empty(w * h * 4, dtype=np.float32)
    prv.image_pixels_float.foreach_get(px)
    if not px.any():
        return None
    return w, h, px


def _checksum(px):
    return float(px[::97].sum())


def begin_draw():
    _BUDGET["left"] = MAX_NEW_PER_DRAW


def texture(mat):
    """GPUTexture of the material's preview, None while there is none (the
    cell draws a placeholder)."""
    key = common.material_key(mat)
    _SEEN[key] = time.monotonic()
    hit = _TEX.get(key)
    if hit is not None:
        return hit[0]
    if _BUDGET["left"] <= 0:
        return None
    _BUDGET["left"] -= 1
    data = _pixels(mat)
    if data is None:
        _PENDING.add(key)
        return None
    w, h, px = data
    import gpu
    buf = gpu.types.Buffer("FLOAT", w * h * 4, px)
    tex = gpu.types.GPUTexture((w, h), format="RGBA16F", data=buf)
    _TEX[key] = (tex, _checksum(px))
    return tex


def _ui_override():
    """Context override with a window and a 3D View area, needed to start a
    preview render job outside a draw callback."""
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", ()):
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                return {"window": window, "screen": screen, "area": area}
    return None


def _preview_job_running():
    return bpy.app.is_job_running("RENDER_PREVIEW")


def _tick():
    now = time.monotonic()
    # 1. ask Blender to render one missing preview, and only while no
    #    preview job runs: asset_generate_preview() stops the running jobs
    #    and waits for them, and a Cycles preview thread that needs the
    #    Python lock at that moment never ends (Blender freezes for good)
    if _PENDING and not _preview_job_running():
        override = _ui_override()
        for key in sorted(_PENDING):
            if now - _REQUESTED.get(key, -10.0) < REQUEST_COOLDOWN:
                continue
            _PENDING.discard(key)
            mat = common.find_material(*key)
            if mat is None or override is None:
                continue
            _REQUESTED[key] = now
            try:
                with bpy.context.temp_override(**override):
                    mat.asset_generate_preview()
            except (RuntimeError, TypeError, AttributeError):
                pass
            break
    # 2. drop textures whose preview changed (render finished / edited)
    for key in list(_TEX):
        if now - _SEEN.get(key, 0.0) > RECENT:
            continue
        mat = common.find_material(*key)
        if mat is None:
            _TEX.pop(key, None)
            continue
        data = _pixels(mat)
        if data is not None and _checksum(data[2]) != _TEX[key][1]:
            _TEX.pop(key, None)
            redraw = True
        else:
            redraw = False
        if redraw:
            from . import tag_redraw_all
            tag_redraw_all()
    return CHECK_INTERVAL


def free_all():
    _TEX.clear()
    _SEEN.clear()
    _PENDING.clear()
    _REQUESTED.clear()


def texture_count():
    return len(_TEX)


@persistent
def _on_load(*_args):
    free_all()


def register():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if not bpy.app.background and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=CHECK_INTERVAL,
                                persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    free_all()


def timer_registered():
    return bpy.app.timers.is_registered(_tick)
