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

from .uv_stripe_balance_core import DEFAULT_BALANCE, balance_value, folded_faces, is_wide, line_key, start_end
from .uv_stripe_core import CACHES, STRETCH_TOLERANCE, Strip, align_edge_in, face_stretch, lay_piece, real_pair
from .uv_stripe_select_core import bend_cut_rungs, slice_strip

AUTO_ANGLE = math.radians(0.5)
STRAIGHT_LAYOUTS = ("TRUE", "STRAIGHT", "EVEN")    # straightest first: the order a tie is settled in
DEFAULT_STRETCH_LIMIT = 1.25
RISE = 0.01          # how much a face may stretch more without a candidate tear and still lose it
TIE = 1e-6      # stretches closer than this are equal
STRAIGHT_SIDES = ("BOTH", "LONGER", "SHORTER", "NONE")
END_CHOICES = ("AUTO", "SLANTED", "BOTH", "LONGER", "SHORTER")
RELAX_MARGIN = 0.05     # on a wide strip with no shape within the limit: a stricter one stands unless a looser
#                         one stretches its worst face this much less
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
    at u = 0, ``uv_stripe_balance_core.start_end``); "AUTO" both on a strip several faces wide (``is_wide``),
    neither on one face wide (``choose_layout`` with ``soft_ends`` frees them where upright stretches beyond the
    stretch limit, ``_choose_wide``). Raises ValueError for an unknown value."""
    if straight_sides not in STRAIGHT_SIDES or ends not in END_CHOICES:
        raise ValueError(f"no shape with straight sides {straight_sides!r} and ends {ends!r}")
    near = far = straight_sides == "BOTH"
    if straight_sides in ("LONGER", "SHORTER"):
        lengths = (_path_length(strip, strip.near), _path_length(strip, strip.far))
        near_longer = lengths[0] >= lengths[1] - TIE * max(lengths)
        near_shorter = lengths[0] <= lengths[1] + TIE * max(lengths)
        near = near_longer if straight_sides == "LONGER" else near_shorter
        far = not near
    end0 = end1 = ends == "BOTH" or (ends == "AUTO" and is_wide(strip))
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


def _picked_side(sides, fid: int, edge) -> str | None:
    """The side (``piece_sides``) a pick of edge ``edge`` (mesh vertex ids) beside face ``fid`` lies on: the side
    whose edge is that edge of that face, its vertices by their stand-ins on a cut-open band
    (``uv_stripe_core.real_pair``: both sides of the cut are one mesh edge), else any side with that edge."""
    edge = tuple(sorted(edge))
    for name, edges in sides.items():
        if any(owner == fid and real_pair(key) == edge for key, owner in edges):
            return name
    return next((name for name, edges in sides.items() if any(key == edge for key, _owner in edges)), None)


def picked_shape(strip: Strip, shape: Shape, picks=()) -> tuple[Shape, bool]:
    """``shape`` with the sides picked on ``strip`` set: ``picks`` holds (face id, sorted vertex-id pair,
    straight) in order, and a pick whose face is one of the piece's and whose edge lies on one of its sides
    (``piece_sides``) sets that side, a later pick over an earlier one. Returns the shape and whether a rail
    was picked (then the stretch limit does not relax it)."""
    sides = piece_sides(strip)
    if not sides:
        return shape, False
    values = {name: getattr(shape, name) for name in SIDE_NAMES}
    rails = False
    for fid, edge, straight in picks:
        name = _picked_side(sides, fid, edge)
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
    unfold). Free ends keep their real slant: no layout that stands them upright is a candidate then. So both
    rails with free ends: "TRUE", then balanced with free ends; both ends upright: "STRAIGHT", "EVEN", then
    balanced; one end upright: balanced. One rail: balanced with that rail. Balanced takes the ends as asked
    ("FREE", "BOTH", "START" or "END", ``uv_stripe_balance_core.balanced_uvs``). With lines picked straight
    (``Strip.lines``) a layout other than balanced counts only when it keeps them (``_measure``), and no rail adds
    balanced with no rail after the unfold."""
    rails = shape.rails
    if rails == "NONE":
        # with lines picked straight, the balanced layout with no rail keeps them where the unfold does not
        return [("SHAPE", "BOTH", "FREE")] + ([("BALANCED", "NONE", "FREE")] if strip.lines else [])
    ends = _ends_mode(strip, shape)
    out: list[Choice] = []
    if rails == "BOTH" and ends == "FREE":
        out.append(("TRUE", "BOTH", "FREE"))
    elif rails == "BOTH" and ends == "BOTH":
        out += [("STRAIGHT", "BOTH", "BOTH"), ("EVEN", "BOTH", "BOTH")]
    out.append(("BALANCED", rails, ends))
    return out


