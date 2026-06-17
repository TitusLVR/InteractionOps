import numpy as np
import pytest

from utils.polygon_match import signature
from utils.polygon_match import pca_frame
from utils.polygon_match import kabsch_with_scale


CUBE = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
])
CUBE_FACES = [
    [0, 1, 2, 3], [4, 5, 6, 7],
    [0, 1, 5, 4], [2, 3, 7, 6],
    [1, 2, 6, 5], [0, 3, 7, 4],
]


def test_signature_basic_cube():
    sig = signature(CUBE, CUBE_FACES)
    assert sig.vert_count == 8
    assert sig.face_count == 6
    # All faces are quads.
    assert sig.face_vcount_hist == ((4, 6),)
    # bbox diag = sqrt(3) for unit cube.
    assert sig.bbox_diag == pytest.approx(np.sqrt(3.0), abs=1e-6)


def test_signature_mixed_face_sizes():
    faces = [[0, 1, 2], [0, 1, 2, 3], [0, 1, 2, 3, 4]]  # tri, quad, pent
    sig = signature(CUBE[:5], faces)
    assert sig.face_count == 3
    assert sig.face_vcount_hist == ((3, 1), (4, 1), (5, 1))


def test_pca_frame_axis_aligned_quad():
    # Unit quad on z=0, centered at origin, lying flat.
    verts = np.array([
        [-1.0, -1.0, 0.0],
        [ 1.0, -1.0, 0.0],
        [ 1.0,  1.0, 0.0],
        [-1.0,  1.0, 0.0],
    ])
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([4.0])
    face_centroids = np.array([[0.0, 0.0, 0.0]])
    frame = pca_frame(verts, face_centroids, face_normals, face_areas)
    # 4x4 matrix.
    assert frame.shape == (4, 4)
    # Origin at quad centroid.
    assert np.allclose(frame[:3, 3], [0.0, 0.0, 0.0], atol=1e-6)
    # Z axis matches face normal.
    assert np.allclose(frame[:3, 2], [0.0, 0.0, 1.0], atol=1e-6)
    # X and Y orthogonal to Z and to each other, unit length.
    x = frame[:3, 0]
    y = frame[:3, 1]
    assert np.isclose(np.linalg.norm(x), 1.0, atol=1e-6)
    assert np.isclose(np.linalg.norm(y), 1.0, atol=1e-6)
    assert np.isclose(np.dot(x, y), 0.0, atol=1e-6)
    assert np.isclose(np.dot(x, [0, 0, 1]), 0.0, atol=1e-6)


def test_pca_frame_translated_offset():
    # Same quad, translated.
    verts = np.array([
        [10.0, 5.0, 2.0],
        [12.0, 5.0, 2.0],
        [12.0, 7.0, 2.0],
        [10.0, 7.0, 2.0],
    ])
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([4.0])
    face_centroids = np.array([[11.0, 6.0, 2.0]])
    frame = pca_frame(verts, face_centroids, face_normals, face_areas)
    assert np.allclose(frame[:3, 3], [11.0, 6.0, 2.0], atol=1e-6)
    assert np.allclose(frame[:3, 2], [0.0, 0.0, 1.0], atol=1e-6)


REF_CLOUD = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
    [1.0, 1.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 1.0],
])


def test_kabsch_with_scale_keep_translation():
    tgt = REF_CLOUD + np.array([5.0, -2.0, 3.0])
    T, rmse = kabsch_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    # Apply T to REF_CLOUD (homogeneous) and compare.
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)
    assert rmse < 1e-6


def test_kabsch_with_scale_uniform_recovers_2x():
    tgt = REF_CLOUD * 2.0
    T, rmse = kabsch_with_scale(REF_CLOUD, tgt, scale_mode="UNIFORM")
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)
    assert rmse < 1e-6


def test_kabsch_rmse_nonzero_on_noise():
    rng = np.random.default_rng(42)
    tgt = REF_CLOUD + rng.normal(0.0, 0.01, REF_CLOUD.shape)
    _, rmse = kabsch_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    assert 0.0 < rmse < 0.1


