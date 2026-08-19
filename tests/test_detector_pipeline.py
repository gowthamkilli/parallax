"""Tests for the binary gunshot detector and the gated pipeline.

The property that matters operationally is not raw accuracy -- it is that the
ranging solver NEVER runs on something the classifier rejected. The crack-thump
maths is pure geometry and will happily return a confident range for a door
slam; the gate is the only thing standing between a nuisance transient and a
marker on a commander's map.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from parallax.ballistics import BallisticObservables
from parallax.detector import GunshotDetector, _rates
from parallax.features import FEATURE_NAMES, extract
from parallax.nwave import synth_crack_thump_channel, synth_nwave
from parallax.pipeline import classification_window, process
from sim.shockwave import Trajectory, node_observables

MODEL = Path("out/gunshot_detector.pkl")
FS = 48_000.0
ORIGIN = (28.6139, 77.2090)

requires_model = pytest.mark.skipif(
    not MODEL.exists(),
    reason="run `python -m sim.train_gunshot_detector` to produce out/gunshot_detector.pkl",
)


# -- feature-level: the N-wave shape features must do their job -------------
def test_nwave_features_separate_shock_from_blast():
    """An N-wave is symmetric with a linear ramp; a blast is neither."""
    from scipy import signal

    t = np.arange(int(0.0006 * FS)) / FS
    nwave = synth_nwave(FS, 0.0004)
    # Friedlander blast: sharp rise, exponential decay, shallow negative phase.
    tau = 0.0011
    tb = np.arange(int(0.006 * FS)) / FS
    blast = (1 - tb / tau) * np.exp(-tb / tau)

    f_n = extract(np.pad(nwave, (200, 2000)), FS)
    f_b = extract(np.pad(blast, (200, 2000)), FS)
    sym = FEATURE_NAMES.index("nwave_symmetry")
    lin = FEATURE_NAMES.index("nwave_ramp_linearity")

    # The N-wave's negative lobe matches its positive lobe far more closely.
    assert f_n[sym] > f_b[sym]
    # And its ramp is closer to a straight line.
    assert f_n[lin] >= f_b[lin]


def test_feature_vector_length_matches_names():
    x = np.random.default_rng(0).standard_normal(4096)
    assert len(extract(x, FS)) == len(FEATURE_NAMES)


def test_tonal_signal_has_no_nwave_structure():
    """A drone-like tone must not present a bipolar shock signature."""
    t = np.arange(int(0.03 * FS)) / FS
    tone = np.sin(2 * np.pi * 150 * t)
    f = extract(tone, FS)
    # A pure tone is symmetric, so allow symmetry, but its ramp is a sine, not
    # a straight line -- linearity must stay well below a true N-wave's.
    assert f[FEATURE_NAMES.index("nwave_ramp_linearity")] < 0.99


# -- classification window --------------------------------------------------
def test_classification_window_locks_onto_first_onset():
    """For a supersonic shot the FIRST onset is the crack, not the blast."""
    ch = synth_crack_thump_channel(FS, t_crack_s=0.02, t_blast_s=0.42,
                                   nwave_T_s=287e-6,
                                   rng=np.random.default_rng(0))
    win = classification_window(ch, FS)
    # The window is short (28 ms), so it cannot contain the blast 400 ms later.
    assert len(win) <= int(0.029 * FS)
    assert len(win) > 0


# -- rate arithmetic --------------------------------------------------------
def test_rates_arithmetic():
    y_true = np.array([1, 1, 1, 0, 0, 0, 0])
    y_pred = np.array([1, 1, 0, 1, 0, 0, 0])
    r = _rates(y_true, y_pred)
    assert r["recall"] == pytest.approx(2 / 3)
    assert r["precision"] == pytest.approx(2 / 3)
    assert r["false_positive_rate"] == pytest.approx(1 / 4)
    assert r["false_negative_rate"] == pytest.approx(1 / 3)


# -- model-level ------------------------------------------------------------
@requires_model
def test_detector_accepts_gunshots_and_rejects_nuisances():
    from sim.train_classifier import door_slam, drone, gunshot, personnel, vehicle

    det = GunshotDetector.load(MODEL)
    rng = np.random.default_rng(11)

    # Supersonic crack + thump captures, across the Whitham duration range.
    for T, dt in ((180e-6, 0.25), (287e-6, 0.41), (450e-6, 0.60)):
        ch = synth_crack_thump_channel(FS, 0.02, 0.02 + dt, T, rng=rng)
        assert det.predict_audio(classification_window(ch, FS), FS).is_gunshot

    # Muzzle blasts (the subsonic / second-arrival case).
    for _ in range(3):
        assert det.predict_audio(gunshot(rng), FS).is_gunshot

    # Non-gunshots must be rejected.
    for generator in (door_slam, drone, vehicle, personnel):
        x = generator(rng)
        x = x / (np.max(np.abs(x)) + 1e-12)
        assert not det.predict_audio(x, FS).is_gunshot


# -- pipeline-level: the gate is load-bearing -------------------------------
def _observables_for(range_m=300.0, miss_m=10.0):
    aim = 20.0
    u = np.array([math.sin(math.radians(aim)), math.cos(math.radians(aim))])
    perp = np.array([u[1], -u[0]])
    back = -math.sqrt(max(range_m ** 2 - miss_m ** 2, 0.0))
    traj = Trajectory(shooter_enu=back * u + miss_m * perp, aim_deg=aim,
                      muzzle_velocity_ms=700.0)
    return node_observables(traj, np.array([0.0, 0.0]), rng=None)


@requires_model
def test_gunshot_is_ranged_and_geolocated():
    det = GunshotDetector.load(MODEL)
    obs, truth = _observables_for(300.0, 10.0)
    audio = synth_crack_thump_channel(FS, 0.02, 0.02 + obs.dt_s,
                                      obs.nwave_duration_s,
                                      rng=np.random.default_rng(42))
    result = process(audio, FS, det, obs, ORIGIN[0], ORIGIN[1], node_id=1, seed=42)
    assert result.is_gunshot
    assert result.contact is not None
    d = result.to_dict()["fix"]
    assert d["distance_m"] == pytest.approx(300.0, abs=20.0)
    assert d["direction_deg"] == pytest.approx(truth.true_blast_bearing_deg, abs=1.0)
    assert d["latitude"] is not None and d["longitude"] is not None


@requires_model
def test_nuisance_never_reaches_the_solver():
    """The whole point of the gate: no classification, no range, no marker."""
    from sim.train_classifier import door_slam, drone

    det = GunshotDetector.load(MODEL)
    obs, _ = _observables_for(300.0, 10.0)   # a perfectly solvable geometry
    rng = np.random.default_rng(5)

    for generator in (door_slam, drone):
        x = generator(rng)
        x = x / (np.max(np.abs(x)) + 1e-12)
        result = process(x, FS, det, obs, ORIGIN[0], ORIGIN[1], node_id=1, seed=1)
        assert not result.is_gunshot
        # Even though `obs` would solve cleanly, no fix is produced.
        assert result.contact is None
        assert result.to_dict()["fix"] is None
