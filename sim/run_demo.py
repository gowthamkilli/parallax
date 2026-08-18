"""End-to-end demo: synthetic shot -> per-node edge processing -> fusion -> JSON.

    python -m sim.run_demo --profile patrol --range 350 --bearing 35

Everything printed is derived from the simulated waveforms by the same code
that would run on a node. Nothing is hard-coded to the truth except the truth
itself, which is printed alongside so the error is visible rather than
asserted.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from pathlib import Path

import numpy as np

from parallax import profiles
from parallax.classifier import TransientClassifier
from parallax.contact import Modality
from parallax.fusion import FusionEngine, NodeState, speed_of_sound
from parallax.geometry import LocalFrame, bearing_between, cross_range_error
from sim.edge_node import EdgeNode
from sim.scenario import Shot, default_squad, render_node_audio

FS = 48_000.0
# Arbitrary but fixed anchor so the demo output is reproducible.
ORIGIN_LAT, ORIGIN_LON = 28.6139, 77.2090
T0_NS = 1_700_000_000_000_000_000  # fixed epoch; no wall-clock in the demo


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default="patrol", choices=sorted(profiles.PROFILES))
    parser.add_argument("--range", type=float, default=350.0, help="true shooter range, m")
    parser.add_argument("--bearing", type=float, default=35.0, help="true bearing from node 2, deg")
    parser.add_argument("--snr", type=float, default=22.0, help="dB")
    parser.add_argument("--temp", type=float, default=20.0, help="air temperature, C")
    parser.add_argument("--no-optical", action="store_true",
                        help="simulate a daylight/defilade flash miss")
    parser.add_argument("--multipath", action="store_true",
                        help="add a specular reflection off a facade")
    parser.add_argument("--no-shockwave", action="store_true",
                        help="disable ballistic shockwave modelling")
    parser.add_argument("--bullet-speed", type=float, default=880.0,
                        help="assumed bullet speed, m/s (ESTIMATE)")
    parser.add_argument("--nodes", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", type=Path, default=Path("out/classifier.pkl"))
    parser.add_argument("--out", type=Path, default=Path("out/tracks.json"))
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    profile = profiles.get(args.profile)
    frame = LocalFrame(ORIGIN_LAT, ORIGIN_LON)

    squad = default_squad()[: args.nodes]
    for node in squad:
        node.temp_c = args.temp
        node.has_optical = not args.no_optical

    # Truth: place the shooter at the requested range/bearing from node 2
    # (or node 1 if the squad is smaller).
    anchor = squad[1] if len(squad) > 1 else squad[0]
    theta = math.radians(args.bearing)
    truth = anchor.enu + args.range * np.array([math.sin(theta), math.cos(theta)])
    # Bullet trajectory: the shooter is firing at the patrol, so aim it
    # toward the anchor node -- gives the anchor node alpha=0 (dead on-axis)
    # for a clean shockwave-ranging demo, while other nodes see whatever
    # miss angle the actual squad geometry produces.
    trajectory_bearing = None if args.no_shockwave else bearing_between(truth, anchor.enu)
    shot = Shot(enu=truth, t_shot_s=0.0, visible_flash=not args.no_optical,
                trajectory_bearing_deg=trajectory_bearing, bullet_speed_mps=args.bullet_speed)

    reflection = None
    if args.multipath:
        # A facade to the west: the image source appears on a wildly wrong bearing.
        reflection = {"enu": truth + np.array([-2 * args.range * 0.9, 0.0]), "coefficient": 0.8}

    classifier = None
    if args.model.exists():
        classifier = TransientClassifier.load(args.model)
    else:
        print(f"[warn] {args.model} not found - run  python -m sim.train_classifier  first.")
        print("[warn] proceeding with a stub classifier (confidence fixed at 0.75).\n")

    print("=" * 74)
    print(f"PARALLAX demo   profile={profile.name}")
    print("=" * 74)
    print(f"TRUTH   shooter at ENU ({truth[0]:+.1f}, {truth[1]:+.1f}) m, "
          f"{args.range:.0f} m / {args.bearing:.1f} deg from node {anchor.node_id}")
    print(f"        c = {speed_of_sound(args.temp):.1f} m/s at {args.temp:.0f} C, "
          f"SNR {args.snr:.0f} dB, optical {'OFF' if args.no_optical else 'ON'}, "
          f"multipath {'ON' if args.multipath else 'OFF'}")
    print()

    reports = []
    print(f"{'node':>5} {'modality':<9} {'true az':>8} {'est az':>8} {'err':>7} "
          f"{'sigma':>7} {'elev':>7} {'class':<10} {'conf':>5}")
    print("-" * 74)

    for sim_node in squad:
        edge = EdgeNode(sim_node, frame, classifier=classifier, profile=profile)
        true_bearing = bearing_between(sim_node.enu, truth)

        audio, capture_start, peak_spl = render_node_audio(
            sim_node, shot, fs=FS, snr_db=args.snr, temp_c=args.temp,
            reflection=reflection, rng=rng,
        )

        # Optical first: the flash is coincident with the shot.
        if sim_node.has_optical:
            optical = edge.make_optical_report(true_bearing, T0_NS, rng=rng)
            reports.append(optical)
            print(f"{sim_node.node_id:>5} {'OPTICAL':<9} {true_bearing:>8.2f} "
                  f"{optical.azimuth_deg:>8.2f} "
                  f"{_werr(optical.azimuth_deg, true_bearing):>7.2f} "
                  f"{optical.azimuth_sigma_deg:>7.2f} {'-':>7} "
                  f"{optical.threat_class.name:<10} {optical.class_confidence:>5.2f}")

        acoustic_reports = edge.make_acoustic_report(
            audio, FS, t_capture_start_s=capture_start, peak_spl_db=peak_spl,
            snr_db=args.snr, t0_ns=T0_NS,
        )
        if not acoustic_reports:
            print(f"{sim_node.node_id:>5} {'ACOUSTIC':<9}  no detection (below threshold)")
            continue
        for acoustic in acoustic_reports:
            reports.append(acoustic)
            label = "SHOCKWAVE" if acoustic.modality == Modality.ACOUSTIC_SHOCKWAVE else "ACOUSTIC"
            print(f"{sim_node.node_id:>5} {label:<9} {true_bearing:>8.2f} "
                  f"{acoustic.azimuth_deg:>8.2f} "
                  f"{_werr(acoustic.azimuth_deg, true_bearing):>7.2f} "
                  f"{acoustic.azimuth_sigma_deg:>7.2f} "
                  f"{acoustic.elevation_deg:>7.2f} "
                  f"{acoustic.threat_class.name:<10} {acoustic.class_confidence:>5.2f}")

    if not reports:
        print("\nNo contacts. Nothing to fuse.")
        return

    print(f"\nwire cost: {len(reports)} reports x {reports[0].to_bytes().__len__()} B "
          f"= {len(reports) * len(reports[0].to_bytes())} B total")

    # -- fusion ------------------------------------------------------------
    node_states = [
        NodeState(node_id=n.node_id, **dict(zip(("lat", "lon"),
                  frame.to_geodetic(n.enu[0], n.enu[1]))), temp_c=n.temp_c)
        for n in squad
    ]
    # Fusion assumes a bullet speed independently of the simulator's truth
    # value; default them equal so the demo's shockwave range recovers
    # cleanly, without mutating the profile's shared FusionConfig instance.
    fusion_config = dataclasses.replace(profile.fusion, bullet_speed_mps=args.bullet_speed)
    engine = FusionEngine(node_states, frame, config=fusion_config)
    tracks = engine.process(reports)

    print("\n" + "=" * 74)
    print(f"FUSION  {len(reports)} reports -> {len(tracks)} track(s)")
    print("=" * 74)
    for track in tracks:
        d = track.to_dict()
        print(f"\ntrack {d['track_id']}  {d['threat_class']}  conf {d['confidence']:.2f}"
              f"  [{', '.join(d['modalities'])}]  nodes {d['contributing_nodes']}")
        print(f"  range method : {d['range_method']}")
        if d["range_m"] is not None:
            error = d["range_m"] - args.range
            print(f"  range        : {d['range_m']:.1f} +/- {d['range_sigma_m']:.1f} m "
                  f"(truth {args.range:.0f} m, error {error:+.1f} m)")
        print(f"  bearing      : {d['bearing_deg']:.2f} +/- {d['bearing_sigma_deg']:.2f} deg "
              f"from node {d['primary_node_id']}")
        if d["position_enu"] is not None:
            est = np.array(d["position_enu"])
            print(f"  position ENU : ({est[0]:+.1f}, {est[1]:+.1f}) m   "
                  f"miss distance {np.linalg.norm(est - truth):.1f} m")
            print(f"  lat/lon      : {d['position_latlon'][0]:.6f}, {d['position_latlon'][1]:.6f}")
        if d["cep50_m"] is not None:
            semi_major, semi_minor, orientation = d["ellipse"]
            print(f"  CEP50        : {d['cep50_m']:.1f} m  "
                  f"(1-sigma ellipse {semi_major:.0f} x {semi_minor:.0f} m @ {orientation:.0f} deg)")
        if d["bearing_sigma_deg"] and d["range_m"]:
            print(f"  cross-range  : {cross_range_error(d['range_m'], d['bearing_sigma_deg']):.1f} m "
                  f"at 1 sigma of bearing")
        alert = "ALERT" if d["confidence"] >= profile.fusion.min_confidence_to_alert else "below alert threshold"
        print(f"  disposition  : {alert} (profile threshold "
              f"{profile.fusion.min_confidence_to_alert:.2f})")
        for note in d["notes"]:
            print(f"    - {note}")

    payload = {
        "profile": profile.key,
        "origin": {"lat": ORIGIN_LAT, "lon": ORIGIN_LON},
        "truth": {"enu": [float(truth[0]), float(truth[1])],
                  "range_m": args.range, "bearing_deg": args.bearing},
        "nodes": [
            {"node_id": n.node_id, "enu": [float(n.enu[0]), float(n.enu[1])],
             "lat": ns.lat, "lon": ns.lon, "has_optical": n.has_optical}
            for n, ns in zip(squad, node_states)
        ],
        "reports": [r.to_dict() for r in reports],
        "tracks": [t.to_dict() for t in tracks],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}   ->  python -m viz.radar {args.out}")


def _werr(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


if __name__ == "__main__":
    main()
