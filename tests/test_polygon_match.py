import numpy as np
import pytest

from utils.polygon_match import signature, pca_ratios
from utils.polygon_match import pca_frame
from utils.polygon_match import kabsch_with_scale, greedy_correspondence


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


def test_pca_ratios_isotropic_cube():
    r = pca_ratios(CUBE)
    # Sum to 1.
    assert np.isclose(sum(r), 1.0, atol=1e-9)
    # All three eigenvalues equal for a cube.
    assert all(np.isclose(x, 1.0 / 3.0, atol=1e-6) for x in r)


def test_pca_ratios_flat_plane():
    # Points on z=0 plane — third eigenvalue near zero.
    pts = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [2.0, 1.0, 0.0]])
    r = pca_ratios(pts)
    assert r[0] > r[1] > r[2]
    assert r[2] < 1e-9


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


def test_greedy_correspondence_recovers_shuffled():
    # Shuffle target, verify correspondence reverses the shuffle.
    rng = np.random.default_rng(7)
    perm = rng.permutation(REF_CLOUD.shape[0])
    tgt = REF_CLOUD[perm] + np.array([3.0, 0.0, 0.0])
    corr = greedy_correspondence(REF_CLOUD, tgt)
    # corr[i] should give the index in tgt that pairs with ref[i].
    paired_tgt = tgt[corr]
    assert np.allclose(paired_tgt - np.array([3.0, 0.0, 0.0]), REF_CLOUD, atol=1e-6)


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


from utils.polygon_match import d2_histogram


def test_d2_deterministic_with_seed():
    h1 = d2_histogram(CUBE, CUBE_FACES, samples=256, bins=16, seed=0)
    h2 = d2_histogram(CUBE, CUBE_FACES, samples=256, bins=16, seed=0)
    assert np.array_equal(h1, h2)


def test_d2_translation_invariant():
    h_a = d2_histogram(CUBE, CUBE_FACES, samples=256, bins=16, seed=0)
    h_b = d2_histogram(CUBE + 10.0, CUBE_FACES, samples=256, bins=16, seed=0)
    assert np.array_equal(h_a, h_b)


def test_d2_scale_invariant_after_normalization():
    # We normalize distances by bbox diag, so the histogram should match.
    h_a = d2_histogram(CUBE, CUBE_FACES, samples=512, bins=16, seed=0)
    h_b = d2_histogram(CUBE * 5.0, CUBE_FACES, samples=512, bins=16, seed=0)
    # χ² distance ~0 between identical-shape clouds at different scales.
    chi2 = float(np.sum((h_a - h_b) ** 2 / np.maximum(h_a + h_b, 1e-9)))
    assert chi2 < 1e-6


def test_d2_distinguishes_different_shapes():
    # Cube vs. very flat slab (different aspect ratio) → distinct histograms.
    slab = CUBE.copy()
    slab[:, 2] *= 0.01
    h_cube = d2_histogram(CUBE, CUBE_FACES, samples=512, bins=16, seed=0)
    h_slab = d2_histogram(slab, CUBE_FACES, samples=512, bins=16, seed=0)
    chi2 = float(np.sum((h_cube - h_slab) ** 2 / np.maximum(h_cube + h_slab, 1e-9)))
    assert chi2 > 0.05


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
        scale_mode="KEEP", pos_tol=0.5, fit_rmse_rel=0.05, bbox_diag=4.0)
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
