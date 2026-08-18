"""Stress / edge-case suite for acoustic-only shockwave-blast ranging.

MEASUREMENT, NOT A FIX. Per explicit instruction, this file characterizes
current behavior at known-risky boundaries -- gate edges, the detect_onsets
blanking threshold, low SNR, and multiple near-simultaneous shots at one
node -- without changing parallax/fusion.py, sim/edge_node.py, or
parallax/features.py to make any of it "pass" more cleanly.

Assertions here are deliberately limited to invariants that should hold
REGARDLESS of whether the ranging math itself is accurate in a given corner
(no crash, no fabricated negative/NaN range, every input report accounted
for after fusion). Anywhere the *correctness* of the output is genuinely in
question, the test prints the observed behavior instead of asserting a
presumed-correct outcome -- see each test's docstring for what to look at
when reading `pytest -s` output.

For the bullet-speed/Mach sensitivity sweep (accuracy as a function of true
Mach, miss angle, and assumed-speed error), see
sim/shockwave_sensitivity_sweep.py -- that is a measurement script, not a
pytest suite, because its point is to produce a full data table for human
review, not a pass/fail signal.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from parallax.contact import ContactReport, Modality, ThreatClass, FLAG_GPS_LOCKED
from parallax.doa import ring_plus_mast
from parallax.fusion import FusionConfig, FusionEngine, NodeState, speed_of_sound
from parallax.geometry import LocalFrame, bearing_between
from parallax.features import detect_onsets
from sim.edge_node import EdgeNode
from sim.scenario import Shot, SimNode, render_node_audio

ORIGIN = LocalFrame(28.6139, 77.2090)
T0 = 1_700_000_000_000_000_000
FS = 48_000.0


def _geometry_for(alpha_deg, d_true, bullet_speed_mps, temp_c=20.0):
    """Same first-principles construction used in test_fusion.py and the
    sensitivity sweep script -- independent of fusion.py's own algebra."""
    c = speed_of_sound(temp_c)
    mach = bullet_speed_mps / c
    theta_m = math.asin(1.0 / mach)
    alpha = math.radians(alpha_deg)
    cross = d_true * math.sin(alpha)
    along = d_true * math.cos(alpha)
    node_enu = np.array([cross, along])
    x_prime = along - cross * math.sqrt(mach * mach - 1.0)
    emission_point = np.array([0.0, x_prime])
    blast_az = bearing_between(node_enu, np.array([0.0, 0.0]))
    shock_az = bearing_between(node_enu, emission_point)
    t_blast = d_true / c
    t_shock = x_prime / bullet_speed_mps + float(np.linalg.norm(node_enu - emission_point)) / c
    return blast_az, shock_az, t_blast - t_shock, node_enu, theta_m


def _reports(blast_az, shock_az, dt_s, t0=T0):
    dt_ns = int(round(dt_s * 1e9))
    return [
        ContactReport(node_id=1, seq=1, t_event_ns=t0, modality=Modality.ACOUSTIC_SHOCKWAVE,
                      threat_class=ThreatClass.GUNSHOT, class_confidence=0.70,
                      azimuth_deg=shock_az, azimuth_sigma_deg=2.0, flags=FLAG_GPS_LOCKED),
        ContactReport(node_id=1, seq=2, t_event_ns=t0 + dt_ns, modality=Modality.ACOUSTIC,
                      threat_class=ThreatClass.GUNSHOT, class_confidence=0.85,
                      azimuth_deg=blast_az, azimuth_sigma_deg=1.5, flags=FLAG_GPS_LOCKED),
    ]


# --------------------------------------------------------------- gate edges
def test_gate_boundary_just_inside_configured_ceiling():
    """alpha a hair under the 30 deg configured ceiling, well under theta_m
    (use a high-Mach round so the physical cone is wide): should ACCEPT."""
    # M = 1/sin(theta_m); choose theta_m=31 deg so it sits just outside the
    # 30 deg config ceiling, leaving room to test alpha=29.9 well inside both.
    v_b = speed_of_sound(20.0) / math.sin(math.radians(31.0))
    blast_az, shock_az, dt_s, node_enu, theta_m = _geometry_for(29.9, 350.0, v_b)
    node = NodeState(node_id=1, lat=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[0],
                     lon=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[1])
    engine = FusionEngine([node], ORIGIN, config=FusionConfig(bullet_speed_mps=v_b))
    track = engine.process(_reports(blast_az, shock_az, dt_s))[0]
    print(f"\n[gate just-inside] theta_m={math.degrees(theta_m):.2f} alpha=29.9 "
          f"method={track.range_method} range={track.range_m} notes={track.notes}")
    assert track.range_method == "shockwave_dt"
    assert track.range_m is not None and track.range_m > 0
    assert math.isfinite(track.range_sigma_m) and track.range_sigma_m > 0


