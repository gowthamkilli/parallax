"""Integration tests: forward geometry -> observables -> geolocated fix -> JSON.

These cover the two field scenarios (ranged vs bearing-only), the geodesy, the
HQ network fusion, and the JSON API contract the JavaScript front end depends
on.
"""

import math

import numpy as np
import pytest

from parallax import api
from parallax.localize import localize_single_node, localize_network
from sim.shockwave import Trajectory, node_observables
from parallax.geometry import LocalFrame

ORIGIN = (28.6139, 77.2090)


def _traj_placing_node_at(range_m, miss_m, aim_deg=20.0, velocity=700.0):
    """Build a trajectory so that a node at ENU origin sees (range_m, miss_m)."""
    aim_u = np.array([math.sin(math.radians(aim_deg)), math.cos(math.radians(aim_deg))])
    perp = np.array([aim_u[1], -aim_u[0]])
    back = -math.sqrt(max(range_m**2 - miss_m**2, 0.0))
    shooter = back * aim_u + miss_m * perp
    return Trajectory(shooter_enu=shooter, aim_deg=aim_deg, muzzle_velocity_ms=velocity)


def test_in_range_node_produces_geolocated_fix():
    traj = _traj_placing_node_at(300.0, 10.0)
    obs, truth = node_observables(traj, np.array([0.0, 0.0]), rng=None)
    assert truth.in_crack_thump_range

    contact = localize_single_node(ORIGIN[0], ORIGIN[1], obs, node_id=1)
    d = contact.to_dict()
    assert d["distance_m"] == pytest.approx(300.0, abs=15.0)
    assert d["latitude"] is not None and d["longitude"] is not None
    assert d["direction_deg"] == pytest.approx(truth.true_blast_bearing_deg, abs=0.5)
    assert 0 < d["accuracy_pct"] <= 99

    # The placed lat/lon must sit ~range away from the node, in the bearing dir.
    frame = LocalFrame(ORIGIN[0], ORIGIN[1])
    east, north = frame.to_enu(d["latitude"], d["longitude"])
    assert math.hypot(east, north) == pytest.approx(d["distance_m"], rel=0.02)


def test_out_of_range_node_is_bearing_only_null_distance():
    # A far, off-axis node: outside the crack-thump reach.
    traj = _traj_placing_node_at(300.0, 10.0)
    far = np.array([700.0, 500.0])
    obs, truth = node_observables(traj, far, rng=None)
    assert not truth.in_crack_thump_range

    contact = localize_single_node(ORIGIN[0], ORIGIN[1], obs, node_id=2)
    d = contact.to_dict()
    assert d["distance_m"] is None            # the "null" the field shows
    assert d["latitude"] is None
    assert d["method"] == "bearing_only"
    assert d["direction_deg"] == pytest.approx(truth.true_blast_bearing_deg, abs=0.5)


def test_hq_network_prefers_the_crack_thump_fix():
    traj = _traj_placing_node_at(300.0, 10.0)
    frame = LocalFrame(*ORIGIN)
    near_ll = ORIGIN
    far_enu = np.array([700.0, 500.0])
    far_ll = frame.to_geodetic(far_enu[0], far_enu[1])

    obs_near, _ = node_observables(traj, np.array([0.0, 0.0]), rng=None)
    obs_far, _ = node_observables(traj, far_enu, rng=None)

    fix = localize_network([
        {"node_id": 1, "lat": near_ll[0], "lon": near_ll[1], "observables": obs_near},
        {"node_id": 2, "lat": far_ll[0], "lon": far_ll[1], "observables": obs_far},
    ])
    d = fix.to_dict()
    assert d["distance_m"] is not None
    assert d["method"] == "crack_thump"
    assert 1 in d["contributing_nodes"]


def test_api_single_node_contract():
    traj = _traj_placing_node_at(300.0, 10.0)
    obs, _ = node_observables(traj, np.array([0.0, 0.0]), rng=None)
    payload = {
        "node": {"id": 1, "lat": ORIGIN[0], "lon": ORIGIN[1], "temp_c": 20},
        "measurement": {
            "blast_bearing_deg": obs.blast_bearing_deg,
            "bearing_split_deg": obs.bearing_split_deg,
            "dt_s": obs.dt_s,
            "nwave_duration_s": obs.nwave_duration_s,
        },
        "bullet": "5.56x45",
    }
    resp = api.process_node_report(payload)
    assert resp["ok"] is True
    fix = resp["fix"]
    assert set(fix) == {"direction", "range_m", "latitude", "longitude", "accuracy_pct"}
    assert fix["range_m"] == pytest.approx(300.0, abs=15.0)
    assert fix["direction"][0] in "NS"  # quadrant bearing, not a raw 0-360 number
    assert fix["latitude"] is not None and fix["longitude"] is not None


def test_api_rejects_bad_input_without_raising():
    resp = api.process_node_report({"node": {"lat": 1.0}})  # missing lon, measurement
    assert resp["ok"] is False
    assert "error" in resp


def test_api_network_contract():
    traj = _traj_placing_node_at(300.0, 10.0)
    frame = LocalFrame(*ORIGIN)
    far_enu = np.array([700.0, 500.0])
    far_ll = frame.to_geodetic(far_enu[0], far_enu[1])
    obs_near, _ = node_observables(traj, np.array([0.0, 0.0]), rng=None)
    obs_far, _ = node_observables(traj, far_enu, rng=None)

    payload = {
        "bullet": "5.56x45",
        "nodes": [
            {"node": {"id": 1, "lat": ORIGIN[0], "lon": ORIGIN[1]},
             "measurement": {"blast_bearing_deg": obs_near.blast_bearing_deg,
                             "bearing_split_deg": obs_near.bearing_split_deg,
                             "dt_s": obs_near.dt_s,
                             "nwave_duration_s": obs_near.nwave_duration_s}},
            {"node": {"id": 2, "lat": far_ll[0], "lon": far_ll[1]},
             "measurement": {"blast_bearing_deg": obs_far.blast_bearing_deg}},
        ],
    }
    resp = api.process_network(payload)
    assert resp["ok"] is True
    assert resp["fix"]["range_m"] is not None
