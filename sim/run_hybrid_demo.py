"""End-to-end demo of the HYBRID architecture: distributed nodes + ballistic
physics + cross-validated fusion, all through the real FusionEngine.

    python -m sim.run_hybrid_demo --range 300 --mach 2.04

This is the integration the design review (docs/07-crack-thump-backend.md,
section 5) asked for: the crack-thump solver is no longer a standalone path
that reports a number unquestioned -- it is ONE contact report pair
(SHOCKWAVE + ACOUSTIC) from one node, fed into the same FusionEngine that
already does association, triangulation and confidence scoring for the rest
of the system. A second node also hears the blast; its bearing triangulates
against the first node's blast bearing, and the two independent range
estimates (ballistic crack-thump vs. triangulation) are cross-validated
against each other -- fused if they agree, flagged if they don't.

Miss distance (how far the bullet's flight path passes from node 1) and the
second node's placement are fixed constants below rather than CLI flags --
they're scenario geometry, not something a demo caller should have to reason
about to see the fusion behaviour.
"""

from __future__ import annotations

import argparse
import math

import numpy as np

from parallax.ballistics import forward_observables, DEFAULT_BULLET_LENGTH_M
from parallax.contact import ContactReport, Modality, ThreatClass, FLAG_GPS_LOCKED
from parallax.fusion import FusionEngine, NodeState, speed_of_sound
from parallax.geometry import LocalFrame, bearing_between

ORIGIN_LAT, ORIGIN_LON = 28.6139, 77.2090
T0_NS = 1_700_000_000_000_000_000

# Fixed scenario geometry -- not CLI knobs. MISS_M is how far the bullet's
# flight path passes from node 1 (small relative to range, as a real close
# pass would be); SECOND_NODE_OFFSET_M is how far east node 2 stands.
MISS_M = 10.0
SECOND_NODE_OFFSET_M = 600.0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--range", type=float, default=300.0)
    p.add_argument("--mach", type=float, default=2.04)
    p.add_argument("--temp", type=float, default=20.0)
    args = p.parse_args()

    frame = LocalFrame(ORIGIN_LAT, ORIGIN_LON)
    node_a = np.array([0.0, 0.0])          # hears crack + blast
    node_b = np.array([SECOND_NODE_OFFSET_M, 0.0])  # hears blast only

    shooter = node_a + args.range * np.array([math.sin(math.radians(198.0)),
                                              math.cos(math.radians(198.0))])
    blast_bearing_a = bearing_between(node_a, shooter)
    blast_bearing_b = bearing_between(node_b, shooter)

    c = speed_of_sound(args.temp)
    fwd = forward_observables(args.range, MISS_M, args.mach,
                              bullet_length_m=DEFAULT_BULLET_LENGTH_M, c=c)
    crack_bearing_a = blast_bearing_a - fwd["bearing_split_deg"]

    lat_a, lon_a = frame.to_geodetic(*node_a)
    lat_b, lon_b = frame.to_geodetic(*node_b)

    shock = ContactReport(
        node_id=1, seq=1, t_event_ns=T0_NS, modality=Modality.SHOCKWAVE,
        threat_class=ThreatClass.GUNSHOT, class_confidence=0.80,
        azimuth_deg=crack_bearing_a % 360.0, azimuth_sigma_deg=1.0,
        nwave_duration_s=fwd["nwave_duration_s"],
        node_lat=lat_a, node_lon=lon_a, flags=FLAG_GPS_LOCKED,
    )
    blast_a = ContactReport(
        node_id=1, seq=2, t_event_ns=T0_NS + int(round(fwd["dt_s"] * 1e9)),
        modality=Modality.ACOUSTIC, threat_class=ThreatClass.GUNSHOT,
        class_confidence=0.85, azimuth_deg=blast_bearing_a % 360.0,
        azimuth_sigma_deg=1.0, node_lat=lat_a, node_lon=lon_a, flags=FLAG_GPS_LOCKED,
    )
    blast_b = ContactReport(
        node_id=2, seq=1, t_event_ns=T0_NS,
        modality=Modality.ACOUSTIC, threat_class=ThreatClass.GUNSHOT,
        class_confidence=0.85, azimuth_deg=blast_bearing_b % 360.0,
        azimuth_sigma_deg=1.0, node_lat=lat_b, node_lon=lon_b, flags=FLAG_GPS_LOCKED,
    )

    print("=" * 74)
    print("PARALLAX hybrid demo -- distributed nodes + ballistic physics + fusion")
    print("=" * 74)
    print(f"TRUTH  shooter {args.range:.0f} m / miss {MISS_M:.0f} m from node 1, "
          f"Mach {args.mach:.2f}, c {c:.1f} m/s")
    print(f"node 1: crack bearing {shock.azimuth_deg:.2f} deg, "
          f"blast bearing {blast_a.azimuth_deg:.2f} deg (split "
          f"{fwd['bearing_split_deg']:.2f} deg)")
    print(f"node 2: blast bearing {blast_b.azimuth_deg:.2f} deg "
          f"(no crack heard -- outside crack-thump reach or simply distant)")
    print()

    nodes = [
        NodeState(node_id=1, lat=lat_a, lon=lon_a),
        NodeState(node_id=2, lat=lat_b, lon=lon_b),
    ]
    engine = FusionEngine(nodes, frame)
    tracks = engine.process([shock, blast_a, blast_b])

    print(f"FUSION  3 reports -> {len(tracks)} track(s)")
    for track in tracks:
        d = track.to_dict()
        print(f"\ntrack {d['track_id']}  {d['threat_class']}  conf {d['confidence']:.2f}  "
              f"[{', '.join(d['modalities'])}]  nodes {d['contributing_nodes']}")
        print(f"  range method : {d['range_method']}")
        if d["range_m"] is not None:
            print(f"  range        : {d['range_m']:.1f} +/- {d['range_sigma_m']:.1f} m "
                  f"(truth {args.range:.0f} m)")
        print(f"  bearing      : {d['bearing_deg']:.2f} +/- {d['bearing_sigma_deg']:.2f} deg "
              f"from node {d['primary_node_id']}")
        if d["position_latlon"] is not None:
            print(f"  lat/lon      : {d['position_latlon'][0]:.6f}, {d['position_latlon'][1]:.6f}")
        for note in d["notes"]:
            print(f"    - {note}")


if __name__ == "__main__":
    main()
