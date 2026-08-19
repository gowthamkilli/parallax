"""Tests for the DoA solver.

These exist because the sign convention in a TDOA solve is the single easiest
thing in the whole system to get backwards, and a 180-degree bearing error is
not obvious from a demo screenshot -- it just points at the wrong building.
"""

import math

import numpy as np
import pytest

from parallax.doa import (
    C_SOUND,
    estimate_doa,
    gcc_phat,
    planar_ring,
    ring_plus_mast,
    theoretical_bearing_floor_deg,
    _fit_plane_wave,
)


FS = 48_000.0


def _plane_wave(geometry, azimuth_deg, elevation_deg=0.0, fs=FS, n=4096, snr_db=None, seed=0):
    """Synthesise an ideal plane wave arriving from a known direction."""
    rng = np.random.default_rng(seed)
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    u = np.array([
        math.sin(az) * math.cos(el),
        math.cos(az) * math.cos(el),
        math.sin(el),
    ])
    # A microphone displaced toward the source hears the wavefront earlier.
    delays = -geometry.positions @ u / C_SOUND

    t = np.arange(n) / fs
    tau = 0.0011
    channels = np.zeros((geometry.n_mics, n))
    t0 = 0.02
    for i, d in enumerate(delays):
        ts = t - t0 - d
        pulse = np.where(ts >= 0, (1 - ts / tau) * np.exp(-np.clip(ts, 0, None) / tau), 0.0)
        channels[i] = pulse
    if snr_db is not None:
        rms = np.sqrt(np.mean(channels**2))
        channels = channels + rng.standard_normal(channels.shape) * rms / 10 ** (snr_db / 20)
    return channels


def test_gcc_phat_sign_convention():
    """gcc_phat(x, y) must return D where y(t) = x(t - D)."""
    rng = np.random.default_rng(1)
    x = rng.standard_normal(4096)
    shift = 37
    y = np.roll(x, shift)  # y is x delayed by +37 samples
    delay, _ = gcc_phat(x, y, FS, interp=1)
    assert delay == pytest.approx(shift / FS, abs=1.5 / FS)


@pytest.mark.parametrize("azimuth", [0.0, 37.0, 95.0, 180.0, 271.0, 349.0])
def test_azimuth_recovered_noiseless(azimuth):
    geometry = ring_plus_mast()
    channels = _plane_wave(geometry, azimuth)
    result = estimate_doa(channels, geometry, FS)
    error = (result.azimuth_deg - azimuth + 180) % 360 - 180
    assert abs(error) < 1.0, f"azimuth error {error:.2f} deg at truth {azimuth}"


@pytest.mark.parametrize("elevation", [-20.0, 0.0, 25.0, 45.0])
def test_elevation_recovered_on_nonplanar_array(elevation):
    geometry = ring_plus_mast()
    assert not geometry.is_planar
    channels = _plane_wave(geometry, 60.0, elevation)
    result = estimate_doa(channels, geometry, FS)
    assert result.elevation_valid
    assert abs(result.elevation_deg - elevation) < 6.0


def test_planar_array_refuses_to_report_elevation():
    """The PS's flat 6-mic ring cannot observe elevation. It must say so."""
    geometry = planar_ring()
    assert geometry.is_planar
    channels = _plane_wave(geometry, 60.0, 30.0)
    result = estimate_doa(channels, geometry, FS)
    assert result.elevation_valid is False
    assert result.elevation_deg == 0.0
    # Azimuth is still recovered correctly despite the elevated source.
    assert abs((result.azimuth_deg - 60.0 + 180) % 360 - 180) < 3.0


def test_bearing_degrades_with_snr_not_silently():
    """Low SNR must inflate the reported sigma, not just the error."""
    geometry = ring_plus_mast()
    clean = estimate_doa(_plane_wave(geometry, 42.0, snr_db=40), geometry, FS)
    noisy = estimate_doa(_plane_wave(geometry, 42.0, snr_db=3, seed=5), geometry, FS)
    assert noisy.azimuth_sigma_deg > clean.azimuth_sigma_deg


def test_theoretical_floor_matches_hand_derivation():
    """d(theta) = c*d(tau)/L with L=0.30 m, fs=48 kHz, 0.1 sample -> ~0.14 deg."""
    floor = theoretical_bearing_floor_deg(0.30, 48_000.0, 0.1)
    assert 0.10 < floor < 0.20


