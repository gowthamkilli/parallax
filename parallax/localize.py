"""Localization: crack-thump observables -> geolocated shooter, with accuracy.

This is the layer between the ballistic solver (which works in range/bearing)
and the map (which wants latitude/longitude). It also implements the two field
scenarios and the HQ relay:

  (a) A node inside crack-thump range produces a full fix -- direction, range,
      and therefore an absolute shooter lat/lon with an accuracy percentage.

  (b) A node outside crack-thump range produces direction only. distance is
      None (the "null" the field pipeline shows) and no lat/lon can be placed
      from a single bearing.

  HQ relay: when several teams report the same shot, localize_network() picks
  the best available fix -- a crack-thump range if any team had one, else a
  cross-bearing triangulation if two or more teams saw it -- and that single
  fix is what gets broadcast back to every team, including those that only ever
  heard a bearing.

Output is JSON-serialisable throughout so a JavaScript front end can consume it
directly:  {direction, latitude, longitude, distance_m, accuracy_pct, ...}.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .ballistics import (
    BallisticObservables,
    DEFAULT_BULLET_LENGTH_M,
    solve_crack_thump,
    speed_of_sound,
)
from .geometry import LocalFrame, triangulate, cep50_from_cov


@dataclass
class GeoContact:
    """One geolocated (or bearing-only) contact, ready for the map/front end."""

    direction_deg: float                 # compass bearing to the shooter
    distance_m: float | None             # None => bearing only (scenario b)
    latitude: float | None
    longitude: float | None
    accuracy_pct: float
    direction_accuracy_pct: float = 0.0        # confidence in direction_deg alone
    distance_accuracy_pct: float | None = None  # confidence in distance_m alone; None if null
    miss_distance_m: float | None = None
    mach: float | None = None
    range_sigma_m: float | None = None
    method: str = "crack_thump"
    in_crack_thump_range: bool = True
    contributing_nodes: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "direction_deg": _r(self.direction_deg, 2),
            "direction_accuracy_pct": _r(self.direction_accuracy_pct, 1),
            "distance_m": _r(self.distance_m, 1),
            "distance_accuracy_pct": _r(self.distance_accuracy_pct, 1),
            "latitude": _r(self.latitude, 6),
            "longitude": _r(self.longitude, 6),
            "accuracy_pct": _r(self.accuracy_pct, 1),
            "miss_distance_m": _r(self.miss_distance_m, 1),
            "mach": _r(self.mach, 3),
            "range_sigma_m": _r(self.range_sigma_m, 1),
            "method": self.method,
            "in_crack_thump_range": self.in_crack_thump_range,
            "contributing_nodes": list(self.contributing_nodes),
            "notes": list(self.notes),
        }


def _project(node_lat: float, node_lon: float, bearing_deg: float,
             range_m: float) -> tuple[float, float]:
    """Shooter lat/lon from a node at (lat, lon) + a bearing and a range."""
    frame = LocalFrame(node_lat, node_lon)
    a = math.radians(bearing_deg)
    east = range_m * math.sin(a)
    north = range_m * math.cos(a)
    return frame.to_geodetic(east, north)


def localize_single_node(node_lat: float, node_lon: float,
                         obs: BallisticObservables,
                         node_id: int | None = None,
                         bullet_length_m: float = DEFAULT_BULLET_LENGTH_M,
                         temp_c: float = 20.0, seed: int = 0) -> GeoContact:
    """Solve one node's observables and place the shooter on the map."""
    c = speed_of_sound(temp_c)
    sol = solve_crack_thump(obs, bullet_length_m=bullet_length_m, c=c, seed=seed)
    nodes = [node_id] if node_id is not None else []

    if sol.range_m is None:
        # Scenario (b): direction only, distance null.
        return GeoContact(
            direction_deg=sol.shooter_bearing_deg, distance_m=None,
            latitude=None, longitude=None, accuracy_pct=sol.accuracy_pct,
            direction_accuracy_pct=sol.direction_accuracy_pct,
            distance_accuracy_pct=None,
            method=sol.method, in_crack_thump_range=False,
            contributing_nodes=nodes, notes=list(sol.notes),
        )

    lat, lon = _project(node_lat, node_lon, sol.shooter_bearing_deg, sol.range_m)
    return GeoContact(
        direction_deg=sol.shooter_bearing_deg, distance_m=sol.range_m,
        latitude=lat, longitude=lon, accuracy_pct=sol.accuracy_pct,
        direction_accuracy_pct=sol.direction_accuracy_pct,
        distance_accuracy_pct=sol.distance_accuracy_pct,
        miss_distance_m=sol.miss_distance_m, mach=sol.mach,
        range_sigma_m=sol.range_sigma_m, method=sol.method,
        in_crack_thump_range=True, contributing_nodes=nodes,
        notes=list(sol.notes),
    )