def test_gate_boundary_just_outside_configured_ceiling():
    """alpha a hair over the 30 deg configured ceiling: should DECLINE, not
    fabricate a range. This is a pure config-ceiling test (theta_m is wide
    enough here that the physical cone isn't the binding constraint)."""
    v_b = speed_of_sound(20.0) / math.sin(math.radians(31.0))
    blast_az, shock_az, dt_s, node_enu, theta_m = _geometry_for(30.1, 350.0, v_b)
    node = NodeState(node_id=1, lat=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[0],
                     lon=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[1])
    engine = FusionEngine([node], ORIGIN, config=FusionConfig(bullet_speed_mps=v_b))
    track = engine.process(_reports(blast_az, shock_az, dt_s))[0]
    print(f"\n[gate just-outside] theta_m={math.degrees(theta_m):.2f} alpha=30.1 "
          f"method={track.range_method} notes={track.notes}")
    assert track.range_method != "shockwave_dt"


def test_gate_boundary_just_inside_physical_mach_cone():
    """alpha a hair under theta_m itself (physical cone edge binds before the
    30 deg config ceiling, using a narrow-cone/high-Mach round). f(alpha,M)
    approaches 0 here, so the reported sigma should be LARGE (this is where
    the range formula is most sensitive), not silently small/confident.
    Reports rather than asserts a specific accuracy bound.
    """
    v_b = 3.0 * speed_of_sound(20.0)  # M=3, theta_m ~ 19.47 deg < 30 deg ceiling
    _, theta_m_check = math.asin(1.0 / 3.0), None
    theta_m_deg = math.degrees(math.asin(1.0 / 3.0))
    alpha_deg = theta_m_deg * 0.999
    blast_az, shock_az, dt_s, node_enu, theta_m = _geometry_for(alpha_deg, 350.0, v_b)
    node = NodeState(node_id=1, lat=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[0],
                     lon=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[1])
    engine = FusionEngine([node], ORIGIN, config=FusionConfig(bullet_speed_mps=v_b))
    track = engine.process(_reports(blast_az, shock_az, dt_s))[0]
    print(f"\n[physical cone edge] theta_m={theta_m_deg:.3f} alpha={alpha_deg:.3f} "
          f"method={track.range_method} range={track.range_m} sigma={track.range_sigma_m} "
          f"notes={track.notes}")
    if track.range_method == "shockwave_dt":
        # It accepted right at the edge where f->0 (D=c*dt/f blows up for any
        # dt-measurement error) -- the finite-difference sigma SHOULD reflect
        # that with a large number. If it doesn't, that's the actual finding
        # to report: sigma is silently understating risk right where the
        # formula is most sensitive.
        print(f"    NOTE: accepted at 99.9% of theta_m with sigma={track.range_sigma_m:.1f} m "
              f"on a {track.range_m:.1f} m range ({track.range_sigma_m/track.range_m*100:.0f}% "
              f"relative) -- compare against a mid-cone case to judge whether this properly "
              f"reflects the ill-conditioning.")
    assert track.range_method in ("shockwave_dt", "none")  # no crash, no third option


# ------------------------------------------------------- blanking-window edge
@pytest.mark.parametrize("gap_ms", [18.0, 19.0, 19.9, 20.0, 20.1, 21.0, 22.0])
def test_blanking_window_threshold_behavior(gap_ms):
    """detect_onsets' hysteresis re-arm requires blank_n=20ms of SUSTAINED
    quiet. Sweep the gap between two clean synthetic pulses right across
    that threshold and report exactly where the transition from 1 onset to
    2 onsets occurs. Not asserting a specific gap value is "correct" --
    that boundary is a direct, known consequence of the 20ms default, and
    this test documents exactly where it bites.
    """
    n = int(0.15 * FS)
    rng = np.random.default_rng(0)
    x = 0.01 * rng.standard_normal(n)
    t = np.arange(n) / FS
    tau = 0.0003

    def pulse(t0):
        ts = t - t0
        return np.where(ts >= 0, np.exp(-np.clip(ts, 0, None) / tau), 0.0)

    x += 1.0 * pulse(0.050)
    x += 1.0 * pulse(0.050 + gap_ms / 1000.0)
    onsets = detect_onsets(x, FS, threshold_sigma=6.0, blanking_s=0.020)
    print(f"\n[blanking edge] gap={gap_ms}ms -> {len(onsets)} onset(s): {onsets}")
    assert len(onsets) in (1, 2)  # no crash, no runaway onset count


# ------------------------------------------------------------------ low SNR
@pytest.mark.parametrize("snr_db", [10.0, 5.0, 0.0, -5.0])
def test_low_snr_does_not_crash_or_fabricate(snr_db):
    """Drive the real audio->onset->DoA->classify->report pipeline at
    increasingly hostile SNR and confirm it degrades safely (no exception,
    no negative/NaN sigma, no crash) rather than checking accuracy, which is
    not the point of this test."""
    node = SimNode(node_id=1, enu=np.array([30.0, 348.0]), geometry=ring_plus_mast())
    shot = Shot(enu=np.array([0.0, 0.0]), trajectory_bearing_deg=0.0, bullet_speed_mps=880.0)
    edge = EdgeNode(node, ORIGIN)  # no classifier: stub GUNSHOT/0.75 path, isolates DoA/detect
    audio, cap_start, peak_spl = render_node_audio(node, shot, fs=FS, snr_db=snr_db,
                                                    rng=np.random.default_rng(11))
    reports = edge.make_acoustic_report(audio, FS, t_capture_start_s=cap_start,
                                        peak_spl_db=peak_spl, snr_db=snr_db, t0_ns=T0)
    print(f"\n[low SNR] snr={snr_db}dB -> {len(reports)} report(s): "
          f"{[(r.modality.name, round(r.azimuth_deg, 1), round(r.azimuth_sigma_deg, 1)) for r in reports]}")
    for r in reports:
        assert math.isfinite(r.azimuth_sigma_deg) and r.azimuth_sigma_deg >= 0
        assert 0.0 <= r.azimuth_deg < 360.0


