"""Tests for the fusion layer -- association, ranging, and honesty.

The last group matters most: several of these tests assert that the system
REFUSES to produce a number. A fusion engine that always emits a position is
easy; one that knows when it cannot is the thing worth building.
"""

import math

import numpy as np
import pytest

from parallax.contact import (
    ContactReport,
    Modality,
    ThreatClass,
    WIRE_SIZE,
    FLAG_GPS_LOCKED,
    crc16_ccitt,
)
from parallax.fusion import FusionConfig, FusionEngine, NodeState, speed_of_sound
from parallax.geometry import LocalFrame, bearing_between, triangulate

ORIGIN = LocalFrame(28.6139, 77.2090)
T0 = 1_700_000_000_000_000_000


def _nodes(*enus):
    states = []
    for i, enu in enumerate(enus, start=1):
        lat, lon = ORIGIN.to_geodetic(enu[0], enu[1])
        states.append(NodeState(node_id=i, lat=lat, lon=lon))
    return states


def _report(node, enu, truth, modality, dt_ns=0, sigma=1.5, threat=ThreatClass.GUNSHOT):
    azimuth = bearing_between(np.array(enu), np.array(truth))
    return ContactReport(
        node_id=node, seq=1, t_event_ns=T0 + dt_ns, modality=modality,
        threat_class=threat, class_confidence=0.85,
        azimuth_deg=azimuth, azimuth_sigma_deg=sigma,
        node_lat=ORIGIN.to_geodetic(enu[0], enu[1])[0],
        node_lon=ORIGIN.to_geodetic(enu[0], enu[1])[1],
        flags=FLAG_GPS_LOCKED,
    )


# ---------------------------------------------------------------- wire format
def test_wire_record_is_42_bytes():
    assert WIRE_SIZE == 42


def test_wire_serialisation_and_crc():
    report = _report(1, (0, 0), (100, 200), Modality.ACOUSTIC)
    raw = report.to_bytes()
    assert len(raw) == 42
    body, crc = raw[:-2], int.from_bytes(raw[-2:], "little")
    assert crc16_ccitt(body) == crc


def test_bandwidth_argument_holds():
    """One second of raw 6ch/48k/24bit audio vs one contact report."""
    audio_bits = 48_000 * 6 * 24
    report_bits = WIRE_SIZE * 8
    assert audio_bits / report_bits > 20_000


# ---------------------------------------------------------------- physics
def test_speed_of_sound_temperature_dependence():
    assert speed_of_sound(20.0) == pytest.approx(343.2, abs=0.5)
    assert speed_of_sound(0.0) == pytest.approx(331.3, abs=0.5)
    # ~0.6 m/s per degree C is the number the range budget rests on.
    assert (speed_of_sound(30) - speed_of_sound(20)) == pytest.approx(6.0, abs=0.5)


def test_triangulation_recovers_known_point():
    origins = np.array([[-200.0, 0.0], [200.0, 0.0]])
    truth = np.array([50.0, 400.0])
    azimuths = np.array([bearing_between(o, truth) for o in origins])
    point, _ = triangulate(origins, azimuths)
    assert np.linalg.norm(point - truth) < 0.5


def test_triangulation_rejects_parallel_bearings():
    with pytest.raises(np.linalg.LinAlgError):
        triangulate(np.array([[0.0, 0.0], [100.0, 0.0]]), np.array([10.0, 10.0]))


# ---------------------------------------------------------------- ranging
def test_flash_acoustic_dt_gives_range_from_a_single_node():
    """The centrepiece: one node + optical = a ranged fix, no triangulation."""
    truth = np.array([200.0, 300.0])
    node_enu = (0.0, 0.0)
    true_range = float(np.linalg.norm(truth))
    c = speed_of_sound(20.0)
    dt_ns = int(true_range / c * 1e9)

    reports = [
        _report(1, node_enu, truth, Modality.OPTICAL_IR, dt_ns=0, sigma=0.6),
        _report(1, node_enu, truth, Modality.ACOUSTIC, dt_ns=dt_ns, sigma=1.5),
    ]
    engine = FusionEngine(_nodes(node_enu), ORIGIN)
    tracks = engine.process(reports)

    assert len(tracks) == 1, "flash and its own acoustic must not double-count"
    track = tracks[0]
    assert track.range_method == "flash_acoustic_dt"
    assert track.range_m == pytest.approx(true_range, rel=0.02)
    assert set(track.modalities) == {"OPTICAL_IR", "ACOUSTIC"}


def test_single_acoustic_node_reports_no_range():
    """A muzzle blast alone carries no range. The system must not invent one."""
    engine = FusionEngine(_nodes((0.0, 0.0)), ORIGIN)
    tracks = engine.process([_report(1, (0, 0), (200, 300), Modality.ACOUSTIC)])
    assert tracks[0].range_method == "none"
    assert tracks[0].range_m is None
    assert tracks[0].position_enu is None
    assert any("BEARING ONLY" in n for n in tracks[0].notes)


def test_negative_dt_is_rejected_as_non_physical():
    """Sound cannot arrive before light."""
    truth = np.array([200.0, 300.0])
    reports = [
        _report(1, (0, 0), truth, Modality.OPTICAL_IR, dt_ns=500_000_000, sigma=0.6),
        _report(1, (0, 0), truth, Modality.ACOUSTIC, dt_ns=0, sigma=1.5),
    ]
    engine = FusionEngine(_nodes((0.0, 0.0)), ORIGIN)
    track = engine.process(reports)[0]
    assert track.range_method == "none"
    assert any("non-physical" in n for n in track.notes)