def localize_network(observations: list[dict],
                     bullet_length_m: float = DEFAULT_BULLET_LENGTH_M,
                     temp_c: float = 20.0) -> GeoContact:
    """Fuse several teams' reports of one shot into the fix HQ will broadcast.

    Each entry in ``observations`` is a dict:
        {"node_id", "lat", "lon", "observables": BallisticObservables}

    Priority: a crack-thump range from any team wins (best single-node fix). If
    no team had a crack, but two or more have bearings, a cross-bearing
    triangulation is attempted. Otherwise the best bearing-only report stands.
    """
    solved = []
    for entry in observations:
        gc = localize_single_node(
            entry["lat"], entry["lon"], entry["observables"],
            node_id=entry.get("node_id"), bullet_length_m=bullet_length_m,
            temp_c=temp_c,
        )
        solved.append((entry, gc))

    ranged = [(e, gc) for e, gc in solved if gc.distance_m is not None]
    if ranged:
        entry, best = max(ranged, key=lambda pair: pair[1].accuracy_pct)
        best.contributing_nodes = [e.get("node_id") for e in observations
                                   if e.get("node_id") is not None]
        best.notes = list(best.notes) + [
            f"HQ broadcast: crack-thump fix from node {entry.get('node_id')}"
        ]
        return best

    # No crack anywhere: try to cross bearings (scenario b, resolved by geometry).
    bearings = [(e, gc) for e, gc in solved]
    if len(bearings) >= 2:
        anchor = LocalFrame(bearings[0][0]["lat"], bearings[0][0]["lon"])
        origins, az, sig = [], [], []
        for e, gc in bearings:
            origins.append(anchor.to_enu(e["lat"], e["lon"]))
            az.append(gc.direction_deg)
            sig.append(max(gc.notes and 2.0 or 1.5, 1.5))
        try:
            point, cov = triangulate(np.vstack(origins), np.array(az), np.array(sig))
            lat, lon = anchor.to_geodetic(point[0], point[1])
            cep = cep50_from_cov(cov)
            acc = float(np.clip(100.0 * (1.0 - min(cep / 250.0, 1.0)), 10.0, 95.0))
            # Range as seen from the first reporting node.
            d0 = point - origins[0]
            return GeoContact(
                direction_deg=bearings[0][1].direction_deg,
                distance_m=float(np.linalg.norm(d0)),
                latitude=lat, longitude=lon, accuracy_pct=round(acc, 1),
                direction_accuracy_pct=bearings[0][1].direction_accuracy_pct,
                distance_accuracy_pct=round(acc, 1),
                method="cross_bearing", in_crack_thump_range=False,
                contributing_nodes=[e.get("node_id") for e, _ in bearings],
                notes=[f"HQ broadcast: {len(bearings)}-team cross-bearing fix, CEP50 {cep:.0f} m"],
            )
        except np.linalg.LinAlgError:
            pass

    # Fall back to the single best bearing.
    _, best = max(solved, key=lambda pair: pair[1].accuracy_pct)
    best.notes = list(best.notes) + ["HQ broadcast: bearing only, awaiting a closer team"]
    return best


def _r(value, digits):
    return None if value is None else round(float(value), digits)
