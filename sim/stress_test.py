"""Stress test the crack-thump solver under REALISTIC sensor noise.

    python -m sim.stress_test

Unlike the demo scripts, this file feeds ``node_observables(..., rng=<seeded>)``
-- i.e. every observable (blast bearing, bearing split, dt, N-wave duration) is
perturbed by its stated 1-sigma sensor uncertainty before it ever reaches the
solver. That is the honest test of the algorithm: how close does it get when
the input isn't the noiseless ground truth.

Three passes:
    1. GRID   - a structured sweep of (range, miss) inside and outside the
                crack-thump regime, N noisy trials per cell.
    2. RANDOM - uniform random draws across range/miss/velocity/temperature/
                aim, including subsonic rounds, to get an overall error budget.
    3. EDGE CASES - specific adversarial inputs: near-zero miss, boundary
                range/miss, transonic (M~1), malformed API payloads.

Reports per-quantity error (direction, range) against ground truth, and checks
whether the reported accuracy_pct actually correlates with real error
(a calibration check, not just a self-consistency check).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from parallax import api
from parallax.ballistics import solve_crack_thump, speed_of_sound
from parallax.localize import localize_single_node
from sim.shockwave import (
    MAX_CRACK_MISS_M,
    MAX_CRACK_RANGE_M,
    Trajectory,
    node_observables,
)

ORIGIN = (28.6139, 77.2090)
TEMP_C = 20.0


def _traj(range_m, miss_m, aim_deg=20.0, velocity=700.0):
    u = np.array([math.sin(math.radians(aim_deg)), math.cos(math.radians(aim_deg))])
    perp = np.array([u[1], -u[0]])
    back = -math.sqrt(max(range_m ** 2 - miss_m ** 2, 0.0))
    shooter = back * u + miss_m * perp
    return Trajectory(shooter_enu=shooter, aim_deg=aim_deg, muzzle_velocity_ms=velocity)


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _run_trial(range_m, miss_m, velocity, aim_deg, rng):
    """One noisy single-node trial. Returns a result dict."""
    traj = _traj(range_m, miss_m, aim_deg, velocity)
    obs, truth = node_observables(traj, np.array([0.0, 0.0]), temp_c=TEMP_C, rng=rng)
    contact = localize_single_node(ORIGIN[0], ORIGIN[1], obs, node_id=1, temp_c=TEMP_C)
    d = contact.to_dict()

    bearing_err = abs(_wrap180(d["direction_deg"] - truth.true_blast_bearing_deg))
    range_err = None
    range_err_pct = None
    if d["distance_m"] is not None:
        range_err = abs(d["distance_m"] - truth.true_range_m)
        range_err_pct = 100.0 * range_err / max(truth.true_range_m, 1e-6)

    return {
        "range_m": range_m, "miss_m": miss_m, "velocity": velocity,
        "truth_in_range": truth.in_crack_thump_range,
        "solver_ranged": d["distance_m"] is not None,
        "bearing_err_deg": bearing_err,
        "range_err_m": range_err,
        "range_err_pct": range_err_pct,
        "direction_accuracy_pct": d["direction_accuracy_pct"],
        "distance_accuracy_pct": d["distance_accuracy_pct"],
        "method": d["method"],
    }


# ---------------------------------------------------------------------------
def grid_pass(trials_per_cell=15, seed=100):
    """Structured sweep, both inside and outside the crack-thump regime."""
    ranges = [80, 150, 250, 350, 450, 600, 750, 900]           # last two exceed max range
    miss_fracs = [0.01, 0.05, 0.10, 0.20, 0.35]                 # fraction of range
    rng = np.random.default_rng(seed)

    rows = []
    for R in ranges:
        for frac in miss_fracs:
            d = min(R * frac, 400.0)
            for _ in range(trials_per_cell):
                rows.append(_run_trial(R, d, 700.0, 20.0, rng))
    return rows


def random_pass(n_trials=400, seed=200):
    """Uniform random draws, including subsonic rounds, across the space."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_trials):
        R = float(rng.uniform(50, 1000))
        frac = float(rng.uniform(0.0, 0.45))
        d = min(R * frac, float(rng.uniform(0.5, 200)))
        velocity = float(rng.uniform(300, 950))   # spans subsonic..supersonic
        aim = float(rng.uniform(0, 360))
        rows.append(_run_trial(R, d, velocity, aim, rng))
    return rows


