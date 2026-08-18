"""Tests for the ballistic shockwave modelling added to sim/scenario.py.

Mirrors the existing test-per-claim convention in tests/test_doa.py and
tests/test_fusion.py: several of these assert an ABSENCE (no shockwave pulse
beyond the Mach cone), which matters as much as the presence does.
"""

import math

import numpy as np
import pytest

from parallax.doa import ring_plus_mast
from parallax.features import bandpass, detect_onsets
from sim.scenario import Shot, SimNode, render_node_audio

FS = 48_000.0


def test_detect_onsets_finds_two_close_transients():
    """Re-arm mechanism in isolation: two clean, fast-settling pulses with a
    gap comfortably larger than the hysteresis blanking window must both be
    found. (Whether a REAL bandpassed blast pulse's own ringing tail can be
    mistaken for a second transient is a separate, scenario-level question --
    see test_no_trajectory_means_no_shockwave.)
    """
    n = int(0.15 * FS)  # > noise_window_s (0.05 s) so the noise floor is real
    rng = np.random.default_rng(0)
    x = 0.01 * rng.standard_normal(n)
    t = np.arange(n) / FS
    tau = 0.0003

    def pulse(t0):
        ts = t - t0
        return np.where(ts >= 0, np.exp(-np.clip(ts, 0, None) / tau), 0.0)

    x += 1.0 * pulse(0.060)
    x += 1.0 * pulse(0.095)  # 35 ms later -- clears the 20 ms hysteresis window
    onsets = detect_onsets(x, FS, threshold_sigma=6.0, blanking_s=0.020)

    assert len(onsets) == 2
    assert onsets[1] > onsets[0]
    assert (onsets[1] - onsets[0]) / FS == pytest.approx(0.035, abs=0.002)


def test_detect_onsets_single_transient_unchanged():
    """No second transient present -> exactly one onset, as before."""
    n = int(0.15 * FS)
    rng = np.random.default_rng(1)
    x = 0.01 * rng.standard_normal(n)
    t = np.arange(n) / FS
    x += np.exp(-np.clip(t - 0.06, 0, None) / 0.0011) * (t >= 0.06)

    assert len(detect_onsets(x, FS, threshold_sigma=6.0)) == 1


def test_shockwave_precedes_blast_on_axis_node():
    """A node placed directly downrange (alpha=0) must see both a shockwave
    onset and a muzzle-blast onset, shockwave first."""
    node = SimNode(node_id=1, enu=np.array([0.0, 350.0]), geometry=ring_plus_mast())
    shot = Shot(enu=np.array([0.0, 0.0]), trajectory_bearing_deg=0.0, bullet_speed_mps=880.0)
    audio, _, _ = render_node_audio(node, shot, fs=FS, snr_db=30.0,
                                    rng=np.random.default_rng(2))
    reference = bandpass(audio[0], FS)
    onsets = detect_onsets(reference, FS, threshold_sigma=6.0)

    assert len(onsets) == 2, "expected both a shockwave and a blast onset"
    assert onsets[1] > onsets[0]


def test_no_shockwave_beyond_mach_cone():
    """A node far off the line of fire (alpha > theta_m) hears only the
    blast -- the shockwave must not be rendered at all, not just weakly."""
    # Muzzle at the origin, trajectory due north; this node sits almost
    # directly EAST of the muzzle -- alpha ~= 89 deg, far outside any
    # rifle's Mach cone (~23 deg for an 880 m/s round).
    node = SimNode(node_id=1, enu=np.array([350.0, 5.0]), geometry=ring_plus_mast())
    shot = Shot(enu=np.array([0.0, 0.0]), trajectory_bearing_deg=0.0, bullet_speed_mps=880.0)
    audio, _, _ = render_node_audio(node, shot, fs=FS, snr_db=30.0,
                                    rng=np.random.default_rng(3))
    reference = bandpass(audio[0], FS)
    onsets = detect_onsets(reference, FS, threshold_sigma=6.0)

    assert len(onsets) == 1, "only the blast should be detected this far off-axis"


def test_no_trajectory_means_no_shockwave():
    """Backward compatibility: trajectory_bearing_deg=None (the default)
    must render exactly what the pre-shockwave code did -- one pulse."""
    node = SimNode(node_id=1, enu=np.array([0.0, 350.0]), geometry=ring_plus_mast())
    shot = Shot(enu=np.array([0.0, 0.0]))
    audio, _, _ = render_node_audio(node, shot, fs=FS, snr_db=30.0,
                                    rng=np.random.default_rng(4))
    reference = bandpass(audio[0], FS)
    onsets = detect_onsets(reference, FS, threshold_sigma=6.0)

    assert len(onsets) == 1


def test_subsonic_bullet_speed_disables_shockwave():
    """Mach <= 1 is physically incapable of producing a shockwave."""
    node = SimNode(node_id=1, enu=np.array([0.0, 350.0]), geometry=ring_plus_mast())
    shot = Shot(enu=np.array([0.0, 0.0]), trajectory_bearing_deg=0.0, bullet_speed_mps=300.0)
    audio, _, _ = render_node_audio(node, shot, fs=FS, snr_db=30.0,
                                    rng=np.random.default_rng(5))
    reference = bandpass(audio[0], FS)
    onsets = detect_onsets(reference, FS, threshold_sigma=6.0)

    assert len(onsets) == 1
