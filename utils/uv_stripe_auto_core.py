"""UV Stripe's layout choice: where a strip is torn and how each piece is laid out, from the measured stretch.

Pure Python (stdlib only), no bpy, so it runs under plain pytest.

Every bend at all (``AUTO_ANGLE``) is a candidate tear; the candidates that do not
lower any face's stretch are dropped (``auto_cuts``). A strip several faces wide
(``uv_stripe_balance_core.is_wide``) is never torn. Pieces are sliced under "TRUE",
so each one takes its own true width as its height.

Each piece is then laid out by what must be straight on it (a ``Shape``): its two
rails (the long sides) and its two ends. ``default_shape`` reads it from the
settings (Straight Sides and Ends), ``picked_shape`` puts the sides clicked on the
piece on top. ``choose_layout`` measures every layout that keeps that shape
(``candidates``) and takes the one whose worst face stretches least, a layout that
folds a face only when every one does. While the worst face stretches beyond the
stretch limit, the shape is relaxed one step at a time (both rails, the longer rail
only, none) unless the rails were clicked.
"""

import math
from dataclasses import dataclass, replace

from .uv_stripe_balance_core import BALANCES, face_flats, folded_faces, is_wide, start_end
from .uv_stripe_core import STRETCH_TOLERANCE, Strip, face_stretch, lay_piece
from .uv_stripe_select_core import bend_cut_rungs, slice_strip

AUTO_ANGLE = math.radians(0.5)
STRAIGHT_LAYOUTS = ("TRUE", "STRAIGHT", "EVEN")    # straightest first: the order a tie is settled in
DEFAULT_STRETCH_LIMIT = 1.25
RISE = 0.01          # how much a face may stretch more without a candidate tear and still lose it
TIE = 1e-6      # stretches closer than this are equal
STRAIGHT_SIDES = ("BOTH", "LONGER", "SHORTER", "NONE")
END_CHOICES = ("SLANTED", "BOTH", "LONGER", "SHORTER")
SIDE_NAMES = ("near", "far", "end0", "end1")      # a piece's four sides: its rails, then its ends


@dataclass(frozen=True)
class Shape:
    """What must be straight on one piece: its near and its far rail (straight and horizontal), and its two
    ends (upright): ``end0`` the end at ``near[0]``, ``end1`` the one at ``near[-1]``. With neither rail the
    piece is unfolded at its real shape and its ends are not used."""

    near: bool = True
    far: bool = True
    end0: bool = False
    end1: bool = False

    @property
    def rails(self) -> str:
        """"BOTH", "NEAR", "FAR" or "NONE"."""
        if self.near and self.far:
            return "BOTH"
        return "NEAR" if self.near else "FAR" if self.far else "NONE"


# A layout choice: (layout, rails, ends) - "TRUE", "STRAIGHT", "EVEN", "SHAPE" or "BALANCED"; the last with
# ``uv_stripe_balance_core.balanced_uvs``'s rails and ends ("FREE", "BOTH", "START", "END").
Choice = tuple[str, str, str]
EVEN_CHOICE: Choice = ("EVEN", "BOTH", "FREE")


def _path_length(strip: Strip, path: list[int]) -> float:
    return sum(math.dist(strip.verts[a], strip.verts[b]) for a, b in zip(path, path[1:]))


def _end_paths(strip: Strip) -> tuple[list[int], list[int]]:
    return ([strip.near[0], *strip.sides[0], strip.far[0]], [strip.near[-1], *strip.sides[1], strip.far[-1]])


def _start(strip: Strip) -> int:
    """``uv_stripe_balance_core.start_end``, 0 when the strip cannot be laid out to tell."""
    try:
        return start_end(strip)
    except ValueError:
        return 0


def default_shape(strip: Strip, straight_sides: str = "BOTH", ends: str = "SLANTED") -> Shape:
    """The shape the settings ask of ``strip``. ``straight_sides`` (``STRAIGHT_SIDES``): both rails, the longer
    or the shorter rail by 3D length (the near rail on a tie), or none. ``ends`` (``END_CHOICES``): neither
    end ("SLANTED"), both, or the end whose cross edges are longer or shorter in 3D (on a tie the end laid
    at u = 0, ``uv_stripe_balance_core.start_end``). Raises ValueError for an unknown value."""
    if straight_sides not in STRAIGHT_SIDES or ends not in END_CHOICES:
        raise ValueError(f"no shape with straight sides {straight_sides!r} and ends {ends!r}")
    near = far = straight_sides == "BOTH"
    if straight_sides in ("LONGER", "SHORTER"):
        lengths = (_path_length(strip, strip.near), _path_length(strip, strip.far))
        near_longer = lengths[0] >= lengths[1] - TIE * max(lengths)
        near_shorter = lengths[0] <= lengths[1] + TIE * max(lengths)
        near = near_longer if straight_sides == "LONGER" else near_shorter
        far = not near
    end0 = end1 = ends == "BOTH"
    if ends in ("LONGER", "SHORTER") and not strip.closed:
        lengths = [_path_length(strip, path) for path in _end_paths(strip)]
        if abs(lengths[0] - lengths[1]) <= TIE * max(max(lengths), TIE):
            pick = _start(strip)
        elif ends == "LONGER":
            pick = 0 if lengths[0] > lengths[1] else 1
        else:
            pick = 0 if lengths[0] < lengths[1] else 1
        end0, end1 = pick == 0, pick == 1
    return Shape(near, far, end0, end1)


