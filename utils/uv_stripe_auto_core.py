"""UV Stripe's Auto layout: where a strip is torn and how each piece is laid out, from the measured stretch.

Pure Python (stdlib only), no bpy, so it runs under plain pytest.

Every bend at all (``AUTO_ANGLE``) is a candidate tear; the candidates that do not
lower any face's stretch are dropped (``auto_cuts``). Each piece is then laid out by
its best straight-row layout while its worst face stays within the stretch limit,
and as True Shape beyond it when that is lower (``auto_layout``). Pieces are sliced
under "TRUE", so each one takes its own true width as its height.
"""

import math
from dataclasses import replace

from .uv_stripe_core import STRETCH_TOLERANCE, Strip, face_stretch, lay_piece
from .uv_stripe_select_core import bend_cut_rungs, slice_strip

AUTO_ANGLE = math.radians(0.5)
STRAIGHT_LAYOUTS = ("TRUE", "STRAIGHT", "EVEN")    # straightest first: the order a tie is settled in
DEFAULT_STRETCH_LIMIT = 1.25
RISE = 0.01          # how much a face may stretch more without a candidate tear and still lose it
TIE = 1e-6      # stretches closer than this are equal


def layout_stretch(piece: Strip, layout: str) -> list[float]:
    """The stretch (``uv_stripe_core.face_stretch``) of every face of ``piece``, in ``piece.faces`` order, laid
    out under ``layout`` as ``uv_stripe_core.lay_piece`` lays it. ``piece`` is not changed. Raises ValueError
    as ``lay_piece`` does."""
    copy = replace(piece)
    uv = lay_piece(copy, layout)
    return [face_stretch([copy.verts[v] for v in face], [uv[(fid, v)] for v in face])
            for fid, face in copy.faces.items()]


def best_straight(piece: Strip) -> tuple[str, list[float]] | None:
    """The straight-row layout of ``STRAIGHT_LAYOUTS`` whose worst face stretches least, with its face stretch
    (``layout_stretch``); on a tie the first. A layout that raises ValueError is skipped; None when all do."""
    best = None
    for layout in STRAIGHT_LAYOUTS:
        try:
            stretch = layout_stretch(piece, layout)
        except ValueError:
            continue
        if best is None or max(stretch, default=1.0) < max(best[1], default=1.0) - TIE:
            best = (layout, stretch)
    return best


def _sliced_stretch(strip: Strip, cuts: list[int], cache: dict) -> dict[int, float] | None:
    """Every face's stretch, by face id, with ``strip`` torn at ``cuts`` and each piece under its
    ``best_straight`` layout; None when the strip cannot be torn there or a piece cannot be laid out.
    ``cache`` keeps each piece's result by its faces, so a trial only measures the pieces it changes."""
    try:
        pieces = slice_strip(strip, cuts)
    except ValueError:
        return None
    out = {}
    for piece in pieces:
        key = frozenset(piece.faces)
        if key not in cache:
            best = best_straight(piece)
            cache[key] = None if best is None else dict(zip(piece.faces, best[1]))
        if cache[key] is None:
            return None
        out.update(cache[key])
    return out


def auto_cuts(strip: Strip, forced_cuts=(), skip_cuts=()) -> list[int]:
    """The bend cuts (rung indices, ascending) Auto tears ``strip`` at, besides ``forced_cuts``.

    The candidates are ``bend_cut_rungs`` at ``AUTO_ANGLE`` but those among
    ``skip_cuts`` or ``forced_cuts``; ``forced_cuts`` (rung indices: seams and manual
    cuts) are made in every trial and never dropped. A candidate is taken in order
    when the strip can still be torn and laid out with it. Then, again and again, the
    candidate whose removal leaves the lowest total stretch is dropped, as long as
    without it no face stretches beyond both ``STRETCH_TOLERANCE`` and its stretch with
    it plus ``RISE``; each face is measured under its piece's ``best_straight`` layout.
    A trial that cannot be torn or laid out is never taken; nothing raises. Empty when
    ``strip`` cannot be torn at ``forced_cuts``.
    """
    base = replace(strip, layout="TRUE")
    forced = sorted(set(forced_cuts))
    left_out = set(skip_cuts) | set(forced)
    try:
        candidates = sorted(set(bend_cut_rungs(base, AUTO_ANGLE)) - left_out)
    except ValueError:
        return []
    cache: dict = {}
    current = _sliced_stretch(base, forced, cache)
    if current is None:
        return []
    kept: list[int] = []
    for k in candidates:
        trial = _sliced_stretch(base, sorted(forced + kept + [k]), cache)
        if trial is not None:
            kept.append(k)
            current = trial
    while kept:
        best = None
        for k in kept:
            trial = _sliced_stretch(base, sorted(forced + [c for c in kept if c != k]), cache)
            if trial is None or any(s > STRETCH_TOLERANCE and s > current[fid] + RISE for fid, s in trial.items()):
                continue
            total = sum(trial.values())
            if best is None or total < best[0]:
                best = (total, k, trial)
        if best is None:
            break
        kept.remove(best[1])
        current = best[2]
    return kept


def auto_layout(piece: Strip, limit: float) -> str:
    """The layout Auto lays ``piece`` out by: its ``best_straight`` layout while that layout's worst face
    stretches no more than ``limit``; beyond it "SHAPE" when True Shape's worst face stretches less, else the
    straight layout. A closed piece, and one no straight layout can lay out, gets "EVEN"; a layout that raises
    ValueError is never picked."""
    if piece.closed:
        return "EVEN"
    best = best_straight(piece)
    if best is None:
        return "EVEN"
    layout, stretch = best
    worst = max(stretch, default=1.0)
    if worst <= limit + TIE:
        return layout
    try:
        shape = max(layout_stretch(piece, "SHAPE"), default=1.0)
    except ValueError:
        return layout
    return "SHAPE" if shape < worst - TIE else layout
