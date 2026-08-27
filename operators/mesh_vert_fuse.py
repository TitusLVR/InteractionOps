"""Vert Fuse: close T-junction gaps -- selected verts that lie on or
near the interior of another edge get welded into it.

Two entry paths, one apply path:

* ``interactive=False`` (or invoked outside a 3D viewport) -->
  ``execute`` resolves the candidates and fuses immediately.
* ``interactive=True`` --> a modal preview. Candidates are computed
  ONCE at invoke; the wheel or ``S`` cycles the merge position and the
  overlay redraws; ``Ctrl+Wheel`` doubles/halves the tolerance (which
  recomputes the candidates); ``LMB`` adds a pick to the vert selection
  and ``Ctrl+LMB`` removes one (either recomputes the candidates);
  ``A`` auto-detects T-junction verts mesh-wide and extends the
  selection with them; confirm (``Enter`` / ``Space``) runs the very
  same ``_apply_fuse`` the direct path uses. The preview never touches
  geometry, so cancel only has to put the invoke-time selection back.

All candidate math lives in ``utils.vert_fuse_core`` (pure Python, no
bpy). This module is the bmesh-aware layer that resolves each
``Candidate`` into an actual edge split + pointmerge.
"""
import bpy
import bmesh
from mathutils import Vector
from bpy.props import EnumProperty, BoolProperty, FloatProperty

from ..ui.draw import primitives as draw_prim, draw_scope
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)
from ..ui.hud import text as hud_text
from ..utils.vert_fuse_core import (fuse_candidates, MERGE_POSITIONS, TOL,
                                    EPS)


# One color per candidate, cycled by candidate index. Deliberately not
# theme roles: the point of the overlay is telling candidates apart, so
# the palette has to stay distinguishable regardless of theme tweaks.
FUSE_PALETTE = (
    (1.00, 0.42, 0.22, 1.0),   # orange
    (0.28, 0.78, 1.00, 1.0),   # cyan
    (0.55, 0.95, 0.35, 1.0),   # green
    (1.00, 0.85, 0.25, 1.0),   # amber
    (0.78, 0.52, 1.00, 1.0),   # violet
    (1.00, 0.50, 0.78, 1.0),   # pink
)

# Ghost (vert --> merge point) lines are drawn as this many dash slots,
# each 60% filled. Cheap stand-in for a real stipple shader.
GHOST_DASHES = 9

# Tolerance clamp for the Ctrl+Wheel adjustment: below 1e-6 nothing
# visible qualifies anyway; above 1.0 the op degenerates into welding
# arbitrary geometry.
TOL_MIN = 1e-6
TOL_MAX = 1.0

# Draw handles registered by any live instance of this operator. A
# blinker/addon reload can free the operator RNA while its handlers are
# still attached to the viewport; `_purge_handles` clears those before a
# new modal starts (same guard `mesh_converge` uses).
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

    Empty when the two points coincide (VERT merge position: the merge
    point IS the vert, so there is nothing to ghost).
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


def _island_ids(bm):
    """``(ids, pos)``: mesh-island id per vert as a list parallel to
    ``enumerate(bm.verts)``, plus the ``vert -> position`` map used to
    build it (callers need the same map to look verts up).

    Plain union-find over ``bm.verts`` connected by ``bm.edges``; an
    edge's island is by construction the island of either endpoint. Ids
    are root positions -- opaque labels, only equality matters.
    """
    pos = {v: i for i, v in enumerate(bm.verts)}
    parent = list(range(len(pos)))

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    for e in bm.edges:
        ra = find(pos[e.verts[0]])
        rb = find(pos[e.verts[1]])
        if ra != rb:
            parent[rb] = ra
    return [find(i) for i in range(len(parent))], pos