def apply_choice(piece: Strip, choice: Choice, balance: float = DEFAULT_BALANCE, align: str = "AUTO",
                 align_edges=()) -> dict:
    """Set ``piece`` up under ``choice`` (and ``balance``, for a balanced layout) and return its UVs
    (``uv_stripe_core.lay_piece``). Raises ValueError as ``lay_piece`` does."""
    layout, rails, ends = choice
    piece.rails, piece.ends = rails, ends
    try:
        piece.balance = balance_value(balance)
    except ValueError:
        piece.balance = DEFAULT_BALANCE
    return lay_piece(piece, layout, align, align_edges)


_MEASURED: dict = {}     # ``measure`` results by piece, choice and the settings that change them
_MEASURED_SIZE = 1024
CACHES.append(_MEASURED)


def _piece_key(piece: Strip):
    used = sorted({v for face in piece.faces.values() for v in face})
    return (tuple(sorted(piece.faces.items())), tuple(piece.near), tuple(piece.far), tuple(piece.sides[0]),
            tuple(piece.sides[1]), tuple(sorted(piece.corner_near.items())), tuple(sorted(piece.corner_far.items())),
            piece.closed, piece.seam, piece.break_edge, round(piece.height, 12),
            tuple((v, tuple(piece.verts[v])) for v in used), line_key(piece))


def measure(piece: Strip, choice: Choice, balance: float = DEFAULT_BALANCE, flats=None) -> tuple[list[float], int]:
    """``_measure``, remembered by the piece (its faces, rows, ends and positions), ``choice``, the balance (for a
    balanced layout) and the align settings (for "SHAPE"): a relayout that changes none of them measures
    nothing again."""
    key = (_piece_key(piece), choice, balance_value(balance) if choice[0] == "BALANCED" else None,
           (piece.align, piece.align_edge) if choice[0] == "SHAPE" else None)
    if key not in _MEASURED:
        while len(_MEASURED) >= _MEASURED_SIZE:
            _MEASURED.pop(next(iter(_MEASURED)))
        try:
            _MEASURED[key] = _measure(piece, choice, balance, flats)
        except ValueError as exc:
            _MEASURED[key] = exc
    found = _MEASURED[key]
    if isinstance(found, ValueError):
        raise ValueError(str(found))
    return list(found[0]), found[1]


def _measure(piece: Strip, choice: Choice, balance: float = DEFAULT_BALANCE, flats=None) -> tuple[list[float], int]:
    """(every face's stretch in ``piece.faces`` order, the number of folded faces,
    ``uv_stripe_balance_core.folded_faces``, over ``flats``: its ``face_flats``, computed when None) of ``piece``
    laid out under ``choice``. ``piece`` is not changed. Raises ValueError as ``apply_choice`` does. A balanced
    layout folds nothing: ``uv_stripe_balance_core.balanced_uvs`` refuses one that would (on the same faces).
    "SHAPE" is turned by the piece's own ``align`` and ``align_edge``. A layout other than balanced that does not
    keep the lines picked on the piece straight (``keeps_lines``) raises ValueError: it is no candidate."""
    copy = replace(piece)
    uv = apply_choice(copy, choice, balance, copy.align, (copy.align_edge,) if copy.align_edge else ())
    if choice[0] != "BALANCED" and not keeps_lines(copy, uv):
        raise ValueError("the layout does not keep the picked lines straight")
    stretch = [face_stretch([copy.verts[v] for v in face], [uv[(fid, v)] for v in face])
               for fid, face in copy.faces.items()]
    return stretch, 0 if choice[0] == "BALANCED" else folded_faces(copy, uv, flats)


