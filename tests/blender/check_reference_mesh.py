"""Smart Edge Slide on the reference mesh: a standalone headless check, not part
of the regular suite (tests/conftest.py ignores tests/blender, and nothing else
runs it).

The reference mesh is the wall piece the operator was designed on (spec,
"Reference case"), exported as a JSON snapshot with the keys ``verts`` (local
coordinates), ``faces`` (vertex index lists), ``hidden_faces``, ``chain`` (the
reference chain's vertex indices, in order) and ``matrix_world``. Run from the
repo root:

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/blender/check_reference_mesh.py -- <reference_mesh.json>

Each run rebuilds the mesh, selects the chain and cuts it with
``bpy.ops.iops.mesh_smart_edge_slide`` on one side: the wall side at widths 0.2,
0.4 and 1.0, and the slanted panel side at width 0.2, all in the default mode. 1.0
runs well past 0.377, where the first build's slide stopped. The mesh keeps
being edited, so the check asserts properties, not vertex or face counts, which
it prints:

- the operator returns FINISHED, and the width fits: the side's limit (the
  operator's own solve on the mesh as rebuilt) is not below it;
- every new vertex lies within 1e-6 of the original surface, and no original
  vertex moves;
- no new degenerate face or zero-length edge;
- wall side: the new loop wraps the pocket, so there are new vertices on the
  pocket top (z = 5.0) at the chain's x minus the width, at both pocket sides;
- panel side: the new vertex of every interior chain vertex lies at the width
  from the chain, measured in the panel plane (within 1e-6 on a planar face,
  1e-5 on a non-planar one: see ``BENT_WIDTH_TOL``).

Distances are measured in double precision from the stored float32
coordinates. The single-precision BVH distance is printed beside them only for
reference: on long thin triangles it is off by a few 1e-6.

The numbers are printed, and operator warnings appear in the log above them.
Exits 1 when a property fails.
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

ADDON = "InteractionOps"

WALL_WIDTHS = (0.2, 0.4, 1.0)  # 1.0 runs well past 0.377, where the first build's slide stopped
PANEL_WIDTH = 0.2
SURFACE_TOL = 1e-6        # new vertex to the original surface
WIDTH_TOL = 1e-6          # panel-side new vertex to the chain, against the width
PLANAR_TOL = 1e-5         # a face whose vertices lie this close to its plane is planar
# The operator measures the width in the surface: the face's own triangles,
# developed. This check projects onto one plane, the panel's, which on a non-planar
# face reads a tilted stretch short. The reference panel is a 15-gon off its plane by
# up to 3.2e-4, and its triangles near the fillet tilt up to 1.83 degrees against
# that plane (0.2 * (1 - cos) = 1e-4 at most). With the panel flattened, the same
# check passes at 2.9e-7. So an anchor in a face that is not planar within
# PLANAR_TOL gets this tolerance on the plane-projected width instead of WIDTH_TOL.
BENT_WIDTH_TOL = 1e-5
MOVED_TOL = 0.0           # an original vertex must not move at all
ANCHOR_MATCH_TOL = 1e-5   # a solved anchor to its vertex in the result (float32 storage)
DEGENERATE_LENGTH = 1e-7  # an edge this short is zero-length
DEGENERATE_AREA = 1e-10   # a face this small is degenerate
# The pocket at the chain's flat top: a step in the ceiling, its top at z = 5.0
# between the pocket sides at y = -3.5 and y = -2.5.
POCKET_TOP_Z = 5.0
POCKET_SIDES_Y = (-3.5, -2.5)
POCKET_TOL = 1e-4

bridge = None
core = None


def enable_addon():
    global bridge, core
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.operators import mesh_smart_edge_slide_bridge as _bridge
    from InteractionOps.utils import smart_edge_slide_core as _core
    bridge = _bridge
    core = _core


def load_snapshot():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("usage: ... --python tests/blender/check_reference_mesh.py -- <reference_mesh.json>")
    with open(argv[0], encoding="utf-8") as f:
        return json.load(f)


# --- double-precision geometry on tuples -----------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add_scaled(a, d, t):
    return (a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a):
    return math.sqrt(_dot(a, a))


def _segment_distance(p, a, b):
    d = _sub(b, a)
    t = max(0.0, min(1.0, _dot(_sub(p, a), d) / _dot(d, d)))
    return _length(_sub(p, _add_scaled(a, d, t)))


def _line_distance(p, a, b):
    d = _sub(b, a)
    return _length(_sub(p, _add_scaled(a, d, _dot(_sub(p, a), d) / _dot(d, d))))


def _triangle_distance(p, a, b, c):
    """Distance from ``p`` to triangle ``abc`` (closest point by Voronoi regions)."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return _length(ap)
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return _length(bp)
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return _length(cp)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return _segment_distance(p, a, b)
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return _segment_distance(p, a, c)
    if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        return _segment_distance(p, b, c)
    total = va + vb + vc
    if total <= 0.0:  # a zero-area triangle: its edges are all of it
        return min(_segment_distance(p, a, b), _segment_distance(p, b, c), _segment_distance(p, c, a))
    q = _add_scaled(_add_scaled(a, ab, vb / total), ac, vc / total)
    return _length(_sub(p, q))


