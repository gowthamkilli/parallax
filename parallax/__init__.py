"""PARALLAX -- distributed passive-sensor threat picture.

Named for the geometric principle it runs on: two separated observers looking
at the same distant object determine its position from the difference in their
lines of sight. That is the whole system in one word.
"""

__version__ = "0.1.0"

from .contact import (  # noqa: F401
    ContactReport,
    FusedTrack,
    Modality,
    ThreatClass,
    WIRE_SIZE,
)
from .doa import (  # noqa: F401
    ArrayGeometry,
    DoAResult,
    estimate_doa,
    planar_ring,
    ring_plus_mast,
    theoretical_bearing_floor_deg,
)
from .fusion import FusionConfig, FusionEngine, NodeState, speed_of_sound  # noqa: F401
from .geometry import LocalFrame, triangulate  # noqa: F401
from .profiles import PROFILES, MissionProfile  # noqa: F401

__all__ = [
    "ContactReport", "FusedTrack", "Modality", "ThreatClass", "WIRE_SIZE",
    "ArrayGeometry", "DoAResult", "estimate_doa", "planar_ring",
    "ring_plus_mast", "theoretical_bearing_floor_deg",
    "FusionConfig", "FusionEngine", "NodeState", "speed_of_sound",
    "LocalFrame", "triangulate", "PROFILES", "MissionProfile",
]