LINE_TOL = 1e-6      # a picked line is straight when its coordinate spreads by less than this of the layout's size


def line_spread(strip: Strip, uv: dict, axis: str, vertices) -> float:
    """How far the vertices ``vertices`` of ``strip`` spread in v ("ALONG") or u ("ACROSS") in its layout ``uv`` (by
    (face id, vertex id) corner), over the layout's size (its larger extent): 0 for a line laid straight."""
    k = 1 if axis == "ALONG" else 0
    points = list(uv.values())
    if not points:
        return 0.0
    size = max(max(p[0] for p in points) - min(p[0] for p in points),
               max(p[1] for p in points) - min(p[1] for p in points), 1e-12)
    vs = set(vertices)
    values = [p[k] for (_fid, v), p in uv.items() if v in vs]
    return (max(values) - min(values)) / size if values else 0.0


def keeps_lines(strip: Strip, uv: dict) -> bool:
    """Whether the layout ``uv`` of ``strip`` lays every line picked on it (``Strip.lines``) straight."""
    return all(line_spread(strip, uv, axis, vs) <= LINE_TOL for axis, vs in strip.lines)


def layout_stretch(piece: Strip, layout: str) -> list[float]:
    """The stretch (``uv_stripe_core.face_stretch``) of every face of ``piece``, in ``piece.faces`` order, laid
    out under ``layout`` as ``uv_stripe_core.lay_piece`` lays it ("BALANCED" with its default modes). ``piece``
    is not changed. Raises ValueError as ``lay_piece`` does."""
    copy = replace(piece)
    copy.rails, copy.ends, copy.balance = "BOTH", "FREE", 1.0
    uv = lay_piece(copy, layout)
    return [face_stretch([copy.verts[v] for v in face], [uv[(fid, v)] for v in face])
            for fid, face in copy.faces.items()]


def best_straight(piece: Strip, layouts=STRAIGHT_LAYOUTS) -> tuple[str, list[float]] | None:
    """The straight-row layout of ``layouts`` (``STRAIGHT_LAYOUTS`` by default; only "TRUE" keeps free ends at
    their real slant) whose worst face stretches least, with its face stretch (``layout_stretch``); on a tie
    the first. A layout that raises ValueError is skipped; None when all do. Auto's tears are measured by it."""
    best = None
    for layout in layouts:
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
    flats = None
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


