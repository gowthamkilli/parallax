"""The gated pipeline: audio in -> "is it a gunshot?" -> direction and range out.

This is the join between the two halves of the system, and the order matters:

    audio -> CLASSIFY -> (gunshot?) -> MEASURE -> SOLVE -> direction + range
                             |
                             +-- not a gunshot: stop. No solve, no map marker.

Nothing downstream of the gate runs on a door slam. That is the whole point of
putting a trained detector in front of a ranging solver rather than beside it:
the crack-thump maths will happily return a confident range for a firecracker,
because it is pure geometry and has no idea what a gunshot is. The model is what
knows.

The pipeline holds the operating constants fixed (temperature, and therefore the
speed of sound) so a caller supplies only what a real node would actually have:
the captured audio and the measured bearings. Muzzle velocity is NOT an input --
it is recovered from the shock geometry (see parallax/ballistics.py), which is
what makes the range ammunition-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .ballistics import BallisticObservables, DEFAULT_BULLET_LENGTH_M
from .detector import Detection, GunshotDetector
from .features import detect_onset
from .localize import GeoContact, localize_single_node

# Fixed operating constants. A field node measures its own air temperature; the
# pipeline pins it so the demo and the tests are reproducible.
TEMP_C = 20.0

# The window the classifier judges, matching sim/edge_node.py's PRE_TRIGGER_S +
# WINDOW_S. The classifier must see the same slice in training and in the field
# -- several features are duration-sensitive, so a longer window is real skew.
PRE_TRIGGER_S = 0.003
WINDOW_S = 0.025


def classification_window(audio: np.ndarray, fs: float) -> np.ndarray:
    """Slice the capture around its FIRST onset, as the edge pipeline does.

    For a supersonic shot that first onset is the ballistic crack, not the
    muzzle blast -- the blast is hundreds of milliseconds behind and falls well
    outside this window. Handing the classifier the whole multi-hundred-
    millisecond capture instead would dilute every duration-sensitive feature
    and is exactly the skew that made an earlier build score real gunshots at
    p ~ 0.28.
    """
    onset = detect_onset(audio, fs)
    if onset is None:
        onset = 0
    lo = max(0, onset - int(PRE_TRIGGER_S * fs))
    hi = min(len(audio), lo + int((PRE_TRIGGER_S + WINDOW_S) * fs))
    return audio[lo:hi]


@dataclass
class PipelineResult:
    """One node's full answer: was it a shot, and if so, where from."""

    detection: Detection
    contact: GeoContact | None
    notes: list = field(default_factory=list)

    @property
    def is_gunshot(self) -> bool:
        return self.detection.is_gunshot

    def to_dict(self) -> dict:
        return {
            "detection": self.detection.to_dict(),
            "fix": self.contact.to_dict() if self.contact is not None else None,
            "notes": list(self.notes),
        }


def process(audio: np.ndarray, fs: float, detector: GunshotDetector,
            observables: BallisticObservables, node_lat: float, node_lon: float,
            node_id: int | None = None,
            bullet_length_m: float = DEFAULT_BULLET_LENGTH_M,
            seed: int = 0) -> PipelineResult:
    """Classify the transient, and range it only if it was a gunshot.

    ``observables`` carries the bearings and timing the sensor front end
    measured (blast bearing, crack/blast bearing split, dt, N-wave duration).
    ``audio`` is the single-channel capture; it is windowed around its first
    onset before classification, exactly as the edge node does.
    """
    detection = detector.predict_audio(classification_window(audio, fs), fs)

    if not detection.is_gunshot:
        return PipelineResult(
            detection=detection, contact=None,
            notes=[f"classified NOT-GUNSHOT (p={detection.probability:.3f} < "
                   f"{detection.threshold:.2f}) - no range solved, no marker emitted"],
        )

    contact = localize_single_node(
        node_lat, node_lon, observables, node_id=node_id,
        bullet_length_m=bullet_length_m, temp_c=TEMP_C, seed=seed,
    )
    notes = [f"classified GUNSHOT (p={detection.probability:.3f}) - ranging engaged"]
    return PipelineResult(detection=detection, contact=contact, notes=notes)
