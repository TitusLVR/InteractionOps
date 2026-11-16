"""Multi-object edit-mesh domain for the falloff tools.

Collects the selected visible verts (all visible verts when nothing is
selected) of every mesh in Edit Mode as world-space numpy arrays, and writes
world-space results back into each object's bmesh.
"""
from __future__ import annotations

import bmesh
import numpy as np

from ...utils import falloff_core as fc


class Entry:
    """One object of the domain. `co32` is the verts' local coordinates as
    stored (float32), kept current by `write_back`."""
    __slots__ = ("obj", "bm", "verts", "mw", "mw_inv", "slice", "co32")

    def __init__(self, obj, bm, verts, mw, mw_inv, rows, co32):
        self.obj, self.bm, self.verts = obj, bm, verts
        self.mw, self.mw_inv, self.slice = mw, mw_inv, rows
        self.co32 = co32


class Domain:
    def __init__(self):
        self.entries = []
        self.P = np.zeros((0, 3))
        self.N = np.zeros((0, 3))
        self.selected = False


def collect_domain(context, *, normals=True):
    """Domain of all edit-mode meshes, or None when no vert is visible.
    `normals=False` skips the bmesh normal refresh (read-only callers such
    as the viewport preview, which then pass `update=False` to
    `finish_domain`); `domain.N` is then as fresh as the mesh's normals."""
    per_obj = []
    for obj in context.objects_in_mode_unique_data:
        if obj.type != "MESH":
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        visible = [v for v in bm.verts if not v.hide]
        if visible and normals:
            # v.normal is only as fresh as the last normal_update; scripts
            # and other tools move verts without one
            bm.normal_update()
        if visible:
            per_obj.append((obj, bm, visible))
    if not per_obj:
        return None
    selected = any(v.select for _, _, vs in per_obj for v in vs)
    dom = Domain()
    dom.selected = selected
    Ps, Ns, start = [], [], 0
    for obj, bm, visible in per_obj:
        verts = [v for v in visible if v.select] if selected else visible
        if not verts:
            continue
        mw = np.array(obj.matrix_world, dtype=np.float64)
        mw_inv = np.linalg.inv(mw)
        co = np.array([v.co[:] for v in verts], dtype=np.float64)
        nr = np.array([v.normal[:] for v in verts], dtype=np.float64)
        # normals transform by the inverse transpose of the linear part
        nw = nr @ mw_inv[:3, :3]
        ln = np.linalg.norm(nw, axis=1, keepdims=True)
        nw = np.where(ln > 1e-12, nw / np.maximum(ln, 1e-12), nw)
        Ps.append(co @ mw[:3, :3].T + mw[:3, 3])
        Ns.append(nw)
        n = len(verts)
        dom.entries.append(Entry(obj, bm, verts, mw, mw_inv,
                                 slice(start, start + n), co.astype(np.float32)))
        start += n
    dom.P = np.concatenate(Ps)
    dom.N = np.concatenate(Ns)
    return dom


def write_back(domain, P, rows=None) -> None:
    """Write world-space `P` (N,3) into the verts; only `rows` (index array or
    boolean mask) when given. A vert whose new position equals its old one
    (as stored, float32) is not assigned: one numpy comparison per object
    against `Entry.co32`, then only the changed rows are written."""
    P = np.asarray(P, dtype=np.float64)
    if rows is None:
        mask = np.ones(len(domain.P), dtype=bool)
    else:
        rows = np.asarray(rows)
        if rows.dtype == bool:
            mask = rows
        else:
            mask = np.zeros(len(domain.P), dtype=bool)
            mask[rows] = True
    for e in domain.entries:
        sl = e.slice
        m = mask[sl]
        if not m.any():
            continue
        local = P[sl] @ e.mw_inv[:3, :3].T + e.mw_inv[:3, 3]
        new32 = local.astype(np.float32)
        changed = np.nonzero(m & np.any(new32 != e.co32, axis=1))[0]
        if not len(changed):
            continue
        verts = e.verts
        for i, co in zip(changed.tolist(), new32[changed].tolist()):
            verts[i].co = co
        e.co32[changed] = new32[changed]
        bmesh.update_edit_mesh(e.obj.data, loop_triangles=False,
                               destructive=False)