def edge_cases():
    """Specific adversarial / boundary inputs, reported individually."""
    results = []

    def record(label, fn):
        t0 = time.perf_counter()
        try:
            out = fn()
            ok, detail = True, out
        except Exception as exc:  # the whole point: nothing should raise
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"case": label, "ok": ok, "detail": detail,
                        "ms": round((time.perf_counter() - t0) * 1000, 2)})

    rng = np.random.default_rng(999)

    record("near-zero miss distance (d~0.1m, axial hit)",
          lambda: _run_trial(300.0, 0.1, 700.0, 20.0, rng))

    record("miss distance at crack-reach boundary (150m)",
          lambda: _run_trial(300.0, MAX_CRACK_MISS_M - 1.0, 700.0, 20.0, rng))

    record("miss distance just beyond crack reach (151m)",
          lambda: _run_trial(300.0, MAX_CRACK_MISS_M + 1.0, 700.0, 20.0, rng))

    record("range at crack-reach boundary (800m)",
          lambda: _run_trial(MAX_CRACK_RANGE_M - 5.0, 5.0, 900.0, 20.0, rng))

    record("range just beyond crack reach (810m)",
          lambda: _run_trial(MAX_CRACK_RANGE_M + 10.0, 5.0, 900.0, 20.0, rng))

    record("very close shot (25m, high Mach)",
          lambda: _run_trial(25.0, 1.0, 900.0, 20.0, rng))

    record("transonic round (M=1.02, barely supersonic)",
          lambda: _run_trial(300.0, 5.0, 1.02 * speed_of_sound(TEMP_C), 20.0, rng))

    record("subsonic pistol round (M=0.85)",
          lambda: _run_trial(150.0, 5.0, 0.85 * speed_of_sound(TEMP_C), 20.0, rng))

    record("degenerate: zero bearing split fed directly to solver",
          _direct_zero_split)

    record("API: well-formed single-node request",
          lambda: api.process_node_report({
              "node": {"id": 1, "lat": ORIGIN[0], "lon": ORIGIN[1]},
              "measurement": {"blast_bearing_deg": 42.0, "bearing_split_deg": 27.4,
                              "dt_s": 0.412, "nwave_duration_s": 287e-6},
          }))

    record("API: missing required fields",
          lambda: api.process_node_report({"node": {"lat": 1.0}}))

    record("API: negative/nonsense dt",
          lambda: api.process_node_report({
              "node": {"id": 1, "lat": ORIGIN[0], "lon": ORIGIN[1]},
              "measurement": {"blast_bearing_deg": 42.0, "bearing_split_deg": 27.4,
                              "dt_s": -0.5, "nwave_duration_s": 287e-6},
          }))

    record("API: wrong types (strings instead of numbers)",
          lambda: api.process_node_report({
              "node": {"id": 1, "lat": "not-a-number", "lon": ORIGIN[1]},
              "measurement": {"blast_bearing_deg": 42.0},
          }))

    return results


def _direct_zero_split():
    from parallax.ballistics import BallisticObservables
    obs = BallisticObservables(blast_bearing_deg=10.0, bearing_split_deg=0.0,
                               dt_s=0.0, nwave_duration_s=0.0)
    sol = solve_crack_thump(obs)
    return {"method": sol.method, "range_m": sol.range_m}


# ---------------------------------------------------------------------------
def _pct(values, q):
    return float(np.percentile(values, q)) if values else float("nan")