def fits_whole(strip: Strip, shape: Shape, limit: float = DEFAULT_STRETCH_LIMIT,
               balance: float = DEFAULT_BALANCE) -> bool:
    """Whether ``strip`` laid out whole by the candidates of ``shape`` (``_best``: the very layouts it will be laid
    out with, balanced at ``balance`` among them) folds nothing and stretches no face beyond ``limit``: then
    Auto does not tear it. False for a closed strip."""
    if strip.closed:
        return False
    best = _best(strip, shape, balance)
    return best is not None and not best[2] and best[1] <= limit + TIE


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
                  balance: float = DEFAULT_BALANCE, soft_ends: bool = False) -> Choice:
    """The layout ``piece`` is laid out by for ``shape``: the best candidate (``_best``: the fewest folded
    faces first, then the least worst stretch). With ``relax``, while that candidate's worst face stretches
    beyond ``limit`` or it folds a face, the next shape of ``relax_steps`` is tried; the first within the
    limit that folds nothing is taken, else the best of all by the same order. Without ``relax`` the best
    candidate of ``shape`` is taken whatever it stretches; only when no candidate of it lays the piece out
    are the relaxed shapes tried, the first that does taken. When every straight-sided step of a shape with
    upright ends folds a face or squashes one flat (a real corner on an upright end), the same straight sides
    with free ends are tried before the real-shape unfold (from both ends upright, each end alone first). When
    the layout taken still folds a face, a straight-row layout ("TRUE", "STRAIGHT", "EVEN", in that order) that
    folds fewer faces replaces it, even one the shape does not ask for. A closed piece, and one nothing can lay
    out, gets ``EVEN_CHOICE``. A strip several faces wide is chosen by ``_choose_wide`` (``soft_ends``: the ends
    are upright while that stays within ``limit``)."""
    if piece.closed:
        return EVEN_CHOICE
    if is_wide(piece):
        return _choose_wide(piece, shape, limit, relax, balance, soft_ends)
    found = []
    steps = relax_steps(piece, shape)
    unfold = [s for s in steps if s.rails == "NONE"]
    straight = [s for s in steps if s.rails != "NONE"]
    collapsed = True                  # every straight-sided step folds a face or squashes one flat
    for step in straight:
        best = _best(piece, step, balance)
        if best is None:
            continue
        choice, worst, folds = best
        if not folds and worst <= limit + TIE:
            return choice
        collapsed = collapsed and (folds > 0 or worst == math.inf)
        found.append(((folds, worst), choice))
        if not relax:
            return _settle(piece, shape, found, balance)
    if relax and collapsed and (shape.end0 or shape.end1) and straight:
        # the upright ends squash a real corner: each end alone (from both upright), then the same straight
        # sides with free ends, before the bent shape
        singles = [replace(s, end1=False) for s in straight if s.end0 and s.end1] + \
            [replace(s, end0=False) for s in straight if s.end0 and s.end1]
        for step in singles:
            best = _best(piece, step, balance)
            if best is None:
                continue
            choice, worst, folds = best
            if not folds and worst <= limit + TIE:
                return choice
            found.append(((folds, worst), choice))
        for step in relax_steps(piece, replace(shape, end0=False, end1=False)):
            if step.rails == "NONE":
                continue
            best = _best(piece, step, balance)
            if best is None:
                continue
            choice, worst, folds = best
            if not folds and worst <= limit + TIE:
                return choice
            found.append(((folds, worst), choice))
    for step in unfold if relax or not found else []:
        best = _best(piece, step, balance)
        if best is None:
            continue
        choice, worst, folds = best
        if not folds and worst <= limit + TIE:
            return choice
        found.append(((folds, worst), choice))
    return _settle(piece, shape, found, balance)


def _choose_wide(piece: Strip, shape: Shape, limit: float, relax: bool, balance: float, soft_ends: bool) -> Choice:
    """``choose_layout`` for a strip several faces wide, where ``limit`` alone decides how far a shape is
    loosened. The shapes are measured from the strictest (``relax_steps``: both rails, the longer rail, no
    rail); at every straight-sided step with upright ends, when they fold a face, each end alone is tried, and
    with ``soft_ends`` (Ends "AUTO", no end picked by hand) free ends with the same rails are measured after the
    upright ones whenever those are not within ``limit``. After each step the strictest clean layout (no fold, finite stretch) measured so far
    whose worst face lies within ``limit`` is taken, however much less a looser one would stretch: a looser
    shape (a freed rail, freed ends, one end alone, the real-shape unfold) is taken only when every stricter
    one measured before it stretches beyond the limit. With hard upright ends that fold at every step, free
    ends follow the straight steps as in ``choose_layout``. With none within the limit, the strictest clean
    layout within ``RELAX_MARGIN`` of the least stretched clean one; failing that ``_settle``. Without
    ``relax`` only ``shape`` (and its end variants) is measured, unless nothing lays it out."""
    found = []        # ((folded faces, worst stretch), choice), strictest shape first

    def measure_step(step):
        best = _best(piece, step, balance)
        if best is not None:
            found.append(((best[2], best[1]), best[0]))
        return best

    def clean(best):
        return best is not None and not best[2] and best[1] < math.inf

    def within_limit():
        # the strictest clean layout within the limit stands, however much less a looser one would stretch
        return next((c for key, c in found if not key[0] and key[1] <= limit + TIE), None)

    steps = relax_steps(piece, shape)
    straight = [s for s in steps if s.rails != "NONE"]
    unfold = [s for s in steps if s.rails == "NONE"]
    collapsed = True
    for step in straight if relax else straight[:1]:
        best = measure_step(step)
        bad = not clean(best)
        if step.end0 and step.end1 and bad:                  # each end alone before free ends
            for single in (replace(step, end1=False), replace(step, end0=False)):
                bad = not clean(measure_step(single)) and bad
        if soft_ends and (step.end0 or step.end1) and within_limit() is None:
            measure_step(replace(step, end0=False, end1=False))    # free ends: only when upright exceeds the limit
        collapsed = collapsed and bad
        choice = within_limit()
        if choice is not None:
            return choice
        if not relax and found:
            break
    if relax and collapsed and not soft_ends and (shape.end0 or shape.end1) and straight:
        for step in straight:
            measure_step(replace(step, end0=False, end1=False))
        choice = within_limit()
        if choice is not None:
            return choice
    for step in unfold if relax or not found else []:
        measure_step(step)
        choice = within_limit()
        if choice is not None:
            return choice
    clean_found = [(key, c) for key, c in found if not key[0] and key[1] < math.inf]
    if clean_found:
        least = min(key[1] for key, _c in clean_found)
        return next(c for key, c in clean_found if key[1] <= least + RELAX_MARGIN + TIE)
    return _settle(piece, shape, found, balance)


