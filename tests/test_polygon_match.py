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