def test_pca_frame_degenerate_pca_falls_back():
    # All vertices collinear along Z, normal also Z → projection of principal
    # PCA axis onto plane perp-to-Z is zero. Fallback must produce a valid
    # orthonormal frame.
    verts = np.array([
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 2.0],
    ])
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([1.0])
    face_centroids = np.array([[0.0, 0.0, 1.0]])
    frame = pca_frame(verts, face_centroids, face_normals, face_areas)
    x = frame[:3, 0]
    z = frame[:3, 2]
    assert np.isclose(np.linalg.norm(x), 1.0, atol=1e-6)
    assert np.isclose(np.dot(x, z), 0.0, atol=1e-6)


from utils.polygon_match import kabsch_mirror_with_scale


def test_kabsch_mirror_recovers_reflection():
    # Reflect REF_CLOUD across the X=0 plane: x -> -x.
    tgt = REF_CLOUD.copy()
    tgt[:, 0] = -tgt[:, 0]
    T, rmse = kabsch_mirror_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)
    assert rmse < 1e-6
    # Determinant of the 3x3 rotation part should be -1 (reflection).
    R = T[:3, :3]
    assert np.linalg.det(R) < 0


def test_kabsch_mirror_on_non_mirror_still_works():
    # On a pure translation, the mirror variant should still find a near-zero
    # RMSE solution (it can pick det=+1 if that's optimal).
    tgt = REF_CLOUD + np.array([5.0, 0.0, 0.0])
    _, rmse = kabsch_mirror_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    assert rmse < 1e-6


def test_kabsch_mirror_high_rmse_on_unrelated():
    # Random target shape — mirror variant won't find a low-RMSE alignment.
    rng = np.random.default_rng(123)
    tgt = rng.normal(0, 1, REF_CLOUD.shape)
    _, rmse = kabsch_mirror_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    # 8 random points in unit-stdev cloud vs ref → RMSE roughly O(1).
    assert rmse > 0.3


from utils.polygon_match import fit_both


def test_fit_both_translation_not_mirror():
    tgt = REF_CLOUD + np.array([2.0, -1.0, 4.0])
    T, rmse, is_mirror = fit_both(REF_CLOUD, tgt, scale_mode="KEEP")
    assert not is_mirror
    assert rmse < 1e-6
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)


def test_fit_both_detects_reflection():
    tgt = REF_CLOUD.copy()
    tgt[:, 0] = -tgt[:, 0]
    T, rmse, is_mirror = fit_both(REF_CLOUD, tgt, scale_mode="KEEP")
    assert is_mirror
    assert rmse < 1e-6
    assert np.linalg.det(T[:3, :3]) < 0


from utils.polygon_match import Candidate, assemble_constellations


def _rigid(pts, R, t):
    return pts @ np.asarray(R).T + np.asarray(t)


# Two reference components, each 2 faces -> 4 anchors. Chiral (non-coplanar)
# so an x -> -x reflection is NOT equivalent to any proper rotation, making
# mirror detection well-posed.
REF_C0 = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
])
REF_C1 = np.array([
    [3.0, 0.0, 0.0], [4.0, 0.0, 0.0],
    [3.0, 1.0, 0.0], [3.0, 0.0, 1.0],
])


def _ref_inputs():
    anchors = [REF_C0, REF_C1]
    cents = [REF_C0.mean(axis=0), REF_C1.mean(axis=0)]
    fc = [2, 2]
    return anchors, cents, fc


