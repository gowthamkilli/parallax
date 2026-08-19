"""Gated end-to-end demo: audio -> "is it a gunshot?" -> direction + range.

    python -m sim.run_detect_demo --range 300 --miss 10

Shows the classifier acting as the GATE in front of the ranging solver: a
gunshot is detected, ranged and geolocated; a nuisance transient (firecracker,
door slam, drone) is rejected and never reaches the solver at all.

Operating constants are fixed (temperature, seed, and therefore the speed of
sound). Muzzle velocity is deliberately NOT an input -- it is recovered from the
shock-cone geometry, which is what makes the range ammunition-agnostic.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from parallax.detector import GunshotDetector
from parallax.geometry import LocalFrame
from parallax.nwave import synth_crack_thump_channel
from parallax.pipeline import TEMP_C, process
from sim.shockwave import Trajectory, node_observables
from sim.train_classifier import FS, door_slam, drone, firecracker

# Fixed operating constants, as requested: nothing here is a user knob.
SEED = 42
MUZZLE_VELOCITY_MS = 700.0
ORIGIN_LAT, ORIGIN_LON = 28.6139, 77.2090
AIM_DEG = 20.0


def _trajectory_placing_node_at(range_m: float, miss_m: float) -> Trajectory:
    """Build a trajectory so the node at ENU origin sees (range_m, miss_m)."""
    aim_u = np.array([math.sin(math.radians(AIM_DEG)), math.cos(math.radians(AIM_DEG))])
    perp = np.array([aim_u[1], -aim_u[0]])
    back = -math.sqrt(max(range_m ** 2 - miss_m ** 2, 0.0))
    return Trajectory(shooter_enu=back * aim_u + miss_m * perp, aim_deg=AIM_DEG,
                      muzzle_velocity_ms=MUZZLE_VELOCITY_MS)


def _report(label: str, result, truth=None):
    d = result.to_dict()
    det = d["detection"]
    verdict = "GUNSHOT" if det["is_gunshot"] else "NOT A GUNSHOT"
    print(f"[{label}]")
    print(f"    classifier : {verdict}  (p={det['probability']:.3f}, "
          f"threshold {det['threshold']:.2f})")
    if d["fix"] is None:
        print("    ranging    : not engaged - no direction, no range, no map marker")
        for note in d["notes"]:
            print(f"      - {note}")
        print()
        return
    fix = d["fix"]
    dist_acc = f"{fix['distance_accuracy_pct']:.0f}%" if fix["distance_accuracy_pct"] is not None else "n/a"
    rng_txt = f"{fix['distance_m']:.1f} m" if fix["distance_m"] is not None else "NULL"
    if truth is not None:
        print(f"    truth      : direction {truth.true_blast_bearing_deg:6.2f} deg   "
              f"range {truth.true_range_m:6.1f} m")
    print(f"    DIRECTION  : {fix['direction_deg']:.2f} deg   (accuracy {fix['direction_accuracy_pct']:.0f}%)")
    print(f"    RANGE      : {rng_txt}   (accuracy {dist_acc})")
    if fix["latitude"] is not None:
        print(f"    lat/lon    : {fix['latitude']:.6f}, {fix['longitude']:.6f}")
    print(f"    overall    : {fix['accuracy_pct']:.0f}%   [{fix['method']}]")
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--range", type=float, default=300.0, help="true shooter range, m")
    p.add_argument("--miss", type=float, default=10.0, help="true miss distance, m")
    p.add_argument("--model", type=Path, default=Path("out/gunshot_detector.pkl"))
    p.add_argument("--out", type=Path, default=Path("out/detect_fix.json"))
    args = p.parse_args()

    if not args.model.exists():
        print(f"[error] {args.model} not found - run  python -m sim.train_gunshot_detector  first.")
        return

    detector = GunshotDetector.load(args.model)
    rng = np.random.default_rng(SEED)
    frame = LocalFrame(ORIGIN_LAT, ORIGIN_LON)

    print("=" * 72)
    print("PARALLAX gated demo   audio -> classify -> direction + range  (SIMULATED)")
    print("=" * 72)
    print(f"constants: T {TEMP_C:.0f} C, seed {SEED}, muzzle velocity "
          f"{MUZZLE_VELOCITY_MS:.0f} m/s (NOT an input to the solver)")
    print(f"detector : {args.model}  threshold {detector.threshold:.2f}")
    print()

    # -- the real shot ------------------------------------------------------
    traj = _trajectory_placing_node_at(args.range, args.miss)
    obs, truth = node_observables(traj, np.array([0.0, 0.0]), temp_c=TEMP_C, rng=None)
    audio = synth_crack_thump_channel(
        FS, t_crack_s=0.02, t_blast_s=0.02 + max(obs.dt_s, 1e-3),
        nwave_T_s=max(obs.nwave_duration_s, 1e-5), rng=rng,
    )
    shot = process(audio, FS, detector, obs, ORIGIN_LAT, ORIGIN_LON,
                   node_id=1, seed=SEED)
    _report("GUNSHOT  supersonic round", shot, truth)

    # -- nuisances that must NOT reach the solver ---------------------------
    results = {"gunshot": shot.to_dict()}
    for label, generator in (("firecracker", firecracker),
                             ("door slam", door_slam),
                             ("drone", drone)):
        x = generator(rng)
        x = x / (np.max(np.abs(x)) + 1e-12)
        res = process(x, FS, detector, obs, ORIGIN_LAT, ORIGIN_LON, node_id=1, seed=SEED)
        _report(f"NUISANCE  {label}", res)
        results[label.replace(" ", "_")] = res.to_dict()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