def _settle(piece: Strip, shape: Shape, found, balance) -> Choice:
    """The best of the ``found`` ((folded faces, worst stretch), choice) of ``choose_layout`` (``_better``), a
    straight-row layout that folds fewer faces in place of one that folds; ``EVEN_CHOICE`` when none."""
    if not found:
        return EVEN_CHOICE
    top = found[0]
    for key, choice in found[1:]:
        if _better(key, top[0]):
            top = (key, choice)
    if top[0][0]:
        # it folds a face: a straight-row layout that folds fewer is taken instead, whatever rails the shape asked;
        # under free ends only the one that keeps their slant ("TRUE")
        fallbacks = [("TRUE", "BOTH", "FREE")]
        if shape.end0 or shape.end1:
            fallbacks += [("STRAIGHT", "BOTH", "BOTH"), ("EVEN", "BOTH", "BOTH")]
        for choice in fallbacks:
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
               limit: float = DEFAULT_STRETCH_LIMIT, balance: float = DEFAULT_BALANCE, picks=(), align: str = "AUTO",
               align_edges=()) -> Choice:
    """Lay ``piece`` out as the settings and the picked sides ask: its ``default_shape``, the ``picks`` on top
    (``picked_shape``), its ``choose_layout`` (relaxed by ``limit`` unless a rail was picked), applied
    (``apply_choice``). The lines picked straight on it (``Strip.lines``) stay straight through every relaxed
    shape: only the layouts that keep them are measured. Returns the choice. Raises ValueError as ``apply_choice``
    does."""
    piece.align = align
    piece.align_edge = align_edge_in(piece, align_edges) if align == "PICKED" else None
    shape, rails_picked = picked_shape(piece, default_shape(piece, straight_sides, ends), picks)
    soft = ends == "AUTO" and not ends_picked(piece, picks)
    if piece.lines:
        choice = _with_lines(piece, shape, limit, not rails_picked, balance, soft)
    else:
        choice = choose_layout(piece, shape, limit, relax=not rails_picked, balance=balance, soft_ends=soft)
    apply_choice(piece, choice, balance, align, align_edges)
    return choice


def ends_picked(strip: Strip, picks=()) -> bool:
    """Whether one of ``picks`` (as ``picked_shape`` reads them) sets an end of ``strip``."""
    sides = piece_sides(strip)
    return any(fid in strip.faces and _picked_side(sides, fid, edge) in ("end0", "end1")
               for fid, edge, _straight in picks)


_RAIL_SIDES = {"BOTH": (True, True), "NEAR": (True, False), "FAR": (False, True), "NONE": (False, False)}


def choice_rails(choice: Choice) -> str:
    """The rails a layout choice keeps straight: "SHAPE" none, "BALANCED" its own, the straight-row layouts both."""
    return "NONE" if choice[0] == "SHAPE" else choice[1] if choice[0] == "BALANCED" else "BOTH"


