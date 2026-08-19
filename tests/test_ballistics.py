"""Tests for the crack-thump ballistic solver.

The reference is the worked example from the design research:

    5.56x45 fired from R = 300 m, passing d = 10 m to one side, at a constant
    700 m/s (M = 2.04) with c = 343 m/s and bullet length l = 23 mm.

    Forward (what the sensor sees):
        Mach angle mu     29.4 deg
        bearing split a   27.4 deg
        blast arrival     0.875 s
        crack arrival     0.462 s
        dt                0.412 s
        N-wave duration   287 us

    Inverse (what the node computes from a, dt, T): R = 300 m, d ~ 10 m,
    M ~ 2.04, converging in two passes.
"""

import math

import pytest

from parallax.ballistics import (
    BallisticObservables,
    forward_observables,
    solve_crack_thump,
    whitham_duration_s,
    timing_dt_s,
    mach_angle_deg,
    _solve_core,
)

C = 343.0
L = 0.023  # 5.56x45 projectile length


def test_forward_matches_worked_example():
    fwd = forward_observables(range_m=300.0, miss_distance_m=10.0, mach=700.0 / C,
                              bullet_length_m=L, c=C)
    assert fwd["mach"] == pytest.approx(2.041, abs=0.005)
    assert fwd["mach_angle_deg"] == pytest.approx(29.4, abs=0.1)
    assert fwd["bearing_split_deg"] == pytest.approx(27.4, abs=0.1)
    assert fwd["t_blast_s"] == pytest.approx(0.875, abs=0.002)
    assert fwd["t_crack_s"] == pytest.approx(0.462, abs=0.002)
    assert fwd["dt_s"] == pytest.approx(0.412, abs=0.002)
    assert fwd["nwave_duration_s"] == pytest.approx(287e-6, abs=3e-6)


def test_inverse_recovers_geometry():
    R, d, M, converged, iters = _solve_core(
        bearing_split_deg=27.43, dt_s=0.412, nwave_T_s=287.5e-6,
        bullet_length_m=L, c=C,
    )
    assert converged
    assert iters <= 4  # "converges in two passes"
    assert R == pytest.approx(300.0, abs=5.0)
    assert d == pytest.approx(10.0, abs=1.5)
    assert M == pytest.approx(2.04, abs=0.03)


def test_roundtrip_forward_then_inverse():
    """Any physical (R, d, M) must survive a forward/inverse round trip."""
    for R0, d0, M0 in [(300, 10, 2.04), (150, 3, 2.6), (500, 25, 1.8), (80, 1.5, 3.0)]:
        fwd = forward_observables(R0, d0, M0, bullet_length_m=L, c=C)
        R, d, M, converged, _ = _solve_core(
            fwd["bearing_split_deg"], fwd["dt_s"], fwd["nwave_duration_s"], L, C
        )
        assert converged
        assert R == pytest.approx(R0, rel=0.05)
        assert M == pytest.approx(M0, rel=0.05)
        # d carries a quarter-power weakness; allow it more slack, by design.
        assert d == pytest.approx(d0, rel=0.30)


def test_full_solver_produces_accuracy_and_latlon_ready_fields():
    fwd = forward_observables(300.0, 10.0, 2.04, bullet_length_m=L, c=C)
    obs = BallisticObservables(
        blast_bearing_deg=42.0,
        bearing_split_deg=fwd["bearing_split_deg"],
        dt_s=fwd["dt_s"],
        nwave_duration_s=fwd["nwave_duration_s"],
    )
    sol = solve_crack_thump(obs, bullet_length_m=L, c=C, seed=1)
    assert sol.method == "crack_thump"
    assert sol.shooter_bearing_deg == pytest.approx(42.0, abs=0.01)
    assert sol.range_m == pytest.approx(300.0, abs=8.0)
    assert 0.0 < sol.accuracy_pct <= 99.0
    assert sol.range_sigma_m is not None and sol.range_sigma_m > 0


def test_no_crack_degrades_to_bearing_only():
    """Scenario (b): no usable crack -> direction shown, range is None (null)."""
    obs = BallisticObservables(
        blast_bearing_deg=137.0,
        bearing_split_deg=0.0,   # no separable crack
        dt_s=0.0,
        nwave_duration_s=0.0,
    )
    sol = solve_crack_thump(obs)
    assert sol.method == "bearing_only"
    assert sol.range_m is None
    assert sol.miss_distance_m is None
    assert sol.shooter_bearing_deg == pytest.approx(137.0)
    assert sol.accuracy_pct > 0  # a bearing is still a useful product


def test_subsonic_mach_angle_rejected():
    with pytest.raises(ValueError):
        mach_angle_deg(0.9)


def test_whitham_and_timing_are_monotonic_sane():
    # Larger miss distance -> longer N-wave (quarter power, but monotone up).
    assert whitham_duration_s(2.0, 20.0, L, C) > whitham_duration_s(2.0, 5.0, L, C)
    # Farther shot -> larger blast-crack gap.
    assert timing_dt_s(400.0, 10.0, 2.0, C) > timing_dt_s(200.0, 10.0, 2.0, C)
