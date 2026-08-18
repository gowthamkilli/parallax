"""Bullet-speed / Mach-number sensitivity sweep for acoustic-only shockwave
ranging (parallax/fusion.py::_range_from_shockwave_blast).

MEASUREMENT ONLY. This script characterizes the existing implementation's
failure surface -- it does not modify parallax/fusion.py or attempt to fix
anything found. Every case is run through the REAL FusionEngine.process()
code path (via directly-constructed ContactReport pairs, exactly matching
how a node's contact reports would arrive), not a reimplementation of the
formula, so the numbers reflect what the shipped code actually does.

    python -m sim.shockwave_sensitivity_sweep

Writes the full grid to out/shockwave_sensitivity_sweep.csv and prints
condensed tables to stdout.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from parallax.contact import ContactReport, Modality, ThreatClass, FLAG_GPS_LOCKED
from parallax.fusion import FusionConfig, FusionEngine, NodeState, speed_of_sound
from parallax.geometry import LocalFrame, bearing_between

ORIGIN = LocalFrame(28.6139, 77.2090)
T0 = 1_700_000_000_000_000_000
D_TRUE = 350.0
TEMP_C = 20.0

# M_crit = sqrt(2) = 1.41421356... is an EXACT boundary (see writeup): below
# it, f(alpha,M) goes negative for large enough alpha; above it, f(alpha,M)
# >= 0 throughout the whole valid cone. 1.40 and 1.4142 bracket it deliberately.
TRUE_MACH = [1.05, 1.10, 1.15, 1.20, 1.30, 1.40, 1.4142, 1.45, 1.50, 1.75, 2.00, 2.50, 3.00, 3.50]
ALPHA_FRAC_OF_GATE = [0.05, 0.25, 0.50, 0.75, 0.90, 0.99]
SPEED_ERROR_FRAC = [-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20]


def geometry_for(alpha_deg, d_true, true_bullet_speed_mps, temp_c=TEMP_C):
    """Same construction as tests/test_fusion.py::_shockwave_geometry --
    independent of fusion.py's own algebraic dt formula, computed from
    first-principles propagation (bullet travel to the emission point, then
    sound to the node; sound directly from muzzle to node)."""
    c = speed_of_sound(temp_c)
    mach = true_bullet_speed_mps / c
    theta_m = math.asin(1.0 / mach)
    alpha = math.radians(alpha_deg)

    cross = d_true * math.sin(alpha)
    along = d_true * math.cos(alpha)
    muzzle = np.array([0.0, 0.0])
    node_enu = np.array([cross, along])
    x_prime = along - cross * math.sqrt(mach * mach - 1.0)
    emission_point = np.array([0.0, x_prime])

    blast_az = bearing_between(node_enu, muzzle)
    shock_az = bearing_between(node_enu, emission_point)
    t_blast = d_true / c
    t_shock = x_prime / true_bullet_speed_mps + float(np.linalg.norm(node_enu - emission_point)) / c
    return blast_az, shock_az, t_blast - t_shock, node_enu, theta_m, c


def run_one(true_mach, alpha_frac, speed_error_frac, config_ceiling_deg=30.0):
    """Returns a dict describing what the REAL fusion pipeline does for one
    (true Mach, miss-angle fraction of the TRUE gate, assumed-speed error)
    combination, using the deployed default config (30 deg ceiling)."""
    c = speed_of_sound(TEMP_C)
    true_speed = true_mach * c
    theta_m_true_deg = math.degrees(math.asin(1.0 / true_mach))
    alpha_deg = alpha_frac * theta_m_true_deg

    blast_az, shock_az, dt_s, node_enu, theta_m_true, _ = geometry_for(alpha_deg, D_TRUE, true_speed)
    assumed_speed = true_speed * (1.0 + speed_error_frac)

    node = NodeState(node_id=1, lat=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[0],
                     lon=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[1])
    cfg = FusionConfig(bullet_speed_mps=assumed_speed, max_shockwave_miss_angle_deg=config_ceiling_deg)
    engine = FusionEngine([node], ORIGIN, config=cfg)
    dt_ns = int(round(dt_s * 1e9))
    reports = [
        ContactReport(node_id=1, seq=1, t_event_ns=T0, modality=Modality.ACOUSTIC_SHOCKWAVE,
                      threat_class=ThreatClass.GUNSHOT, class_confidence=0.70,
                      azimuth_deg=shock_az, azimuth_sigma_deg=2.0, flags=FLAG_GPS_LOCKED),
        ContactReport(node_id=1, seq=2, t_event_ns=T0 + dt_ns, modality=Modality.ACOUSTIC,
                      threat_class=ThreatClass.GUNSHOT, class_confidence=0.85,
                      azimuth_deg=blast_az, azimuth_sigma_deg=1.5, flags=FLAG_GPS_LOCKED),
    ]
    tracks = engine.process(reports)
    track = tracks[0] if tracks else None

    result = {
        "true_mach": true_mach,
        "theta_m_true_deg": theta_m_true_deg,
        "alpha_frac_of_gate": alpha_frac,
        "alpha_deg": alpha_deg,
        "speed_error_pct": speed_error_frac * 100,
        "assumed_mach": assumed_speed / c,
        "true_dt_ms": dt_s * 1000,
        "decided": None,
        "decline_reason": "",
        "range_m": None,
        "error_pct": None,
        "sigma_m": None,
    }
    if track is None or track.range_method not in ("shockwave_dt",):
        result["decided"] = "DECLINED"
        notes = track.notes if track else []
        if any("non-physical" in n for n in notes):
            result["decline_reason"] = "dt<=0 (f(alpha,M) went negative for the TRUE geometry)"
        elif any("miss angle" in n and "outside" in n for n in notes):
            result["decline_reason"] = "recovered alpha outside [0, gate] (assumed-Mach mismatch)"
        elif any("subsonic" in n for n in notes):
            result["decline_reason"] = "assumed speed subsonic"
        else:
            result["decline_reason"] = (notes[-1] if notes else "no track / did not associate")
        return result

    result["decided"] = "ACCEPTED"
    result["range_m"] = track.range_m
    result["error_pct"] = (track.range_m - D_TRUE) / D_TRUE * 100
    result["sigma_m"] = track.range_sigma_m
    return result


def run_grid():
    rows = []
    for true_mach in TRUE_MACH:
        for alpha_frac in ALPHA_FRAC_OF_GATE:
            for speed_error in SPEED_ERROR_FRAC:
                rows.append(run_one(true_mach, alpha_frac, speed_error))
    return rows


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def fmt_cell(row):
    if row["decided"] == "DECLINED":
        return "decl"
    e = row["error_pct"]
    return f"{e:+.0f}%" if abs(e) < 1000 else f"{e:+.2e}%"


def print_table_a(rows):
    """Fixed mid-cone angle (alpha_frac=0.50): true Mach (rows) x assumed
    speed error (cols)."""
    print("\n" + "=" * 100)
    print("TABLE A -- alpha = 0.50 * true gate (mid-cone), range error % vs true Mach x assumed speed error")
    print("=" * 100)
    header = "true_M  theta_m ".ljust(16) + "".join(f"{e*100:+.0f}%".rjust(9) for e in SPEED_ERROR_FRAC)
    print(header)
    for m in TRUE_MACH:
        row_cells = [r for r in rows if r["true_mach"] == m and r["alpha_frac_of_gate"] == 0.50]
        row_cells.sort(key=lambda r: r["speed_error_pct"])
        theta = row_cells[0]["theta_m_true_deg"]
        line = f"{m:5.2f}  {theta:6.1f}deg  ".ljust(16)
        line += "".join(fmt_cell(r).rjust(9) for r in row_cells)
        print(line)


def print_table_b(rows):
    """Transonic zone only (Mach<=1.5), 0% speed error, all alpha fractions."""
    print("\n" + "=" * 100)
    print("TABLE B -- transonic zone, 0%% speed error (perfect bullet-speed knowledge), range error %% vs true Mach x alpha fraction of gate")
    print("=" * 100)
    header = "true_M  theta_m ".ljust(16) + "".join(f"a={f:.2f}".rjust(10) for f in ALPHA_FRAC_OF_GATE)
    print(header)
    for m in TRUE_MACH:
        if m > 1.5:
            continue
        row_cells = [r for r in rows if r["true_mach"] == m and r["speed_error_pct"] == 0.0]
        row_cells.sort(key=lambda r: r["alpha_frac_of_gate"])
        theta = row_cells[0]["theta_m_true_deg"]
        line = f"{m:5.2f}  {theta:6.1f}deg  ".ljust(16)
        line += "".join(fmt_cell(r).rjust(10) for r in row_cells)
        print(line)


def print_table_c(rows):
    """Worst-case (max abs error among ACCEPTED cells) per true Mach, across
    all alpha/speed-error combos -- the overall danger-zone summary."""
    print("\n" + "=" * 100)
    print("TABLE C -- worst-case ACCEPTED range error %% per true Mach (across all alpha/speed-error combos)")
    print("=" * 100)
    print("true_M  theta_m    n_accepted  n_declined  worst_error%   at(alpha_frac, speed_err%)")
    for m in TRUE_MACH:
        cells = [r for r in rows if r["true_mach"] == m]
        accepted = [r for r in cells if r["decided"] == "ACCEPTED"]
        declined = [r for r in cells if r["decided"] == "DECLINED"]
        theta = cells[0]["theta_m_true_deg"]
        if accepted:
            worst = max(accepted, key=lambda r: abs(r["error_pct"]))
            print(f"{m:5.2f}   {theta:6.1f}deg   {len(accepted):10d}  {len(declined):10d}  "
                  f"{worst['error_pct']:+12.1f}%   (alpha_frac={worst['alpha_frac_of_gate']:.2f}, "
                  f"speed_err={worst['speed_error_pct']:+.0f}%)")
        else:
            print(f"{m:5.2f}   {theta:6.1f}deg   {len(accepted):10d}  {len(declined):10d}  "
                  f"{'(none accepted)':>14s}")


def print_table_d(rows):
    """Decline-reason breakdown per true Mach."""
    print("\n" + "=" * 100)
    print("TABLE D -- decline reason breakdown per true Mach (counts out of 42 cells: 6 alpha x 7 speed-error)")
    print("=" * 100)
    for m in TRUE_MACH:
        cells = [r for r in rows if r["true_mach"] == m]
        declined = [r for r in cells if r["decided"] == "DECLINED"]
        accepted = len(cells) - len(declined)
        reasons = {}
        for r in declined:
            key = r["decline_reason"].split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
        reason_str = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
        print(f"M={m:6.4f}  accepted={accepted:2d}  declined={len(declined):2d}   {reason_str}")


def main():
    rows = run_grid()
    out_path = Path("out/shockwave_sensitivity_sweep.csv")
    write_csv(rows, out_path)
    print(f"wrote full {len(rows)}-row grid -> {out_path}")

    print_table_a(rows)
    print_table_b(rows)
    print_table_c(rows)
    print_table_d(rows)

    danger = [r for r in rows if r["decided"] == "ACCEPTED" and abs(r["error_pct"]) > 25.0]
    print(f"\n{len(danger)} / {len(rows)} cells ACCEPTED a range with >25% error "
          f"(fabricated-looking-plausible but wrong).")
    if danger:
        machs = sorted({r["true_mach"] for r in danger})
        print(f"Danger zone spans true Mach in: {machs}")


if __name__ == "__main__":
    main()