def _with_lines(piece: Strip, shape: Shape, limit: float, relax: bool, balance: float, soft: bool = False) -> Choice:
    """The layout of ``piece`` with its picked lines (``Strip.lines``): a picked line only adds a constraint, it
    never loosens a rail. The piece is first laid out without the lines (``choose_layout`` by ``shape``, relaxed
    by ``limit`` with ``relax``, ``soft`` ends); the rails that layout keeps straight stay so, its ends as they
    are, the lines are kept on top and nothing is relaxed further (balanced with no rail only where the piece had
    no straight rail anyway). When no layout keeps both, the layout without the lines stands (the lines are then
    not straight: the interactive mode does not store such a pick)."""
    base = choose_layout(replace(piece, lines=()), shape, limit, relax=relax, balance=balance, soft_ends=soft)
    near, far = _RAIL_SIDES[choice_rails(base)]
    laid = replace(piece, layout=base[0], rails=base[1], ends=base[2])
    held = laid_shape(laid) if base[0] != "SHAPE" else shape
    kept = choose_layout(piece, replace(shape, near=near, far=far, end0=held.end0, end1=held.end1), limit,
                         relax=False, balance=balance)
    had, has = _RAIL_SIDES[choice_rails(base)], _RAIL_SIDES[choice_rails(kept)]
    if any(h and not k for h, k in zip(had, has)):
        return base
    try:
        uv = apply_choice(replace(piece), kept, balance, piece.align, (piece.align_edge,) if piece.align_edge else ())
    except ValueError:
        return base
    return kept if keeps_lines(piece, uv) else base


def _sliced_stretch(strip: Strip, cuts: list[int], cache: dict, layouts=STRAIGHT_LAYOUTS) -> dict[int, float] | None:
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
            best = best_straight(piece, layouts)
            cache[key] = None if best is None else dict(zip(piece.faces, best[1]))
        if cache[key] is None:
            return None
        out.update(cache[key])
    return out


def auto_cuts(strip: Strip, forced_cuts=(), skip_cuts=(), layouts=STRAIGHT_LAYOUTS, limit: float | None = None) -> list[int]:
    """The bend cuts (rung indices, ascending) Auto tears ``strip`` at, besides ``forced_cuts``.

    The candidates are ``bend_cut_rungs`` at ``AUTO_ANGLE`` but those among
    ``skip_cuts`` or ``forced_cuts``; ``forced_cuts`` (rung indices: seams and manual
    cuts) are made in every trial and never dropped. A candidate is taken in order
    when the strip can still be torn and laid out with it; the candidates refused are
    tried again, in order, once the later ones are in (a ring that cannot be torn at
    one corner alone can be at all four), until a round takes none. Then, again and again, the
    candidate whose removal leaves the lowest total stretch is dropped, as long as
    without it no face stretches beyond both ``STRETCH_TOLERANCE`` and its stretch with
    it plus ``RISE``; each face is measured under its piece's ``best_straight`` layout among ``layouts`` (only
    "TRUE" under free ends: a layout that stands them upright is no candidate there). With ``limit`` (the Stretch
    Limit) a candidate is dropped while no face then stretches beyond the limit either, so the strip is torn
    into as few pieces as keep every face within it.
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
    current = _sliced_stretch(base, forced, cache, layouts)
    if current is None:
        return []
    kept: list[int] = []
    pending = candidates_
    while pending:
        rejected = []
        for k in pending:
            trial = _sliced_stretch(base, sorted(forced + kept + [k]), cache, layouts)
            if trial is not None:
                kept.append(k)
                current = trial
            else:
                rejected.append(k)
        if len(rejected) == len(pending):
            break
        pending = rejected        # a candidate refused before the later ones were in is tried again
    kept.sort()
    tolerance = STRETCH_TOLERANCE if limit is None else max(STRETCH_TOLERANCE, limit)
    while kept:
        best = None
        for k in kept:
            trial = _sliced_stretch(base, sorted(forced + [c for c in kept if c != k]), cache, layouts)
            if trial is None or any(s > tolerance and s > current[fid] + RISE for fid, s in trial.items()):
                continue
            total = sum(trial.values())
            if best is None or total < best[0]:
                best = (total, k, trial)
        if best is None:
            break
        kept.remove(best[1])
        current = best[2]
    return kept
