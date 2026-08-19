"""End-to-end crack-thump demo: trajectory -> observables -> geolocated fix.

    python -m sim.run_ballistic_demo --range 300 --miss 10 --velocity 700

Runs the two field scenarios and the HQ relay:
  * a team INSIDE crack-thump range -> full fix (direction + distance + lat/lon)
  * a team OUTSIDE crack-thump range -> direction only, distance null
  * HQ fuses both and broadcasts the best fix to everyone

Truth is printed next to every estimate so the error is visible, not asserted.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from parallax.ballistics import speed_of_sound
from parallax.localize import localize_single_node, localize_network
from parallax.nwave import synth_crack_thump_channel, measure_crack_thump
from sim.shockwave import Trajectory, node_observables

ORIGIN_LAT, ORIGIN_LON = 28.6139, 77.2090


def _latlon(node_enu):
    from parallax.geometry import LocalFrame
    return LocalFrame(ORIGIN_LAT, ORIGIN_LON).to_geodetic(node_enu[0], node_enu[1])


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--range", type=float, default=300.0, help="true shooter range from the near team, m")
    p.add_argument("--miss", type=float, default=10.0, help="true miss distance, m")
    p.add_argument("--velocity", type=float, default=700.0, help="muzzle velocity, m/s")
    p.add_argument("--temp", type=float, default=20.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", type=Path, default=Path("out/ballistic_fix.json"))
    args = p.parse_args()

    rng = np.random.default_rng(args.seed)
    c = speed_of_sound(args.temp)
    mach = args.velocity / c

    # Place the shooter and aim so the NEAR team (node 1) sits at the requested
    # range/miss. A FAR team (node 2) is 900 m away, outside crack range.
    near_enu = np.array([0.0, 0.0])
    aim = 20.0  # bullet travels roughly north-north-east
    aim_u = np.array([math.sin(math.radians(aim)), math.cos(math.radians(aim))])
    # Shooter is 'range' behind the near team along a line offset by 'miss'.
    back = -math.sqrt(max(args.range**2 - args.miss**2, 0.0))
    perp = np.array([aim_u[1], -aim_u[0]])
    shooter_enu = near_enu + back * aim_u + args.miss * perp
    traj = Trajectory(shooter_enu=shooter_enu, aim_deg=aim,
                      muzzle_velocity_ms=args.velocity)

    far_enu = near_enu + np.array([700.0, 500.0])

    print("=" * 72)
    print("PARALLAX crack-thump demo (SIMULATED)")
    print("=" * 72)
    print(f"TRUTH  shooter ENU ({shooter_enu[0]:+.1f}, {shooter_enu[1]:+.1f}) m, "
          f"aim {aim:.0f} deg, v {args.velocity:.0f} m/s (M {mach:.2f}), c {c:.1f} m/s")
    print()

    reports = []
    for node_id, enu, label in [(1, near_enu, "NEAR team"), (2, far_enu, "FAR team")]:
        obs, truth = node_observables(traj, enu, temp_c=args.temp, rng=rng)
        lat, lon = _latlon(enu)
        contact = localize_single_node(lat, lon, obs, node_id=node_id, temp_c=args.temp)
        d = contact.to_dict()

        print(f"[{label}] node {node_id}  in-crack-thump-range={truth.in_crack_thump_range}"
              f"  ({truth.reason})")
        print(f"    truth : bearing {truth.true_blast_bearing_deg:6.2f} deg  "
              f"range {truth.true_range_m:6.1f} m  miss {truth.true_miss_m:5.1f} m  "
              f"M {truth.true_mach:.2f}")
        rng_txt = f"{d['distance_m']:.1f} m" if d["distance_m"] is not None else "NULL"
        print(f"    est   : bearing {d['direction_deg']:6.2f} deg  range {rng_txt:>8}  "
              f"miss {d['miss_distance_m'] if d['miss_distance_m'] is not None else '   -'}  "
              f"acc {d['accuracy_pct']:.0f}%  [{d['method']}]")
        if d["latitude"] is not None:
            print(f"    latlon: {d['latitude']:.6f}, {d['longitude']:.6f}")
        for note in d["notes"]:
            print(f"      - {note}")
        print()

        reports.append({"node_id": node_id, "lat": lat, "lon": lon, "observables": obs})

    # -- HQ relay: fuse and broadcast ---------------------------------------
    hq = localize_network(reports, temp_c=args.temp)
    hd = hq.to_dict()
    print("=" * 72)
    print("HQ RELAY  broadcast fix to all teams")
    print("=" * 72)
    print(f"  direction {hd['direction_deg']:.2f} deg   "
          f"distance {hd['distance_m'] if hd['distance_m'] is not None else 'NULL'} m   "
          f"accuracy {hd['accuracy_pct']:.0f}%   method {hd['method']}")
    if hd["latitude"] is not None:
        print(f"  shooter lat/lon: {hd['latitude']:.6f}, {hd['longitude']:.6f}")
    for note in hd["notes"]:
        print(f"    - {note}")

    # -- prove the audio -> measurement path too ----------------------------
    obs_near, truth_near = node_observables(traj, near_enu, temp_c=args.temp, rng=None)
    channel = synth_crack_thump_channel(
        48_000.0, t_crack_s=0.02, t_blast_s=0.02 + obs_near.dt_s,
        nwave_T_s=obs_near.nwave_duration_s, rng=rng,
    )
    meas = measure_crack_thump(channel, 48_000.0)
    print("\naudio->measurement check (near team, single channel):")
    print(f"  measured dt {meas.dt_s*1e3 if meas.dt_s else float('nan'):.1f} ms "
          f"(truth {obs_near.dt_s*1e3:.1f} ms), "
          f"T {meas.nwave_duration_s*1e6 if meas.nwave_duration_s else float('nan'):.0f} us "
          f"(truth {obs_near.nwave_duration_s*1e6:.0f} us)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"per_node": [r["node_id"] for r in reports],
                                    "hq_fix": hd}, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