def test_assemble_single_component_passthrough():
    t = np.array([5.0, 1.0, -2.0])
    cand = Candidate((10, 11), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    res = assemble_constellations(
        [REF_C0], [REF_C0.mean(axis=0)], [2], 0, [[cand]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["order"] == (10, 11)
    assert res[0]["faces"] == frozenset((10, 11))
    assert not res[0]["mirror"]


def test_assemble_two_components_correct():
    anchors, cents, fc = _ref_inputs()
    t = np.array([10.0, 0.0, 0.0])
    c0 = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    c1 = Candidate((3, 4), (REF_C1 + t).mean(axis=0), REF_C1 + t)
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["faces"] == frozenset((1, 2, 3, 4))
    assert res[0]["order"] == (1, 2, 3, 4)
    assert not res[0]["mirror"]


def test_assemble_rejects_wrong_arrangement():
    anchors, cents, fc = _ref_inputs()
    t = np.array([10.0, 0.0, 0.0])
    c0 = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    bad = REF_C1 + t + np.array([0.0, 0.0, 20.0])  # far from predicted slot
    c1 = Candidate((3, 4), bad.mean(axis=0), bad)
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert res == []


def test_assemble_detects_mirror():
    anchors, cents, fc = _ref_inputs()

    def mirror(pts):
        m = pts.copy()
        m[:, 0] = -m[:, 0]
        return m

    c0 = Candidate((1, 2), mirror(REF_C0).mean(axis=0), mirror(REF_C0))
    c1 = Candidate((3, 4), mirror(REF_C1).mean(axis=0), mirror(REF_C1))
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["mirror"]


def test_assemble_degenerate_anchor_pairwise_seed():
    # comp0 is a single face: its 2 anchors lie on the Z axis through origin,
    # so a 90-deg rotation about Z is invisible to a comp0-only fit. The
    # pairwise seed with comp1 (off-axis) must recover it.
    ref_c0_single = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.5]])
    anchors = [ref_c0_single, REF_C1]
    cents = [ref_c0_single.mean(axis=0), REF_C1.mean(axis=0)]
    fc = [1, 2]
    theta = np.pi / 2.0
    R = np.array([[np.cos(theta), -np.sin(theta), 0.0],
                  [np.sin(theta), np.cos(theta), 0.0],
                  [0.0, 0.0, 1.0]])
    t = np.array([7.0, 3.0, 0.0])
    c0 = Candidate((1,), _rigid(ref_c0_single, R, t).mean(axis=0),
                   _rigid(ref_c0_single, R, t))
    c1 = Candidate((3, 4), _rigid(REF_C1, R, t).mean(axis=0),
                   _rigid(REF_C1, R, t))
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["faces"] == frozenset((1, 3, 4))
    assert res[0]["order"] == (1, 3, 4)


