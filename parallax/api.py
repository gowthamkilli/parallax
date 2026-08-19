"""JSON API boundary for the (future) JavaScript front end.

Everything crossing this boundary is a plain dict / JSON value -- no numpy, no
dataclasses, no Python-only types -- so a browser can POST a measurement and
render the returned fix without any glue. Two entry points:

    process_node_report(payload)   one team's measurement -> one geolocated fix
    process_network(payload)       several teams' measurements -> the HQ fix

Input schema (single node)
--------------------------
    {
      "node":   {"id": 2, "lat": 28.6139, "lon": 77.2090, "temp_c": 20},
      "measurement": {
          "blast_bearing_deg": 42.0,
          "bearing_split_deg": 27.4,        # alpha; omit/0 => no crack
          "dt_s": 0.412,                    # blast - crack; omit/0 => no crack
          "nwave_duration_s": 0.000287,     # T; omit/0 => no crack
          "sigmas": {                        # all optional
              "blast_bearing_deg": 1.0,
              "bearing_split_deg": 1.5,
              "dt_s": 0.003,
              "nwave_duration_s": 3e-5
          }
      },
      "bullet": "5.56x45"                    # optional; selects Whitham length
    }

Output schema
-------------
    {
      "ok": true,
      "fix": {
          "direction": "N42.0E",              # quadrant compass bearing
          "range_m": 300.1,                   # null in scenario (b)
          "latitude": 28.616949,              # null if no range
          "longitude": 77.211075,
          "accuracy_pct": 87.3
      }
    }

``direction`` is the classic surveying quadrant-bearing notation (N/E/S/W
cardinals print bare; everything else is "N42.0E", "S8.3W", etc. -- which
quadrant, and how many degrees off the nearer of N/S) rather than a raw
0-360 number. See parallax.geometry.compass_bearing.

On bad input the response is {"ok": false, "error": "..."} rather than an
exception, so the front end always gets a JSON body it can branch on.
"""

from __future__ import annotations

from .ballistics import BULLET_LENGTHS_M, DEFAULT_BULLET_LENGTH_M, BallisticObservables
from .geometry import compass_bearing
from .localize import localize_single_node, localize_network


def _slim_fix(contact_dict: dict) -> dict:
    """Trim a GeoContact's full dict down to the five fields the front end
    actually needs, with direction re-expressed as a compass quadrant bearing
    instead of a raw 0-360 degree number. "range_m", not "distance_m" --
    this is a range to a shooter, not a generic distance."""
    return {
        "direction": compass_bearing(contact_dict["direction_deg"]),
        "range_m": contact_dict["distance_m"],
        "latitude": contact_dict["latitude"],
        "longitude": contact_dict["longitude"],
        "accuracy_pct": contact_dict["accuracy_pct"],
    }


def _bullet_length(name) -> float:
    if name is None:
        return DEFAULT_BULLET_LENGTH_M
    return BULLET_LENGTHS_M.get(str(name), DEFAULT_BULLET_LENGTH_M)


def _observables_from(measurement: dict) -> BallisticObservables:
    """Build a BallisticObservables from the measurement sub-dict."""
    sig = measurement.get("sigmas", {}) or {}
    return BallisticObservables(
        blast_bearing_deg=float(measurement["blast_bearing_deg"]),
        bearing_split_deg=float(measurement.get("bearing_split_deg", 0.0) or 0.0),
        dt_s=float(measurement.get("dt_s", 0.0) or 0.0),
        nwave_duration_s=float(measurement.get("nwave_duration_s", 0.0) or 0.0),
        blast_bearing_sigma_deg=float(sig.get("blast_bearing_deg", 1.0)),
        bearing_split_sigma_deg=float(sig.get("bearing_split_deg", 1.5)),
        dt_sigma_s=float(sig.get("dt_s", 0.003)),
        nwave_duration_sigma_s=float(sig.get("nwave_duration_s", 30e-6)),
    )


def process_node_report(payload: dict) -> dict:
    """One team's measurement -> one geolocated (or bearing-only) fix."""
    try:
        node = payload["node"]
        measurement = payload["measurement"]
        obs = _observables_from(measurement)
        contact = localize_single_node(
            node_lat=float(node["lat"]),
            node_lon=float(node["lon"]),
            obs=obs,
            node_id=node.get("id"),
            bullet_length_m=_bullet_length(payload.get("bullet")),
            temp_c=float(node.get("temp_c", 20.0)),
        )
        return {"ok": True, "fix": _slim_fix(contact.to_dict())}
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"bad node report: {exc}"}


def process_network(payload: dict) -> dict:
    """Several teams' measurements of one shot -> the fix HQ broadcasts."""
    try:
        bullet_length = _bullet_length(payload.get("bullet"))
        temp_c = float(payload.get("temp_c", 20.0))
        observations = []
        for entry in payload["nodes"]:
            node = entry["node"]
            observations.append({
                "node_id": node.get("id"),
                "lat": float(node["lat"]),
                "lon": float(node["lon"]),
                "observables": _observables_from(entry["measurement"]),
            })
        if not observations:
            return {"ok": False, "error": "no node reports supplied"}
        contact = localize_network(observations, bullet_length_m=bullet_length,
                                   temp_c=temp_c)
        return {"ok": True, "fix": _slim_fix(contact.to_dict())}
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"bad network payload: {exc}"}