def test_multi_node_triangulation():
    truth = np.array([60.0, 380.0])
    enus = [(-220.0, 0.0), (0.0, 40.0), (220.0, 0.0)]
    c = speed_of_sound(20.0)
    reports = [
        _report(i, enu, truth, Modality.ACOUSTIC,
                dt_ns=int(np.linalg.norm(truth - np.array(enu)) / c * 1e9))
        for i, enu in enumerate(enus, start=1)
    ]
    engine = FusionEngine(_nodes(*enus), ORIGIN)
    tracks = engine.process(reports)
    assert len(tracks) == 1
    assert tracks[0].range_method == "triangulation"
    assert np.linalg.norm(np.array(tracks[0].position_enu) - truth) < 30.0


# ---------------------------------------------------------------- association
def test_association_window_scales_with_node_baseline():
    """Nodes 1 km apart get a ~2.9 s window; nodes 50 m apart get ~150 ms."""
    far = _nodes((0.0, 0.0), (1000.0, 0.0))
    near = _nodes((0.0, 0.0), (50.0, 0.0))
    truth = (500.0, 800.0)
    a = _report(1, (0, 0), truth, Modality.ACOUSTIC)
    b = _report(2, (1000, 0), truth, Modality.ACOUSTIC)

    engine_far = FusionEngine(far, ORIGIN)
    engine_near = FusionEngine(near, ORIGIN)
    lag_far = engine_far._max_lag_s(a, b)
    lag_near = engine_near._max_lag_s(a, _report(2, (50, 0), truth, Modality.ACOUSTIC))
    assert lag_far == pytest.approx(1000 / speed_of_sound(20) + 0.010, rel=0.05)
    assert lag_near < 0.3
    assert lag_far > 8 * lag_near


def test_unrelated_events_do_not_merge():
    """Two shots 30 s apart are two tracks, not one."""
    enus = [(-220.0, 0.0), (220.0, 0.0)]
    truth = np.array([0.0, 400.0])
    reports = [
        _report(1, enus[0], truth, Modality.ACOUSTIC, dt_ns=0),
        _report(2, enus[1], truth, Modality.ACOUSTIC, dt_ns=30_000_000_000),
    ]
    engine = FusionEngine(_nodes(*enus), ORIGIN)
    assert len(engine.process(reports)) == 2


def test_different_threat_classes_do_not_merge():
    enus = [(-220.0, 0.0), (220.0, 0.0)]
    truth = np.array([0.0, 400.0])
    reports = [
        _report(1, enus[0], truth, Modality.ACOUSTIC, threat=ThreatClass.GUNSHOT),
        _report(2, enus[1], truth, Modality.ACOUSTIC, threat=ThreatClass.DRONE),
    ]
    engine = FusionEngine(_nodes(*enus), ORIGIN)
    assert len(engine.process(reports)) == 2


def test_back_bearings_do_not_associate():
    """Two nodes bearing AWAY from each other's crossing must not fuse."""
    enus = [(-200.0, 0.0), (200.0, 0.0)]
    engine = FusionEngine(_nodes(*enus), ORIGIN)
    a = _report(1, enus[0], (0.0, 400.0), Modality.ACOUSTIC)
    b = _report(2, enus[1], (0.0, 400.0), Modality.ACOUSTIC)
    b.azimuth_deg = (b.azimuth_deg + 180.0) % 360.0  # flip node 2 to a back bearing
    assert len(engine.process([a, b])) == 2


# ---------------------------------------------------------------- conflict
def test_shallow_crossing_angle_degrades_to_bearing_only():
    """Two nearly-collinear bearings must not be sold as a fix."""
    enus = [(0.0, 0.0), (0.0, 30.0)]  # nodes almost on top of each other
    truth = np.array([0.0, 2000.0])
    engine = FusionEngine(_nodes(*enus), ORIGIN,
                          config=FusionConfig(min_crossing_angle_deg=15.0))
    reports = [
        _report(1, enus[0], truth, Modality.ACOUSTIC),
        _report(2, enus[1], truth, Modality.ACOUSTIC),
    ]
    track = engine.process(reports)[0]
    assert track.range_method == "none"
    assert any("crossing angle" in n for n in track.notes)


def test_outlier_bearing_is_rejected_with_three_nodes():
    """A reflection-corrupted bearing is dropped when a majority disagrees."""
    enus = [(-220.0, 0.0), (0.0, 40.0), (220.0, 0.0)]
    truth = np.array([60.0, 380.0])
    reports = [_report(i, enu, truth, Modality.ACOUSTIC, sigma=1.0)
               for i, enu in enumerate(enus, start=1)]
    reports[2].azimuth_deg = (reports[2].azimuth_deg + 40.0) % 360.0  # bad bearing

    engine = FusionEngine(_nodes(*enus), ORIGIN)
    tracks = engine.process(reports)
    fixed = [t for t in tracks if t.position_enu is not None]
    assert fixed, "the two good bearings should still produce a fix"
    assert np.linalg.norm(np.array(fixed[0].position_enu) - truth) < 60.0


def test_confidence_rises_with_corroboration():
    truth = np.array([200.0, 300.0])
    c = speed_of_sound(20.0)
    dt_ns = int(np.linalg.norm(truth) / c * 1e9)
    engine = FusionEngine(_nodes((0.0, 0.0)), ORIGIN)

    acoustic_only = engine.process(
        [_report(1, (0, 0), truth, Modality.ACOUSTIC)]
    )[0].confidence
    both = engine.process([
        _report(1, (0, 0), truth, Modality.OPTICAL_IR, dt_ns=0, sigma=0.6),
        _report(1, (0, 0), truth, Modality.ACOUSTIC, dt_ns=dt_ns),
    ])[0].confidence
    assert both > acoustic_only
