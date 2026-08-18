"""Category -> preset parameter mapping.

MVP: category is judge-selected (one of the three keys below). Stretch goal
(not built yet): category gets COMPUTED from real aim-direction geometry
(alpha vs theta_m, see parallax/fusion.py::_range_from_shockwave_blast) from
a second judge click, instead of picked from buttons. Keeping this mapping
isolated in one small table -- rather than inlined into pipeline.py -- is
what makes that swap a replacement of the caller, not a rewrite of the
pipeline: whatever computes `category` in the future just has to keep
returning one of these same three keys.

Every preset stays on the blast+triangulation path (no Shot.trajectory_
bearing_deg is ever set in pipeline.py) -- categories only vary detection
SNR and, for outside_cone, the triangulation crossing-angle gate, not which
ranging method runs.
"""

from __future__ import annotations

CATEGORY_PRESETS = {
    "inside_cone": {
        "label": "Inside cone",
        "snr_db": 28.0,
        "fusion_overrides": None,
    },
    "edge": {
        "label": "Edge",
        "snr_db": 14.0,
        "fusion_overrides": None,
    },
    "outside_cone": {
        "label": "Outside cone",
        "snr_db": 10.0,
        # Deterministically forces the triangulation crossing-angle gate to
        # reject (default is 15 deg) so this category reliably declines to
        # range rather than depending on chance SNR-driven detector misses,
        # which would be flaky live.
        "fusion_overrides": {"min_crossing_angle_deg": 60.0},
    },
}
