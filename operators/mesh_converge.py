"""Converge: weld pairs of selected edges together at their computed
intersection point.

Two entry paths, one apply path:

* ``interactive=False`` (or invoked outside a 3D viewport) -->
  ``execute`` resolves the strategy and welds immediately.
* ``interactive=True`` --> a modal preview. Candidates are computed
  ONCE at invoke; the wheel or ``S`` cycles the strategy and the
  overlay redraws; ``Shift+LMB`` extends the edge selection (which
  recomputes the candidates); confirm runs the very same
  ``_apply_converge`` the direct path uses. The preview never touches
  geometry, so cancel only has to put the invoke-time selection back.

All candidate-pair math lives in ``utils.converge_core`` (pure Python,
no bpy). This module is the bmesh-aware layer that resolves each
``Candidate`` into an actual vert move + weld.
"""
import bpy
import bmesh
from mathutils import Vector
from bpy.props import EnumProperty, BoolProperty

from ..ui.draw import primitives as draw_prim, draw_scope
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)
from ..ui.hud import text as hud_text
from ..utils.converge_core import candidate_pairs, STRATEGIES, TOL


# One color per resolved pair, cycled by pair index. Deliberately not
# theme roles: the point of the overlay is telling pairs apart, so the
# palette has to stay distinguishable regardless of theme tweaks.
PAIR_PALETTE = (
    (1.00, 0.42, 0.22, 1.0),   # orange
    (0.28, 0.78, 1.00, 1.0),   # cyan
    (0.55, 0.95, 0.35, 1.0),   # green
    (1.00, 0.85, 0.25, 1.0),   # amber
    (0.78, 0.52, 1.00, 1.0),   # violet
    (1.00, 0.50, 0.78, 1.0),   # pink
)

# Ghost (vert --> target) lines are drawn as this many dash slots, each
# 60% filled. Cheap stand-in for a real stipple shader.
GHOST_DASHES = 9

# Draw handles registered by any live instance of this operator. A
# blinker/addon reload can free the operator RNA while its handlers are
# still attached to the viewport; `_purge_handles` clears those before a
# new modal starts (same guard `mesh_straight_bevel` uses).
_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


def _dashed(a, b, dashes=GHOST_DASHES):
    """Flat list of world-space points -- consecutive pairs are the dash
    segments of a dashed line from ``a`` to ``b`` (for ``edges_3d``).

    Empty when the two points coincide (a coplanar pair whose moving
    vert already sits on its target has nothing to preview).
    """
    if (b - a).length < 1e-9:
        return []
    dashes = max(1, int(dashes))
    out = []
    for k in range(dashes):
        t0 = k / dashes
        out.append(a.lerp(b, t0))
        out.append(a.lerp(b, t0 + 0.6 / dashes))
    return out