def test_aperture_and_geometry_properties():
    ring = ring_plus_mast(radius=0.15, mast_height=0.15)
    assert ring.n_mics == 6
    # Largest spacing across a 0.15 m ring is the ring diameter chord.
    assert 0.25 < ring.aperture_m < 0.31
    assert planar_ring(6, 0.15).aperture_m == pytest.approx(0.30, abs=0.01)


# ------------------------------------------------------- outlier-pair rejection
def test_fit_plane_wave_rejects_one_bad_pair():
    """One badly corrupted pair (a reflection winning that one correlation)
    must be dropped and refit, not allowed to drag the whole bearing."""
    true_u = np.array([0.6, 0.8, 0.0])
    rows = np.array([
        [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0],
        [1.0, -1.0, 0.0], [-1.0, 1.0, 0.0], [0.5, 0.5, 0.0],
    ])
    b_clean = rows @ true_u
    b_bad = b_clean.copy()
    b_bad[0] += 5.0  # one badly corrupted correlation peak

    u_clean, _, rejected_clean, n_clean = _fit_plane_wave(rows, b_clean, planar=True)
    u_bad, _, rejected_bad, n_bad = _fit_plane_wave(rows, b_bad, planar=True)

    assert not rejected_clean
    assert n_clean == len(rows)
    assert rejected_bad
    assert n_bad == len(rows) - 1
    # After rejecting the bad pair, the recovered direction should land close
    # to the clean-data solution rather than being dragged toward the outlier.
    assert np.linalg.norm(u_bad - u_clean) < 0.05


def test_outlier_rejection_has_no_false_triggers_on_clean_signal():
    """The rejection mechanism must cost nothing when there is nothing to
    reject -- verified across many independent noise draws, not one seed."""
    geometry = ring_plus_mast()
    errors = []
    triggers = 0
    for seed in range(40):
        result = estimate_doa(_plane_wave(geometry, 55.0, snr_db=25, seed=seed), geometry, FS)
        errors.append(abs((result.azimuth_deg - 55.0 + 180) % 360 - 180))
        triggers += result.outlier_pair_rejected
    assert np.mean(errors) < 0.5
    assert triggers == 0, "outlier rejection fired on clean data -- false positive"


def test_outlier_rejection_recovers_bearing_from_one_bad_correlation():
    """The mechanism's actual target failure mode: GCC-PHAT picks the wrong
    peak on ONE pair (a plausible partial-multipath outcome), the other 14
    pairs stay good. This is a Monte Carlo over the geometry-level fit
    (isolating the rejection logic from audio synthesis specifics), matching
    what a full estimate_doa() call does internally.

    Measured before writing this assertion: mean error over 30 trials was
    11.8 deg (max 42.6 deg) without rejection, 0.9 deg (max 2.5 deg) with it.
    NOTE: this is a genuinely different failure mode from a whole corrupted
    channel (which touches 5 of 15 pairs at once) -- single-pair rejection
    does not, and is not expected to, fix that broader case.
    """
    geometry = ring_plus_mast()
    true_az = 55.0
    u_true = np.array([math.sin(math.radians(true_az)), math.cos(math.radians(true_az)), 0.0])
    n = geometry.n_mics
    rows = [geometry.positions[i] - geometry.positions[j]
            for i in range(n) for j in range(i + 1, n)]
    a_mat = np.asarray(rows)
    b_clean = a_mat @ u_true

    rng = np.random.default_rng(0)
    with_rej, without_rej = [], []
    for _ in range(30):
        b = b_clean + rng.normal(0, 0.01, size=len(b_clean))
        bad_idx = rng.integers(0, len(b_clean))
        b[bad_idx] += rng.choice([-1, 1]) * rng.uniform(0.3, 1.0)

        u_no, *_ = _fit_plane_wave(a_mat, b, planar=True, reject_outlier=False)
        u_yes, *_ = _fit_plane_wave(a_mat, b, planar=True, reject_outlier=True)
        az_no = math.degrees(math.atan2(u_no[0], u_no[1])) % 360
        az_yes = math.degrees(math.atan2(u_yes[0], u_yes[1])) % 360
        without_rej.append(abs((az_no - true_az + 180) % 360 - 180))
        with_rej.append(abs((az_yes - true_az + 180) % 360 - 180))

    assert np.mean(with_rej) < np.mean(without_rej) / 3
    assert np.mean(with_rej) < 3.0