def _plane_point(p, origin, normal):
    return _add_scaled(p, normal, -_dot(_sub(p, origin), normal))


def _non_planarity(pts):
    """Largest distance of a polygon's points from its Newell plane through their mean."""
    nx = ny = nz = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(pts, pts[1:] + pts[:1]):
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    nl = math.sqrt(nx * nx + ny * ny + nz * nz)
    normal = (nx / nl, ny / nl, nz / nl)
    center = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
    return max(abs(_dot(_sub(p, center), normal)) for p in pts)


# --- the mesh -------------------------------------------------------------------

def rebuild(snap):
    """The snapshot as the active object in Edit Mode (edge select), with the chain selected.

    Removes every object an earlier rebuild left, so each run starts fresh.
    """
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in [o for o in bpy.data.objects if o.name.startswith("reference_mesh")]:
        me = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(me)
    for other in bpy.context.view_layer.objects:
        other.select_set(False)

    bm = bmesh.new()
    verts = [bm.verts.new(co) for co in snap["verts"]]
    for face in snap["faces"]:
        bm.faces.new([verts[i] for i in face])
    bm.faces.ensure_lookup_table()
    for i in snap["hidden_faces"]:
        bm.faces[i].hide = True
    chain = snap["chain"]
    for a, b in zip(chain, chain[1:]):
        edge = bm.edges.get((verts[a], verts[b]))
        assert edge is not None, f"chain vertices {a} and {b} share no edge"
        edge.select_set(True)
    me = bpy.data.meshes.new("reference_mesh")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("reference_mesh", me)
    obj.matrix_world = Matrix(snap["matrix_world"])
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.context.tool_settings.mesh_select_mode = (False, True, False)
    bpy.ops.object.mode_set(mode="EDIT")
    return obj