class IOPS_OT_mesh_converge(bpy.types.Operator):
    """Weld pairs of selected edges together at their intersection point"""

    bl_idname = "iops.mesh_converge"
    bl_label = "Converge"
    bl_description = (
        "Find crossing/coplanar pairs among the selected edges and weld "
        "each pair's nearest endpoints together at the pair's "
        "intersection point"
    )
    bl_options = {"REGISTER", "UNDO"}

    strategy: EnumProperty(
        name="Strategy",
        description="How to resolve which candidate pairs get welded",
        items=[
            ("GREEDY", "Greedy",
             "Nearest pairs first; each edge is used in at most one weld"),
            ("ALL", "All",
             "Collapse every selected edge into the convergence point of "
             "the two rails: the loop's end edges, or the first two edges "
             "in selection history"),
            ("ORDER", "Order",
             "Pair edges by selection order (1st+2nd, 3rd+4th, ...)"),
        ],
        default="GREEDY",
    )
    interactive: BoolProperty(
        name="Interactive",
        description="Run the modal preview before applying (adjust strategy live)",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ------------------------------------------------------------------
    # Invoke / execute
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        area = context.area
        if not self.interactive or area is None or area.type != "VIEW_3D":
            # No viewport to draw the preview in (or preview switched
            # off) -- behave exactly like the direct-execute path.
            return self.execute(context)
        return self._invoke_modal(context, event)

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Active object is not a mesh")
            return {"CANCELLED"}

        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        selected = [e for e in bm.edges if e.select]
        if len(selected) < 2:
            self.report({"WARNING"}, "Select at least 2 edges")
            return {"CANCELLED"}

        edges_co = [(tuple(e.verts[0].co), tuple(e.verts[1].co)) for e in selected]
        candidates = candidate_pairs(edges_co, tol=TOL)
        if not candidates:
            self.report({"WARNING"}, "No valid candidate pairs among selected edges")
            return {"CANCELLED"}

        pairs, strategy_used = self._resolve_pairs(
            bm, selected, candidates, edges_co)
        if not pairs:
            self.report({"WARNING"}, "No pairs resolved by strategy")
            return {"CANCELLED"}

        error = self._apply_and_flush(bm, me, selected, pairs)
        self.strategy = strategy_used
        if error is not None:
            self.report({"ERROR"},
                        f"Converge: apply stopped partway -- {error}")
        return {"FINISHED"}

    # ------------------------------------------------------------------
    # Strategy resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _history_indices(bm, selected):
        """Selection-history edge indices, mapped into ``selected``'s
        index space (the space ``Candidate.i`` / ``.j`` live in)."""
        index_of = {e: i for i, e in enumerate(selected)}
        return [
            index_of[e] for e in bm.select_history
            if isinstance(e, bmesh.types.BMEdge) and e in index_of
        ]

    def _resolve_pairs(self, bm, selected, candidates, edges_co):
        """Run ``self.strategy`` over ``candidates``.

        Returns ``(pairs, strategy_used)``. ORDER falls back to GREEDY
        (with a warning report) when selection history holds fewer than
        two of the currently-selected edges; ALL falls back when no
        rails can be determined or they don't converge.
        """
        strategies = dict(STRATEGIES)
        strategy = self.strategy
        history_idx = self._history_indices(bm, selected)
        if strategy == "ALL":
            pairs = strategies["ALL"](candidates, history_idx, edges_co)
            if pairs:
                return pairs, "ALL"
            self.report(
                {"WARNING"},
                "ALL: no converging rails (loop ends / first two edges in "
                "selection history); falling back to GREEDY",
            )
            strategy = "GREEDY"
        if strategy == "ORDER":
            if len(history_idx) < 2:
                self.report(
                    {"WARNING"},
                    "ORDER needs at least 2 selected edges in selection "
                    "history; falling back to GREEDY",
                )
                strategy = "GREEDY"
            else:
                return strategies["ORDER"](candidates, history_idx), "ORDER"
        return strategies[strategy](candidates), strategy

    @staticmethod
    def _select_result(bm, result_verts):
        """Replace the selection with the welded verts."""
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = False
        for v in result_verts:
            v.select_set(True)
        bm.select_flush_mode()

    # ------------------------------------------------------------------
    # Modal preview
    # ------------------------------------------------------------------

    def _invoke_modal(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Active object is not a mesh")
            return {"CANCELLED"}

        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        selected = [e for e in bm.edges if e.select]
        if len(selected) < 2:
            self.report({"WARNING"}, "Select at least 2 edges")
            return {"CANCELLED"}

        # Modal state. `_sel_edges` is the index space the Candidates
        # were computed in, so confirm must pass this exact list to
        # `_apply_converge` -- not a freshly-gathered selection. It is
        # re-read (together with every derived list) only on an explicit
        # Shift+LMB add, never on mouse move.
        self._obj = obj
        self._bm = bm
        # Kept for the `view3d.select` context override in `_pick_edge`.
        self._area = context.area
        self._region = context.region
        # Invoke-time selection, so cancel can put it back after any
        # Shift+LMB adds. `_sel_dirty` stays False until an add actually
        # changes the selection, so a plain cancel -- or a cancel after
        # nothing but miss-clicks -- touches nothing at all.
        self._snap_edges, self._snap_history = \
            self._selection_signature(bm)
        self._sel_dirty = False
        self._keys = []
        self._key_idx = 0
        self._pairs = []
        self._candidates = []
        self._edges_co = []
        self._history_idx = []
        self._read_selection(bm)
        if not self._candidates:
            # Drop the bmesh/BMElement references again: Blender keeps
            # this operator instance around for the redo stack.
            self._release_state()
            self.report({"WARNING"},
                        "No valid candidate pairs among selected edges")
            return {"CANCELLED"}
        self._handle_view = None
        self._handle_text = None

        _purge_handles()

        self._hud = HUDOverlay("converge")
        self._hud.title = "Converge"
        self._hud.bind_region(context.region)
        self._hud.add_param(HUDParam(
            "Strategy", lambda: self._current_key(), "str"))
        self._hud.add_param(HUDParam(
            "Pairs", lambda: len(self._pairs), "int"))
        self._hud.add_param(HUDParam(
            "Candidates", lambda: len(self._candidates), "int"))
        self._help = HelpOverlay("converge")
        self._help.add_section(HUDSection("Converge", [
            HUDItem("Cycle strategy", "Wheel / S", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Add edge",       "Shift+LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",        "LMB / Enter / Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",         "Esc / RMB",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Navigate",       "MMB",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H",       ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # Two handlers: world-space preview geometry in POST_VIEW, HUD /
        # help text in POST_PIXEL. Both are torn down by `_finish`, which
        # every exit route goes through.
        self._handle_view = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_geometry, (context,),
            "WINDOW", "POST_VIEW")
        _ACTIVE_HANDLES.add(self._handle_view)
        self._handle_text = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_text, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle_text)

        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    @staticmethod
    def _selection_signature(bm):
        """``(selected_edges, history_edges)`` as **lookup-table
        positions** -- the snapshot cancel restores from, and the value
        used to tell whether a pick changed anything at all.

        Positions, not ``BMEdge.index``: ``ensure_lookup_table()`` builds
        the table `bm.edges[i]` indexes, but it does NOT refresh the
        index layer -- that needs ``index_update()``. A dirty index layer
        (routine after any mid-session topology edit) would therefore
        make ``bm.edges[e.index]`` resolve to a *different* edge than the
        one snapshotted, and cancel would restore the wrong edges.
        Enumerating the sequence matches ``bm.edges[i]`` by construction
        (the lookup table is filled in iteration order), so no index
        layer is involved.

        The history tuple keeps its order -- it is what ORDER pairs on.
        """
        pos = {e: i for i, e in enumerate(bm.edges)}
        selected = frozenset(i for e, i in pos.items() if e.select)
        history = tuple(pos[e] for e in bm.select_history
                        if isinstance(e, bmesh.types.BMEdge) and e in pos)
        return selected, history

    def _read_selection(self, bm):
        """Re-read the edge selection and rebuild every derived list.

        The selection is the source of truth. Called once at invoke and
        again after each Shift+LMB add; nothing else in the modal
        touches these lists.

        Keeps the currently-previewed strategy key when it is still
        available and falls back to the first available one otherwise --
        ORDER can appear *or* disappear here, because an add grows the
        selection history.

        A selection that dropped below 2 edges, or that yields no
        candidate pairs, is not an error: the lists simply come out empty
        and the modal stays alive showing 0 pairs.
        """
        selected = [e for e in bm.edges if e.select]
        if len(selected) >= 2:
            edges_co = [(tuple(e.verts[0].co), tuple(e.verts[1].co))
                        for e in selected]
            candidates = candidate_pairs(edges_co, tol=TOL)
        else:
            edges_co = []
            candidates = []

        self._sel_edges = selected
        self._edges_co = edges_co
        self._candidates = candidates
        self._history_idx = self._history_indices(bm, selected)
        # ORDER is only offered when the history can actually pair edges,
        # ALL only when converging rails exist; cycling skips them
        # entirely rather than showing an empty preview.
        want = self._keys[self._key_idx] if self._keys else self.strategy
        self._keys = [k for k, _ in STRATEGIES
                      if k != "ORDER" or len(self._history_idx) >= 2]
        if not self._pairs_for("ALL"):
            self._keys.remove("ALL")
        self._key_idx = self._keys.index(want) if want in self._keys else 0
        self._pairs = self._pairs_for(self._current_key())

    def _current_key(self):
        return self._keys[self._key_idx]

    def _pairs_for(self, key):
        """Resolve ``key`` over the frozen candidate list."""
        strategies = dict(STRATEGIES)
        if key == "ORDER":
            return strategies["ORDER"](self._candidates, self._history_idx)
        if key == "ALL":
            return strategies["ALL"](self._candidates, self._history_idx,
                                     self._edges_co)
        return strategies[key](self._candidates)

    def _cycle(self, context, delta):
        if len(self._keys) > 1:
            self._key_idx = (self._key_idx + delta) % len(self._keys)
            self._pairs = self._pairs_for(self._current_key())
        context.workspace.status_text_set(self._status_text())
        if context.area:
            context.area.tag_redraw()

    def _status_text(self):
        return (
            f"Converge: {self._current_key()} | "
            f"pairs {len(self._pairs)} of {len(self._candidates)} candidates | "
            "[Wheel/S] cycle strategy | [Shift+LMB] add edge | "
            "[LMB/Enter/Space] confirm | [Esc/RMB] cancel"
        )

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # A bmesh element (or the operator's own RNA) was freed
            # mid-modal -- undo, addon reload, or another op editing the
            # mesh. Tear the handlers down so the viewport isn't left
            # with a dangling callback.
            self._finish(context)
            self.report({"WARNING"},
                        "converge: bmesh data became invalid -- cancelled")
            return {"CANCELLED"}
        except Exception:
            # Any other failure would also leave the handlers stuck.
            self._finish(context)
            raise

    def _modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        # Wheel is the strategy cycler, so it never reaches the viewport
        # zoom -- MMB / NDOF / trackpad carry navigation instead.
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.value == "PRESS":
                self._cycle(context, 1 if event.type == "WHEELUPMOUSE" else -1)
            return {"RUNNING_MODAL"}

        if (event.type == "MIDDLEMOUSE"
                or event.type.startswith("NDOF")
                or event.type.startswith("TRACKPAD")):
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            # Nothing is recomputed on mouse move: the selection and the
            # candidate list only change on an explicit Shift+LMB add.
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type == "S":
                self._cycle(context, 1)
                return {"RUNNING_MODAL"}

            # Shift+LMB extends the selection instead of confirming.
            # Checked before the confirm branch, and only for a bare
            # Shift so Ctrl/Alt/OS-key combos keep falling through to
            # their existing meaning (none today -- they stay inert
            # rather than silently picking).
            if (event.type == "LEFTMOUSE" and event.shift
                    and not (event.ctrl or event.alt or event.oskey)):
                return self._pick_edge(context, event)

            # Bare LMB confirms. Ctrl/Alt/OS-key combos fall through to
            # here too, so the gate above (not event.ctrl/alt/oskey)
            # keeps them inert instead of silently confirming.
            if (event.type == "LEFTMOUSE"
                    and not (event.ctrl or event.alt or event.oskey)):
                return self._confirm(context)

            if event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
                return self._confirm(context)

            if event.type in {"RIGHTMOUSE", "ESC"}:
                # The preview never edited geometry; the only thing to
                # undo is any Shift+LMB selection change.
                return self._cancel_modal(context)

        return {"RUNNING_MODAL"}

    def _pick_edge(self, context, event):
        """Shift+LMB: extend the edge selection by one click, then
        recompute candidates/pairs from the new selection.

        Picking is delegated to Blender's own ``view3d.select`` so
        click-behaviour (nearest element, occlusion, x-ray, select mode)
        matches normal edit mode exactly instead of being reimplemented
        as a ray-cast. A miss, or a re-click on an already-selected
        element, is a harmless recompute -- never an error.
        """
        loc = (event.mouse_region_x, event.mouse_region_y)
        before = self._selection_signature(self._bm)
        try:
            bpy.ops.view3d.select(extend=True, location=loc)
        except RuntimeError:
            # A wrong-context poll failure is the only expected failure
            # here (the modal normally already runs in the VIEW_3D whose
            # region the mouse coords belong to). Retry explicitly bound
            # to the invoke-time area/region.
            area = getattr(self, "_area", None)
            region = getattr(self, "_region", None)
            if area is None or region is None:
                return {"RUNNING_MODAL"}
            try:
                with context.temp_override(area=area, region=region):
                    bpy.ops.view3d.select(extend=True, location=loc)
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Converge: pick failed -- {exc}")
                return {"RUNNING_MODAL"}

        # `view3d.select` can hand back a different edit-mesh bmesh, so
        # re-fetch the wrapper rather than reusing `self._bm`.
        bm = bmesh.from_edit_mesh(self._obj.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        # Only arm the cancel-restore once the pick genuinely moved the
        # selection. A miss on empty space, or a re-pick of an edge that
        # is already included, leaves the signature identical -- and must
        # not make cancel rewrite the selection it never changed.
        if self._selection_signature(bm) != before:
            self._sel_dirty = True
        self._bm = bm
        self._read_selection(bm)
        context.workspace.status_text_set(self._status_text())
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _confirm(self, context):
        """Apply the currently-previewed strategy through the same
        ``_apply_converge`` call the direct-execute path uses."""
        pairs = list(self._pairs)
        obj = self._obj
        bm = self._bm
        edges = self._sel_edges
        # Write the cycled strategy back so the redo panel (and a later
        # re-execute) reflects what the user actually confirmed.
        self.strategy = self._current_key()
        if not pairs:
            self._finish(context)
            self.report({"WARNING"}, "No pairs resolved by strategy")
            return {"CANCELLED"}

        error = self._apply_and_flush(bm, obj.data, edges, pairs)
        self._finish(context)
        if error is not None:
            self.report({"ERROR"},
                        f"Converge: apply stopped partway -- {error}")
        return {"FINISHED"}

    def _cancel_modal(self, context):
        """User cancel: put the invoke-time selection back, then tear
        down. Returns the modal return value so `_modal` can `return`
        this directly."""
        self._restore_selection()
        self._finish(context)
        return {"CANCELLED"}

    def cancel(self, context):
        """Blender-initiated teardown (area closed, file load, another
        op cancelling this one) -- and also called by Blender right after
        `_modal` returns CANCELLED. Both `_restore_selection` and
        `_finish` are idempotent, so the second pass is a no-op."""
        self._cancel_modal(context)

    def _restore_selection(self):
        """Restore the invoke-time edge selection (cancel path only).

        No-op unless a Shift+LMB add actually changed the selection, so a
        plain cancel of an untouched preview -- or one after nothing but
        miss-clicks -- writes nothing to the mesh.

        The snapshot is lookup-table *positions*, not BMEdge references
        (the picking operator can hand back a different bmesh) and not
        ``.index`` (see `_selection_signature`). Only edges are restored
        to the selection history (verts/faces in the history are dropped)
        -- the history matters here purely for ORDER pairing.

        The restore has to be *exact*, which rules out a blanket
        ``select_flush(True)``: that selects every edge whose two verts
        are selected and every face whose verts all are, so two opposite
        edges of a quad -- a canonical Converge selection -- would come
        back with the other two edges and the face lit up as well. Same
        trap and same fix as `mesh_selection_sets._bm_set_exact_selection`:
        clear everything, select exactly the snapshot, and let the
        per-element downward flush plus one `select_flush_mode()` settle
        mode consistency.
        """
        if not getattr(self, "_sel_dirty", False):
            return
        # One shot: `cancel()` may run this again after `_modal` already
        # returned CANCELLED.
        self._sel_dirty = False
        obj = getattr(self, "_obj", None)
        if obj is None:
            return
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            for v in bm.verts:
                v.select = False
            for e in bm.edges:
                e.select = False
            for f in bm.faces:
                f.select = False
            bm.select_history.clear()
            n = len(bm.edges)
            for i in self._snap_edges:
                if 0 <= i < n:
                    # `select_set` flushes DOWNWARD only (the edge drags
                    # its two verts along), which is what we want.
                    bm.edges[i].select_set(True)
            for i in self._snap_history:
                if 0 <= i < n:
                    bm.select_history.add(bm.edges[i])
            bm.select_history.validate()
            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                                   destructive=False)
        except (ReferenceError, AttributeError, RuntimeError, IndexError):
            # The object/mesh went away mid-cancel (file load, area
            # closed, an undo step) -- nothing left to restore.
            pass

    def _finish(self, context):
        """Single teardown for every exit route: confirm, cancel,
        exception, and Blender-initiated cancel."""
        for attr in ("_handle_view", "_handle_text"):
            h = getattr(self, attr, None)
            if h is not None:
                _ACTIVE_HANDLES.discard(h)
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError):
                    pass
                setattr(self, attr, None)
        try:
            context.workspace.status_text_set(None)
        except AttributeError:
            pass
        if context.area:
            context.area.tag_redraw()
        self._release_state()

    def _release_state(self):
        """Drop the bmesh wrapper and every BMElement / bpy-struct
        reference. Blender keeps finished operator instances around for
        the redo stack; a later addon reload would otherwise dealloc a
        stale bmesh wrapper against freed mesh data and crash.

        Also used by `_invoke_modal` when it bails out after the state
        was already built."""
        self._bm = None
        self._obj = None
        self._area = None
        self._region = None
        self._sel_edges = []
        self._candidates = []
        self._edges_co = []
        self._pairs = []
        self._snap_edges = frozenset()
        self._snap_history = ()
        self._sel_dirty = False
        self._hud = None
        self._help = None

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _draw_geometry(self, context):
        """POST_VIEW: one dot per pair at its merge point P, plus dashed
        ghost lines from each moving vert to its target (mvert1 -> p1,
        mvert2 -> p2). Candidates are plain float tuples, so this path
        never dereferences bmesh data."""
        if context.region_data is None:
            return
        # Guard ONLY the state reads (same narrowing as
        # `mesh_shear._draw_callback`): a blinker/addon reload can free
        # the operator RNA while this handler is still registered, and
        # `self._obj` / `matrix_world` are the only touches here that
        # raise once it is gone. Everything below stays outside the
        # guard so a genuine bug in the overlay code tracebacks to the
        # console instead of silently deleting both handlers mid-modal.
        try:
            obj = self._obj
            pairs = self._pairs
            if obj is None or not pairs:
                return
            mw = obj.matrix_world
        except (ReferenceError, AttributeError):
            # Operator RNA freed (blinker reload) or state already torn
            # down while a redraw was still queued.
            _purge_handles()
            return

        dots = {}
        ghosts = {}
        for n, c in enumerate(pairs):
            col = PAIR_PALETTE[n % len(PAIR_PALETTE)]
            dots.setdefault(col, []).append(mw @ Vector(c.P))
            seg = ghosts.setdefault(col, [])
            seg.extend(_dashed(mw @ Vector(c.mvert1), mw @ Vector(c.p1)))
            seg.extend(_dashed(mw @ Vector(c.mvert2), mw @ Vector(c.p2)))
        # POST_VIEW runs mid-pipeline, so restore point size too --
        # `primitives.points` sets it globally and Blender's own
        # vertex drawing would inherit a fat size otherwise.
        with draw_scope(blend="ALPHA", depth="NONE", point_size=1.0):
            for col, segs in ghosts.items():
                if segs:
                    draw_prim.edges_3d(
                        segs, color=(col[0], col[1], col[2], 0.7),
                        context=context)
            for col, pts in dots.items():
                draw_prim.points(pts, color=col, size=11.0,
                                 context=context)

    def _draw_text(self, context):
        """POST_PIXEL: HUD + help. Wrapped in `hud_text.isolated` so the
        blf SHADOW bit never leaks onto Blender's shared font 0 (which
        otherwise flickers the outliner)."""
        # As in `_draw_geometry`: the guard covers only the reads off
        # `self` (freed RNA / already-torn-down state). `get_theme` and
        # the two `draw()` calls are deliberately outside it, so an
        # AttributeError inside the HUD/help drawing code surfaces as a
        # console traceback rather than a silently vanished overlay.
        try:
            hud = self._hud
            helpo = self._help
            if hud is None and helpo is None:
                return
            last_event = getattr(self, "_last_event", None)
            header = None
            if hud is not None:
                header = (
                    f"Strategy: {self._current_key()}",
                    f"Pairs: {len(self._pairs)} / {len(self._candidates)}",
                )
        except (ReferenceError, AttributeError):
            _purge_handles()
            return

        theme = get_theme(context)
        with hud_text.isolated(theme):
            if helpo is not None:
                helpo.draw(context, last_event)
            if hud is not None:
                hud.set_header(*header)
                hud.draw(context, last_event)

    # ------------------------------------------------------------------
    # Apply (reusable -- both `execute` and the modal confirm call this)
    # ------------------------------------------------------------------

    def _apply_and_flush(self, bm, mesh, edges, pairs):
        """Apply ``pairs``, select the result, and flush the bmesh --
        flushing even when the apply raises partway.

        ``bmesh.ops.pointmerge`` runs once per pair, so a failure on
        pair N leaves the first N-1 merges already in the bmesh. If that
        exception escapes the operator, Blender turns it into
        ``CANCELLED`` and pushes no undo step -- yet the applied merges
        are still there and surface at the next flush, with no undo
        entry to reverse them. Flushing in ``finally`` and letting the
        caller return ``FINISHED`` puts whatever was applied inside this
        operator's undo step instead.

        Returns the exception that stopped the apply, or ``None``. The
        caller reports it -- it is never silently swallowed.
        """
        try:
            result_verts = self._apply_converge(bm, edges, pairs)
            self._select_result(bm, result_verts)
        except Exception as exc:
            return exc
        finally:
            bmesh.update_edit_mesh(mesh)
        return None

    def _apply_converge(self, bm, edges, pairs):
        """Apply resolved ``Candidate`` pairs as vert moves + bmesh welds.

        ``edges`` is the list of ``BMEdge`` in the same order/index space
        the ``Candidate``\\ s were computed from (``candidate.i`` /
        ``candidate.j`` index into this list). ``pairs`` is the strategy-
        resolved list of Candidates to apply, in the order to apply them.

        Handles vert-identity chaining: with the ``ALL`` strategy the
        same edge (and so the same underlying vert) can be consumed by
        more than one pair. A vert already merged away by an earlier
        pair in this same call is looked up through an alias map to find
        the vert that survived that merge, and later pairs weld against
        that survivor instead of a stale/invalid reference.

        Returns the ``set`` of surviving ``BMVert`` -- callers select
        these as the operator's resulting selection.
        """
        # Capture every (edge, moving-end) vert reference up front, before
        # any pointmerge runs -- Candidate.moving_end_i/j index into this
        # snapshot, not into the live (post-merge) bmesh.
        slots = [[e.verts[0], e.verts[1]] for e in edges]
        alias = {}

        def resolve(v):
            while v in alias:
                v = alias[v]
            return v

        result = set()
        for c in pairs:
            v1 = resolve(slots[c.i][c.moving_end_i])
            v2 = resolve(slots[c.j][c.moving_end_j])
            if v1 is v2 or not v1.is_valid or not v2.is_valid:
                continue
            v1.co = Vector(c.p1)
            v2.co = Vector(c.p2)
            bmesh.ops.pointmerge(bm, verts=[v1, v2], merge_co=Vector(c.P))
            survivor, dead = (v1, v2) if v1.is_valid else (v2, v1)
            alias[dead] = survivor
            result.discard(dead)
            result.add(survivor)
        return {v for v in result if v.is_valid}