def piece_sides(strip: Strip) -> dict[str, list[tuple[tuple[int, int], int]]]:
    """The four sides of an open piece (``SIDE_NAMES``): each as its edges, (sorted vertex-id pair, the id of the
    piece's face that has the edge), in path order. Empty for a closed piece, which has no ends."""
    if strip.closed:
        return {}
    owner: dict[tuple[int, int], int] = {}
    for fid in sorted(strip.faces):
        face = strip.faces[fid]
        for a, b in zip(face, face[1:] + face[:1]):
            owner.setdefault((min(a, b), max(a, b)), fid)
    out = {}
    for name, path in zip(SIDE_NAMES, (strip.near, strip.far, *_end_paths(strip))):
        edges = []
        for a, b in zip(path, path[1:]):
            key = (min(a, b), max(a, b))
            if a != b and key in owner:
                edges.append((key, owner[key]))
        out[name] = edges
    return out


def picked_shape(strip: Strip, shape: Shape, picks=()) -> tuple[Shape, bool]:
    """``shape`` with the sides picked on ``strip`` set: ``picks`` holds (face id, sorted vertex-id pair,
    straight) in order, and a pick whose face is one of the piece's and whose edge lies on one of its sides
    (``piece_sides``) sets that side, a later pick over an earlier one. Returns the shape and whether a rail
    was picked (then the stretch limit does not relax it)."""
    sides = piece_sides(strip)
    if not sides:
        return shape, False
    where = {edge: name for name, edges in sides.items() for edge, _fid in edges}
    values = {name: getattr(shape, name) for name in SIDE_NAMES}
    rails = False
    for fid, edge, straight in picks:
        name = where.get(tuple(sorted(edge)))
        if fid not in strip.faces or name is None:
            continue
        values[name] = bool(straight)
        rails = rails or name in ("near", "far")
    return Shape(**values), rails


def _ends_mode(strip: Strip, shape: Shape) -> str:
    if shape.end0 and shape.end1:
        return "BOTH"
    if shape.end0 or shape.end1:
        first = _start(strip)
        return "START" if (shape.end0 if first == 0 else shape.end1) else "END"
    return "FREE"


def candidates(strip: Strip, shape: Shape) -> list[Choice]:
    """The layouts that keep ``shape`` on an open piece, in the order a tie is settled in. No rail: "SHAPE" (the
    unfold). Free ends are free, not slanted on purpose: an upright end keeps them too. So both rails with free
    ends: "TRUE", "STRAIGHT", "EVEN", balanced with free ends, balanced with both ends upright; both ends
    upright: "STRAIGHT", "EVEN", then balanced; one end upright: balanced. One rail: balanced with that rail,
    with free ends also balanced with both upright. Balanced takes the ends as asked ("FREE", "BOTH", "START"
    or "END", ``uv_stripe_balance_core.balanced_uvs``)."""
    rails = shape.rails
    if rails == "NONE":
        return [("SHAPE", "BOTH", "FREE")]
    ends = _ends_mode(strip, shape)
    out: list[Choice] = []
    if rails == "BOTH" and ends in ("FREE", "BOTH"):
        if ends == "FREE":
            out.append(("TRUE", "BOTH", "FREE"))
        out += [("STRAIGHT", "BOTH", "BOTH"), ("EVEN", "BOTH", "BOTH")]
    out.append(("BALANCED", rails, ends))
    if ends == "FREE":
        out.append(("BALANCED", rails, "BOTH"))
    return out


def apply_choice(piece: Strip, choice: Choice, balance: str = "EVEN_TEXEL", align: str = "AUTO",
                 align_edges=()) -> dict:
    """Set ``piece`` up under ``choice`` (and ``balance``, for a balanced layout) and return its UVs
    (``uv_stripe_core.lay_piece``). Raises ValueError as ``lay_piece`` does."""
    layout, rails, ends = choice
    piece.rails, piece.ends = rails, ends
    piece.balance = balance if balance in BALANCES else "EVEN_TEXEL"
    return lay_piece(piece, layout, align, align_edges)