def _bm(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    return bm


def _degenerate(bm):
    """Faces (as vertex index sets) and edges (as vertex index pairs) of zero size."""
    faces = {
        frozenset(v.index for v in f.verts)
        for f in bm.faces
        if f.calc_area() <= DEGENERATE_AREA or any(e.calc_length() <= DEGENERATE_LENGTH for e in f.edges)
    }
    edges = {frozenset(v.index for v in e.verts) for e in bm.edges if e.calc_length() <= DEGENERATE_LENGTH}
    return faces, edges


def classify_sides(obj):
    """{"+": "panel" or "wall", "-": ...} and each side's first face normal.

    The panel side's faces beside the chain are coplanar. ``chain_sides`` refers
    to the chain as ``collect_chains`` orders it, so each side's sign is read
    from that order, not from the snapshot's.
    """
    bm = _bm(obj)
    chains, warnings = bridge.collect_chains(bm)
    assert len(chains) == 1 and not warnings, f"expected one chain, got {len(chains)} ({warnings})"
    chain = chains[0].verts
    kinds, normals = {}, {}
    for sign, side in (("+", 1), ("-", -1)):
        faces = []
        for a, b in zip(chain, chain[1:]):
            start = a if side > 0 else b
            faces += [lp.face for lp in bm.edges.get((a, b)).link_loops if lp.vert is start]
        first = faces[0].normal
        kinds[sign] = "panel" if all(f.normal.dot(first) > 1.0 - 1e-6 for f in faces) else "wall"
        normals[sign] = tuple(first)
    assert sorted(kinds.values()) == ["panel", "wall"], f"sides not told apart: {kinds}"
    return kinds, normals


def panel_anchors(obj, side, width):
    """(chain vertex, position, face) of each interior chain vertex's new vertex, and the chain in
    ``collect_chains`` order.

    Read from the operator's own solve on the same mesh before the operator
    runs, only to tell the anchors apart from the other new vertices.
    """
    bm = _bm(obj)
    chains, _warnings = bridge.collect_chains(bm)
    build, err = bridge.build_band(bm, chains[0], side)
    assert build is not None, f"no band on the panel side: {err}"
    cut = core.Slider(build.band).solve(width)
    assert not cut.clamped, f"panel side clamped at {cut.width}"
    chain = build.band.chain
    anchors = [
        (chain[k], tuple(cut.points[a].co), cut.points[a].face)
        for k, a in enumerate(cut.anchors)
        if 0 < k < len(chain) - 1 and a is not None
    ]
    assert all(face >= 0 for _v, _co, face in anchors), "a panel-side anchor lies in a lid"
    return anchors, [v.index for v in chains[0].verts]


def side_limit(obj, side):
    """The widest width the operator's own solve fits on ``side`` in the default mode, or None without a band."""
    bm = _bm(obj)
    chains, _warnings = bridge.collect_chains(bm)
    build, _err = bridge.build_band(bm, chains[0], side)
    return None if build is None else core.Slider(build.band).limit()


def _state(bm):
    return {
        "n_verts": len(bm.verts),
        "n_faces": len(bm.faces),
        "coords": [tuple(v.co) for v in bm.verts],
        "degenerate": _degenerate(bm),
    }


def run(snap, sign, kind, width):
    """Rebuild, cut on ``sign`` at ``width``; the before and after state for the checks."""
    obj = rebuild(snap)
    bm = _bm(obj)
    before = _state(bm)
    before["bvh"] = BVHTree.FromBMesh(bm)
    before["triangles"] = [tuple(tuple(lp.vert.co) for lp in tri) for tri in bm.calc_loop_triangles()]
    side = 1 if sign == "+" else -1
    before["limit"] = side_limit(obj, side)
    anchors, chain_ids = panel_anchors(obj, side, width) if kind == "panel" else ([], None)
    result = bpy.ops.iops.mesh_smart_edge_slide('EXEC_DEFAULT', width=width, chain_sides=sign)
    bm = _bm(obj)
    after = _state(bm)
    after["selected_edges"] = sum(e.select for e in bm.edges)
    return result, before, after, anchors, chain_ids


# --- checks ---------------------------------------------------------------------

FAILURES = []


def check(ok, what):
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        FAILURES.append(what)


def common_checks(label, result, before, after, width):
    new = after["coords"][before["n_verts"]:]
    limit = before["limit"]
    print(f"{label}: operator returned {sorted(result)}")
    print(f"  vertices {before['n_verts']} -> {after['n_verts']} ({len(new)} new), "
          f"faces {before['n_faces']} -> {after['n_faces']}, {after['selected_edges']} loop edges selected")
    print(f"  limit on this side: {'none' if limit is None else f'{limit:.6f}'}")
    check(result == {'FINISHED'}, f"{label}: operator returns FINISHED")
    check(limit is not None and limit >= width, f"{label}: the width fits (limit {limit})")
    check(len(new) > 0, f"{label}: the cut adds vertices ({len(new)})")
    moved = max((_length(_sub(a, b)) for a, b in zip(before["coords"], after["coords"])), default=0.0)
    check(moved <= MOVED_TOL, f"{label}: no original vertex moves (largest move {moved:.3g})")

    off = [min(_triangle_distance(co, *tri) for tri in before["triangles"]) for co in new]
    nearest = [before["bvh"].find_nearest(co) for co in new]
    worst = max(off, default=0.0)
    worst_bvh = max((hit[3] for hit in nearest), default=0.0)
    check(worst <= SURFACE_TOL, f"{label}: every new vertex on the original surface "
          f"(largest distance {worst:.3g}, tolerance {SURFACE_TOL:g}; single-precision BVH: {worst_bvh:.3g})")

    faces_before, edges_before = before["degenerate"]
    faces_after, edges_after = after["degenerate"]
    new_faces, new_edges = faces_after - faces_before, edges_after - edges_before
    print(f"  degenerate faces before/after: {len(faces_before)}/{len(faces_after)}, "
          f"zero-length edges before/after: {len(edges_before)}/{len(edges_after)}")
    check(not new_faces, f"{label}: no new degenerate face ({sorted(map(sorted, new_faces))})")
    check(not new_edges, f"{label}: no new zero-length edge ({sorted(map(sorted, new_edges))})")

    print("  new vertices: distance to the original surface (BVH distance), nearest original face")
    for co, dist, hit in zip(new, off, nearest):
        print(f"    ({co[0]: .6f}, {co[1]: .6f}, {co[2]: .6f})  {dist:.3g} ({hit[3]:.3g})  face {hit[2]}")
    return new


def wall_checks(snap, new, width):
    label = f"wall side, width {width}"
    chain = [snap["verts"][i] for i in snap["chain"]]
    print(f"{label}: {len(new)} new vertices in total")
    for y in POCKET_SIDES_Y:
        # The chain's x at the pocket mouth: its vertex at this pocket side.
        mouth = min(chain, key=lambda p: abs(p[1] - y))
        want = (mouth[0] - width, y, POCKET_TOP_Z)
        got = min(new, key=lambda co: _length(_sub(co, want))) if new else None
        dist = _length(_sub(got, want)) if got is not None else math.inf
        shown = tuple(round(c, 6) for c in got) if got is not None else None
        check(dist <= POCKET_TOL, f"{label}: new vertex on the pocket top at "
              f"({want[0]:.6f}, {y}, {POCKET_TOP_Z}) (nearest {shown}, off by {dist:.3g})")


def panel_checks(snap, new, anchors, chain_ids, normal, width):
    label = f"panel side, width {width}"
    verts = snap["verts"]
    origin = tuple(verts[chain_ids[0]])
    chain = [_plane_point(tuple(verts[i]), origin, normal) for i in chain_ids]
    pos = {v: k for k, v in enumerate(chain_ids)}
    print(f"{label}: {len(new)} new vertices in total, {len(anchors)} interior anchors "
          f"(of {len(chain_ids) - 2} interior chain vertices)")
    check(len(anchors) == len(chain_ids) - 2, f"{label}: every interior chain vertex has an anchor")
    worst = {WIDTH_TOL: 0.0, BENT_WIDTH_TOL: 0.0}  # largest error per tolerance
    worst_lines = 0.0
    for v, co, face in anchors:
        got = min(new, key=lambda c: _length(_sub(c, co))) if new else None
        if got is None or _length(_sub(got, co)) > ANCHOR_MATCH_TOL:
            check(False, f"{label}: anchor of chain vertex {v} is in the result (solved at {co})")
            continue
        bent = _non_planarity([tuple(verts[i]) for i in snap["faces"][face]])
        tol = WIDTH_TOL if bent <= PLANAR_TOL else BENT_WIDTH_TOL
        p = _plane_point(got, origin, normal)
        k = pos[v]
        to_chain = min(_segment_distance(p, a, b) for a, b in zip(chain, chain[1:]))
        to_lines = (_line_distance(p, chain[k - 1], chain[k]), _line_distance(p, chain[k], chain[k + 1]))
        print(f"    chain vertex {v:>3}: to the chain {to_chain:.9f}, "
              f"to its two edges' lines {to_lines[0]:.9f} / {to_lines[1]:.9f}; "
              f"face {face} off its plane by {bent:.3g}, tolerance {tol:g}")
        worst[tol] = max(worst[tol], abs(to_chain - width))
        worst_lines = max(worst_lines, *(abs(d - width) for d in to_lines))
    check(worst[WIDTH_TOL] <= WIDTH_TOL and worst[BENT_WIDTH_TOL] <= BENT_WIDTH_TOL,
          f"{label}: every anchor {width} from the chain in the panel plane (largest error "
          f"{worst[WIDTH_TOL]:.3g} in planar faces, tolerance {WIDTH_TOL:g}; "
          f"{worst[BENT_WIDTH_TOL]:.3g} in non-planar faces, tolerance {BENT_WIDTH_TOL:g})")
    print(f"  largest error against the lines of each anchor's two chain edges: {worst_lines:.3g}")


def main():
    enable_addon()
    snap = load_snapshot()
    print(f"reference mesh: {len(snap['verts'])} vertices, {len(snap['faces'])} faces, "
          f"{len(snap['hidden_faces'])} hidden, chain {snap['chain']}")
    kinds, normals = classify_sides(rebuild(snap))
    print(f"chain_sides: {kinds}")
    for sign, kind in sorted(kinds.items()):
        for width in WALL_WIDTHS if kind == "wall" else (PANEL_WIDTH,):
            result, before, after, anchors, chain_ids = run(snap, sign, kind, width)
            new = common_checks(f"{kind} side ({sign}), width {width}", result, before, after, width)
            if kind == "wall":
                wall_checks(snap, new, width)
            else:
                panel_checks(snap, new, anchors, chain_ids, normals[sign], width)
    print("REFERENCE CHECK " + (f"FAILED: {len(FAILURES)}" if FAILURES else "OK"))
    if FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    main()
