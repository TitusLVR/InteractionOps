# Part 1: Imports and Class Definition with Modifier Management
import bpy
import mathutils
import bmesh
import math
from mathutils import Vector, Matrix
import bpy_extras
try:
    import numpy as _np
except ImportError:  # Blender bundles NumPy; fall back to pure Python without it
    _np = None

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..utils.picking import px_world_at, pull_toward_viewer
from ..utils.cursor_bisect_core import (walk_island, normals_split, DELIMIT_LABELS,
                                        next_delimit_type, next_axis, axis_vector,
                                        cut_set_for_axis, cached_island,
                                        SNAP_SOURCE_LABELS, next_snap_source,
                                        oriented_extents, bounds_layout,
                                        bounds_split, AXES)
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)
from ..ui.hud.text import draw as draw_text, measure as measure_text

# Constants
DEFAULT_ANGLE_THRESHOLD = 5.0
DEFAULT_ROTATION_STEP = 45.0
DEFAULT_MERGE_DISTANCE = 0.005
BISECT_PLANE_EPSILON = 1e-4  # Matches Blender's mesh.bisect default threshold; snaps near-plane verts so we don't get slivers / unwelded verts
DEFAULT_SNAP_THRESHOLD = 30.0
DEFAULT_FACE_DEPTH = 5
DEFAULT_MAX_FACES = 1000
DEFAULT_EDGE_SUBDIVISIONS = 1
PREVIEW_PULL_PX = 2.0  # Preview lines are pulled this many px toward the viewer at draw time (see picking.pull_toward_viewer)
PREVIEW_PLANE_HALF_PX = 120.0  # Half-size of the plane preview square, in screen px at cursor depth
DEFAULT_DISTANCE_TEXT_SIZE = 16
DEFAULT_DISTANCE_TEXT_OFFSET_X = 20
DEFAULT_DISTANCE_TEXT_OFFSET_Y = -30
MAX_RAYCAST_ITERATIONS = 100
RAYCAST_OFFSET_DISTANCE = 0.0001
EPSILON = 1e-6
DEFAULT_INSET_DISTANCE_CM = 10.0
UV_SPLIT_EPSILON = 1e-6  # Loop UVs across an edge differing by more than this = UV island boundary


# --- Delimiter (BMesh side) -------------------------------------------------

def delimit_boundary_test(bm, delimit_type, angle_deg):
    """Return `is_boundary(edge, face_a, face_b)` for the given delimiter
    type. The walk never crosses an edge for which it returns True."""
    if delimit_type == 'SEAM':
        return lambda e, a, b: e.seam
    if delimit_type == 'SHARP':
        return lambda e, a, b: not e.smooth
    if delimit_type == 'MATERIAL':
        return lambda e, a, b: a.material_index != b.material_index
    if delimit_type == 'NORMAL':
        return lambda e, a, b: normals_split(a.normal, b.normal, angle_deg)
    if delimit_type == 'UV':
        uv = bm.loops.layers.uv.active
        if uv is None:
            return lambda e, a, b: False

        def uv_split(e, a, b):
            for v in e.verts:
                la = next((l for l in a.loops if l.vert is v), None)
                lb = next((l for l in b.loops if l.vert is v), None)
                if la is None or lb is None:
                    continue
                ua, ub = la[uv].uv, lb[uv].uv
                if abs(ua.x - ub.x) > UV_SPLIT_EPSILON or abs(ua.y - ub.y) > UV_SPLIT_EPSILON:
                    return True
            return False
        return uv_split
    return lambda e, a, b: False  # ISLAND


def delimited_faces(bm, start_index, candidates, delimit_type, angle_deg,
                    is_visible=None):
    """Indices of the faces reachable from `bm.faces[start_index]` without
    crossing a `delimit_type` boundary, restricted to `candidates` (a set
    of face indices) and to faces passing `is_visible`. Empty set when the
    start index is out of range or the start face is filtered out."""
    bm.faces.ensure_lookup_table()
    if start_index < 0 or start_index >= len(bm.faces):
        return set()
    faces = bm.faces
    is_boundary = delimit_boundary_test(bm, delimit_type, angle_deg)

    def in_candidates(idx):
        if idx not in candidates:
            return False
        return is_visible is None or is_visible(faces[idx])

    def neighbors(idx):
        face = faces[idx]
        for e in face.edges:
            for other in e.link_faces:
                if other is not face:
                    yield e, other.index

    def boundary(e, ia, ib):
        return is_boundary(e, faces[ia], faces[ib])

    return walk_island(start_index, in_candidates, neighbors, boundary)


SEL_LAYER_NAME = "cursor_bisect_sel"
CUT_LAYER_NAME = "cursor_bisect_cut"
SCRATCH_LAYER_NAMES = (SEL_LAYER_NAME, CUT_LAYER_NAME)


def drop_scratch_layers(bm):
    """Remove the selection-snapshot and cut scratch layers by name.

    Always by name, never through a BMLayerItem handle: a handle is just a
    per-type index, so removing one int layer shifts every later handle onto
    the wrong layer (or past the end, where reading it raises "layer has
    become invalid"). Call this before creating either layer (a stale layer
    removed after the other was created would alias the two handles) and
    again once the cut is done."""
    for name in SCRATCH_LAYER_NAMES:
        layer = bm.faces.layers.int.get(name)
        if layer is not None:
            bm.faces.layers.int.remove(layer)


def stamp_cut_layer(bm, face_indices):
    """Fresh int layer with 1 on the faces to cut. Like the selection
    snapshot layer it survives bisect_plane (split halves inherit it), so
    every plane of a bevel / fill cut sees the same face set.
    Caller runs drop_scratch_layers() first."""
    layer = bm.faces.layers.int.new(CUT_LAYER_NAME)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f[layer] = 1 if f.index in face_indices else 0
    return layer


def world_align_rotation(normal_axis, world_axis):
    """3x3 rotation that puts the cursor's `normal_axis` (the cut normal)
    onto the given world axis."""
    table = {
        'X': {'X': Matrix.Identity(3),
              'Y': Matrix.Rotation(math.radians(90), 3, 'Z'),
              'Z': Matrix.Rotation(math.radians(-90), 3, 'Y')},
        'Y': {'X': Matrix.Rotation(math.radians(90), 3, 'Z'),
              'Y': Matrix.Identity(3),
              'Z': Matrix.Rotation(math.radians(-90), 3, 'X')},
        'Z': {'X': Matrix.Rotation(math.radians(90), 3, 'Y'),
              'Y': Matrix.Rotation(math.radians(-90), 3, 'X'),
              'Z': Matrix.Identity(3)},
    }
    return table[normal_axis][world_axis]


def face_straddles_plane(face, plane_co, plane_no, eps):
    """True when the face has vertices strictly on both sides of the plane,
    which is exactly when bisect_plane (dist=eps) splits it. A face lying in
    the plane, or only touching it with a vertex / edge, is not cut."""
    above = below = False
    for v in face.verts:
        d = (v.co - plane_co).dot(plane_no)
        if d > eps:
            above = True
        elif d < -eps:
            below = True
        if above and below:
            return True
    return False


def merge_cut_doubles(bm, cut_layer, dist, *, restrict):
    """Merge Doubles after a cut. With `restrict` only the vertices of the
    faces stamped on `cut_layer` take part, so a delimited cut never welds
    geometry outside its island (islands often share vertex positions)."""
    if restrict:
        verts = list({v for f in bm.faces if f[cut_layer] == 1 for v in f.verts})
    else:
        verts = bm.verts
    if verts:
        bmesh.ops.remove_doubles(bm, verts=verts, dist=dist)


# --- Selection Bounds snap source (BMesh side) ----------------------------------

def cut_set_world_points(bm, matrix_world, face_indices):
    """World-space coordinates (plain 3-tuples) of the unique vertices of
    the faces `face_indices` of `bm`. Out-of-range indices are skipped."""
    bm.faces.ensure_lookup_table()
    faces = bm.faces
    n = len(faces)
    verts = {v for i in face_indices if 0 <= i < n for v in faces[i].verts}
    return [tuple(matrix_world @ v.co) for v in verts]


def rotation_axes(rotation):
    """The three world-space unit axes (columns) of a cut rotation
    (Quaternion or 3x3 Matrix), as plain tuples."""
    m = rotation.to_matrix() if hasattr(rotation, "to_matrix") else rotation
    return tuple(tuple(m.col[i].normalized()) for i in range(3))


def points_extents(points, axes):
    """`oriented_extents` for the cached cut-set points. A NumPy array
    (the operator's cache) is projected in one matrix product; any other
    iterable goes through the pure-Python core function."""
    if _np is not None and isinstance(points, _np.ndarray):
        if points.size == 0:
            return None
        proj = points @ _np.asarray(axes, dtype=_np.float64).T
        return (tuple(float(x) for x in proj.min(axis=0)),
                tuple(float(x) for x in proj.max(axis=0)))
    return oriented_extents(points, axes)


def selection_bounds_layout(points, rotation, normal_axis, subdivisions,
                            inset_distance, inset_on):
    """Oriented box of `points` (world) in the frame of `rotation`, with its
    divisions / inset points / cut positions along `normal_axis`; None when
    there are no points. See utils.cursor_bisect_core.bounds_layout."""
    axes = rotation_axes(rotation)
    ext = points_extents(points, axes)
    if ext is None:
        return None
    lo, hi = ext
    return bounds_layout(lo, hi, axes, AXES.index(normal_axis), subdivisions,
                         inset_distance, inset_on)


# Set of (post_kind, handle) tuples for SpaceView3D draw handlers owned by
# this operator. Survives addon reloads and orphaned exits so a fresh invoke
# can clean up after dead instances.
_ACTIVE_HANDLES: set = set()


def _drop_stale_handles():
    for kind, h in list(_ACTIVE_HANDLES):
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, 'WINDOW')
        except (ValueError, RuntimeError):
            pass
        _ACTIVE_HANDLES.discard((kind, h))

NUMERIC_KEYS = {
    'ZERO': '0', 'ONE': '1', 'TWO': '2', 'THREE': '3', 'FOUR': '4',
    'FIVE': '5', 'SIX': '6', 'SEVEN': '7', 'EIGHT': '8', 'NINE': '9',
    'NUMPAD_0': '0', 'NUMPAD_1': '1', 'NUMPAD_2': '2', 'NUMPAD_3': '3',
    'NUMPAD_4': '4', 'NUMPAD_5': '5', 'NUMPAD_6': '6', 'NUMPAD_7': '7',
    'NUMPAD_8': '8', 'NUMPAD_9': '9',
}


