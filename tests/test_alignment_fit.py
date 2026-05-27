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
