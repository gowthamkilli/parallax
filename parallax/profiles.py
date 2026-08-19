"""Mission profiles: ONE node, ONE fusion engine, four configurations.

The claim that has to survive a judge is "same hardware, same code, different
config". So a profile is exactly that -- a config object. It changes sensor
weighting, alert thresholds and dashboard emphasis. It does not change the
sensor complement, the edge pipeline, the fusion algorithm or the wire format.
If a profile ever needed a code path of its own, the claim would be false and
we would have to stop making it.

What is genuinely different per profile, and why:

    PERIMETER   Fixed nodes with surveyed positions and mains/solar power. The
                only profile where seismic earns its place, because nodes can
                be buried at the wire, 20-40 m from the approach -- inside the
                range where a geophone actually works. Long dwell, low
                threshold: a false alarm costs a look, not a life.

    CONVOY      Moving platform. Node position changes continuously, so
                triangulation across a convoy uses the *instantaneous* GNSS
                baseline between vehicles. Engine, tyre and wind noise raise
                the floor by an estimated 15-25 dB, which is the single
                largest degradation any profile suffers. Threshold is raised
                hard: a convoy that halts on every false alarm stops moving.

    PATROL      Man-portable, battery-critical. Duty-cycles the RF receiver
                and runs the classifier only on detector triggers. Weighted
                toward the acoustic + optical pair because that is what
                localises a sniper. Often only 1-2 nodes present, so this
                profile lives on bearing-only and flash/acoustic dt range far
                more than on triangulation -- which is precisely the case the
                optical channel was added to serve.

    URBAN       Elevated mount, hard reflective surfaces everywhere. Bearing
                sigmas are inflated and the multipath gate is tightened,
                because in a street canyon the reflection is sometimes louder
                than the direct path. Requires more corroboration before
                alerting; accepts that it will miss more shots to avoid
                pointing the commander at a wall.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contact import Modality, ThreatClass
from .fusion import FusionConfig


@dataclass
class MissionProfile:
    key: str
    name: str
    fusion: FusionConfig
    detector_threshold_sigma: float
    min_class_confidence: float
    seismic_enabled: bool
    rf_duty_cycle: float  # 1.0 = continuous
    dashboard_priority: tuple  # threat classes, most emphasised first
    bearing_sigma_inflation: float
    notes: str = ""


def _cfg(**overrides) -> FusionConfig:
    cfg = FusionConfig()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


PERIMETER = MissionProfile(
    key="perimeter",
    name="Static perimeter / FOB defence",
    fusion=_cfg(
        min_confidence_to_alert=0.45,
        max_crossing_cep_m=200.0,
        min_crossing_angle_deg=20.0,
        modality_weights={
            Modality.OPTICAL_IR: 1.0,
            Modality.ACOUSTIC: 0.9,
            Modality.SHOCKWAVE: 0.9,
            Modality.RF_PASSIVE: 0.7,
            Modality.SEISMIC: 0.6,
        },
    ),
    detector_threshold_sigma=5.0,
    min_class_confidence=0.40,
    seismic_enabled=True,
    rf_duty_cycle=1.0,
    dashboard_priority=(ThreatClass.PERSONNEL, ThreatClass.GUNSHOT, ThreatClass.DRONE, ThreatClass.VEHICLE),
    bearing_sigma_inflation=1.0,
    notes="Surveyed node positions; best triangulation geometry of any profile.",
)

CONVOY = MissionProfile(
    key="convoy",
    name="Convoy escort",
    fusion=_cfg(
        min_confidence_to_alert=0.70,
        max_crossing_cep_m=300.0,
        min_crossing_angle_deg=25.0,
        onset_jitter_s=0.008,
        modality_weights={
            Modality.OPTICAL_IR: 1.0,
            Modality.ACOUSTIC: 0.7,
            # A shockwave's sharp N-wave shape survives engine/tyre/wind noise
            # far better than the blast's lower-frequency energy does, so it
            # is NOT knocked down the way ACOUSTIC is in this profile.
            Modality.SHOCKWAVE: 0.85,
            Modality.RF_PASSIVE: 0.6,
            Modality.SEISMIC: 0.0,
        },
    ),
    detector_threshold_sigma=8.0,
    min_class_confidence=0.65,
    seismic_enabled=False,
    rf_duty_cycle=1.0,
    dashboard_priority=(ThreatClass.GUNSHOT, ThreatClass.VEHICLE, ThreatClass.DRONE, ThreatClass.PERSONNEL),
    notes=(
        "Platform noise raises the floor by an ESTIMATED 15-25 dB, cutting "
        "effective acoustic range. Optical is weighted highest because a "
        "flash is unaffected by engine noise."
    ),
    bearing_sigma_inflation=1.4,
)

PATROL = MissionProfile(
    key="patrol",
    name="Dismounted patrol / forward OP",
    fusion=_cfg(
        min_confidence_to_alert=0.55,
        max_crossing_cep_m=250.0,
        min_crossing_angle_deg=15.0,
        modality_weights={
            Modality.OPTICAL_IR: 1.0,
            Modality.ACOUSTIC: 0.9,
            Modality.SHOCKWAVE: 0.9,
            Modality.RF_PASSIVE: 0.5,
            Modality.SEISMIC: 0.0,
        },
    ),
    detector_threshold_sigma=6.0,
    min_class_confidence=0.50,
    seismic_enabled=False,
    rf_duty_cycle=0.25,
    dashboard_priority=(ThreatClass.GUNSHOT, ThreatClass.PERSONNEL, ThreatClass.DRONE, ThreatClass.VEHICLE),
    bearing_sigma_inflation=1.1,
    notes=(
        "Frequently 1-2 nodes only; depends on flash/acoustic dt or ballistic "
        "crack-thump ranging (parallax/ballistics.py) rather than triangulation."
    ),
)

URBAN = MissionProfile(
    key="urban",
    name="Urban overwatch",
    fusion=_cfg(
        min_confidence_to_alert=0.65,
        max_crossing_cep_m=150.0,
        min_crossing_angle_deg=30.0,
        bearing_gate_sigma=2.0,
        modality_weights={
            Modality.OPTICAL_IR: 1.0,
            Modality.ACOUSTIC: 0.6,  # least trusted here, by design
            # A reflected crack is a much sharper anomaly to catch than a
            # reflected blast (the N-wave shape is distinctive), but a street
            # canyon can still bounce it, so it is trusted more than the
            # blast here but not as much as in other profiles.
            Modality.SHOCKWAVE: 0.7,
            Modality.RF_PASSIVE: 0.7,
            Modality.SEISMIC: 0.0,
        },
    ),
    detector_threshold_sigma=7.0,
    min_class_confidence=0.60,
    seismic_enabled=False,
    rf_duty_cycle=1.0,
    dashboard_priority=(ThreatClass.GUNSHOT, ThreatClass.DRONE, ThreatClass.PERSONNEL, ThreatClass.VEHICLE),
    bearing_sigma_inflation=2.0,
    notes=(
        "Deliberately trades recall for precision. A street-canyon reflection "
        "can exceed the direct path; pointing at a wall is the failure mode "
        "this profile exists to prevent."
    ),
)

PROFILES = {p.key: p for p in (PERIMETER, CONVOY, PATROL, URBAN)}


def get(key: str) -> MissionProfile:
    if key not in PROFILES:
        raise KeyError(f"unknown profile {key!r}; have {sorted(PROFILES)}")
    return PROFILES[key]
