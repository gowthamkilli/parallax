"""The backend function: enemy position + category -> fused track result.

run_scenario() is the single call site the stretch goal replaces the CALLER
of, not the function itself: today the judge screen POSTs a category string
picked from buttons; later, a second (aim-direction) click would compute
category from real Mach-cone geometry and call this exact same function.

Deliberately never sets Shot.trajectory_bearing_deg, so every category stays
on the blast + triangulation path validated earlier this session -- no live
shockwave detection, per the demo-strategy decision.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import numpy as np

from parallax import profiles
from parallax.classifier import TransientClassifier
from parallax.fusion import FusionEngine, NodeState
from parallax.geometry import LocalFrame
from sim.edge_node import EdgeNode
from sim.scenario import Shot, default_squad, render_node_audio

from .presets import CATEGORY_PRESETS

FS = 48_000.0
ORIGIN = LocalFrame(28.6139, 77.2090)
T0_NS = 1_700_000_000_000_000_000
CLASSIFIER_PATH = Path("out/classifier.pkl")

_classifier = None
_classifier_loaded = False


def _get_classifier():
    global _classifier, _classifier_loaded
    if not _classifier_loaded:
        if CLASSIFIER_PATH.exists():
            _classifier = TransientClassifier.load(CLASSIFIER_PATH)
        _classifier_loaded = True
    return _classifier


def squad_positions() -> list[dict]:
    """Static soldier positions for the judge map -- reused as-is from the
    existing default_squad() config, never recomputed per request."""
    return [
        {"node_id": n.node_id, "e": float(n.enu[0]), "n": float(n.enu[1])}
        for n in default_squad()
    ]


def squad_centroid() -> tuple[float, float]:
    squad = default_squad()
    e = float(np.mean([n.enu[0] for n in squad]))
    n = float(np.mean([n.enu[1] for n in squad]))
    return e, n


def run_scenario(enemy_e: float, enemy_n: float, category: str,
                 seed: int | None = None) -> dict:
    if category not in CATEGORY_PRESETS:
        raise ValueError(f"unknown category {category!r}; have {sorted(CATEGORY_PRESETS)}")
    preset = CATEGORY_PRESETS[category]

    squad = default_squad()
    truth = np.array([enemy_e, enemy_n], dtype=float)
    shot = Shot(enu=truth, t_shot_s=0.0, visible_flash=False)  # optical/shockwave stay off

    profile = profiles.get("patrol")
    fusion_config = profile.fusion
    if preset["fusion_overrides"]:
        fusion_config = dataclasses.replace(profile.fusion, **preset["fusion_overrides"])

    rng = np.random.default_rng(seed)  # seed=None -> fresh entropy each call
    classifier = _get_classifier()

    reports = []
    for node in squad:
        edge = EdgeNode(node, ORIGIN, classifier=classifier, profile=profile)
        audio, cap_start, peak_spl = render_node_audio(
            node, shot, fs=FS, snr_db=preset["snr_db"], temp_c=20.0, rng=rng,
        )
        reports.extend(edge.make_acoustic_report(
            audio, FS, t_capture_start_s=cap_start, peak_spl_db=peak_spl,
            snr_db=preset["snr_db"], t0_ns=T0_NS,
        ))

    node_states = [
        NodeState(node_id=n.node_id,
                  lat=ORIGIN.to_geodetic(n.enu[0], n.enu[1])[0],
                  lon=ORIGIN.to_geodetic(n.enu[0], n.enu[1])[1],
                  temp_c=20.0)
        for n in squad
    ]
    engine = FusionEngine(node_states, ORIGIN, config=fusion_config)
    tracks = engine.process(reports) if reports else []
    primary = tracks[0] if tracks else None

    result: dict = {
        "timestamp": time.time(),
        "category": category,
        "category_label": preset["label"],
        "enemy_enu": [enemy_e, enemy_n],
        "n_reports": len(reports),
        "track": None,
    }
    if primary is not None:
        result["track"] = {
            "threat_class": primary.threat_class.name,
            "confidence": round(primary.confidence, 3),
            "alert": primary.confidence >= fusion_config.min_confidence_to_alert,
            "bearing_deg": (round(primary.bearing_deg, 2)
                            if primary.bearing_deg is not None else None),
            "bearing_sigma_deg": (round(primary.bearing_sigma_deg, 2)
                                  if primary.bearing_sigma_deg is not None else None),
            "range_m": round(primary.range_m, 1) if primary.range_m is not None else None,
            "range_method": primary.range_method,
            "position_enu": (list(map(float, primary.position_enu))
                             if primary.position_enu else None),
            "notes": primary.notes,
        }
    return result