def measure(piece: Strip, choice: Choice, balance: str = "EVEN_TEXEL", flats=None) -> tuple[list[float], int]:
    """(every face's stretch in ``piece.faces`` order, the number of folded faces,
    ``uv_stripe_balance_core.folded_faces``, over ``flats``: its ``face_flats``, computed when None) of ``piece``
    laid out under ``choice``. ``piece`` is not changed. Raises ValueError as ``apply_choice`` does."""
    copy = replace(piece)
    uv = apply_choice(copy, choice, balance)
    stretch = [face_stretch([copy.verts[v] for v in face], [uv[(fid, v)] for v in face])
               for fid, face in copy.faces.items()]
    return stretch, folded_faces(copy, uv, flats)


def layout_stretch(piece: Strip, layout: str) -> list[float]:
    """The stretch (``uv_stripe_core.face_stretch``) of every face of ``piece``, in ``piece.faces`` order, laid
    out under ``layout`` as ``uv_stripe_core.lay_piece`` lays it ("BALANCED" with its default modes). ``piece``
    is not changed. Raises ValueError as ``lay_piece`` does."""
    copy = replace(piece)
    copy.rails, copy.ends, copy.balance = "BOTH", "FREE", "EVEN_TEXEL"
    uv = lay_piece(copy, layout)
    return [face_stretch([copy.verts[v] for v in face], [uv[(fid, v)] for v in face])
            for fid, face in copy.faces.items()]


def best_straight(piece: Strip) -> tuple[str, list[float]] | None:
    """The straight-row layout of ``STRAIGHT_LAYOUTS`` whose worst face stretches least, with its face stretch
    (``layout_stretch``); on a tie the first. A layout that raises ValueError is skipped; None when all do.
    Auto's tears are measured by it."""
    best = None
    for layout in STRAIGHT_LAYOUTS:
        try:
            stretch = layout_stretch(piece, layout)
        except ValueError:
            continue
        if best is None or max(stretch, default=1.0) < max(best[1], default=1.0) - TIE:
            best = (layout, stretch)
    return best


def _best(piece: Strip, shape: Shape, balance: str) -> tuple[Choice, float, int] | None:
    """The candidate of ``shape`` (``candidates``) that folds the fewest faces (none, when one does not) and,
    among those, whose worst face stretches least; first on a tie. The balanced solves (the costly ones, last
    in the list) are skipped when the best of the cheap straight-row layouts before them already folds
    nothing and stretches no face beyond ``STRETCH_TOLERANCE``: it is clean, and a balanced layout could only
    be cleaner below what counts as stretch. (choice, worst stretch, folded faces), or None when no candidate
    lays the piece out."""
    best = None
    flats = face_flats(piece)
    for choice in candidates(piece, shape):
        if choice[0] == "BALANCED" and best is not None and not best[2] and best[1] <= STRETCH_TOLERANCE + TIE:
            break
        try:
            stretch, folds = measure(piece, choice, balance, flats)
        except ValueError:
            continue
        worst = max(stretch, default=1.0)
        if best is None or _better((folds, worst), (best[2], best[1])):
            best = (choice, worst, folds)
    return best


def _better(a: tuple[int, float], b: tuple[int, float]) -> bool:
    """Whether (folded faces, worst stretch) ``a`` beats ``b``: fewer folds, then less stretch beyond ``TIE``."""
    return a[0] < b[0] or (a[0] == b[0] and a[1] < b[1] - TIE)


def relax_steps(strip: Strip, shape: Shape) -> list[Shape]:
    """``shape`` and the relaxed shapes the stretch limit tries after it, in order: from both rails the longer
    rail only (by 3D length, the near rail on a tie), then no rail; from one rail no rail; the ends as set."""
    steps = [shape]
    if shape.rails == "BOTH":
        longer = default_shape(strip, "LONGER")
        steps.append(replace(shape, near=longer.near, far=longer.far))
    if shape.rails != "NONE":
        steps.append(replace(shape, near=False, far=False))
    return steps