# ------------------------------------------------- multiple near-simultaneous shots
def test_two_shots_close_in_time_do_not_fabricate_a_cross_paired_range():
    """Two DIFFERENT shots at the same node, close enough in time that the
    shockwave-pair timing window (up to ~2s, see _max_lag_s) could plausibly
    span both events. The same-node bearing-agreement gate is EXEMPTED for
    ACOUSTIC/ACOUSTIC_SHOCKWAVE pairs (by design, since their bearings are
    supposed to differ) -- which means the association layer has no bearing
    check standing between shot A's shockwave and shot B's blast if their
    timing happens to overlap.

    Association still merges the two shots into one cluster/track here (that
    over-merge is a KNOWN, DOCUMENTED, UNFIXED limitation -- see the session
    notes; fixing the association layer itself was explicitly scoped out
    tonight as higher-risk). What this test verifies is the narrower,
    lower-risk guard that WAS added: _range_from_shockwave_blast must not
    silently pick an arbitrary (and possibly cross-shot) pair of reports out
    of an ambiguous cluster and report a fabricated range for it. Shot A and
    shot B deliberately use DIFFERENT true ranges (300 m vs 900 m) so a wrong
    cross-pairing would be numerically distinguishable from either truth --
    the original version of this test used identical ranges for both shots,
    which made a wrong pairing look identical to a right one and was a real
    gap in the test itself, not just the code.
    """
    v_b = 880.0
    az_a_blast, az_a_shock, dt_a, enu_a, _ = _geometry_for(10.0, 300.0, v_b)
    az_b_blast, az_b_shock, dt_b, enu_b, _ = _geometry_for(10.0, 900.0, v_b)
    # Two different shots, different truth bearings (rotate shot B's whole
    # geometry by 150 deg so the two events are clearly physically distinct)
    # but both heard at the SAME node, T_B starting 0.4s after shot A's own
    # shockwave -- comfortably inside the ~2s shockwave-pair window.
    rot = 150.0
    az_b_blast = (az_b_blast + rot) % 360.0
    az_b_shock = (az_b_shock + rot) % 360.0

    t_shot_a = T0
    t_shot_b = T0 + int(0.4e9)
    reports = _reports(az_a_blast, az_a_shock, dt_a, t0=t_shot_a) + \
        _reports(az_b_blast, az_b_shock, dt_b, t0=t_shot_b)
    # both shots use node_id=1 by construction in _reports()

    node = NodeState(node_id=1, lat=0.0, lon=0.0)
    engine = FusionEngine([node], ORIGIN, config=FusionConfig(bullet_speed_mps=v_b))
    tracks = engine.process(reports)

    print(f"\n[two shots, same node] {len(reports)} reports in -> {len(tracks)} track(s) out")
    total_in_tracks = 0
    for t in tracks:
        mods = [(r.seq, r.modality.name, round(r.azimuth_deg, 1)) for r in t.contributing_reports]
        total_in_tracks += len(t.contributing_reports)
        print(f"  track {t.track_id}: range_method={t.range_method} range={t.range_m} "
              f"reports={mods} notes={t.notes}")

    # The one invariant that should ALWAYS hold regardless of clustering
    # correctness: no report is dropped or duplicated across tracks.
    assert total_in_tracks == len(reports)

    if len(tracks) == 1:
        # Association still over-merged (the known, unfixed limitation).
        # What must NOT happen: reporting a shockwave_dt range for that
        # ambiguous merged track, cross-paired or otherwise. It must decline.
        track = tracks[0]
        assert track.range_method != "shockwave_dt", (
            f"ambiguity guard did not fire -- got a fabricated shockwave_dt "
            f"range of {track.range_m} m from an ambiguous cross-shot cluster"
        )
        assert any("multiple ACOUSTIC" in n for n in track.notes), (
            "expected the ambiguity-guard note explaining the decline"
        )
    else:
        # Association happened to keep them separate for this geometry --
        # then each track's own range (if any) must match ITS shot's truth,
        # not the other shot's, and never something matching neither.
        for t in tracks:
            if t.range_method == "shockwave_dt":
                assert t.range_m == pytest.approx(300.0, rel=0.05) or \
                    t.range_m == pytest.approx(900.0, rel=0.05), (
                    f"track range {t.range_m} m matches neither shot's true range "
                    "(300 m or 900 m) -- looks like a cross-shot pairing"
                )