class IOPS_OT_mesh_vert_fuse(bpy.types.Operator):
    """Weld selected verts into the nearby edges they should touch"""

    bl_idname = "iops.mesh_vert_fuse"
    bl_label = "Vert Fuse"
    bl_description = (
        "Find selected verts lying on or near the interior of another "
        "edge, split that edge at the vert's projection and weld the "
        "vert into it (closes T-junction gaps)"
    )
    bl_options = {"REGISTER", "UNDO"}

    merge_position: EnumProperty(
        name="Merge Position",
        description="Where the vert and the split point meet",
        items=[
            ("PROJECT", "Project",
             "Merge at the projection point -- the target edge stays straight"),
            ("VERT", "Vert",
             "Merge at the vert's position -- the target edge bends to it"),
            ("MID", "Mid",
             "Merge halfway between the vert and its projection"),
        ],
        default="PROJECT",
    )
    tolerance: FloatProperty(
        name="Tolerance",
        description="Max gap between a vert and the edge it fuses into",
        default=TOL,
        min=0.0,
        soft_max=0.1,
        subtype="DISTANCE",
        precision=4,
    )
    interactive: BoolProperty(
        name="Interactive",
        description="Run the modal preview before applying (adjust merge position live)",
        default=True,
    )
    cross_island: BoolProperty(
        name="Cross Island",
        description="Let the A auto-detect scan fuse verts into edges of "
                    "a different mesh island (manual picks always may)",
        default=False,
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

        sel_verts, all_edges, candidates = self._gather(bm)
        if not sel_verts:
            self.report({"WARNING"}, "Select at least 1 vertex")
            return {"CANCELLED"}
        if not candidates:
            self.report({"WARNING"},
                        "No edges within tolerance of the selected verts")
            return {"CANCELLED"}

        error = self._apply_and_flush(bm, me, sel_verts, all_edges,
                                      candidates)
        if error is not None:
            self.report({"ERROR"},
                        f"Vert Fuse: apply stopped partway -- {error}")
        return {"FINISHED"}

    # ------------------------------------------------------------------
    # Candidate gathering (shared by both paths)
    # ------------------------------------------------------------------

    def _gather(self, bm):
        """``(sel_verts, all_edges, candidates)`` from the current
        selection. Selected verts are the movers; targets are ALL mesh
        edges except each vert's own linked edges (the exclude map) --
        the interior/endpoint rules in the core do the rest.
        Candidates index into ``sel_verts`` / ``all_edges``."""
        sel_verts = [v for v in bm.verts if v.select]
        all_edges = list(bm.edges)
        if not sel_verts:
            return [], all_edges, []
        edge_pos = {e: i for i, e in enumerate(all_edges)}
        verts_co = [tuple(v.co) for v in sel_verts]
        edges_co = [(tuple(e.verts[0].co), tuple(e.verts[1].co))
                    for e in all_edges]
        exclude = {i: {edge_pos[e] for e in v.link_edges}
                   for i, v in enumerate(sel_verts)}
        candidates = fuse_candidates(verts_co, edges_co,
                                     tol=self.tolerance, exclude=exclude)
        return sel_verts, all_edges, candidates

    @staticmethod
    def _select_result(bm, result_verts):
        """Replace the selection with the fused verts."""
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

        if not any(v.select for v in bm.verts):
            self.report({"WARNING"}, "Select at least 1 vertex")
            return {"CANCELLED"}

        # Modal state. `_sel_verts` / `_all_edges` are the index spaces
        # the Candidates were computed in, so confirm must pass these
        # exact lists to `_apply_fuse` -- not a freshly-gathered
        # selection. They are re-read (together with every derived list)
        # only on an explicit pick (LMB add / Ctrl+LMB remove), an A
        # auto-detect, or a tolerance change, never on mouse move.
        self._obj = obj
        self._bm = bm
        # Kept for the `view3d.select` context override in `_pick_vert`.
        self._area = context.area
        self._region = context.region
        # Invoke-time selection, so cancel can put it back after any
        # picks or A-scans. `_sel_dirty` stays False until one actually
        # changes the selection, so a plain cancel -- or a cancel after
        # nothing but miss-clicks -- touches nothing at all.
        self._snapshot = self._selection_signature(bm)
        self._sel_dirty = False
        self._keys = [k for k, _ in MERGE_POSITIONS]
        self._key_idx = self._keys.index(self.merge_position)
        self._tol = self.tolerance
        self._candidates = []
        self._ghosts = []
        self._read_selection(bm)
        if not self._candidates:
            # Drop the bmesh/BMElement references again: Blender keeps
            # this operator instance around for the redo stack.
            self._release_state()
            self.report({"WARNING"},
                        "No edges within tolerance of the selected verts")
            return {"CANCELLED"}
        self._handle_view = None
        self._handle_text = None

        _purge_handles()

        self._hud = HUDOverlay("vert_fuse")
        self._hud.title = "Vert Fuse"
        self._hud.bind_region(context.region)
        self._hud.add_param(HUDParam(
            "Position", lambda: self._current_key(), "str"))
        self._hud.add_param(HUDParam(
            "Candidates", lambda: len(self._candidates), "int"))
        self._hud.add_param(HUDParam(
            "Tolerance", lambda: self._tol, "float", fmt="{:g}"))
        self._hud.add_param(HUDParam(
            "Island Filter",
            lambda: "OFF" if self.cross_island else "ON", "str"))
        self._help = HelpOverlay("vert_fuse")
        self._help.add_section(HUDSection("Vert Fuse", [
            HUDItem("Cycle position", "Wheel / S", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Tolerance x2 / /2", "Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Add vert",       "LMB",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Remove vert",    "Ctrl+LMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Auto detect",    "A",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",        "Enter / Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
        """``(verts, edges, faces)`` selection as frozensets of
        **lookup-table positions** -- the snapshot cancel restores from,
        and the value used to tell whether a pick changed anything.

        Positions, not ``.index``: ``ensure_lookup_table()`` builds the
        table ``bm.verts[i]`` indexes, but it does NOT refresh the index
        layer -- that needs ``index_update()``. A dirty index layer
        (routine after any mid-session topology edit) would make
        ``bm.verts[v.index]`` resolve to a *different* vert than the one
        snapshotted, and cancel would restore the wrong verts.
        Enumerating the sequences matches ``bm.verts[i]`` by
        construction (the lookup table is filled in iteration order).

        All three element domains are snapshotted so the restore is
        exact in any select mode -- no flush guessing (same trap and
        same fix as `mesh_selection_sets._bm_set_exact_selection`).
        """
        return (
            frozenset(i for i, v in enumerate(bm.verts) if v.select),
            frozenset(i for i, e in enumerate(bm.edges) if e.select),
            frozenset(i for i, f in enumerate(bm.faces) if f.select),
        )

    def _read_selection(self, bm):
        """Re-read the vert selection and rebuild every derived list.

        The selection is the source of truth. Called once at invoke and
        again after each pick, A-scan, or tolerance change; nothing else
        in the modal touches these lists.

        Deliberately island-UNFILTERED: manual / selection-driven
        gathering may cross islands -- only the A-scan filters. Known
        mild edge case: an auto-added vert's nearest edge may be
        cross-island and this gather will target it. A real gap either
        way; acceptable.

        A selection that yields no candidates is not an error here: the
        lists simply come out empty and the modal stays alive showing 0
        candidates.
        """
        self._sel_verts, self._all_edges, self._candidates = \
            self._gather(bm)
        self._rebuild_ghosts()

    def _rebuild_ghosts(self):
        """Per-candidate ``(vert_co, merge_co)`` plain-tuple pairs for
        the draw callback -- recomputed on merge-position cycle (the
        candidates themselves are unchanged by a cycle)."""
        merge = dict(MERGE_POSITIONS)[self._current_key()]
        verts_co = [tuple(v.co) for v in self._sel_verts]
        self._ghosts = [
            (verts_co[c.vert_index], merge(verts_co[c.vert_index], c.proj))
            for c in self._candidates
        ]

    def _current_key(self):
        return self._keys[self._key_idx]

    def _cycle(self, context, delta):
        """Wheel / S: next merge position. Candidates are untouched --
        only the merge points move."""
        self._key_idx = (self._key_idx + delta) % len(self._keys)
        self._rebuild_ghosts()
        context.workspace.status_text_set(self._status_text())
        if context.area:
            context.area.tag_redraw()

    def _adjust_tolerance(self, context, factor):
        """Ctrl+Wheel: scale the tolerance and recompute candidates."""
        self._tol = min(TOL_MAX, max(TOL_MIN, self._tol * factor))
        self.tolerance = self._tol
        self._read_selection(self._bm)
        context.workspace.status_text_set(self._status_text())
        if context.area:
            context.area.tag_redraw()

    def _status_text(self):
        return (
            f"Vert Fuse: {self._current_key()} | "
            f"candidates {len(self._candidates)} | "
            f"tol {self._tol:g} | "
            "[Wheel/S] cycle position | [Ctrl+Wheel] tolerance | "
            "[LMB] add vert | [Ctrl+LMB] remove vert | [A] auto detect | "
            "[Enter/Space] confirm | [Esc/RMB] cancel"
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
                        "vert fuse: bmesh data became invalid -- cancelled")
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

        # Wheel is claimed (position cycle / tolerance), so it never
        # reaches the viewport zoom -- MMB / NDOF / trackpad carry
        # navigation instead.
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.value == "PRESS":
                up = event.type == "WHEELUPMOUSE"
                if event.ctrl:
                    self._adjust_tolerance(context, 2.0 if up else 0.5)
                else:
                    self._cycle(context, 1 if up else -1)
            return {"RUNNING_MODAL"}

        if (event.type == "MIDDLEMOUSE"
                or event.type.startswith("NDOF")
                or event.type.startswith("TRACKPAD")):
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            # Nothing is recomputed on mouse move: the selection and the
            # candidate list only change on an explicit pick, an A-scan,
            # or a tolerance step.
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type == "S":
                self._cycle(context, 1)
                return {"RUNNING_MODAL"}

            if event.type == "A":
                self._auto_detect(context)
                return {"RUNNING_MODAL"}

            # Bare LMB adds a pick; Ctrl+LMB removes one. LMB never
            # confirms -- confirm is Enter/Space only, so the mouse is
            # free for picking. Any other modifier combo stays inert
            # rather than silently picking or confirming.
            if (event.type == "LEFTMOUSE"
                    and not (event.shift or event.ctrl or event.alt
                             or event.oskey)):
                return self._pick_vert(context, event)

            if (event.type == "LEFTMOUSE" and event.ctrl
                    and not (event.shift or event.alt or event.oskey)):
                return self._pick_vert(context, event, deselect=True)

            if event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
                return self._confirm(context)

            if event.type in {"RIGHTMOUSE", "ESC"}:
                # The preview never edited geometry; the only thing to
                # undo is any pick / auto-detect selection change.
                return self._cancel_modal(context)

        return {"RUNNING_MODAL"}

    def _pick_vert(self, context, event, deselect=False):
        """LMB: add one click to the selection; Ctrl+LMB (``deselect``):
        remove one. Either way candidates are recomputed from the new
        selection.

        Picking is delegated to Blender's own ``view3d.select`` so
        click-behaviour (nearest element, occlusion, x-ray, select mode)
        matches normal edit mode exactly instead of being reimplemented
        as a ray-cast. A miss, or a re-click on an element already in
        the target state, is a harmless recompute -- never an error.
        """
        loc = (event.mouse_region_x, event.mouse_region_y)
        kwargs = {"deselect": True} if deselect else {"extend": True}
        before = self._selection_signature(self._bm)
        try:
            bpy.ops.view3d.select(location=loc, **kwargs)
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
                    bpy.ops.view3d.select(location=loc, **kwargs)
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Vert Fuse: pick failed -- {exc}")
                return {"RUNNING_MODAL"}

        # `view3d.select` can hand back a different edit-mesh bmesh, so
        # re-fetch the wrapper rather than reusing `self._bm`.
        bm = bmesh.from_edit_mesh(self._obj.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        # Only arm the cancel-restore once the pick genuinely moved the
        # selection. A miss on empty space, or a pick of an element
        # already in the target state, leaves the signature identical --
        # and must not make cancel rewrite the selection it never
        # changed.
        if self._selection_signature(bm) != before:
            self._sel_dirty = True
        self._bm = bm
        self._read_selection(bm)
        context.workspace.status_text_set(self._status_text())
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _auto_detect(self, context):
        """A: scan the whole mesh for T-junction verts and EXTEND the
        selection with every one that found a fuse target -- never
        replace, so manual picks (including cross-island ones) survive.
        Pressing A again just re-scans (idempotent).

        Movers are the wire/boundary verts only: an unwelded T-junction
        vert always sits on a boundary loop or a wire edge (the face fan
        around a fully-interior vert is closed), so scanning just these
        keeps the pass cheap on dense meshes.

        Unlike the selection-driven gather, this scan applies the island
        rule: a vert never auto-fuses into an edge of a different mesh
        island unless ``cross_island`` lifts the filter.
        """
        bm = self._bm
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        movers = [v for v in bm.verts if v.is_wire or v.is_boundary]
        if movers:
            all_edges = list(bm.edges)
            edge_pos = {e: i for i, e in enumerate(all_edges)}
            verts_co = [tuple(v.co) for v in movers]
            edges_co = [(tuple(e.verts[0].co), tuple(e.verts[1].co))
                        for e in all_edges]
            exclude = {i: {edge_pos[e] for e in v.link_edges}
                       for i, v in enumerate(movers)}
            vert_islands = edge_islands = None
            if not self.cross_island:
                ids, pos = _island_ids(bm)
                vert_islands = [ids[pos[v]] for v in movers]
                edge_islands = [ids[pos[e.verts[0]]] for e in all_edges]
            found = fuse_candidates(verts_co, edges_co, tol=self._tol,
                                    exclude=exclude,
                                    vert_islands=vert_islands,
                                    edge_islands=edge_islands)
            if found:
                # Same dirty rule as `_pick_vert`: arm the cancel-restore
                # only when the scan genuinely moved the selection.
                before = self._selection_signature(bm)
                for c in found:
                    movers[c.vert_index].select = True
                bm.select_flush_mode()
                if self._selection_signature(bm) != before:
                    self._sel_dirty = True
                    bmesh.update_edit_mesh(self._obj.data,
                                           loop_triangles=False,
                                           destructive=False)
        # Candidates come from the normal (island-UNFILTERED) gather --
        # see `_read_selection` for the known cross-island edge case.
        self._read_selection(bm)
        context.workspace.status_text_set(self._status_text())
        if context.area:
            context.area.tag_redraw()

    def _confirm(self, context):
        """Apply the currently-previewed candidates through the same
        ``_apply_fuse`` call the direct-execute path uses."""
        candidates = list(self._candidates)
        obj = self._obj
        bm = self._bm
        verts = self._sel_verts
        edges = self._all_edges
        # Write the cycled position / adjusted tolerance back so the
        # redo panel (and a later re-execute) reflects what the user
        # actually confirmed.
        self.merge_position = self._current_key()
        self.tolerance = self._tol
        if not candidates:
            self._finish(context)
            self.report({"WARNING"},
                        "No edges within tolerance of the selected verts")
            return {"CANCELLED"}

        error = self._apply_and_flush(bm, obj.data, verts, edges,
                                      candidates)
        self._finish(context)
        if error is not None:
            self.report({"ERROR"},
                        f"Vert Fuse: apply stopped partway -- {error}")
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
        """Restore the invoke-time selection (cancel path only).

        No-op unless a pick or A-scan actually changed the selection, so
        a plain cancel of an untouched preview -- or one after nothing
        but miss-clicks -- writes nothing to the mesh.

        The snapshot is lookup-table *positions* over all three element
        domains (see `_selection_signature`), restored verbatim: clear
        everything, set exactly the snapshotted flags, and let one
        `select_flush_mode()` settle mode consistency -- no directional
        flush that could light up extra elements.
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
            # Faces too: the snapshot loop below indexes `bm.faces[i]`,
            # and a dirty face table would raise IndexError into the
            # blanket except -- silently skipping the flush and leaving
            # a half-restored selection.
            bm.faces.ensure_lookup_table()
            for v in bm.verts:
                v.select = False
            for e in bm.edges:
                e.select = False
            for f in bm.faces:
                f.select = False
            snap_verts, snap_edges, snap_faces = self._snapshot
            for seq, snap in ((bm.verts, snap_verts),
                              (bm.edges, snap_edges),
                              (bm.faces, snap_faces)):
                n = len(seq)
                for i in snap:
                    if 0 <= i < n:
                        seq[i].select = True
            # LMB picks appended to the history (active element); the
            # snapshot doesn't cover it, so drop it rather than leave a
            # picked element active after cancel.
            bm.select_history.clear()
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
        self._sel_verts = []
        self._all_edges = []
        self._candidates = []
        self._ghosts = []
        self._snapshot = (frozenset(), frozenset(), frozenset())
        self._sel_dirty = False
        self._hud = None
        self._help = None

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _draw_geometry(self, context):
        """POST_VIEW: one dot per candidate at its merge point, plus a
        dashed ghost line from the moving vert to it. `_ghosts` is plain
        float tuples, so this path never dereferences bmesh data."""
        if context.region_data is None:
            return
        # Guard ONLY the state reads (same narrowing as
        # `mesh_converge._draw_geometry`): a blinker/addon reload can
        # free the operator RNA while this handler is still registered,
        # and `self._obj` / `matrix_world` are the only touches here that
        # raise once it is gone. Everything below stays outside the
        # guard so a genuine bug in the overlay code tracebacks to the
        # console instead of silently deleting both handlers mid-modal.
        try:
            obj = self._obj
            ghosts = self._ghosts
            if obj is None or not ghosts:
                return
            mw = obj.matrix_world
        except (ReferenceError, AttributeError):
            # Operator RNA freed (blinker reload) or state already torn
            # down while a redraw was still queued.
            _purge_handles()
            return

        dots = {}
        lines = {}
        for n, (vert_co, merge_co) in enumerate(ghosts):
            col = FUSE_PALETTE[n % len(FUSE_PALETTE)]
            merge_w = mw @ Vector(merge_co)
            dots.setdefault(col, []).append(merge_w)
            seg = lines.setdefault(col, [])
            seg.extend(_dashed(mw @ Vector(vert_co), merge_w))
        # POST_VIEW runs mid-pipeline, so restore point size too --
        # `primitives.points` sets it globally and Blender's own
        # vertex drawing would inherit a fat size otherwise.
        with draw_scope(blend="ALPHA", depth="NONE", point_size=1.0):
            for col, segs in lines.items():
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
                    f"Position: {self._current_key()}",
                    f"Candidates: {len(self._candidates)}",
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

    def _apply_and_flush(self, bm, mesh, verts, edges, candidates):
        """Apply ``candidates``, select the result, and flush the bmesh
        -- flushing even when the apply raises partway.

        The split+merge runs once per candidate, so a failure on
        candidate N leaves the first N-1 fuses already in the bmesh. If
        that exception escapes the operator, Blender turns it into
        ``CANCELLED`` and pushes no undo step -- yet the applied fuses
        are still there and surface at the next flush, with no undo
        entry to reverse them. Flushing in ``finally`` and letting the
        caller return ``FINISHED`` puts whatever was applied inside this
        operator's undo step instead.

        Returns the exception that stopped the apply, or ``None``. The
        caller reports it -- it is never silently swallowed.
        """
        try:
            result_verts = self._apply_fuse(bm, verts, edges, candidates)
            self._select_result(bm, result_verts)
        except Exception as exc:
            return exc
        finally:
            bmesh.update_edit_mesh(mesh)
        return None

    def _apply_fuse(self, bm, verts, edges, candidates):
        """Apply ``Candidate``\\ s as edge splits + pointmerges.

        ``verts`` / ``edges`` are the ``BMVert`` / ``BMEdge`` lists in
        the same index spaces the Candidates were computed from
        (``candidate.vert_index`` / ``.edge_index`` index into them).

        Handles split chaining: an earlier candidate may have already
        split this candidate's target edge, so the recorded original
        edge is no longer the piece the vert projects onto. A map
        ``edge_index -> [live sub-edges]`` tracks every split; the vert
        is re-projected over the live pieces and fuses into the one
        whose interior actually contains its projection.

        Returns the ``set`` of surviving ``BMVert`` -- callers select
        these as the operator's resulting selection.
        """
        merge = dict(MERGE_POSITIONS)[self.merge_position]
        sub_edges = {}
        result = set()
        for c in candidates:
            v = verts[c.vert_index]
            if not v.is_valid:
                continue
            pieces = sub_edges.setdefault(c.edge_index,
                                          [edges[c.edge_index]])
            target = self._resolve_sub_edge(pieces, tuple(v.co),
                                            self.tolerance)
            if target is None:
                continue
            edge, t, proj = target
            new_edge, new_vert = bmesh.utils.edge_split(
                edge, edge.verts[0], t)
            # `edge` stays in `pieces` as one half of the split; the
            # other half joins it.
            pieces.append(new_edge)
            if not v.is_valid or not new_vert.is_valid or v is new_vert:
                # Can't-happen-in-practice guard (edge_split doesn't
                # invalidate `v`) -- but if it ever trips, the split
                # already ran and its stray vert stays on the target
                # edge inside this operator's undo step.
                continue
            merge_co = Vector(merge(tuple(v.co), proj))
            bmesh.ops.pointmerge(bm, verts=[v, new_vert],
                                 merge_co=merge_co)
            survivor = v if v.is_valid else new_vert
            if survivor.is_valid:
                result.add(survivor)
        return {v for v in result if v.is_valid}

    @staticmethod
    def _resolve_sub_edge(pieces, p, tol):
        """``(edge, t, proj)`` for the live sub-edge whose interior
        contains ``p``'s projection (nearest wins), or ``None`` when no
        piece qualifies any more (an earlier merge landed exactly on
        this vert's projection, or the pieces got freed).

        Re-checks ``tol``: an earlier VERT/MID fuse can bend pieces of
        this same original edge, and a weld beyond tolerance would land
        visibly off the previewed ghost -- skip instead."""
        best = None
        for e in pieces:
            if not e.is_valid:
                continue
            a = e.verts[0].co
            b = e.verts[1].co
            d = b - a
            dd = d.dot(d)
            if dd < EPS * EPS:
                continue
            t = (Vector(p) - a).dot(d) / dd
            if t <= 0.0 or t >= 1.0:
                continue
            proj = a + d * t
            if (proj - a).length <= EPS or (proj - b).length <= EPS:
                continue
            gap = (Vector(p) - proj).length
            if gap > tol:
                continue
            if best is None or gap < best[3]:
                best = (e, t, tuple(proj), gap)
        if best is None:
            return None
        return best[0], best[1], best[2]