def test_assemble_anchor_idx_nonzero():
    anchors, cents, fc = _ref_inputs()
    t = np.array([0.0, 6.0, -1.0])
    c0 = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    c1 = Candidate((3, 4), (REF_C1 + t).mean(axis=0), REF_C1 + t)
    res = assemble_constellations(
        anchors, cents, fc, 1, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["faces"] == frozenset((1, 2, 3, 4))
    assert res[0]["order"] == (1, 2, 3, 4)
    assert not res[0]["mirror"]


from utils.polygon_match import refine_fit_icp

_ICP_C = np.array([[0.0, 0, 0], [3, 0, 0], [0, 2, 0], [0, 0, 1]], dtype=float)
_ICP_N = np.array([[0.0, 0, 1], [0, 1, 0], [1, 0, 0], [0, 1, 1]], dtype=float)


def _icp_anchors(off=0.5):
    rows = []
    for c, n in zip(_ICP_C, _ICP_N):
        rows.append(c)
        rows.append(c + n * off)
    return np.array(rows, dtype=float)


def _icp_apply(T, A):
    h = np.hstack([A, np.ones((len(A), 1))])
    return (h @ T.T)[:, :3]


def _icp_swap(A, fperm):
    return A.reshape(-1, 2, 3)[fperm].reshape(-1, 3)


def _rotT(th=0.5, t=(1.0, 2.0, -1.0)):
    R = np.array([[np.cos(th), -np.sin(th), 0],
                  [np.sin(th), np.cos(th), 0],
                  [0, 0, 1.0]])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def test_refine_icp_proper_correct_correspondence():
    ref = _icp_anchors()
    tgt = _icp_apply(_rotT(), ref)
    T, rmse, mir, perm = refine_fit_icp(ref, tgt, "KEEP")
    assert rmse < 1e-6
    assert not mir


def test_refine_icp_proper_twisted_correspondence():
    # Faces 1 and 2 mislabeled — ICP must re-pair geometrically and fit at ~0,
    # NOT settle for a false mirror.
    ref = _icp_anchors()
    tgt = _icp_swap(_icp_apply(_rotT(), ref), [0, 2, 1, 3])
    T, rmse, mir, perm = refine_fit_icp(ref, tgt, "KEEP")
    assert rmse < 1e-6
    assert not mir


def test_refine_icp_mirror_correct_correspondence():
    ref = _icp_anchors()
    tgt = ref.copy()
    tgt[:, 0] = -tgt[:, 0]
    T, rmse, mir, perm = refine_fit_icp(ref, tgt, "KEEP")
    assert rmse < 1e-6
    assert mir


def test_refine_icp_mirror_twisted_correspondence():
    ref = _icp_anchors()
    tgt = ref.copy()
    tgt[:, 0] = -tgt[:, 0]
    tgt = _icp_swap(tgt, [1, 0, 3, 2])
    T, rmse, mir, perm = refine_fit_icp(ref, tgt, "KEEP")
    assert rmse < 1e-6
    assert mir


def test_assemble_dedups_face_overlap_keeps_best():
    # Two single-component candidates that SHARE a face: the perfect one
    # (rmse 0) and an overlapping worse one. Face-disjoint dedup must keep only
    # the perfect match. A third, face-disjoint candidate must survive.
    t = np.array([5.0, 0.0, 0.0])
    good = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    worse = Candidate((2, 3), (REF_C0 + t).mean(axis=0),
                      REF_C0 + t + np.array([0.0, 0.0, 0.02]))  # shares face 2
    far = Candidate((7, 8), (REF_C0 + t + np.array([50.0, 0.0, 0.0])).mean(axis=0),
                    REF_C0 + t + np.array([50.0, 0.0, 0.0]))    # disjoint
    res = assemble_constellations(
        [REF_C0], [REF_C0.mean(axis=0)], [2], 0, [[good, worse, far]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    face_sets = {r["faces"] for r in res}
    assert frozenset((1, 2)) in face_sets       # perfect kept
    assert frozenset((2, 3)) not in face_sets    # overlapping worse dropped
    assert frozenset((7, 8)) in face_sets        # disjoint survives
    assert len(res) == 2


def test_fit_both_prefers_proper_on_near_tie():
    # Mirror-degenerate cloud: nearly coplanar points, target is the exact
    # reflection. The chirality residuals differ only at noise level — the
    # proper rotation must win, otherwise the mirror flag flips on float
    # noise and the aligner stamps randomly flipped clones.
    rng = np.random.default_rng(3)
    pts = rng.normal(size=(10, 3))
    pts[:, 2] *= 1e-7
    tgt = pts.copy()
    tgt[:, 2] = -tgt[:, 2]
    _T, _rmse, is_mirror = fit_both(pts, tgt, scale_mode="KEEP")
    assert not is_mirror


def test_fit_both_still_detects_decisive_mirror():
    # Chiral cloud, true reflection: mirror beats proper by a wide margin and
    # must still be reported.
    tgt = REF_CLOUD.copy()
    tgt[:, 0] = -tgt[:, 0]
    _T, rmse, is_mirror = fit_both(REF_CLOUD, tgt, scale_mode="UNIFORM")
    assert is_mirror
    assert rmse < 1e-6


def test_assemble_dedups_same_placement_disjoint_faces():
    # Symmetric meshes yield two DISJOINT face sets matching at the same spot.
    # Face-disjoint filtering alone keeps both -> two clones stacked on each
    # other. Placement-level dedup must keep only the best one.
    t = np.array([5.0, 0.0, 0.0])
    a = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    b = Candidate((3, 4), (REF_C0 + t).mean(axis=0), REF_C0 + t + 1e-4)
    res = assemble_constellations(
        [REF_C0], [REF_C0.mean(axis=0)], [2], 0, [[a, b]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["faces"] == frozenset((1, 2))


def test_assemble_keeps_distinct_placements():
    # Two matches farther apart than the dedup radius are genuinely separate
    # instances and must both survive.
    t = np.array([5.0, 0.0, 0.0])
    a = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    far_off = t + np.array([10.0, 0.0, 0.0])
    b = Candidate((3, 4), (REF_C0 + far_off).mean(axis=0), REF_C0 + far_off)
    res = assemble_constellations(
        [REF_C0], [REF_C0.mean(axis=0)], [2], 0, [[a, b]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 2


def test_refine_icp_stable_under_noise():
    # 4-fold symmetric anchor layout: many (T, perm) solutions tie near rmse 0.
    # Sub-tolerance noise must not flip which correspondence/orientation wins —
    # the identity-order proper solution should be chosen every time.
    c = np.array([[1.0, 1, 0], [-1, 1, 0], [-1, -1, 0], [1, -1, 0]])
    n = np.array([[0.0, 0, 1]] * 4)
    ref = np.empty((8, 3))
    ref[0::2] = c
    ref[1::2] = c + n * 0.5
    for seed in range(10):
        rng = np.random.default_rng(seed)
        tgt = ref + np.array([3.0, 0.0, 0.0]) + rng.normal(0, 1e-7, ref.shape)
        _T, rmse, mir, perm = refine_fit_icp(ref, tgt, "KEEP")
        assert rmse < 1e-5
        assert not mir, f"seed {seed} flipped to mirror"
        assert np.array_equal(perm, np.arange(4)), f"seed {seed} perm {perm}"


def test_pca_frame_x_sign_deterministic_by_skew():
    # X-sign must follow the vertex distribution's skew, not the eigensolver's
    # arbitrary sign convention. A cloud and its x-negated copy share the same
    # covariance, so without an explicit rule both get the SAME X — one of the
    # two frames is then 180-deg wrong for the poly-force fit.
    xs = np.array([0.0, 1.0, 2.0, 3.0, 10.0])
    verts = np.zeros((10, 3))
    verts[:5, 0] = xs
    verts[5:, 0] = xs
    verts[5:, 1] = 1.0
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([1.0])
    face_centroids = verts.mean(axis=0, keepdims=True)
    f_pos = pca_frame(verts, face_centroids, face_normals, face_areas)
    neg = verts.copy()
    neg[:, 0] = -neg[:, 0]
    f_neg = pca_frame(neg, face_centroids * [-1.0, 1.0, 1.0], face_normals, face_areas)
    assert f_pos[0, 0] > 0.0, "X must point toward the heavy +x tail"
    assert f_neg[0, 0] < 0.0, "X must follow the mirrored tail to -x"


def test_fit_both_matches_reference_impl():
    # fit_both must equal "run both kabsch variants, take the lower-rmse one"
    # across scale modes and reflected/non-reflected targets. Guards the
    # shared-SVD optimization against numeric drift.
    rng = np.random.default_rng(11)
    base = rng.normal(size=(12, 3))
    for mode in ("KEEP", "UNIFORM", "STRETCH"):
        for reflect in (False, True):
            Q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
            if np.linalg.det(Q) < 0:
                Q[:, 0] = -Q[:, 0]
            s = 1.0 if mode == "KEEP" else 2.3
            tgt = (base @ Q.T) * s + np.array([1.0, -2.0, 0.5])
            if reflect:
                tgt = tgt.copy()
                tgt[:, 0] = -tgt[:, 0]
            T, rmse, is_mir = fit_both(base, tgt, scale_mode=mode)
            Tn, rn = kabsch_with_scale(base, tgt, scale_mode=mode)
            Tm, rm = kabsch_mirror_with_scale(base, tgt, scale_mode=mode)
            ref_is_mir = rm < rn
            ref_T = Tm if ref_is_mir else Tn
            ref_rmse = rm if ref_is_mir else rn
            assert is_mir == ref_is_mir, (mode, reflect)
            assert rmse == pytest.approx(ref_rmse, abs=1e-9), (mode, reflect)
            assert np.allclose(T, ref_T, atol=1e-9), (mode, reflect)
