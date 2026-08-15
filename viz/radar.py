"""C2 dashboard renderer. Consumes tracks.json; knows nothing about signals.

    python -m viz.radar out/tracks.json --save out/dashboard.png

This is the deliberate split from the locked design decisions: the
localisation and fusion code emits structured data and never touches a
display, and this module renders that data and never touches a waveform. The
algorithm is therefore testable headlessly, and the display can be re-skinned
for a wrist unit, a vehicle screen or an HQ wall without recompiling anything
that computes a bearing.

Layout mirrors the reference C2 UI:
    top     - large azimuth / elevation / range readout
    left    - polar radar dial, bearing needles, range rings, error wedge
    centre  - plan view: node positions, bearing rays, fix + error ellipse
    bottom  - event table  # | Type | Az | Elev | Range | Conf | Time
    footer  - link/packet health
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse  # noqa: E402

BG = "#0b1014"
PANEL = "#121a20"
GRID = "#1f2d37"
FG = "#c8d6de"
ACCENT = "#00d9a3"
WARN = "#ffb020"
ALERT = "#ff4d5e"
NODE = "#4aa3ff"

CLASS_COLOUR = {
    "GUNSHOT": ALERT,
    "DRONE": "#c77dff",
    "VEHICLE": WARN,
    "PERSONNEL": ACCENT,
    "NUISANCE": "#6b7d89",
    "UNKNOWN": "#6b7d89",
}


def render(payload: dict, save: Path | None = None, show: bool = False):
    tracks = payload["tracks"]
    nodes = payload["nodes"]
    reports = payload["reports"]
    truth = payload.get("truth")
    primary = tracks[0] if tracks else None

    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    grid = fig.add_gridspec(
        3, 2, height_ratios=[0.9, 3.2, 1.7], width_ratios=[1, 1.35],
        hspace=0.32, wspace=0.16, left=0.05, right=0.97, top=0.94, bottom=0.06,
    )

    _readout(fig.add_subplot(grid[0, :]), primary, payload)
    _dial(fig.add_subplot(grid[1, 0], projection="polar"), tracks, nodes)
    _plan(fig.add_subplot(grid[1, 1]), tracks, nodes, truth)
    _table(fig.add_subplot(grid[2, :]), reports, tracks)

    fig.text(0.05, 0.015,
             f"PARALLAX  |  profile: {payload.get('profile', '-').upper()}  |  "
             f"nodes online {len(nodes)}/{len(nodes)}  |  "
             f"contact reports rx {len(reports)}  |  wire 42 B/report  |  "
             f"SIMULATED DATA",
             color="#5d7180", fontsize=8, family="monospace")
    fig.text(0.97, 0.015, "DIAL | GIS | LIST | SETTINGS | START",
             color="#5d7180", fontsize=8, family="monospace", ha="right")

    if save:
        save.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save, dpi=120, facecolor=BG)
        print(f"wrote {save}")
    if show:
        plt.show()
    plt.close(fig)


def _readout(ax, track, payload):
    ax.set_facecolor(PANEL)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)

    if track is None:
        ax.text(0.5, 0.5, "NO CONTACTS", color="#5d7180", fontsize=22,
                ha="center", va="center", family="monospace")
        return

    colour = CLASS_COLOUR.get(track["threat_class"], FG)
    range_text = f"{track['range_m']:.0f} m" if track["range_m"] is not None else "-- NO FIX --"
    # Scoped to THIS track's own contributing nodes -- a payload can hold
    # several tracks (e.g. one real fix plus a multipath-degraded bearing-only
    # track from a different node), and pulling from all reports in the
    # payload could show one track's azimuth/range next to another track's
    # elevation.
    track_node_ids = set(track.get("contributing_nodes", []))
    elev = next((r["elevation_deg"] for r in payload["reports"]
                 if r.get("node_id") in track_node_ids and r.get("flags", 0) & 0x02), None)
    elev_text = f"{elev:+.1f}°" if elev is not None else "n/a"

    fields = [
        ("AZIMUTH", f"{track['bearing_deg']:.1f}°", colour),
        ("ELEVATION", elev_text, FG),
        ("RANGE", range_text, colour if track["range_m"] is not None else "#5d7180"),
        ("TYPE", track["threat_class"], colour),
        ("CONF", f"{track['confidence']:.2f}", colour),
    ]
    for i, (label, value, col) in enumerate(fields):
        x = 0.045 + i * 0.195
        ax.text(x, 0.72, label, color="#5d7180", fontsize=9, family="monospace")
        ax.text(x, 0.22, value, color=col, fontsize=26, family="monospace", weight="bold")

    method_short = {
        "flash_acoustic_dt+triangulation": "DT+TRI FUSED",
        "flash_acoustic_dt": "FLASH/ACOUSTIC DT",
        "triangulation": "TRIANGULATED",
        "none": "BEARING ONLY",
    }.get(track["range_method"], track["range_method"].upper())
    ax.text(0.985, 0.86, method_short, color="#5d7180", fontsize=9,
            family="monospace", ha="right")
    if track["cep50_m"] is not None:
        ax.text(0.985, 0.10, f"CEP50 {track['cep50_m']:.0f} m",
                color=FG, fontsize=12, family="monospace", ha="right")


def _dial(ax, tracks, nodes):
    ax.set_facecolor(PANEL)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    max_range = 500.0
    for track in tracks:
        if track["range_m"] is not None:
            max_range = max(max_range, track["range_m"] * 1.3)
    rings = np.linspace(max_range / 4, max_range, 4)

    ax.set_ylim(0, max_range)
    ax.set_yticks(rings)
    ax.set_yticklabels([f"{r:.0f}m" for r in rings], color="#5d7180", fontsize=8)
    ax.set_xticks(np.radians(np.arange(0, 360, 30)))
    ax.set_xticklabels([f"{d}" for d in range(0, 360, 30)], color=FG, fontsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines["polar"].set_color(GRID)
    ax.set_title("BEARING", color="#5d7180", fontsize=10, family="monospace", pad=14)

    for track in tracks:
        colour = CLASS_COLOUR.get(track["threat_class"], FG)
        theta = math.radians(track["bearing_deg"])
        sigma = track["bearing_sigma_deg"] or 1.0
        has_range = track["range_m"] is not None
        r = track["range_m"] if has_range else max_range

        # 1-sigma bearing wedge: the honest depiction of angular uncertainty.
        # Built directly in the axes' own (theta, r) data coordinates via
        # ax.fill -- NOT matplotlib.patches.Wedge, which is drawn in plain
        # mathematical angle convention and ignores this axes' compass
        # zero_location/direction remapping, so it renders in the wrong
        # place on a compass-oriented polar plot.
        wedge_theta = np.radians(np.linspace(
            track["bearing_deg"] - sigma, track["bearing_deg"] + sigma, 24
        ))
        ax.fill(
            np.concatenate([[0.0], wedge_theta, [0.0]]),
            np.concatenate([[0.0], np.full_like(wedge_theta, r), [0.0]]),
            color=colour, alpha=0.16, edgecolor="none",
        )
        ax.plot([theta, theta], [0, r], color=colour, linewidth=2.0,
                alpha=0.95 if has_range else 0.5,
                linestyle="-" if has_range else "--")
        if has_range:
            ax.plot([theta], [track["range_m"]], "o", color=colour, markersize=9,
                    markeredgecolor="white", markeredgewidth=0.8)
            ax.annotate(f" {track['threat_class'][:4]}", (theta, track["range_m"]),
                        color=colour, fontsize=9, family="monospace")
        else:
            ax.annotate(" BEARING ONLY", (theta, r * 0.92), color=colour,
                        fontsize=8, family="monospace")


def _plan(ax, tracks, nodes, truth):
    ax.set_facecolor(PANEL)
    ax.set_aspect("equal")
    ax.tick_params(colors="#5d7180", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.6, linestyle=":")
    ax.set_xlabel("East (m)", color="#5d7180", fontsize=9)
    ax.set_ylabel("North (m)", color="#5d7180", fontsize=9)
    ax.set_title("PLAN VIEW  — bearing rays and fused fix",
                 color="#5d7180", fontsize=10, family="monospace", pad=10)

    node_xy = {n["node_id"]: np.array(n["enu"]) for n in nodes}
    points = list(node_xy.values())

    for node in nodes:
        x, y = node["enu"]
        ax.plot(x, y, "^", color=NODE, markersize=11, markeredgecolor="white",
                markeredgewidth=0.7, zorder=5)
        label = f"N{node['node_id']}" + ("  [IR]" if node.get("has_optical") else "")
        ax.annotate(label, (x, y), textcoords="offset points", xytext=(9, -4),
                    color=NODE, fontsize=9, family="monospace")

    for track in tracks:
        colour = CLASS_COLOUR.get(track["threat_class"], FG)
        ray_length = (track["range_m"] if track["range_m"] is not None else 600.0) * 1.15

        # One ray per contributing node, drawn from that node's own bearing.
        for report in track.get("_reports", []) or []:
            pass  # reports are drawn below from the payload-level list
        for node_id in track["contributing_nodes"]:
            origin = node_xy[node_id]
            bearing = track["bearing_deg"] if node_id == track["primary_node_id"] else None
            if bearing is None and track["position_enu"]:
                delta = np.array(track["position_enu"]) - origin
                bearing = math.degrees(math.atan2(delta[0], delta[1])) % 360.0
            if bearing is None:
                continue
            direction = np.array([math.sin(math.radians(bearing)),
                                  math.cos(math.radians(bearing))])
            end = origin + ray_length * direction
            ax.plot([origin[0], end[0]], [origin[1], end[1]],
                    color=colour, linewidth=1.1, alpha=0.55, linestyle="--")
            points.append(end)

        if track["position_enu"]:
            px, py = track["position_enu"]
            points.append(np.array([px, py]))
            if track["ellipse"]:
                semi_major, semi_minor, orientation = track["ellipse"]
                ax.add_patch(Ellipse(
                    (px, py), 2 * semi_major, 2 * semi_minor, angle=-orientation,
                    facecolor=colour, alpha=0.16, edgecolor=colour, linewidth=1.0,
                ))
            ax.plot(px, py, "X", color=colour, markersize=14,
                    markeredgecolor="white", markeredgewidth=0.9, zorder=6)
            ax.annotate(f"{track['threat_class']}  {track['confidence']:.2f}",
                        (px, py), textcoords="offset points", xytext=(12, 8),
                        color=colour, fontsize=10, family="monospace", weight="bold")

    if truth:
        tx, ty = truth["enu"]
        points.append(np.array([tx, ty]))
        ax.plot(tx, ty, "+", color="white", markersize=16, markeredgewidth=1.6, zorder=7)
        ax.annotate("TRUTH (sim)", (tx, ty), textcoords="offset points",
                    xytext=(12, -14), color="white", fontsize=8, family="monospace")

    pts = np.vstack(points)
    pad = max(60.0, 0.12 * float(np.ptp(pts, axis=0).max()))
    ax.set_xlim(pts[:, 0].min() - pad, pts[:, 0].max() + pad)
    ax.set_ylim(pts[:, 1].min() - pad, pts[:, 1].max() + pad)


def _table(ax, reports, tracks):
    ax.set_facecolor(PANEL)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)

    headers = ["#", "NODE", "MODALITY", "TYPE", "AZ", "SIGMA", "ELEV", "RANGE", "CONF", "T+ms"]
    xs = [0.02, 0.08, 0.16, 0.29, 0.42, 0.50, 0.59, 0.68, 0.79, 0.88]
    for x, header in zip(xs, headers):
        ax.text(x, 0.87, header, color="#5d7180", fontsize=9, family="monospace")
    ax.axhline(0.80, color=GRID, linewidth=1.0)

    if not reports:
        return
    t0 = min(r["t_event_ns"] for r in reports)
    ordered = sorted(reports, key=lambda r: r["t_event_ns"])[:8]

    for i, report in enumerate(ordered):
        y = 0.68 - i * 0.098
        newest = i == len(ordered) - 1
        colour = CLASS_COLOUR.get(report["threat_class"], FG)
        if newest:
            ax.axhspan(y - 0.035, y + 0.055, color=colour, alpha=0.12)
        cells = [
            str(i + 1),
            f"N{report['node_id']}",
            report["modality"],
            report["threat_class"],
            f"{report['azimuth_deg']:.2f}°",
            f"{report['azimuth_sigma_deg']:.2f}°",
            f"{report['elevation_deg']:+.1f}°" if report["flags"] & 0x02 else "n/a",
            f"{report['range_m']:.0f} m" if report["range_m"] else "—",  # per-report range is always 0 today (contact reports never carry it)
            f"{report['class_confidence']:.2f}",
            f"{(report['t_event_ns'] - t0) / 1e6:.1f}",
        ]
        for x, cell in zip(xs, cells):
            ax.text(x, y, cell, color=colour if newest else FG,
                    fontsize=9, family="monospace")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracks", type=Path, nargs="?", default=Path("out/tracks.json"))
    parser.add_argument("--save", type=Path, default=Path("out/dashboard.png"))
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    payload = json.loads(args.tracks.read_text(encoding="utf-8"))
    render(payload, save=args.save, show=args.show)


if __name__ == "__main__":
    main()
