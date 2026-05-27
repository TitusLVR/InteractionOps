import math
import numpy as np
import pytest

from utils.alignment_fit import kabsch


# A non-degenerate reference cloud (unit cube corners) reused across tests.
REF = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
    [1.0, 1.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 1.0],
])


def _rot_z(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def test_kabsch_pure_translation():
    t = np.array([1.0, 2.0, 3.0])
    tgt = REF + t
    R, tt = kabsch(REF, tgt)
    assert np.allclose(R, np.eye(3), atol=1e-6)
    assert np.allclose(tt, t, atol=1e-6)


def test_kabsch_recovers_rotation():
    Rz = _rot_z(90.0)
    tgt = REF @ Rz.T
    R, tt = kabsch(REF, tgt)
    recon = REF @ R.T + tt
    assert np.allclose(recon, tgt, atol=1e-6)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)


def test_kabsch_no_reflection_on_mirrored_input():
    mirror = np.array([[-1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    tgt = REF @ mirror.T
    R, _ = kabsch(REF, tgt)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)


from utils.alignment_fit import umeyama


def test_umeyama_recovers_uniform_scale():
    Rz = _rot_z(30.0)
    s = 2.5
    t = np.array([4.0, -1.0, 0.5])
    tgt = s * (REF @ Rz.T) + t
    R, tt, scale = umeyama(REF, tgt)
    recon = scale * (REF @ R.T) + tt
    assert np.allclose(recon, tgt, atol=1e-6)
    assert np.isclose(scale, s, atol=1e-6)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)


def test_umeyama_unit_scale_when_rigid():
    Rz = _rot_z(45.0)
    tgt = REF @ Rz.T + np.array([1.0, 0.0, 0.0])
    _R, _t, scale = umeyama(REF, tgt)
    assert np.isclose(scale, 1.0, atol=1e-6)


from utils.alignment_fit import affine_fit, solve_fit


def _apply4(m4, pts):
    homog = np.hstack([pts, np.ones((pts.shape[0], 1))])
    out = homog @ m4.T
    return out[:, :3]


def test_affine_recovers_non_uniform_scale():
    a = np.diag([1.0, 2.0, 3.0])
    t = np.array([0.5, 0.0, -1.0])
    tgt = REF @ a.T + t
    m4 = affine_fit(REF, tgt)
    assert np.allclose(_apply4(m4, REF), tgt, atol=1e-6)


def test_solve_fit_uniform_is_default_path():
    Rz = _rot_z(20.0)
    tgt = 1.5 * (REF @ Rz.T) + np.array([2.0, 2.0, 2.0])
    m4 = solve_fit(REF, tgt, "UNIFORM")
    assert m4.shape == (4, 4)
    assert np.allclose(_apply4(m4, REF), tgt, atol=1e-6)


def test_solve_fit_keep_ignores_scale():
    Rz = _rot_z(10.0)
    tgt = 2.0 * (REF @ Rz.T)
    m4 = solve_fit(REF, tgt, "KEEP")
    linear = m4[:3, :3]
    norms = np.linalg.norm(linear, axis=0)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_solve_fit_stretch_matches_affine():
    a = np.diag([2.0, 0.5, 1.0])
    tgt = REF @ a.T
    m4 = solve_fit(REF, tgt, "STRETCH")
    assert np.allclose(_apply4(m4, REF), tgt, atol=1e-6)


def test_solve_fit_rejects_bad_method():
    with pytest.raises(ValueError):
        solve_fit(REF, REF, "NOPE")