def choose_layout(piece: Strip, shape: Shape, limit: float = DEFAULT_STRETCH_LIMIT, relax: bool = True,
                  balance: str = "EVEN_TEXEL") -> Choice:
    """The layout ``piece`` is laid out by for ``shape``: the best candidate (``_best``: the fewest folded
    faces first, then the least worst stretch). With ``relax``, while that candidate's worst face stretches
    beyond ``limit`` or it folds a face, the next shape of ``relax_steps`` is tried; the first within the
    limit that folds nothing is taken, else the best of all by the same order. Without ``relax`` the best
    candidate of ``shape`` is taken whatever it stretches; only when no candidate of it lays the piece out
    are the relaxed shapes tried, the first that does taken. When the layout taken still folds a face, a
    straight-row layout ("TRUE", "STRAIGHT", "EVEN", in that order) that folds fewer faces replaces it, even
    one the shape does not ask for. A closed piece, and one nothing can lay out, gets ``EVEN_CHOICE``."""
    if piece.closed:
        return EVEN_CHOICE
    found = []
    for step in relax_steps(piece, shape):
        best = _best(piece, step, balance)
        if best is None:
            continue
        choice, worst, folds = best
        if not folds and worst <= limit + TIE:
            return choice
        found.append(((folds, worst), choice))
        if not relax:
            break
    if not found:
        return EVEN_CHOICE
    top = found[0]
    for key, choice in found[1:]:
        if _better(key, top[0]):
            top = (key, choice)
    if top[0][0]:
        # it folds a face: a straight-row layout that folds fewer is taken instead, whatever the shape asked
        for choice in (("TRUE", "BOTH", "FREE"), ("STRAIGHT", "BOTH", "BOTH"), ("EVEN", "BOTH", "BOTH")):
            try:
                stretch, folds = measure(piece, choice, balance)
            except ValueError:
                continue
            if folds < top[0][0]:
                top = ((folds, max(stretch, default=1.0)), choice)
    return top[1]


def laid_shape(piece: Strip) -> Shape:
    """The shape ``piece`` is laid out with, by its layout: "TRUE" both rails, ends at their slant; "STRAIGHT"
    and "EVEN" both rails, both ends upright; "SHAPE" nothing straight; "BALANCED" its ``rails`` and ``ends``."""
    layout = piece.layout
    if layout == "SHAPE":
        return Shape(False, False, False, False)
    if layout == "BALANCED":
        rails, ends = piece.rails, piece.ends
        if ends in ("START", "END"):
            first = _start(piece)
            on0 = (ends == "START") == (first == 0)
            end0, end1 = on0, not on0
        else:
            end0 = end1 = ends == "BOTH"
        return Shape(rails in ("BOTH", "NEAR"), rails in ("BOTH", "FAR"), end0, end1)
    if layout in ("STRAIGHT", "EVEN") and not piece.closed:
        return Shape(True, True, True, True)
    return Shape(True, True, False, False)


def lay_shaped(piece: Strip, straight_sides: str = "BOTH", ends: str = "SLANTED",
               limit: float = DEFAULT_STRETCH_LIMIT, balance: str = "EVEN_TEXEL", picks=(), align: str = "AUTO",
               align_edges=()) -> Choice:
    """Lay ``piece`` out as the settings and the picked sides ask: its ``default_shape``, the ``picks`` on top
    (``picked_shape``), its ``choose_layout`` (relaxed by ``limit`` unless a rail was picked), applied
    (``apply_choice``). Returns the choice. Raises ValueError as ``apply_choice`` does."""
    shape, rails_picked = picked_shape(piece, default_shape(piece, straight_sides, ends), picks)
    choice = choose_layout(piece, shape, limit, relax=not rails_picked, balance=balance)
    apply_choice(piece, choice, balance, align, align_edges)
    return choice


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
    when the strip can still be torn and laid out with it; the candidates refused are
    tried again, in order, once the later ones are in (a ring that cannot be torn at
    one corner alone can be at all four), until a round takes none. Then, again and again, the
    candidate whose removal leaves the lowest total stretch is dropped, as long as
    without it no face stretches beyond both ``STRETCH_TOLERANCE`` and its stretch with
    it plus ``RISE``; each face is measured under its piece's ``best_straight`` layout.
    A trial that cannot be torn or laid out is never taken; nothing raises. Empty when
    ``strip`` cannot be torn at ``forced_cuts``, and for a strip several faces wide
    (``uv_stripe_balance_core.is_wide``), which stays one piece.
    """
    if is_wide(strip):
        return []
    base = replace(strip, layout="TRUE")
    forced = sorted(set(forced_cuts))
    left_out = set(skip_cuts) | set(forced)
    try:
        candidates_ = sorted(set(bend_cut_rungs(base, AUTO_ANGLE)) - left_out)
    except ValueError:
        return []
    cache: dict = {}
    current = _sliced_stretch(base, forced, cache)
    if current is None:
        return []
    kept: list[int] = []
    pending = candidates_
    while pending:
        rejected = []
        for k in pending:
            trial = _sliced_stretch(base, sorted(forced + kept + [k]), cache)
            if trial is not None:
                kept.append(k)
                current = trial
            else:
                rejected.append(k)
        if len(rejected) == len(pending):
            break
        pending = rejected        # a candidate refused before the later ones were in is tried again
    kept.sort()
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