class IOPS_OT_Mesh_Cursor_Bisect(bpy.types.Operator):
    bl_idname = "iops.mesh_cursor_bisect"
    is_bindable = True
    bl_label = "Cursor Bisect"
    bl_description = "Bisect mesh. S-snap, Shift+S-snap source, D-hold points, F-fill cut, Z-deselect all, Ctrl+Z-undo, A-lock orientation, X-toggle normal axis, W-world align, P-toggle preview mode, I-toggle distance info"
    bl_options = {'REGISTER', 'UNDO'}

    merge_doubles: bpy.props.BoolProperty(name="Merge Doubles", default=True)

    _handle = None
    hit_location = None
    hit_normal = None
    hit_obj = None
    hit_face_index = -1
    edge_index = 0
    face_edges = []
    normal_axis = 'X'
    lock_orientation = False
    locked_rotation = None
    locked_edge_world = None  # (Vector, Vector) world-space snapshot of the edge that defined the lock
    world_axis = 'X'  # Track current world axis alignment: 'X', 'Y', or 'Z'

    # Add timer for better modal handling
    _timer = None

    # Mouse coordinate tracking for screen-space snapping
    _current_mouse_coord = (0, 0)

    # Snapping system
    snapping_enabled = True  # Active by default
    snap_points = []
    closest_snap_point = None
    edge_subdivisions = 0  # 0 subdivisions by default (only vertices and center)
    hold_snap_points = False  # Hold snap points without recalculating
    last_face_index = -1  # Track last face to avoid unnecessary recalculations

    # Snap source (Shift+S): 'EDGE' = points of the hovered face, 'BOUNDS' =
    # divisions of the cut set's oriented box along the cut axis.
    snap_source = 'EDGE'
    _bounds_layout = None        # dict from selection_bounds_layout, or None
    _bounds_layout_key = None    # inputs the layout was built from
    _bounds_points_cache = None  # (key, world points of the cut set)

    # Cut preview system
    cut_preview_mode = 'LINES'  # 'LINES' or 'PLANE' - default to lines
    cut_preview_lines = []  # Store cut preview line segments

    # Fill cut system - bisect at every snap position along highlighted edge
    fill_cut_mode = False
    fill_cut_preview_lines = []

    # Inset points: snap points at fixed distance from edge endpoints
    inset_active = False
    inset_distance_bu = 0.1  # In Blender Units (meters); 0.1 = 10 cm default
    inset_input_string = ""
    inset_points = []
    # Bevel mode: when active, the operator produces TWO parallel cuts
    # offset ±inset_distance_bu perpendicular to the would-be cut line, in
    # the hit face plane. Affects both the live preview lines and the
    # execute step. Distance is shared with Inset.
    bevel_active = False

    # Edge marking system (M toggles, N cycles type)
    mark_edges_active = False
    mark_type_idx = 0
    MARK_TYPES = ('SEAM', 'SHARP', 'CREASE', 'BEVEL')

    # Delimiter (L toggles, Shift+L cycles type): confine the cut to the
    # piece of mesh under the mouse. See utils.cursor_bisect_core.
    delimit_active = False
    delimit_type = 'ISLAND'
    hover_valid = False      # True after a MOUSEMOVE hit, False after a miss
    _mesh_version = 0        # Bumped on every cut / selection change; keys the island cache
    _island_cache = None     # (key, frozenset) of the last delimited face set
    _bvh_cache = None        # {(obj name, _mesh_version): (BVHTree, face map)} for hover picking

    # Distance text system
    show_distance_info = True  # Toggle for showing distance info (I key)
    distance_text_offset_x = 20  # Offset from mouse cursor in pixels
    distance_text_offset_y = -30  # Offset from mouse cursor in pixels
    distance_text_size = 16  # Text size

    # Modifier Management System
    _modifier_states = {}  # Store original modifier states {obj_name: {modifier_name: show_viewport}}
    
    # Modifier types that should be disabled during bisect operation
    DISABLE_MODIFIER_TYPES = {
        'TRIANGULATE',
        'SOLIDIFY', 
        'ARRAY',
        'SCREW',
        'SPIN',
        'WELD',
        'DECIMATE',
        'REMESH',
        'SKIN',
        'SUBSURF',
        'MULTIRES',
        'DISPLACE',
        'CAST',
        'HOOK',
        'LAPLACIANDEFORM',
        'LATTICE',
        'MESH_DEFORM',
        'SHRINKWRAP',
        'SIMPLE_DEFORM',
        'SMOOTH',
        'CORRECTIVE_SMOOTH',
        'LAPLACIANSMOOTH',
        'SURFACE_DEFORM',
        'WARP',
        'WAVE',
        'CLOTH',
        'COLLISION',
        'DYNAMIC_PAINT',
        'EXPLODE',
        'FLUID',
        'OCEAN',
        'PARTICLE_INSTANCE',
        'PARTICLE_SYSTEM',
        'SOFT_BODY',
        'SURFACE'
    }
    
    # Modifier types that should NOT be disabled (keep enabled)
    KEEP_MODIFIER_TYPES = {
        'MIRROR',
        'BEVEL',
        'EDGE_SPLIT',
        'WEIGHTED_NORMAL',
        'NORMAL_EDIT',
        'UV_PROJECT',
        'UV_WARP'
    }

    @staticmethod
    def get_preferences(context):
        """Get addon preferences with fallback to defaults"""
        try:
            return context.preferences.addons["InteractionOps"].preferences
        except (KeyError, AttributeError):
            return None

    def store_modifier_states(self, context):
        """Store the current show_viewport state of all modifiers for selected objects"""
        self._modifier_states.clear()

        for obj in self._edit_mesh_objects(context):
            if obj.modifiers:
                obj_states = {}
                for modifier in obj.modifiers:
                    # Store original show_viewport state
                    obj_states[modifier.name] = modifier.show_viewport
                self._modifier_states[obj.name] = obj_states
                
        print(f"DEBUG: Stored modifier states for {len(self._modifier_states)} objects")

    def disable_modifiers_for_bisect(self, context):
        """Disable specified modifier types for better bisect operation"""
        disabled_count = 0

        for obj in self._edit_mesh_objects(context):
            if obj.modifiers:
                for modifier in obj.modifiers:
                    # Only disable modifiers that are currently visible and should be disabled
                    if (modifier.show_viewport and 
                        modifier.type in self.DISABLE_MODIFIER_TYPES and
                        modifier.type not in self.KEEP_MODIFIER_TYPES):
                        
                        modifier.show_viewport = False
                        disabled_count += 1
                        print(f"DEBUG: Disabled {modifier.type} modifier '{modifier.name}' on {obj.name}")
        
        if disabled_count > 0:
            # Update the depsgraph to reflect modifier changes
            context.view_layer.update()
            print(f"DEBUG: Disabled {disabled_count} modifiers for bisect operation")

    def restore_modifier_states(self, context):
        """Restore the original show_viewport state of all modifiers"""
        if not self._modifier_states:
            return
            
        restored_count = 0
        
        # Get all objects that were processed
        for obj_name, modifier_states in self._modifier_states.items():
            # Find the object in the scene
            obj = bpy.data.objects.get(obj_name)
            if obj and obj.modifiers:
                for modifier_name, original_state in modifier_states.items():
                    # Find the modifier
                    modifier = obj.modifiers.get(modifier_name)
                    if modifier:
                        # Restore original state
                        modifier.show_viewport = original_state
                        restored_count += 1
                        
        if restored_count > 0:
            # Update the depsgraph to reflect modifier changes
            context.view_layer.update()
            print(f"DEBUG: Restored {restored_count} modifier states")
        
        # Clear stored states
        self._modifier_states.clear()

    # Part 2: Status Bar and Distance Calculation Methods

    @staticmethod
    def _snapshot_face_selection(bm, is_visible):
        """Stamp each visible+selected face with 1 on a fresh int layer.
        The layer survives bisect_plane and remove_doubles (split / merged faces
        inherit the value), so it's the robust way to restore selection after ops
        that re-create faces. Returns the layer handle.
        Caller runs drop_scratch_layers() first."""
        layer = bm.faces.layers.int.new(SEL_LAYER_NAME)
        for f in bm.faces:
            f[layer] = 1 if (f.select and is_visible(f)) else 0
        return layer

    @staticmethod
    def _restore_face_selection(bm, layer, is_visible):
        """Clear all selection then reselect faces whose layer value is 1."""
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = False
        for f in bm.faces:
            if f[layer] == 1 and is_visible(f):
                f.select = True

    @staticmethod
    def _recover_after_failed_cut(obj):
        """A cut that raised mid-way may have split faces already: drop the
        scratch layers and push the edit mesh through update_edit_mesh so
        the viewport rebuilds its triangulation instead of drawing stale
        looptris over freed faces (hard crash in extract_tris)."""
        try:
            bm_err = bmesh.from_edit_mesh(obj.data)
            drop_scratch_layers(bm_err)
            bmesh.update_edit_mesh(obj.data)
        except (AttributeError, ValueError, ReferenceError, RuntimeError):
            pass

    def _current_mark_type(self):
        return self.MARK_TYPES[self.mark_type_idx % len(self.MARK_TYPES)]

    def _apply_edge_mark(self, bm, edges):
        """Apply the currently selected mark type to the given edges."""
        if not edges:
            return
        mt = self._current_mark_type()
        if mt == 'SEAM':
            for e in edges:
                e.seam = True
        elif mt == 'SHARP':
            for e in edges:
                e.smooth = False
        elif mt == 'CREASE':
            layer = bm.edges.layers.float.get("crease_edge")
            if layer is None:
                layer = bm.edges.layers.float.new("crease_edge")
            for e in edges:
                e[layer] = 1.0
        elif mt == 'BEVEL':
            layer = bm.edges.layers.float.get("bevel_weight_edge")
            if layer is None:
                layer = bm.edges.layers.float.new("bevel_weight_edge")
            for e in edges:
                e[layer] = 1.0

    def update_status_bar(self, context):
        """Update workspace status text with current shortcuts and mode info"""
        snap_status = "ON" if self.snapping_enabled else "OFF"
        hold_status = " (HOLD)" if self.hold_snap_points else ""
        lock_status = " (LOCKED)" if self.lock_orientation else ""
        preview_mode = self.cut_preview_mode
        distance_status = "ON" if self.show_distance_info else "OFF"
        fill_cut_status = "ON" if self.fill_cut_mode else "OFF"
        if self.inset_active:
            scale, suffix = self._bu_to_display_units(context)
            v_display = self.inset_distance_bu * scale
            inset_info = f"ON:{self._fmt(v_display)}{suffix}"
        else:
            inset_info = "OFF"
        if self.bevel_active:
            scale, suffix = self._bu_to_display_units(context)
            v_display = self.inset_distance_bu * scale
            bevel_info = f"ON:{self._fmt(v_display)}{suffix}"
        else:
            bevel_info = "OFF"
        mark_status = f"ON:{self._current_mark_type()}" if self.mark_edges_active else f"OFF:{self._current_mark_type()}"
        delimit_status = f"ON:{DELIMIT_LABELS[self.delimit_type]}" if self.delimit_active else "OFF"

        # Create status text with simple letter prefixes in brackets for visual clarity
        snap_source = SNAP_SOURCE_LABELS.get(self.snap_source, self.snap_source)
        status_text = (f"Cursor Bisect: [LMB] Execute | [A] Lock{lock_status} | [S] Snap({snap_status}{hold_status}) | "
                      f"[Shift+S] Snap Source({snap_source}) | "
                      f"[D] Hold Points | [F] Fill Cut({fill_cut_status}) | [V] Inset({inset_info}) | [B] Bevel({bevel_info}) | [M] Mark({mark_status}) | [N] Mark Type | [L] Delimit({delimit_status}) | [P] Preview({preview_mode}) | [I] Distance Info({distance_status}) | [X] Axis({self.normal_axis}) | [W] World({self.world_axis}) | [RMB] Select Face | "
                      f"[Shift+RMB] Select Coplanar | [Ctrl+Wheel] Subdivisions({self.edge_subdivisions}) | "
                      f"[Alt+Wheel] Rotate Z | [Z] Deselect | [Ctrl+Z] Undo | [Space] Finish | [Esc] Cancel")

        # Set workspace status text
        context.workspace.status_text_set(status_text)

    @staticmethod
    def _bu_to_display_units(context):
        """Get multiplier and suffix to convert Blender internal units (meters) to scene display units.
        Returns (scale, suffix). Usage: display_value = internal_value * scale"""
        unit_settings = context.scene.unit_settings
        s = unit_settings.scale_length

        if unit_settings.system == 'METRIC':
            table = {
                'KILOMETERS':  (s * 0.001,     "km"),
                'METERS':      (s * 1.0,       "m"),
                'CENTIMETERS': (s * 100.0,     "cm"),
                'MILLIMETERS': (s * 1000.0,    "mm"),
                'MICROMETERS': (s * 1000000.0, "µm"),
            }
            return table.get(unit_settings.length_unit, (s * 100.0, "cm"))
        elif unit_settings.system == 'IMPERIAL':
            table = {
                'MILES':  (s * 0.000621371, "mi"),
                'FEET':   (s * 3.28084,     "ft"),
                'INCHES': (s * 39.3701,     "in"),
                'THOU':   (s * 39370.1,     "thou"),
            }
            return table.get(unit_settings.length_unit, (s * 39.3701, "in"))
        else:
            return (s * 1.0, "BU")

    @staticmethod
    def _fmt(value):
        """Format a distance value: strip unnecessary trailing zeros"""
        return f"{value:.2f}".rstrip('0').rstrip('.')

    def _snapshot_active_edge_world(self):
        """Capture the currently-highlighted edge endpoints in world space."""
        if not (self.hit_obj and self.face_edges and
                0 <= self.edge_index < len(self.face_edges)):
            return None
        try:
            if self.hit_obj.mode != 'EDIT':
                return None
            bm = bmesh.from_edit_mesh(self.hit_obj.data)
            bm.edges.ensure_lookup_table()
            edge_idx = self.face_edges[self.edge_index]
            if edge_idx >= len(bm.edges):
                return None
            v1, v2 = bm.edges[edge_idx].verts
            mw = self.hit_obj.matrix_world
            return (mw @ v1.co.copy(), mw @ v2.co.copy())
        except (IndexError, AttributeError, ValueError, ReferenceError):
            return None

    def get_edge_split_distances(self, context):
        """Calculate the edge length and split distance (cursor to nearest vertex).
        With the Selection Bounds snap source: the box side along the cut
        axis and the cursor's distance to its nearer end."""
        if self.snap_source == 'BOUNDS':
            return self._bounds_split_distances(context)
        if not (self.hit_obj and self.face_edges and 0 <= self.edge_index < len(self.face_edges)):
            return None

        try:
            if self.hit_obj.mode != 'EDIT':
                return None

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.edges.ensure_lookup_table()

            edge_idx = self.face_edges[self.edge_index]
            if edge_idx >= len(bm.edges):
                return None

            edge = bm.edges[edge_idx]
            v1, v2 = edge.verts

            v1_world = self.hit_obj.matrix_world @ v1.co
            v2_world = self.hit_obj.matrix_world @ v2.co
            total_edge_length = (v2_world - v1_world).length

            cursor_pos = context.scene.cursor.location
            edge_vec = v2_world - v1_world
            cursor_vec = cursor_pos - v1_world

            if edge_vec.length > 0:
                t = max(0, min(1, cursor_vec.dot(edge_vec) / edge_vec.length_squared))
                dist1 = total_edge_length * t
                dist2 = total_edge_length * (1.0 - t)

                scale, suffix = self._bu_to_display_units(context)

                return {
                    'total': total_edge_length * scale,
                    'split': min(dist1, dist2) * scale,
                    'unit': suffix,
                }

        except (IndexError, AttributeError, ValueError):
            pass

        return None

    def _bounds_split_distances(self, context):
        """Distance info for the Selection Bounds snap source, read from the
        last built layout (never rebuilt here: the HUD calls this per frame)."""
        lay = self._bounds_layout
        if not lay:
            return None
        try:
            length, split = bounds_split(lay['lo'], lay['hi'], lay['axes'],
                                         lay['axis_index'],
                                         tuple(context.scene.cursor.location))
            scale, suffix = self._bu_to_display_units(context)
        except (AttributeError, KeyError, ValueError, TypeError):
            return None
        return {'total': length * scale, 'split': split * scale, 'unit': suffix,
                'label': 'Bounds'}

    # Part 3: Coplanar Face Selection Method

    def select_coplanar_faces(self, context, event):
        """Select faces that are coplanar with the clicked face within angle threshold"""
        result, loc, normal, face_index, obj, _ = self.mouse_raycast(context, event, full=True)
        if not result or not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            return

        # Get angle threshold from preferences and convert to threshold for select_similar
        prefs = self.get_preferences(context)
        if prefs and hasattr(prefs, 'cursor_bisect_coplanar_angle'):
            angle_threshold = prefs.cursor_bisect_coplanar_angle
        else:
            angle_threshold = DEFAULT_ANGLE_THRESHOLD

        # Convert angle threshold to the threshold format used by select_similar
        similarity_threshold = angle_threshold / 180.0  # Convert degrees to 0-1 range
        similarity_threshold = max(0.001, min(1.0, similarity_threshold))  # Clamp to valid range

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            if face_index >= len(bm.faces):
                return

            clicked_face = bm.faces[face_index]
            if not self.is_face_visible_and_valid(clicked_face):
                return

            # Store current selection state
            original_selection = {f.index: f.select for f in bm.faces}

            # Check if the clicked face is already selected to determine add/remove mode
            clicked_face_was_selected = clicked_face.select

            # Temporarily clear selection and select only the clicked face for similarity detection
            for face in bm.faces:
                face.select = False
            clicked_face.select = True
            bmesh.update_edit_mesh(obj.data)

            # Use Blender's built-in select similar with coplanar type
            bpy.ops.mesh.select_similar(type='FACE_COPLANAR', threshold=similarity_threshold)

            # Refresh bmesh to get the similarity results
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            # Get the faces that were detected as coplanar
            coplanar_faces = [f.index for f in bm.faces if f.select and self.is_face_visible_and_valid(f)]

            # Restore original selection
            for face in bm.faces:
                face.select = original_selection.get(face.index, False)

            # Now apply add/remove logic based on whether clicked face was originally selected
            if clicked_face_was_selected:
                # Clicked face was selected - REMOVE coplanar faces from selection
                removed_count = 0
                for face_idx in coplanar_faces:
                    if face_idx < len(bm.faces):
                        face = bm.faces[face_idx]
                        if face.select:
                            face.select = False
                            removed_count += 1

                action_text = f"Removed {removed_count} coplanar faces from selection"

            else:
                # Clicked face was not selected - ADD coplanar faces to selection
                added_count = 0
                for face_idx in coplanar_faces:
                    if face_idx < len(bm.faces):
                        face = bm.faces[face_idx]
                        if not face.select:
                            face.select = True
                            added_count += 1

                action_text = f"Added {added_count} coplanar faces to selection"

            # Flush selection to edges and vertices
            bm.select_flush(True)
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)

            self._mesh_version += 1
            # Update cut preview after selection change
            self.calculate_cut_preview(context)

            # Show feedback message
            self.report({'INFO'}, f"{action_text} (angle ≤ {angle_threshold}°)")

        except Exception as e:
            self.report({'WARNING'}, f"Failed to select coplanar faces: {e}")
            # Restore original selection on error
            try:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                for face in bm.faces:
                    face.select = original_selection.get(face.index, False)
                bmesh.update_edit_mesh(obj.data)
            except (AttributeError, ReferenceError, ValueError):
                pass

    # Part 4: Modal Method (First Half)

    def modal(self, context, event):
        # Track latest event for HUD positioning
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        # HUD/Help toggles. Keys come from keymap items
        # (iops.ui_help_toggle, iops.ui_hud_params_toggle), editable in
        # the addon's Keymaps tab.
        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "help", None)
            hud = getattr(self, "hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
        # Pin HUD during viewport navigation. Rolling timer is refreshed on
        # every nav-related event; once events stop coming, the HUD resumes
        # cursor-follow automatically. Warp detection inside HUDOverlay
        # handles drift between explicit pin events.
        if getattr(self, "hud", None) is not None:
            if event.type == 'MIDDLEMOUSE':
                self.hud.pin_for(0.5)
            elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                self.hud.pin_for(0.3)
            elif event.type == 'TRACKPADPAN':
                self.hud.pin_for(0.3)
        # Keep HUD item states in sync with operator state every frame
        self._sync_hud_state()
        # Handle timer events
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}

        # Inset/Bevel numeric input: intercept digits when either mode is on.
        if (self.inset_active or self.bevel_active) and event.value == 'PRESS':
            if self._handle_inset_input(context, event):
                return {'RUNNING_MODAL'}

        # Handle Ctrl+Wheel for edge subdivision control.
        # Always consume so Blender's default mesh.select_more (also bound to
        # Ctrl+Wheel in edit mode) doesn't fire underneath this modal.
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl and not event.shift:
            if self.snapping_enabled:
                if event.type == 'WHEELUPMOUSE':
                    self.edge_subdivisions = min(self.edge_subdivisions + 1, 100)
                else:
                    self.edge_subdivisions = max(self.edge_subdivisions - 1, 0)
                if self.hit_obj and self.hit_face_index != -1 and not self.hold_snap_points:
                    self.update_snapping(context, context.scene.cursor.location)
                if self.fill_cut_mode:
                    self.calculate_fill_cut_preview(context)
                self.update_status_bar(context)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Handle Alt+Wheel for Z-axis rotation
        elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.alt and not event.shift and not event.ctrl:
            # Get rotation step from preferences
            prefs = self.get_preferences(context)
            if prefs and hasattr(prefs, 'cursor_bisect_rotation_step'):
                rotation_step = prefs.cursor_bisect_rotation_step
            else:
                rotation_step = DEFAULT_ROTATION_STEP

            # Convert to radians
            rotation_radians = math.radians(rotation_step)

            # Determine rotation direction
            if event.type == 'WHEELUPMOUSE':
                rotation_radians = -rotation_radians  # Counter-clockwise
            # else: clockwise (positive rotation)

            # Get current cursor rotation
            cursor = context.scene.cursor
            if self.lock_orientation and self.locked_rotation:
                current_rotation = self.locked_rotation
            else:
                current_rotation = cursor.matrix.to_quaternion()

            # Get the cursor's local Z-axis
            cursor_matrix = current_rotation.to_matrix()
            local_z_axis = cursor_matrix @ Vector((0, 0, 1))

            # Create rotation around cursor's local Z-axis
            z_rotation = mathutils.Quaternion(local_z_axis, rotation_radians)

            # Apply rotation
            new_rotation = z_rotation @ current_rotation

            # Update cursor and locked rotation
            cursor.rotation_mode = 'QUATERNION'
            cursor.rotation_quaternion = new_rotation

            if self.lock_orientation:
                self.locked_rotation = new_rotation

            # Update cut preview if in lines mode
            if self.cut_preview_mode == 'LINES':
                self.calculate_cut_preview(context)
            self._refresh_bounds(context)

            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Allow navigation - don't intercept middle mouse or plain navigation wheel
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        # Mouse movement - update cursor position and orientation
        if event.type == 'MOUSEMOVE':
            # Store current mouse coordinates for screen-space snapping
            self._current_mouse_coord = (event.mouse_region_x, event.mouse_region_y)

            result, loc, normal, face_index, obj, _ = self.mouse_raycast(context, event)
            if result and obj and obj.type == 'MESH' and obj.mode == 'EDIT':
                self.hover_valid = True
                self.hit_location = loc
                self.hit_normal = normal
                self.hit_obj = obj

                # Check if face changed
                face_changed = (face_index != self.last_face_index)
                self.hit_face_index = face_index
                self.last_face_index = face_index

                # Only reset edge cache if face changed AND not holding snap points
                if face_changed and not self.hold_snap_points:
                    self.face_edges.clear()
                    self.edge_index = 0

                # Update edge selection based on mouse position
                try:
                    mesh = obj.data
                    bm = bmesh.from_edit_mesh(mesh)
                    bm.faces.ensure_lookup_table()

                    if face_index < len(bm.faces):
                        face = bm.faces[face_index]
                        if face.edges:
                            if not self.face_edges or face_changed:
                                self.face_edges = [e.index for e in face.edges]
                            closest_edge = self.find_closest_edge_to_mouse(context, event, face)
                            if closest_edge != self.edge_index:
                                self.edge_index = closest_edge

                except (IndexError, AttributeError):
                    pass

                # Selection Bounds are built in the cut frame, so the frame
                # must be this event's: align before snapping (Face Edge mode
                # keeps its original order, alignment after the snap).
                bounds_source = self.snap_source == 'BOUNDS'
                if bounds_source and not self.lock_orientation and not self.hold_snap_points:
                    self.align_cursor_orientation()

                # Update snapping (now with screen-space support)
                self.update_snapping(context, loc)

                # Update cut preview
                self.calculate_cut_preview(context)

                # Set cursor position (snap to closest point if snapping enabled)
                if self.snapping_enabled and self.closest_snap_point:
                    _, _, snap_world = self.closest_snap_point
                    context.scene.cursor.location = snap_world
                else:
                    context.scene.cursor.location = loc

                # Only update orientation if face changed or if not locked/holding
                if (not bounds_source and (face_changed or not self.lock_orientation)
                        and not self.hold_snap_points):
                    if not self.lock_orientation:
                        self.align_cursor_orientation()

                context.area.tag_redraw()
            else:
                # Ray miss: the tracked face stays (hold-snap relies on it)
                # but it no longer counts as "under the mouse".
                if self.hover_valid:
                    self.hover_valid = False
                    if self.delimit_active:
                        self.cut_preview_lines = []
                        self.fill_cut_preview_lines = []
                        if self.snap_source == 'BOUNDS' and not self.hold_snap_points:
                            # The delimited cut set is empty off the mesh.
                            self._bounds_layout = None
                            self._bounds_layout_key = None
                            self.snap_points = []
                            self.inset_points = []
                            self.closest_snap_point = None
                        context.area.tag_redraw()

        # Toggle distance info display
        elif event.type == 'I' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.show_distance_info = not self.show_distance_info
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

    # Part 5: Modal Method (Second Half)

        # Toggle orientation lock
        elif event.type == 'A' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.lock_orientation = not self.lock_orientation

            if self.lock_orientation and self.hit_obj:
                self.align_cursor_orientation()
                self.locked_edge_world = self._snapshot_active_edge_world()
            else:
                self.locked_edge_world = None
            self._refresh_bounds(context)

            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle normal axis
        elif event.type == 'X' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.normal_axis = next_axis(self.normal_axis)
            self._enforce_z_restrictions()

            # Update cut preview immediately when changing axis (needed for LINES mode)
            if self.cut_preview_mode == 'LINES':
                self.calculate_cut_preview(context)
            self._refresh_bounds(context)

            self.update_status_bar(context)
            self._sync_hud_state()
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # World alignment - cycle through X, Y, Z
        elif event.type == 'W' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            # Cycle through world axes: X -> Y -> Z -> X -> ...
            if self.world_axis == 'X':
                self.world_axis = 'Y'
            elif self.world_axis == 'Y':
                self.world_axis = 'Z'
            else:  # world_axis == 'Z'
                self.world_axis = 'X'
            
            self.align_cursor_to_world(context, self.world_axis)
            self._refresh_bounds(context)
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Face selection and coplanar selection
        elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS' and not event.ctrl:
            if event.shift:
                # Shift+RMB: Select coplanar faces
                self.select_coplanar_faces(context, event)
                self._refresh_bounds(context)
            else:
                # Regular RMB: Toggle face selection
                result, loc, normal, face_index, obj, _ = self.mouse_raycast(context, event, full=True)
                if result and obj and obj.type == 'MESH' and obj.mode == 'EDIT':
                    try:
                        bm = bmesh.from_edit_mesh(obj.data)
                        bm.faces.ensure_lookup_table()
                        if face_index < len(bm.faces):
                            face = bm.faces[face_index]
                            face.select_set(not face.select)
                            bm.select_flush(True)
                            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
                            self._mesh_version += 1
                            # Update cut preview after selection change
                            self.calculate_cut_preview(context)
                    except (IndexError, AttributeError):
                        pass
                self._refresh_bounds(context)
            return {'RUNNING_MODAL'}

        # Toggle cut preview mode
        elif event.type == 'P' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            if self.cut_preview_mode == 'LINES':
                self.cut_preview_mode = 'PLANE'
                self.cut_preview_lines = []  # Clear lines when switching to plane
            else:
                self.cut_preview_mode = 'LINES'
                # Update cut preview immediately when switching to lines
                self.calculate_cut_preview(context)

            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle fill cut mode
        elif event.type == 'F' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            if self._z_blocked():
                return {'RUNNING_MODAL'}
            self.fill_cut_mode = not self.fill_cut_mode
            if self.fill_cut_mode:
                self.calculate_fill_cut_preview(context)
            else:
                self.fill_cut_preview_lines = []
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle inset points mode
        elif event.type == 'V' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            if self._z_blocked():
                return {'RUNNING_MODAL'}
            self.inset_active = not self.inset_active
            if self.inset_active:
                # Force-enable snap: inset points are meaningless without
                # snapping to them.
                self.snapping_enabled = True
                scale, _ = self._bu_to_display_units(context)
                display_val = self.inset_distance_bu * scale
                self.inset_input_string = self._fmt(display_val)
                self.calculate_inset_points()
            else:
                self.inset_points = []
                if not self.bevel_active:
                    self.inset_input_string = ""
            if self.hit_obj and self.hit_face_index != -1:
                self.update_snapping(context, context.scene.cursor.location)
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle bevel mode — two parallel cuts offset perpendicular to
        # the cut line in the face plane (distance shared with Inset).
        elif event.type == 'B' and event.value == 'PRESS' and not event.shift and not event.ctrl and not event.alt:
            if self._z_blocked():
                return {'RUNNING_MODAL'}
            self.bevel_active = not self.bevel_active
            if self.bevel_active:
                if not self.inset_input_string:
                    scale, _ = self._bu_to_display_units(context)
                    self.inset_input_string = self._fmt(self.inset_distance_bu * scale)
            else:
                if not self.inset_active:
                    self.inset_input_string = ""
            # Refresh preview so the second line appears/disappears now.
            self.calculate_cut_preview(context)
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle edge marking for new cut edges
        elif event.type == 'M' and event.value == 'PRESS' and not event.shift and not event.ctrl and not event.alt:
            self.mark_edges_active = not self.mark_edges_active
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Cycle edge mark type
        elif event.type == 'N' and event.value == 'PRESS' and not event.shift and not event.ctrl and not event.alt:
            self.mark_type_idx = (self.mark_type_idx + 1) % len(self.MARK_TYPES)
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Delimiter on/off (L) and type cycle (Shift+L)
        elif event.type == 'L' and event.value == 'PRESS' and not event.ctrl and not event.alt:
            if event.shift:
                self.delimit_type = next_delimit_type(self.delimit_type)
            else:
                self.delimit_active = not self.delimit_active
            self._island_cache = None
            self.calculate_cut_preview(context)
            if self.fill_cut_mode:
                self.calculate_fill_cut_preview(context)
            self._refresh_bounds(context)
            self.update_status_bar(context)
            self._sync_hud_state()
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Execute bisect (or fill cut)
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self.fill_cut_mode:
                self.execute_fill_cut(context)
            else:
                self.execute(context)
            return {'RUNNING_MODAL'}

        # Cycle snap source: Face Edge <-> Selection Bounds
        elif event.type == 'S' and event.value == 'PRESS' and event.shift and not event.ctrl and not event.alt:
            self.snap_source = next_snap_source(self.snap_source)
            # Held points belong to the previous source.
            self.hold_snap_points = False
            self._bounds_layout = None
            self._bounds_layout_key = None
            if self.snap_source == 'BOUNDS':
                # Bounds points are the whole point of this source.
                self.snapping_enabled = True
            if self.hit_obj and self.hit_face_index != -1:
                self.update_snapping(context, context.scene.cursor.location)
            else:
                self.snap_points = []
                self.closest_snap_point = None
            if self.fill_cut_mode:
                self.calculate_fill_cut_preview(context)
            self.update_status_bar(context)
            self._sync_hud_state()
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle snapping
        elif event.type == 'S' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.snapping_enabled = not self.snapping_enabled
            if not self.snapping_enabled:
                self.snap_points = []
                self.closest_snap_point = None
                self.hold_snap_points = False  # Reset hold when disabling snapping
            else:
                # Update snapping immediately
                if self.hit_obj and self.hit_face_index != -1:
                    self.update_snapping(context, context.scene.cursor.location)

            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle hold snap points
        elif event.type == 'D' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            if self.snapping_enabled:
                self.hold_snap_points = not self.hold_snap_points
                if not self.hold_snap_points:
                    # When releasing hold, immediately update snap points for current face
                    if self.hit_obj and self.hit_face_index != -1:
                        self.update_snapping(context, context.scene.cursor.location)

                self.update_status_bar(context)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Undo with Ctrl+Z
        elif event.type == 'Z' and event.value == 'PRESS' and event.ctrl and not event.shift:
            bpy.ops.ed.undo()
            self._mesh_version += 1
            self._island_cache = None
            # Refresh the bmesh data after undo
            if self.hit_obj and self.hit_obj.mode == 'EDIT':
                bmesh.update_edit_mesh(self.hit_obj.data)
                # Clear caches since geometry might have changed
                self.face_edges.clear()
                self.edge_index = 0
                if not self.hold_snap_points:
                    self.snap_points = []
                    self.closest_snap_point = None
            self._refresh_bounds(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Deselect all with Z
        elif event.type == 'Z' and event.value == 'PRESS' and not event.ctrl and not event.shift:
            # Deselect all in all selected mesh objects in edit mode
            edit_objects = [obj for obj in context.selected_objects
                           if obj.type == 'MESH' and obj.mode == 'EDIT']

            for obj in edit_objects:
                try:
                    bm = bmesh.from_edit_mesh(obj.data)
                    # Deselect all vertices, edges, and faces
                    for vert in bm.verts:
                        vert.select = False
                    for edge in bm.edges:
                        edge.select = False
                    for face in bm.faces:
                        face.select = False
                    bmesh.update_edit_mesh(obj.data)
                except (IndexError, AttributeError):
                    pass

            self._mesh_version += 1
            self._refresh_bounds(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Finish operator
        elif event.type == 'SPACE' and event.value == 'PRESS':
            self.cancel(context)
            return {'FINISHED'}

        # Cancel operator
        elif event.type == 'ESC':
            self.cancel(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}
    # Part 6: Execute Method

    def execute(self, context):
        """Execute the bisect operation on all selected mesh objects in edit mode"""
         # Push undo state before operation
        bpy.ops.ed.undo_push(message="Cursor Bisect")
        self._mesh_version += 1

        # Get all selected mesh objects in edit mode
        edit_objects = [obj for obj in context.selected_objects
                       if obj.type == 'MESH' and obj.mode == 'EDIT']

        if not edit_objects:
            self.report({'ERROR'}, "No mesh objects in Edit Mode selected.")
            return {'CANCELLED'}

        # Get cursor transform
        cursor = context.scene.cursor
        rotation = self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

        # Calculate bisect axis
        axis = self._axis_vector()
        axis_world = rotation @ axis

        # Bevel mode → two parallel planes offset ±perp*d; else one plane.
        plane_origins_world = self._plane_origins_world(context)

        success_count = 0
        cut_objects = 0  # objects where at least one plane had faces to cut

        # Execute bisect on each object
        for obj in edit_objects:
            try:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()

                is_vis = self.is_face_visible_and_valid

                # Snapshot selection into a face int layer — survives bisect
                # (split halves inherit it) and remove_doubles (merged faces
                # inherit it), so we can reselect exactly the right faces
                # afterward without leaning on select-flush heuristics.
                drop_scratch_layers(bm)
                sel_layer = self._snapshot_face_selection(bm, is_vis)
                cut_layer = stamp_cut_layer(bm, self._cut_face_set(context, bm, obj))

                # Transform plane to object space
                obj_matrix = obj.matrix_world
                plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
                plane_no.normalize()

                all_cut_edges = []
                obj_cut = False
                for origin_world in plane_origins_world:
                    # Rebuild source geom each pass — the prior bisect added
                    # new verts/edges to bm and we want the second cut to
                    # see them so it slices the freshly-split faces too.
                    source_faces = [f for f in bm.faces if f[cut_layer] == 1 and is_vis(f)]
                    if not source_faces:
                        continue
                    obj_cut = True

                    geom = list({v for f in source_faces for v in f.verts} |
                                {e for f in source_faces for e in f.edges} |
                                set(source_faces))

                    plane_co = obj_matrix.inverted() @ origin_world

                    result = bmesh.ops.bisect_plane(
                        bm,
                        geom=geom,
                        plane_co=plane_co,
                        plane_no=plane_no,
                        dist=BISECT_PLANE_EPSILON,
                    )

                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()

                    all_cut_edges.extend(
                        e for e in result.get('geom_cut', ())
                        if isinstance(e, bmesh.types.BMEdge) and e.is_valid
                    )

                if obj_cut:
                    cut_objects += 1

                if not plane_origins_world or (self.delimit_active and not obj_cut):
                    # Nothing cut here: leave the object exactly as it was.
                    drop_scratch_layers(bm)
                    continue

                if self.mark_edges_active and all_cut_edges:
                    self._apply_edge_mark(bm, all_cut_edges)

                # Merge doubles if requested
                if self.merge_doubles:
                    # Get merge distance from preferences
                    prefs = self.get_preferences(context)
                    if prefs and hasattr(prefs, 'cursor_bisect_merge_distance'):
                        merge_distance = prefs.cursor_bisect_merge_distance
                    else:
                        merge_distance = DEFAULT_MERGE_DISTANCE
                    merge_cut_doubles(bm, cut_layer, merge_distance,
                                      restrict=self.delimit_active)
                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()

                # Restore face selection from the snapshot layer, then flush
                self._restore_face_selection(bm, sel_layer, is_vis)
                drop_scratch_layers(bm)
                bm.select_flush_mode()

                bmesh.update_edit_mesh(obj.data)
                success_count += 1

            except Exception as e:
                self.report({'WARNING'}, f"Bisect failed on {obj.name}: {e}")
                self._recover_after_failed_cut(obj)
                continue

        self._refresh_hover(context)

        if self.delimit_active and cut_objects == 0 and success_count > 0:
            self._cut_report(context)
            return {'CANCELLED'}

        if success_count > 0:
            self.report({'INFO'}, f"Bisect completed on {success_count} object(s)")
        else:
            self.report({'ERROR'}, "Bisect failed on all objects")
            return {'CANCELLED'}

        return {'FINISHED'}
    
    # Part 7: Cancel and Draw Methods

    def _save_scene_props(self, context):
        """Save persistent operator state to scene properties."""
        props = context.scene.IOPS
        props.cursor_bisect_snapping = self.snapping_enabled
        props.cursor_bisect_snap_source = self.snap_source
        props.cursor_bisect_normal_axis = self.normal_axis
        props.cursor_bisect_preview_mode = self.cut_preview_mode
        props.cursor_bisect_fill_cut = self.fill_cut_mode
        props.cursor_bisect_show_distance = self.show_distance_info
        props.cursor_bisect_edge_subdivisions = self.edge_subdivisions
        props.cursor_bisect_inset_active = self.inset_active
        props.cursor_bisect_inset_distance = self.inset_distance_bu
        props.cursor_bisect_inset_input = self.inset_input_string
        props.cursor_bisect_bevel_active = self.bevel_active
        props.cursor_bisect_mark_active = self.mark_edges_active
        props.cursor_bisect_mark_type_idx = self.mark_type_idx
        props.cursor_bisect_delimit = self.delimit_active
        props.cursor_bisect_delimit_type = self.delimit_type

    def _load_scene_props(self, context):
        """Load persistent operator state from scene properties."""
        props = context.scene.IOPS
        self.snapping_enabled = props.cursor_bisect_snapping
        self.snap_source = props.cursor_bisect_snap_source
        self.normal_axis = props.cursor_bisect_normal_axis
        self.cut_preview_mode = props.cursor_bisect_preview_mode
        self.fill_cut_mode = props.cursor_bisect_fill_cut
        self.show_distance_info = props.cursor_bisect_show_distance
        self.edge_subdivisions = props.cursor_bisect_edge_subdivisions
        self.inset_active = props.cursor_bisect_inset_active
        self.inset_distance_bu = props.cursor_bisect_inset_distance
        self.inset_input_string = props.cursor_bisect_inset_input
        self.bevel_active = props.cursor_bisect_bevel_active
        self.mark_edges_active = props.cursor_bisect_mark_active
        self.mark_type_idx = props.cursor_bisect_mark_type_idx
        self.delimit_active = props.cursor_bisect_delimit
        self.delimit_type = props.cursor_bisect_delimit_type

    def cancel(self, context):
        """Clean up and cancel the operation"""
        self._save_scene_props(context)

        # Restore modifier states before cleaning up
        self.restore_modifier_states(context)
        
        if self._handle:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, 'WINDOW')
            _ACTIVE_HANDLES.discard(('POST_VIEW', self._handle))
            self._handle = None

        if self._handle_pixel:
            safe_handler_remove(self._handle_pixel, bpy.types.SpaceView3D, 'WINDOW')
            _ACTIVE_HANDLES.discard(('POST_PIXEL', self._handle_pixel))
            self._handle_pixel = None

        if self._handle_iops_text:
            safe_handler_remove(self._handle_iops_text, bpy.types.SpaceView3D, 'WINDOW')
            _ACTIVE_HANDLES.discard(('POST_PIXEL', self._handle_iops_text))
            self._handle_iops_text = None

        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        # Clear workspace status text
        context.workspace.status_text_set(None)
        context.area.tag_redraw()

    def draw(self, context):
        layout = self.layout

        # Main operator property
        layout.prop(self, "merge_doubles")

        # Show current merge distance from preferences (read-only info)
        if self.merge_doubles:
            prefs = self.get_preferences(context)
            if prefs and hasattr(prefs, 'cursor_bisect_merge_distance'):
                row = layout.row()
                row.prop(prefs, "cursor_bisect_merge_distance", text="Merge Distance")

    def calculate_snap_points(self, face):
        """Delegates to utils.picking.face_snap_points (the canonical
        implementation lifted from this operator). Subdivisions come from
        the operator's local state."""
        from ..utils.picking import face_snap_points
        return face_snap_points(face, subdivisions=self.edge_subdivisions)
    
    # Part 8: Snap Point Methods

    def find_closest_snap_point(self, context, mouse_coord, mouse_pos_world):
        """Find the snap point closest to the mouse using weighted screen +
        world distance. Delegates to utils.picking."""
        from ..utils.picking import closest_snap_point
        if not self.snap_points or not context or self.hit_obj is None:
            return None
        prefs = self.get_preferences(context)
        threshold_px = (prefs.cursor_bisect_snap_threshold
                        if prefs and hasattr(prefs, "cursor_bisect_snap_threshold")
                        else DEFAULT_SNAP_THRESHOLD)
        # Selection Bounds points sit on the box, which can float well off
        # the surface under the mouse (non-planar cut set); score them on
        # screen only, or the depth gap to the ray hit makes them unreachable.
        extra = {'screen_weight': 1.0} if self.snap_source == 'BOUNDS' else {}
        try:
            return closest_snap_point(context, self.snap_points,
                                      self.hit_obj.matrix_world,
                                      mouse_coord, mouse_pos_world,
                                      screen_threshold_px=threshold_px, **extra)
        except Exception:
            return None

    def find_closest_edge_to_mouse(self, context, event, face):
        """Find the closest edge in the face to the mouse cursor."""
        from ..utils.picking import closest_face_edge
        mouse_coord = (event.mouse_region_x, event.mouse_region_y)
        return closest_face_edge(context, face,
                                 self.hit_obj.matrix_world, mouse_coord)

    def update_snapping(self, context, mouse_pos_world):
        """Update snap points and find closest snap point"""
        if self.snap_source == 'BOUNDS':
            self._update_bounds_snapping(context, mouse_pos_world)
            return

        if not self.snapping_enabled:
            self.snap_points = []
            self.closest_snap_point = None
            return

        # Get mouse coordinates for screen-space calculation
        mouse_coord = getattr(self, '_current_mouse_coord', (0, 0))

        # If holding snap points, only update closest point calculation, not the snap points themselves
        if self.hold_snap_points and self.snap_points:
            self.closest_snap_point = self.find_closest_snap_point(context, mouse_coord, mouse_pos_world)
            return

        # Regular snap point calculation
        if not self.hit_obj or self.hit_face_index == -1:
            self.snap_points = []
            self.closest_snap_point = None
            return

        try:
            # Check if object is still in edit mode
            if self.hit_obj.mode != 'EDIT':
                self.snap_points = []
                self.closest_snap_point = None
                return

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()

            if self.hit_face_index >= len(bm.faces):
                return

            face = bm.faces[self.hit_face_index]
            self.snap_points = self.calculate_snap_points(face)

            if self.inset_active:
                self.calculate_inset_points()
                self.snap_points.extend(self.inset_points)

            self.closest_snap_point = self.find_closest_snap_point(context, mouse_coord, mouse_pos_world)

        except (IndexError, AttributeError, ValueError):
            self.snap_points = []
            self.closest_snap_point = None

    # Selection Bounds snap source

    def _cut_rotation(self, context):
        cursor = context.scene.cursor
        return self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

    def _bounds_points_key(self, context, objects):
        """Everything the cut set of every edit object depends on, or None
        when the delimiter island under the mouse is not cached yet (the
        caller then rebuilds). The rotation is not part of it: the cached
        world points are re-projected on a frame change."""
        try:
            objs_key = tuple((o.name, tuple(tuple(r) for r in o.matrix_world))
                             for o in objects)
            hover = None
            if self.delimit_active:
                if not self.hover_valid or self.hit_obj is None:
                    hover = ('none',)
                else:
                    ikey = (self.hit_obj.name, self.delimit_type,
                            self._delimit_angle(context), self._mesh_version)
                    cache = self._island_cache
                    if cache is None or cache[0] != ikey or self.hit_face_index not in cache[1]:
                        return None
                    hover = (self.hit_obj.name, cache[1])
            z_hover = None
            if self.normal_axis == 'Z':
                # In Z the hovered face is dropped from the cut set.
                z_hover = (self.hover_valid,
                           self.hit_obj.name if self.hit_obj else None,
                           self.hit_face_index)
            return (self._mesh_version, self.delimit_active, self.delimit_type,
                    objs_key, hover, z_hover)
        except ReferenceError:
            return None

    def _bounds_cut_points(self, context):
        """`(key, points)`: world-space vertices of the cut set across every
        mesh in Edit Mode, rebuilt only when the cut set can have changed."""
        objects = self._edit_mesh_objects(context)
        key = self._bounds_points_key(context, objects)
        cache = self._bounds_points_cache
        if key is not None and cache is not None and cache[0] == key:
            return cache
        points = []
        for obj in objects:
            try:
                bm = bmesh.from_edit_mesh(obj.data)
                faces = self._cut_face_set(context, bm, obj)
                points.extend(cut_set_world_points(bm, obj.matrix_world, faces))
            except (IndexError, AttributeError, ValueError, ReferenceError):
                continue
        key = self._bounds_points_key(context, objects)  # island cache is filled now
        if key is None:
            key = object()  # unknown inputs: never matches, rebuild next time
        if _np is not None:
            points = _np.asarray(points, dtype=_np.float64).reshape(-1, 3)
        self._bounds_points_cache = (key, points)
        return self._bounds_points_cache

    def _bounds_layout_for(self, context):
        """The Selection Bounds layout for the current cut frame, axis,
        subdivisions and inset; the frozen one while points are held."""
        if self.hold_snap_points and self._bounds_layout is not None:
            return self._bounds_layout
        try:
            rotation = self._cut_rotation(context)
            if rotation is None:
                return None
            points_key, points = self._bounds_cut_points(context)
            key = (points_key, tuple(rotation), self.normal_axis,
                   self.edge_subdivisions, self.inset_active, self.inset_distance_bu)
            if key != self._bounds_layout_key:
                self._bounds_layout = selection_bounds_layout(
                    points, rotation, self.normal_axis, self.edge_subdivisions,
                    self.inset_distance_bu, self.inset_active)
                self._bounds_layout_key = key
        except (AttributeError, ValueError, ReferenceError):
            self._bounds_layout = None
            self._bounds_layout_key = None
        return self._bounds_layout

    def _update_bounds_snapping(self, context, mouse_pos_world):
        """Selection Bounds: the box divisions (and inset points) replace the
        hovered face's points. Stored local to `hit_obj` like face points, so
        the closest-point search, cursor placement and drawing are shared;
        re-localised on every call so held points stay put when the hover
        moves to another object."""
        lay = self._bounds_layout_for(context)
        self.snap_points = []
        self.inset_points = []
        self.closest_snap_point = None
        if not lay or not self.snapping_enabled or self.hit_obj is None:
            return
        try:
            if self.hit_obj.mode != 'EDIT':
                return
            inv = self.hit_obj.matrix_world.inverted_safe()
        except (AttributeError, ReferenceError):
            return
        self.snap_points = [('bounds', inv @ Vector(p)) for p in lay['divisions']]
        self.inset_points = [('inset', inv @ Vector(p)) for p in lay['insets']]
        self.snap_points.extend(self.inset_points)
        mouse_coord = getattr(self, '_current_mouse_coord', (0, 0))
        self.closest_snap_point = self.find_closest_snap_point(context, mouse_coord, mouse_pos_world)

    def _refresh_bounds(self, context):
        """Selection Bounds: rebuild box and snap points after a change of
        rotation, cut axis, selection or delimiter. No-op for the Face Edge
        source (its behaviour is unchanged) and while points are held."""
        if self.snap_source != 'BOUNDS' or self.hold_snap_points:
            return
        try:
            if self.hit_obj and self.hit_face_index != -1:
                self.update_snapping(context, context.scene.cursor.location)
            else:
                self._bounds_layout_for(context)
            if self.cut_preview_mode == 'LINES':
                self.calculate_cut_preview(context)
            elif self.fill_cut_mode:
                self.calculate_fill_cut_preview(context)
        except ReferenceError:
            pass

    # Inset points methods

    def _handle_inset_input(self, context, event):
        """Handle numeric input for inset distance. Returns True if event was consumed."""
        if event.type in NUMERIC_KEYS:
            self.inset_input_string += NUMERIC_KEYS[event.type]
        elif event.type in {'PERIOD', 'NUMPAD_PERIOD'}:
            if '.' not in self.inset_input_string:
                self.inset_input_string += '.'
        elif event.type == 'BACK_SPACE':
            self.inset_input_string = self.inset_input_string[:-1]
        elif event.type in {'RET', 'NUMPAD_ENTER'}:
            return True
        else:
            return False

        self._update_inset_distance(context)
        if self.inset_active:
            self.calculate_inset_points()
        if self.bevel_active:
            self.calculate_cut_preview(context)
        if self.hit_obj and self.hit_face_index != -1:
            self.update_snapping(context, context.scene.cursor.location)
        self.update_status_bar(context)
        context.area.tag_redraw()
        return True

    def _update_inset_distance(self, context):
        """Convert the user's typed display-unit value to internal BU distance."""
        if self.inset_input_string and self.inset_input_string != '.':
            try:
                display_val = float(self.inset_input_string)
                scale, _ = self._bu_to_display_units(context)
                if scale > EPSILON:
                    self.inset_distance_bu = display_val / scale
            except ValueError:
                pass

    def calculate_inset_points(self):
        """Calculate snap points at inset distance from each endpoint of the highlighted edge."""
        self.inset_points = []
        if not self.inset_active:
            return
        if not self.hit_obj or not self.face_edges or self.edge_index >= len(self.face_edges):
            return

        try:
            if self.hit_obj.mode != 'EDIT':
                return

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.edges.ensure_lookup_table()

            edge_idx = self.face_edges[self.edge_index]
            if edge_idx >= len(bm.edges):
                return

            edge = bm.edges[edge_idx]
            v1, v2 = edge.verts

            v1_world = self.hit_obj.matrix_world @ v1.co
            v2_world = self.hit_obj.matrix_world @ v2.co
            edge_world_length = (v2_world - v1_world).length

            if edge_world_length < EPSILON or self.inset_distance_bu <= 0:
                return
            if self.inset_distance_bu >= edge_world_length:
                return

            t = self.inset_distance_bu / edge_world_length

            self.inset_points.append(('inset', v1.co.lerp(v2.co, t)))
            if abs(t - (1.0 - t)) > EPSILON:
                self.inset_points.append(('inset', v1.co.lerp(v2.co, 1.0 - t)))

        except (IndexError, AttributeError, ValueError, ReferenceError):
            pass

    def _bevel_offset_world(self, context):
        """World-space offset vector for bevel mode: perp_world * d, where
        perp is the in-face direction perpendicular to the cut line and d
        is `inset_distance_bu`. Returns None if bevel can't be computed
        (no hit face, degenerate geometry, zero distance)."""
        if not self.bevel_active:
            return None
        if not self.hit_obj or self.hit_face_index < 0:
            return None
        if self.inset_distance_bu <= EPSILON:
            return None
        try:
            if self.hit_obj.mode != 'EDIT':
                return None
            bm = bmesh.from_edit_mesh(self.hit_obj.data)
            bm.faces.ensure_lookup_table()
            if self.hit_face_index >= len(bm.faces):
                return None
            face = bm.faces[self.hit_face_index]
            obj_mat = self.hit_obj.matrix_world
            face_normal_world = (obj_mat.to_3x3() @ face.normal)
            if face_normal_world.length < EPSILON:
                return None
            face_normal_world.normalize()

            cursor = context.scene.cursor
            rotation = (self.locked_rotation if self.lock_orientation
                        else cursor.matrix.to_quaternion())
            axis = self._axis_vector()
            plane_no_world = rotation @ axis
            plane_no_world.normalize()

            # In-face direction perpendicular to the cut line: strip the
            # face-normal component out of plane_no_world.
            perp = plane_no_world - face_normal_world * plane_no_world.dot(face_normal_world)
            if perp.length < EPSILON:
                return None
            perp.normalize()
            # `inset_distance_bu` is the FULL gap between the two bevel
            # planes — each plane sits at ±d/2 from the cursor.
            return perp * (self.inset_distance_bu * 0.5)
        except (IndexError, AttributeError, ValueError, ReferenceError):
            return None

    def _plane_origins_world(self, context):
        """Return the list of world-space origins for cut planes this
        frame: a single cursor position normally, or two offset positions
        in bevel mode."""
        cursor = context.scene.cursor.location
        if self.bevel_active:
            off = self._bevel_offset_world(context)
            if off is not None:
                return [cursor + off, cursor - off]
        return [cursor]

    def draw_inset_input_text(self, context):
        """Draw the inset distance input text near the mouse cursor."""
        if not self.inset_active:
            return

        try:
            _, suffix = self._bu_to_display_units(context)
            input_str = self.inset_input_string if self.inset_input_string else "0"
            v_text = f"Inset: {input_str}{suffix}"

            mouse_x, mouse_y = self._current_mouse_coord
            text_x = mouse_x + self.distance_text_offset_x
            text_y = mouse_y + self.distance_text_offset_y - (self.distance_text_size + 6)

            region = context.region
            theme = get_theme(context)
            text_width, text_height = measure_text(v_text, theme=theme,
                                                   size_token="hud_label")

            text_x = min(max(text_x, 10), region.width - text_width - 10)
            text_y = min(max(text_y, 10), region.height - text_height - 10)

            draw_text(v_text, int(text_x), int(text_y),
                      theme=theme, role=Role.HUD_ACTIVE_VALUE, size_token="hud_label")

        except (AttributeError, KeyError, ValueError, TypeError):
            pass

    # Part 9: Face Processing Methods

    def get_connected_faces_by_depth(self, bm, start_face_index, max_depth=5):
        """Get faces connected to start face within specified depth"""
        if start_face_index >= len(bm.faces) or start_face_index < 0:
            return set()

        visited = set()
        current_depth_faces = {start_face_index}
        visited.add(start_face_index)

        for depth in range(max_depth):
            if not current_depth_faces:
                break

            next_depth_faces = set()

            for face_idx in current_depth_faces:
                if face_idx >= len(bm.faces):
                    continue

                face = bm.faces[face_idx]

                # Get connected faces through shared edges
                for edge in face.edges:
                    for linked_face in edge.link_faces:
                        if linked_face.index not in visited:
                            visited.add(linked_face.index)
                            next_depth_faces.add(linked_face.index)

            current_depth_faces = next_depth_faces

        return visited

    def is_face_visible_and_valid(self, face):
        """Check if face is visible (not hidden) and valid for processing"""
        if not face or not face.is_valid:
            return False

        # Check if face is hidden
        if face.hide:
            return False

        return True

    def _axis_vector(self):
        """Cursor-space cut normal for the current normal_axis."""
        return Vector(axis_vector(self.normal_axis))

    def _enforce_z_restrictions(self):
        """Inset / Bevel / Fill Cut are built on the cut line across the
        hovered face; in Z the plane *is* the face, so they are off."""
        if self.normal_axis != 'Z':
            return
        self.fill_cut_mode = False
        self.inset_active = False
        self.bevel_active = False
        self.inset_points = []
        self.fill_cut_preview_lines = []
        self.inset_input_string = ""

    def _z_blocked(self):
        if self.normal_axis == 'Z':
            self.report({'INFO'}, "Not available with Z axis")
            return True
        return False

    def _delimit_angle(self, context):
        prefs = self.get_preferences(context if context is not None else bpy.context)
        return float(getattr(prefs, 'cursor_bisect_delimit_angle', 30.0)) if prefs else 30.0

    def _delimited_candidates(self, context, bm, obj, candidates):
        """Apply the delimiter to `candidates` (set of face indices).
        None when the delimiter is off; an empty set when this object is
        not the one under the mouse or nothing is hovered."""
        if not self.delimit_active:
            return None
        if not self.hover_valid or self.hit_obj != obj or self.hit_face_index < 0:
            return set()
        angle = self._delimit_angle(context)
        key = (obj.name, self.delimit_type, angle, self._mesh_version)
        cached = cached_island(self._island_cache, key, self.hit_face_index)
        if cached is not None:
            return cached
        faces = delimited_faces(bm, self.hit_face_index, candidates, self.delimit_type,
                                angle, is_visible=self.is_face_visible_and_valid)
        self._island_cache = (key, frozenset(faces))
        return faces

    def _cut_face_set(self, context, bm, obj):
        """Indices of the faces a cut on `obj` works on: the selected visible
        faces if any, else all visible faces; then narrowed by the delimiter
        when it is on."""
        if self.delimit_active and (not self.hover_valid or self.hit_obj != obj):
            return set()
        is_vis = self.is_face_visible_and_valid
        candidates = {f.index for f in bm.faces if f.select and is_vis(f)}
        if not candidates:
            candidates = {f.index for f in bm.faces if is_vis(f)}
        delimited = self._delimited_candidates(context, bm, obj, candidates)
        faces = candidates if delimited is None else delimited
        hovered = self.hit_face_index if (self.hover_valid and self.hit_obj == obj) else None
        return cut_set_for_axis(faces, self.normal_axis, hovered)

    def _refresh_hover(self, context):
        """Re-pick the face under the mouse after a cut: remove_doubles can
        renumber faces, so the remembered index may now name another face."""
        from ..utils.picking import raycast_edit_meshes
        self._island_cache = None
        objects = self._edit_mesh_objects(context)
        if not objects or context.region is None:
            self.hover_valid = False
            return
        result, loc, normal, face_index, obj, _ = raycast_edit_meshes(
            context, self._current_mouse_coord, objects,
            cache=self._bvh_cache, version=self._mesh_version)
        if result and obj and obj.mode == 'EDIT':
            self.hit_obj = obj
            self.hit_face_index = face_index
            self.last_face_index = face_index
            self.hit_location = loc
            self.hit_normal = normal
            self.hover_valid = True
        else:
            self.hover_valid = False

    def _cut_report(self, context):
        """Explain an empty delimited cut."""
        if not self.hover_valid or self.hit_obj is None:
            self.report({'INFO'}, "Delimiter: no face under the cursor")
        else:
            self.report({'INFO'}, "Delimiter: face under the cursor is not selected")

    def get_faces_to_process(self, bm, obj, face_depth, context=None):
        """Get faces to process based on selection and visibility"""
        if self.delimit_active:
            return self._cut_face_set(context, bm, obj)

        faces_to_process = set()

        # Get selected faces that are visible
        selected_faces = [f for f in bm.faces if f.select and self.is_face_visible_and_valid(f)]

        if selected_faces:
            # ONLY use selected faces - no connectivity expansion for preview
            for face in selected_faces:
                faces_to_process.add(face.index)
        else:
            # If we have a hit face from raycast, use connectivity-based selection
            if self.hit_obj == obj and self.hit_face_index != -1:
                if self.hit_face_index < len(bm.faces):
                    hit_face = bm.faces[self.hit_face_index]
                    if self.is_face_visible_and_valid(hit_face):
                        connected_faces = self.get_connected_faces_by_depth(bm, self.hit_face_index, face_depth)
                        # Filter connected faces to only include visible ones
                        for face_idx in connected_faces:
                            if face_idx < len(bm.faces):
                                connected_face = bm.faces[face_idx]
                                if self.is_face_visible_and_valid(connected_face):
                                    faces_to_process.add(face_idx)

            # If still no faces to process, use all visible faces
            if not faces_to_process:
                # Get preferences for max faces limit (use bpy.context if context not provided)
                ctx = context if context is not None else bpy.context
                prefs = self.get_preferences(ctx)
                if prefs and hasattr(prefs, 'cursor_bisect_max_faces'):
                    max_faces = prefs.cursor_bisect_max_faces
                else:
                    max_faces = DEFAULT_MAX_FACES

                visible_faces = [f.index for f in bm.faces if self.is_face_visible_and_valid(f)]
                faces_to_process = set(visible_faces[:max_faces])

        return faces_to_process
    
    # Part 10: Cut Preview Calculation

    def calculate_cut_preview(self, context):
        """Calculate cut preview lines for selected mesh objects using face connectivity with improved visibility"""
        self.cut_preview_lines = []

        if self.cut_preview_mode == 'PLANE':
            return  # No line calculation needed for plane mode

        # Get all selected mesh objects in edit mode
        edit_objects = [obj for obj in context.selected_objects
                       if obj.type == 'MESH' and obj.mode == 'EDIT']

        if not edit_objects:
            return

        # Get cursor transform
        cursor = context.scene.cursor
        rotation = self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

        # Calculate bisect axis
        axis = self._axis_vector()
        if not rotation:
            rotation = Vector((1, 0, 0))
        axis_world = rotation @ axis

        # Get preferences for depth setting and line elevation
        prefs = self.get_preferences(context)
        if prefs and hasattr(prefs, 'cursor_bisect_face_depth'):
            face_depth = prefs.cursor_bisect_face_depth
        else:
            face_depth = DEFAULT_FACE_DEPTH
        
        # In bevel mode there are two parallel cut planes offset along the
        # in-face perpendicular by ±d; otherwise a single plane through
        # the cursor.
        plane_origins_world = self._plane_origins_world(context)

        # Calculate cut preview for each object
        for obj in edit_objects:
          try:
            # Check if object is still in edit mode
            if obj.mode != 'EDIT':
                continue

            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            obj_matrix = obj.matrix_world
            plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
            plane_no.normalize()

            # Get faces to process with improved selection and visibility checking
            faces_to_process = self.get_faces_to_process(bm, obj, face_depth, context)

            if not faces_to_process:
                continue
          except (IndexError, AttributeError, ValueError):
            continue

          for origin_world in plane_origins_world:
            try:
                plane_co = obj_matrix.inverted() @ origin_world

                # Collect intersection points per face to create connected lines
                face_intersections = {}

                # Process only edges that belong to our target faces
                processed_edges = set()
                for face_idx in faces_to_process:
                    if face_idx >= len(bm.faces):
                        continue
                    face = bm.faces[face_idx]
                    if not self.is_face_visible_and_valid(face):
                        continue
                    if not face_straddles_plane(face, plane_co, plane_no, BISECT_PLANE_EPSILON):
                        continue

                    # Process each edge of this face
                    for edge in face.edges:
                        if edge.index in processed_edges:
                            continue
                        processed_edges.add(edge.index)

                        # Only process if edge belongs to our target faces
                        edge_faces = [f.index for f in edge.link_faces if f.index in faces_to_process and self.is_face_visible_and_valid(f)]
                        if not edge_faces:
                            continue

                        v1, v2 = edge.verts

                        # Calculate distances from plane
                        d1 = (v1.co - plane_co).dot(plane_no)
                        d2 = (v2.co - plane_co).dot(plane_no)

                        # Check if edge crosses the plane (different signs or one is zero)
                        if abs(d1) < EPSILON and abs(d2) < EPSILON:
                            continue  # edge lies in the plane: nothing to cut there
                        if (d1 * d2 < 0) or (abs(d1) < EPSILON) or (abs(d2) < EPSILON):
                            # Calculate intersection point
                            if abs(d1 - d2) > EPSILON:  # Avoid division by zero
                                t = d1 / (d1 - d2)
                                intersection = v1.co.lerp(v2.co, t)

                                # Transform to world space. The line is lifted
                                # off the surface at draw time, in pixels.
                                world_intersection = obj_matrix @ intersection

                                # Group intersections by faces that share this edge
                                for face_idx in edge_faces:
                                    if face_idx not in face_intersections:
                                        face_intersections[face_idx] = []
                                    face_intersections[face_idx].append(world_intersection)

                # Create connected lines within each face
                for face_idx, intersections in face_intersections.items():
                    if len(intersections) >= 2:
                        # Sort intersections to create proper connections
                        intersections.sort(key=lambda p: (p.x, p.y, p.z))

                        # Connect consecutive intersection points
                        for i in range(len(intersections) - 1):
                            self.cut_preview_lines.append((intersections[i], intersections[i + 1]))

                        # If more than 2 points, this might be a complex intersection
                        # Connect the last point to the first to close if it's a polygon cut
                        if len(intersections) > 2:
                            # Only close if the points form a reasonable polygon
                            dist_to_close = (intersections[-1] - intersections[0]).length
                            avg_edge_length = sum((intersections[i] - intersections[i-1]).length
                                                for i in range(1, len(intersections))) / (len(intersections) - 1)

                            # Close the loop if the closing distance is reasonable
                            if dist_to_close <= avg_edge_length * 2:
                                self.cut_preview_lines.append((intersections[-1], intersections[0]))

            except (IndexError, AttributeError, ValueError):
                continue

        if self.fill_cut_mode:
            self.calculate_fill_cut_preview(context)

    def get_fill_cut_positions(self, context=None):
        """Get world-space cut positions along the highlighted edge based on subdivision count.
        With the Selection Bounds snap source: one position per division /
        inset offset along the cut axis of the cut set's oriented box."""
        if self.snap_source == 'BOUNDS':
            lay = self._bounds_layout_for(context if context is not None else bpy.context)
            return [Vector(p) for p in lay['positions']] if lay else []
        if not self.hit_obj or not self.face_edges or self.edge_index >= len(self.face_edges):
            return []

        try:
            if self.hit_obj.mode != 'EDIT':
                return []

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.edges.ensure_lookup_table()

            edge_idx = self.face_edges[self.edge_index]
            if edge_idx >= len(bm.edges):
                return []

            edge = bm.edges[edge_idx]
            v1, v2 = edge.verts

            positions = []

            # Subdivision cuts: skip the fallback midpoint when inset points provide positions
            if self.inset_active and self.inset_points:
                num_cuts = self.edge_subdivisions
            else:
                num_cuts = max(1, self.edge_subdivisions)

            for i in range(1, num_cuts + 1):
                t = i / (num_cuts + 1)
                point_local = v1.co.lerp(v2.co, t)
                point_world = self.hit_obj.matrix_world @ point_local
                positions.append(point_world)

            if self.inset_active and self.inset_points:
                for _, pt_local in self.inset_points:
                    pt_world = self.hit_obj.matrix_world @ pt_local
                    positions.append(pt_world)

            return positions

        except (IndexError, AttributeError, ValueError, ReferenceError):
            return []

    def calculate_fill_cut_preview(self, context):
        """Calculate preview lines for fill cut at each position along the highlighted edge"""
        self.fill_cut_preview_lines = []

        if not self.fill_cut_mode:
            return

        positions = self.get_fill_cut_positions(context)
        if not positions:
            return

        cursor = context.scene.cursor
        rotation = self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

        axis = self._axis_vector()
        if not rotation:
            return
        axis_world = rotation @ axis

        prefs = self.get_preferences(context)
        if prefs and hasattr(prefs, 'cursor_bisect_face_depth'):
            face_depth = prefs.cursor_bisect_face_depth
        else:
            face_depth = DEFAULT_FACE_DEPTH


        edit_objects = [obj for obj in context.selected_objects
                       if obj.type == 'MESH' and obj.mode == 'EDIT']

        for cut_pos in positions:
            for obj in edit_objects:
                try:
                    if obj.mode != 'EDIT':
                        continue

                    bm = bmesh.from_edit_mesh(obj.data)
                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()

                    obj_matrix = obj.matrix_world
                    plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
                    plane_no.normalize()
                    plane_co = obj_matrix.inverted() @ cut_pos

                    faces_to_process = self.get_faces_to_process(bm, obj, face_depth, context)
                    if not faces_to_process:
                        continue

                    face_intersections = {}
                    processed_edges = set()

                    for face_idx in faces_to_process:
                        if face_idx >= len(bm.faces):
                            continue
                        face = bm.faces[face_idx]
                        if not self.is_face_visible_and_valid(face):
                            continue
                        if not face_straddles_plane(face, plane_co, plane_no, BISECT_PLANE_EPSILON):
                            continue

                        for edge in face.edges:
                            if edge.index in processed_edges:
                                continue
                            processed_edges.add(edge.index)

                            edge_faces = [f.index for f in edge.link_faces
                                         if f.index in faces_to_process
                                         and self.is_face_visible_and_valid(f)]
                            if not edge_faces:
                                continue

                            v1, v2 = edge.verts
                            d1 = (v1.co - plane_co).dot(plane_no)
                            d2 = (v2.co - plane_co).dot(plane_no)

                            if abs(d1) < EPSILON and abs(d2) < EPSILON:
                                continue  # edge lies in the plane: nothing to cut there
                            if (d1 * d2 < 0) or (abs(d1) < EPSILON) or (abs(d2) < EPSILON):
                                if abs(d1 - d2) > EPSILON:
                                    t = d1 / (d1 - d2)
                                    intersection = v1.co.lerp(v2.co, t)

                                    world_pt = obj_matrix @ intersection

                                    for fi in edge_faces:
                                        if fi not in face_intersections:
                                            face_intersections[fi] = []
                                        face_intersections[fi].append(world_pt)

                    for face_idx, intersections in face_intersections.items():
                        if len(intersections) >= 2:
                            intersections.sort(key=lambda p: (p.x, p.y, p.z))
                            for i in range(len(intersections) - 1):
                                self.fill_cut_preview_lines.append(
                                    (intersections[i], intersections[i + 1]))

                            if len(intersections) > 2:
                                dist_to_close = (intersections[-1] - intersections[0]).length
                                avg_edge_length = sum(
                                    (intersections[i] - intersections[i - 1]).length
                                    for i in range(1, len(intersections))
                                ) / (len(intersections) - 1)
                                if dist_to_close <= avg_edge_length * 2:
                                    self.fill_cut_preview_lines.append(
                                        (intersections[-1], intersections[0]))

                except (IndexError, AttributeError, ValueError):
                    continue

    def execute_fill_cut(self, context):
        """Execute bisect at each snap position along the highlighted edge"""
        positions = self.get_fill_cut_positions(context)
        if not positions:
            self.report({'WARNING'}, "No fill cut positions available")
            return {'CANCELLED'}

        bpy.ops.ed.undo_push(message="Fill Cut Bisect")
        self._mesh_version += 1

        edit_objects = [obj for obj in context.selected_objects
                       if obj.type == 'MESH' and obj.mode == 'EDIT']

        if not edit_objects:
            self.report({'ERROR'}, "No mesh objects in Edit Mode selected.")
            return {'CANCELLED'}

        cursor = context.scene.cursor
        rotation = self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

        axis = self._axis_vector()
        axis_world = rotation @ axis

        total_cuts = 0
        cut_objects = 0  # objects where the (delimited) face set was non-empty

        for obj in edit_objects:
            try:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()

                is_vis = self.is_face_visible_and_valid

                # Snapshot selection once. The int layer propagates through every
                # subsequent bisect_plane (split faces inherit) and through the
                # final remove_doubles, so we restore selection exactly at the end.
                drop_scratch_layers(bm)
                sel_layer = self._snapshot_face_selection(bm, is_vis)
                had_selection = any(f[sel_layer] == 1 for f in bm.faces)
                cut_layer = stamp_cut_layer(bm, self._cut_face_set(context, bm, obj))
                if any(f[cut_layer] == 1 for f in bm.faces):
                    cut_objects += 1
                elif self.delimit_active:
                    # Nothing to cut here: leave the object exactly as it was.
                    drop_scratch_layers(bm)
                    continue

                for cut_pos in positions:
                    obj_matrix = obj.matrix_world
                    plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
                    plane_no.normalize()
                    plane_co = obj_matrix.inverted() @ cut_pos

                    # Pick target faces for this iteration from the cut layer
                    # so it stays consistent after splits.
                    tracked = [f for f in bm.faces
                               if f[cut_layer] == 1 and is_vis(f)]

                    if not tracked:
                        break

                    geom = list({v for f in tracked for v in f.verts} |
                                {e for f in tracked for e in f.edges} |
                                set(tracked))

                    result = bmesh.ops.bisect_plane(
                        bm, geom=geom, plane_co=plane_co, plane_no=plane_no,
                        dist=BISECT_PLANE_EPSILON)

                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()

                    cut_edges = [e for e in result.get('geom_cut', ())
                                 if isinstance(e, bmesh.types.BMEdge) and e.is_valid]

                    if self.mark_edges_active and cut_edges:
                        self._apply_edge_mark(bm, cut_edges)

                    total_cuts += 1

                if self.merge_doubles:
                    prefs = self.get_preferences(context)
                    if prefs and hasattr(prefs, 'cursor_bisect_merge_distance'):
                        merge_distance = prefs.cursor_bisect_merge_distance
                    else:
                        merge_distance = DEFAULT_MERGE_DISTANCE
                    merge_cut_doubles(bm, cut_layer, merge_distance,
                                      restrict=self.delimit_active)
                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()

                # Restore face selection from the snapshot, then flush
                if had_selection:
                    self._restore_face_selection(bm, sel_layer, is_vis)
                drop_scratch_layers(bm)
                bm.select_flush_mode()
                bmesh.update_edit_mesh(obj.data)

            except Exception as e:
                self.report({'WARNING'}, f"Fill cut failed on {obj.name}: {e}")
                self._recover_after_failed_cut(obj)
                continue

        self._refresh_hover(context)

        if self.delimit_active and cut_objects == 0:
            self._cut_report(context)
            return {'CANCELLED'}

        if total_cuts > 0:
            self.report({'INFO'},
                       f"Fill cut: {total_cuts} cuts on {len(edit_objects)} object(s)")
        else:
            self.report({'ERROR'}, "Fill cut failed")
            return {'CANCELLED'}

        return {'FINISHED'}

    # Draw Help text — unified HUD overlay
    def draw_iops_text(self, context):
        # Resync HUD state at draw time so handlers that mutate state and
        # only call tag_redraw (e.g. _handle_inset_input typing digits)
        # don't leave the header showing stale values until the next
        # mouse-move modal tick. Why: in modal() _sync_hud_state runs
        # BEFORE the input handlers, so a same-frame state change isn't
        # reflected without this draw-time refresh.
        self._sync_hud_state()
        helpo = getattr(self, "help", None)
        hud = getattr(self, "hud", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            hud.draw(context, last_event)

    def _sync_hud_state(self):
        """Reflect current operator state in the HUD overlay items."""
        if getattr(self, "help", None) is None:
            return
        s = self.help.set_state
        s("S", ItemState.ON if self.snapping_enabled else ItemState.OFF)
        s("Shift+S", ItemState.ON if self.snap_source == 'BOUNDS' else ItemState.OFF)
        s("D", ItemState.ON if self.hold_snap_points else ItemState.OFF)
        if self.normal_axis == 'Z':
            s("F", ItemState.DISABLED)
            s("V", ItemState.DISABLED)
            s("B", ItemState.DISABLED)
        else:
            s("F", ItemState.ON if self.fill_cut_mode else ItemState.OFF)
            s("V", ItemState.ON if self.inset_active else ItemState.OFF)
            s("B", ItemState.ON if self.bevel_active else ItemState.OFF)
        s("M", ItemState.ON if self.mark_edges_active else ItemState.OFF)
        s("A", ItemState.ON if self.lock_orientation else ItemState.OFF)
        s("P", ItemState.ON if self.cut_preview_mode == 'PLANE' else ItemState.OFF)
        s("I", ItemState.ON if self.show_distance_info else ItemState.OFF)
        s("L", ItemState.ON if self.delimit_active else ItemState.OFF)
        self._sync_hud_header()

    def _sync_hud_header(self):
        """Update HUD header lines: distance info, mark type (while M is on), inset/bevel prompt."""
        if getattr(self, "hud", None) is None:
            return
        lines = []
        if self.show_distance_info:
            try:
                info = self.get_edge_split_distances(bpy.context)
            except Exception:
                info = None
            if info:
                unit = info.get("unit", "")
                total = self._fmt(info["total"])
                split = self._fmt(info["split"])
                lines.append(f"{info.get('label', 'Edge')}: {total}{unit}")
                lines.append(f"Split: {split}{unit}")

        if self.snap_source == 'BOUNDS':
            lines.append(f"Snap Source: {SNAP_SOURCE_LABELS['BOUNDS']}")

        if self.mark_edges_active:
            lines.append(f"Mark: {self._current_mark_type()}")

        if self.delimit_active:
            lines.append(f"Delimit: {DELIMIT_LABELS[self.delimit_type]}")

        if self.inset_active or self.bevel_active:
            scale = bpy.context.scene.unit_settings.scale_length or 1.0
            if self.inset_input_string:
                val = self.inset_input_string
            else:
                val = self._fmt(self.inset_distance_bu * scale)
            if self.inset_active:
                lines.append(f"Inset: {val}")
            if self.bevel_active:
                lines.append(f"Bevel: {val}")

        self.hud.set_header(*lines)

    def _build_hud(self, context):
        from ..ui.draw.theme import get_theme
        hud = HUDOverlay("cursor_bisect")
        hud.title = "Bisect"
        hud.bind_region(context.region)
        helpo = HelpOverlay("cursor_bisect")
        helpo.add_section(HUDSection("Bisect", [
            HUDItem("Snap",             "S",          ItemState.ON if self.snapping_enabled else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Snap Source",      "Shift+S",    ItemState.ON if self.snap_source == 'BOUNDS' else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Subdivide",        "Ctrl+Wheel", ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Hold Points",      "D",          ItemState.ON if self.hold_snap_points else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Fill Cut",         "F",          ItemState.ON if self.fill_cut_mode else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Inset Points",     "V",          ItemState.ON if self.inset_active else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Bevel Points",     "B",          ItemState.ON if self.bevel_active else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Mark Cut Edges",   "M",          ItemState.ON if self.mark_edges_active else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Mark Type",        "N",          ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Delimiter",        "L",          ItemState.ON if self.delimit_active else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Delimit Type",     "Shift+L",    ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Select Face",      "RMB",        ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Coplanar Select",  "Shift+RMB",  ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Rotate",           "Alt+Wheel",  ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Lock Orientation", "A",          ItemState.ON if self.lock_orientation else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Select Direction", "X",          ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("World Align",      "W",          ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Preview",          "P",          ItemState.ON if self.cut_preview_mode == 'PLANE' else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Distance Info",    "I",          ItemState.ON if self.show_distance_info else ItemState.OFF, default_state=ItemState.OFF),
            HUDItem("Help / Toggle HUD","H",          ItemState.ON,  default_state=ItemState.OFF, always_show=True),
            HUDItem("Bisect",           "LMB",        ItemState.ON,  default_state=ItemState.OFF, always_show=True),
            HUDItem("Finish",           "Space",      ItemState.ON,  default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",           "Esc",        ItemState.ON,  default_state=ItemState.OFF, always_show=True),
        ]))
        helpo.bind_region(context.region)
        hud.mirror_help(helpo)
        return hud, helpo

    # Part 11: Distance Text Drawing

    def draw_mouse_distance_text(self, context):
        """Draw distance information as text near the mouse cursor"""
        prefs = self.get_preferences(context)
        if not prefs:
            return

        # Get distance information
        distance_info = self.get_edge_split_distances(context)
        if not distance_info:
            return

        try:
            total = distance_info['total']
            split = distance_info['split']
            unit = distance_info['unit']
            label = distance_info.get('label', 'Edge')
            distance_text = f"{label}: {self._fmt(total)}{unit} | Split: {self._fmt(split)}{unit}"

            # Get current mouse position and offsets
            mouse_x, mouse_y = self._current_mouse_coord
            text_x = mouse_x + self.distance_text_offset_x
            text_y = mouse_y + self.distance_text_offset_y

            # Ensure text stays within screen bounds
            region = context.region
            theme = get_theme(context)
            text_width, text_height = measure_text(distance_text, theme=theme,
                                                    size_token="hud_label")

            text_x = min(max(text_x, 10), region.width - text_width - 10)
            text_y = min(max(text_y, 10), region.height - text_height - 10)

            draw_text(distance_text, int(text_x), int(text_y),
                      theme=theme, role=Role.HUD_ACTIVE_VALUE, size_token="hud_label")

        except (AttributeError, KeyError, ValueError, TypeError) as e:
            print(f"Error in draw_mouse_distance_text: {e}")


    def draw_callback(self, context):
        """Draw the bisect plane preview, snap points, and distance text - with debug info"""
        # Safety check: ensure the operator is still valid
        try:
            _ = self.lock_orientation
        except ReferenceError:
            return

        if not context or not context.scene:
            return

        # Multi-viewport guard: only draw in the region where the modal was invoked.
        mr = getattr(self, "_modal_region", None)
        if mr is not None and context.region.as_pointer() != mr:
            return

        try:
            # Get preferences for all colors and sizes
            prefs = self.get_preferences(context)

            origin = context.scene.cursor.location
            rotation = self.locked_rotation if self.lock_orientation else context.scene.cursor.matrix.to_quaternion()
            mat = rotation.to_matrix()

            # Calculate plane vectors based on normal axis
            if self.normal_axis == 'X':
                u = mat @ Vector((0, 1, 0))
                v = mat @ Vector((0, 0, 1))
            elif self.normal_axis == 'Y':
                u = mat @ Vector((1, 0, 0))
                v = mat @ Vector((0, 0, 1))
            else:  # Z: the cursor's XY plane
                u = mat @ Vector((1, 0, 0))
                v = mat @ Vector((0, 1, 0))

            rv3d = context.space_data.region_3d
            size = PREVIEW_PLANE_HALF_PX * px_world_at(context.region, rv3d, origin) if rv3d else 2.0
            corners = [
                origin + (u + v) * size,
                origin + (u - v) * size,
                origin + (-u - v) * size,
                origin + (-u + v) * size,
            ]

            # Draw the plane fill (when in PLANE mode)
            if self.cut_preview_mode == 'PLANE':
                # Expand TRI_FAN(corners[0..3]) into two triangles
                fill_tris = [
                    corners[0], corners[1], corners[2],
                    corners[0], corners[2], corners[3],
                ]
                with draw_scope(blend="ALPHA", depth="LESS"):
                    draw.tris(fill_tris, role=Role.PREVIEW_LINE, context=context)

                # Plane outline (LINE_STRIP closed)
                outline_coords = corners + [corners[0]]
                with draw_scope(blend="ALPHA", depth="LESS"):
                    draw.polyline(outline_coords, role=Role.ACTIVE_LINE,
                                  context=context)

            # Draw cut preview lines (when in LINES mode)
            if self.cut_preview_mode == 'LINES' and self.cut_preview_lines:
                try:
                    preview_coords = []
                    for line_start, line_end in self.cut_preview_lines:
                        preview_coords.extend([line_start, line_end])

                    if preview_coords:
                        # Lift the lines a couple of pixels toward the viewer
                        # so they win the depth test against the face they
                        # lie on, at any mesh size or zoom; a world-unit
                        # offset z-fights on big meshes.
                        rv3d = context.space_data.region_3d
                        if rv3d is not None:
                            preview_coords = pull_toward_viewer(
                                context.region, rv3d, preview_coords, PREVIEW_PULL_PX)
                        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
                            draw.edges_3d(preview_coords, role=Role.PREVIEW_LINE,
                                          context=context)

                except (IndexError, AttributeError, ReferenceError, ValueError, TypeError):
                    pass

            # Draw fill cut preview lines
            if self.fill_cut_mode and self.fill_cut_preview_lines:
                try:
                    fill_coords = []
                    for line_start, line_end in self.fill_cut_preview_lines:
                        fill_coords.extend([line_start, line_end])

                    if fill_coords:
                        with draw_scope(blend="ALPHA", depth="ALWAYS"):
                            draw.edges_3d(fill_coords, role=Role.PREVIEW_LINE,
                                          context=context)

                except (IndexError, AttributeError, ReferenceError, ValueError, TypeError):
                    pass

            # Draw the lock-anchor edge (snapshot) in LOCKED color first…
            if self.lock_orientation and self.locked_edge_world is not None:
                try:
                    with draw_scope(blend="ALPHA", depth="ALWAYS"):
                        draw.edges_3d(list(self.locked_edge_world),
                                      role=Role.LOCKED_LINE, context=context)
                except (AttributeError, ValueError, ReferenceError, TypeError):
                    pass

            # …then the live mouse-hover edge in ACTIVE color.
            if (self.hit_obj and self.face_edges
                    and 0 <= self.edge_index < len(self.face_edges)):
                try:
                    if self.hit_obj.mode == 'EDIT':
                        bm = bmesh.from_edit_mesh(self.hit_obj.data)
                        bm.edges.ensure_lookup_table()
                        edge_idx = self.face_edges[self.edge_index]
                        if edge_idx < len(bm.edges):
                            v1, v2 = bm.edges[edge_idx].verts
                            mw = self.hit_obj.matrix_world
                            world_coords = [mw @ v1.co.copy(), mw @ v2.co.copy()]
                            with draw_scope(blend="ALPHA", depth="ALWAYS"):
                                draw.edges_3d(world_coords,
                                              role=Role.ACTIVE_LINE,
                                              context=context)
                except (IndexError, AttributeError, ValueError, ReferenceError, TypeError):
                    pass

            # Selection Bounds box wire (guide), under the snap points.
            if self.snap_source == 'BOUNDS' and self._bounds_layout:
                try:
                    wire = [p for edge in self._bounds_layout['wire'] for p in edge]
                    if wire:
                        with draw_scope(blend="ALPHA", depth="ALWAYS"):
                            draw.edges_3d(wire, role=Role.BBOX, context=context)
                except (KeyError, AttributeError, ReferenceError, ValueError, TypeError):
                    pass

            # Snap / inset points are drawn LAST so they sit on top of edges.
            if self.snapping_enabled and self.snap_points and self.hit_obj:
                try:
                    mw = self.hit_obj.matrix_world
                    regular = [mw @ p for kind, p in self.snap_points if kind != 'center']
                    centers = [mw @ p for kind, p in self.snap_points if kind == 'center']
                    snap_role = Role.PREVIEW_POINT if self.hold_snap_points else Role.POINT
                    with draw_scope(blend="ALPHA", depth="ALWAYS"):
                        if regular:
                            draw.points(regular, role=snap_role, context=context)
                        if centers:
                            draw.points(centers, role=Role.ACTIVE_POINT,
                                        context=context)
                        if self.closest_snap_point:
                            _, _, closest_world = self.closest_snap_point
                            closest_role = (Role.ACTIVE_POINT if self.hold_snap_points
                                            else Role.CLOSEST_POINT)
                            draw.points([closest_world], role=closest_role,
                                        context=context)
                except (IndexError, AttributeError, ReferenceError, ValueError):
                    pass

            if self.inset_active and self.inset_points and self.hit_obj:
                try:
                    v_coords = [self.hit_obj.matrix_world @ pt
                                for _, pt in self.inset_points]
                    if v_coords:
                        with draw_scope(blend="ALPHA", depth="ALWAYS"):
                            draw.points(v_coords, role=Role.PREVIEW_POINT,
                                        context=context)
                except (IndexError, AttributeError, ReferenceError, ValueError):
                    pass


        except (ReferenceError, AttributeError, ValueError) as e:
            print(f"DEBUG: Exception in draw_callback: {e}")
            return

    # Part 14: Final Methods and Registration
    def draw_distance_text_callback(self, context):
        # Distance and inset info both live inside the HUD header now —
        # no separate cursor-anchored text drawing.
        return

    @staticmethod
    def _edit_mesh_objects(context):
        """Every mesh object currently in Edit Mode (multi-object editing)."""
        return [o for o in context.objects_in_mode if o.type == 'MESH']

    def mouse_raycast(self, context, event, *, full=False):
        """Raycast the edit-mode BMesh of every mesh in Edit Mode.

        The cast goes at the cage, not at the evaluated mesh: `scene.ray_cast`
        indexes the modifier output, so with Triangulate / Mirror / Bevel on
        its face index names the wrong `bm.faces` entry or falls outside the
        range and the hover looks like it shoots straight through the mesh.

        `full=False` (default, used for MOUSEMOVE hover tracking): one ray
        from the cursor; if it misses, return miss immediately. Keeps the
        modal handler fast so the HUD/redraw stays responsive when the
        cursor leaves the mesh.

        `full=True` (used by commit actions like LMB / fill-cut): adds the
        8-corner viewport fallback so a click on a very large face whose
        center is occluded still resolves."""
        from ..utils.picking import (
            raycast_edit_meshes, raycast_edit_meshes_with_corner_fallback,
        )
        objects = self._edit_mesh_objects(context)
        if not objects:
            return False, None, None, None, None, None
        coord = (event.mouse_region_x, event.mouse_region_y)
        cast = raycast_edit_meshes_with_corner_fallback if full else raycast_edit_meshes
        return cast(context, coord, objects,
                    cache=self._bvh_cache, version=self._mesh_version)

    def align_cursor_orientation(self):
        """Align cursor to selected edge and face normal"""
        if not self.hit_obj or self.hit_face_index == -1:
            return

        try:
            # Check if object is still in edit mode
            if self.hit_obj.mode != 'EDIT':
                return

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            if self.hit_face_index >= len(bm.faces):
                return

            face = bm.faces[self.hit_face_index]
            if not face.edges:
                return

            # Cache face edges if not already done
            if not self.face_edges:
                self.face_edges = [e.index for e in face.edges]

            # Ensure edge index is valid
            self.edge_index = self.edge_index % len(self.face_edges)
            edge_index = self.face_edges[self.edge_index]

            if edge_index >= len(bm.edges):
                return

            edge = bm.edges[edge_index]
            v1, v2 = edge.verts

            # Get vectors in object space first
            edge_vec_local = (v2.co - v1.co).normalized()
            normal_local = face.normal.normalized()

            # Transform to world space using object matrix
            obj_matrix = self.hit_obj.matrix_world
            edge_vec_world = (obj_matrix.to_3x3() @ edge_vec_local).normalized()
            normal_world = (obj_matrix.to_3x3() @ normal_local).normalized()

            # Build coordinate system
            x_axis = edge_vec_world
            z_axis = normal_world
            y_axis = z_axis.cross(x_axis).normalized()
            x_axis = y_axis.cross(z_axis).normalized()  # Recompute for orthogonality

            # Create rotation matrix and convert to quaternion
            rot_matrix = Matrix((x_axis, y_axis, z_axis)).transposed()
            self.locked_rotation = rot_matrix.to_quaternion()

            # Apply to cursor
            cursor = bpy.context.scene.cursor
            cursor.rotation_mode = 'QUATERNION'
            cursor.rotation_quaternion = self.locked_rotation

        except (IndexError, AttributeError, ValueError, ReferenceError):
            pass

    def align_cursor_to_world(self, context, world_axis):
        """Align cursor's normal_axis (the cut normal) to the given world axis."""
        rot_matrix = world_align_rotation(self.normal_axis, world_axis)

        # Convert matrix to quaternion
        world_rotation = rot_matrix.to_quaternion()
        
        # Apply to cursor
        cursor = context.scene.cursor
        cursor.rotation_mode = 'QUATERNION'
        cursor.rotation_quaternion = world_rotation
        
        # Update locked rotation if orientation is locked
        if self.lock_orientation:
            self.locked_rotation = world_rotation
        
        # Update cut preview if in lines mode
        if self.cut_preview_mode == 'LINES':
            self.calculate_cut_preview(context)

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "View3D not found")
            return {'CANCELLED'}

        # Store modifier states before any operation
        self.store_modifier_states(context)
        
        # Disable specific modifiers for better bisect operation
        self.disable_modifiers_for_bisect(context)

        # Load persistent user toggles from scene
        self._load_scene_props(context)
        self._enforce_z_restrictions()

        # Reset runtime/raycast state
        self._bvh_cache = {}
        self._mesh_version += 1
        self.hit_location = None
        self.hit_normal = None
        self.hit_obj = None
        self.hit_face_index = -1
        self.edge_index = 0
        self.face_edges = []
        self.lock_orientation = False
        self.locked_rotation = None
        self.snap_points = []
        self.closest_snap_point = None
        self.hold_snap_points = False
        self.last_face_index = -1
        self.cut_preview_lines = []
        self.fill_cut_preview_lines = []
        self.inset_points = []
        self._bounds_layout = None
        self._bounds_layout_key = None
        self._bounds_points_cache = None
        self._current_mouse_coord = (0, 0)

        # Build unified HUD overlay
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._modal_region = context.region.as_pointer()
        self.hud, self.help = self._build_hud(context)

        # Drop any leftover draw handlers from prior invocations whose Python
        # operator was destroyed before invoke->modal cleanup ran (e.g. when
        # the addon was reloaded mid-operation, or a previous exit path
        # skipped _remove_handles). Without this they keep firing with a dead
        # self and overdraw the current modal.
        _drop_stale_handles()

        # Add draw handler
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self.draw_callback, (context,), 'WINDOW', 'POST_VIEW', tick=True)
        self._handle_pixel = safe_handler_add(
            bpy.types.SpaceView3D, self.draw_distance_text_callback, (context,), 'WINDOW', 'POST_PIXEL', tick=True)
        self._handle_iops_text = safe_handler_add(
            bpy.types.SpaceView3D, self.draw_iops_text,(context,), "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.update({
            ('POST_VIEW',  self._handle),
            ('POST_PIXEL', self._handle_pixel),
            ('POST_PIXEL', self._handle_iops_text),
        })
        # Add timer for smoother updates
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)

        # Set workspace status text
        self.update_status_bar(context)

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}