def summarize(rows: list[dict]) -> dict:
    in_range = [r for r in rows if r["truth_in_range"]]
    out_range = [r for r in rows if not r["truth_in_range"]]

    # Regime-classification correctness: does the solver produce a range iff
    # the truth says the geometry is inside crack-thump reach?
    regime_correct = sum(1 for r in rows if r["truth_in_range"] == r["solver_ranged"])

    bearing_errs = [r["bearing_err_deg"] for r in rows]
    range_errs = [r["range_err_pct"] for r in in_range if r["range_err_pct"] is not None]
    range_errs_m = [r["range_err_m"] for r in in_range if r["range_err_m"] is not None]

    # Calibration: bucket by reported distance_accuracy_pct, check mean actual
    # error rises as reported accuracy falls.
    buckets = {}
    for r in in_range:
        if r["distance_accuracy_pct"] is None or r["range_err_pct"] is None:
            continue
        bucket = int(r["distance_accuracy_pct"] // 10) * 10
        buckets.setdefault(bucket, []).append(r["range_err_pct"])
    calibration = {
        f"{b}-{b+9}%": {"n": len(v), "mean_range_err_pct": round(float(np.mean(v)), 2)}
        for b, v in sorted(buckets.items())
    }

    return {
        "n_trials": len(rows),
        "n_in_crack_thump_range": len(in_range),
        "n_out_of_range": len(out_range),
        "regime_classification_accuracy": round(regime_correct / max(len(rows), 1), 4),
        "bearing_error_deg": {
            "mean": round(float(np.mean(bearing_errs)), 3),
            "median": round(float(np.median(bearing_errs)), 3),
            "p95": round(_pct(bearing_errs, 95), 3),
            "max": round(float(np.max(bearing_errs)), 3),
        },
        "range_error_pct_when_ranged": {
            "n": len(range_errs),
            "mean": round(float(np.mean(range_errs)), 2) if range_errs else None,
            "median": round(float(np.median(range_errs)), 2) if range_errs else None,
            "p95": round(_pct(range_errs, 95), 2) if range_errs else None,
            "max": round(float(np.max(range_errs)), 2) if range_errs else None,
        },
        "range_error_m_when_ranged": {
            "mean": round(float(np.mean(range_errs_m)), 1) if range_errs_m else None,
            "median": round(float(np.median(range_errs_m)), 1) if range_errs_m else None,
            "p95": round(_pct(range_errs_m, 95), 1) if range_errs_m else None,
        },
        "accuracy_calibration_by_reported_bucket": calibration,
        "out_of_range_never_fabricated_a_distance":
            sum(1 for r in out_range if not r["solver_ranged"]) == len(out_range),
    }


def main():
    t0 = time.perf_counter()

    print("=" * 78)
    print("PARALLAX crack-thump STRESS TEST (realistic sensor noise, not truth)")
    print("=" * 78)

    print("\n[1/3] grid sweep ...")
    grid_rows = grid_pass()
    grid_summary = summarize(grid_rows)
    print(json.dumps(grid_summary, indent=2))

    print("\n[2/3] random sweep (includes subsonic rounds) ...")
    random_rows = random_pass()
    random_summary = summarize(random_rows)
    print(json.dumps(random_summary, indent=2))

    print("\n[3/3] edge cases ...")
    edge = edge_cases()
    for e in edge:
        status = "OK" if e["ok"] else "RAISED"
        print(f"  [{status:>6}] {e['case']:<55} ({e['ms']:.2f} ms)")
        if not e["ok"]:
            print(f"           -> {e['detail']}")

    elapsed = time.perf_counter() - t0
    n_total = len(grid_rows) + len(random_rows)
    print(f"\n{n_total} solver trials + {len(edge)} edge cases in {elapsed:.2f}s "
          f"({1000*elapsed/max(n_total,1):.2f} ms/trial)")

    all_ok = all(e["ok"] for e in edge)
    print(f"\nedge cases: {'ALL PASSED (no exceptions)' if all_ok else 'FAILURES ABOVE'}")

    report = {
        "grid_pass": grid_summary,
        "random_pass": random_summary,
        "edge_cases": edge,
        "n_solver_trials": n_total,
        "elapsed_s": round(elapsed, 2),
    }
    out = Path("out/stress_test_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