def finish_domain(domain, *, normals=True, update=True) -> None:
    """Drop the domain's BMesh references; with `update` (default) refresh
    normals (`normals`) and tag the edit meshes. A read-only caller passes
    `update=False`: tagging from a draw handler would fire a depsgraph
    update that dirties the preview again on every redraw."""
    for e in domain.entries:
        try:
            if update:
                if normals:
                    e.bm.normal_update()
                bmesh.update_edit_mesh(e.obj.data, loop_triangles=False,
                                       destructive=False)
        except ReferenceError:
            pass
        e.bm = None
        e.verts = None


def selection_signature(domain) -> str:
    if domain is None or len(domain.P) == 0:
        return "0"
    lo = domain.P.min(axis=0)
    hi = domain.P.max(axis=0)
    return "%d|%s|%s" % (len(domain.P),
                         ",".join("%.5f" % x for x in lo),
                         ",".join("%.5f" % x for x in hi))


def _active_element_frame(context, domain):
    """(pivot, normal, tangent) in world space: the active element
    (select_history), else the active face, else the domain centre and the
    summed normals of the domain."""
    obj = context.edit_object
    entry = next((e for e in domain.entries
                  if e.obj == obj and e.bm is not None), None)
    if entry is not None:
        bm, mw = entry.bm, entry.mw
        nmat = entry.mw_inv[:3, :3].T

        def world(v):
            return mw[:3, :3] @ np.array(v.co[:], dtype=np.float64) + mw[:3, 3]

        def wnormal(n):
            return nmat @ np.array(n[:], dtype=np.float64)

        elem = None
        try:
            elem = bm.select_history.active
            if elem is None:
                elem = bm.faces.active
        except (AttributeError, ReferenceError):
            elem = None
        if isinstance(elem, bmesh.types.BMFace) and elem.is_valid:
            cos = np.array([world(v) for v in elem.verts])
            tangent = None
            if len(elem.edges):
                a, b = elem.edges[0].verts
                tangent = world(b) - world(a)
            return cos.mean(axis=0), wnormal(elem.normal), tangent
        if isinstance(elem, bmesh.types.BMEdge) and elem.is_valid:
            a, b = elem.verts
            pa, pb = world(a), world(b)
            return (pa + pb) * 0.5, wnormal(a.normal + b.normal), pb - pa
        if isinstance(elem, bmesh.types.BMVert) and elem.is_valid:
            return world(elem), wnormal(elem.normal), None
    return fc.bbox_center(domain.P), domain.N.sum(axis=0), None


def _orthonormal_columns(R):
    """Normalise columns and re-orthogonalise via SVD so a scaled or sheared
    matrix still yields a proper rotation."""
    u, _, vt = np.linalg.svd(np.asarray(R, dtype=np.float64))
    Q = u @ vt
    if np.linalg.det(Q) < 0:
        Q[:, 2] *= -1.0
    return Q


def auto_pivot(context, domain) -> np.ndarray:
    basis = context.scene.IOPS.falloff.basis
    if basis == "CURSOR":
        return np.array(context.scene.cursor.location[:], dtype=np.float64)
    if basis == "WORLD":
        return np.zeros(3)
    if basis == "NORMAL":
        return _active_element_frame(context, domain)[0]
    return fc.bbox_center(domain.P)


def basis_matrix(context, domain) -> np.ndarray:
    basis = context.scene.IOPS.falloff.basis
    if basis == "CURSOR":
        return _orthonormal_columns(context.scene.cursor.matrix.to_3x3())
    if basis == "WORLD":
        return np.eye(3)
    if basis == "NORMAL":
        _, normal, tangent = _active_element_frame(context, domain)
        return fc.basis_from_normal(normal, tangent)
    obj = context.edit_object or context.active_object
    if obj is None:
        return np.eye(3)
    return _orthonormal_columns(obj.matrix_world.to_3x3())
