"""Standalone demonstration of the acoustic-only shockwave-ranging formula.

WHAT THIS IS
    A worked, narrated proof that D = c*dt / f(alpha, M) with
    alpha = theta_m - gamma (see parallax/fusion.py's
    _range_from_shockwave_blast docstring for the full derivation) correctly
    recovers a shooter's range from a single node's shockwave-to-blast
    timing gap and its own two bearings -- no optical channel, no second
    node.

WHAT THIS IS NOT
    A live audio capture demo. The two ContactReports below are constructed
    directly from geometry (muzzle position, node position, assumed bullet
    speed), the same way tests/test_fusion.py's
    test_shockwave_blast_range_recovered_near_axis validates the formula --
    NOT rendered through sim/scenario.py's audio synthesis and DoA solver.

    That distinction matters and is being stated plainly rather than
    glossed over: as of this session, feeding a *rendered* shockwave pulse
    through the real onset-detect -> bandpass -> GCC-PHAT -> plane-wave-fit
    pipeline (sim/edge_node.py + parallax/doa.py) does not yet recover an
    accurate shockwave bearing. The blast pulse's bearing recovers cleanly
    (see the main `sim.run_demo` demo). The shockwave pulse's does not, and
    the fix is still being investigated -- it is not a quick fix, and is
    NOT claimed to be working here. This script exists so the underlying
    math can be shown correct and working tonight without overstating what
    the live sensor pipeline currently does.

    python -m sim.demo_shockwave_math
"""

from __future__ import annotations

import math

import numpy as np

from parallax.contact import ContactReport, Modality, ThreatClass, FLAG_GPS_LOCKED
from parallax.fusion import FusionConfig, FusionEngine, NodeState, speed_of_sound
from parallax.geometry import LocalFrame, bearing_between

ORIGIN = LocalFrame(28.6139, 77.2090)
T0 = 1_700_000_000_000_000_000


def shockwave_geometry(alpha_deg: float, d_true: float, bullet_speed_mps: float,
                       temp_c: float = 20.0):
    """Construct muzzle (S), node (O), and shockwave emission point (P) for
    a trajectory pointing due north, then derive the blast and shockwave
    arrival times from first-principles propagation -- bullet travel time
    to P, then sound from P to O; sound directly from S to O. This is
    independent of fusion.py's own algebraic dt formula, so recovering
    d_true through the fusion engine below is a genuine end-to-end check
    of the math, not a circular one.
    """
    c = speed_of_sound(temp_c)
    mach = bullet_speed_mps / c
    theta_m = math.asin(1.0 / mach)
    alpha = math.radians(alpha_deg)
    assert alpha <= theta_m, (
        f"alpha={alpha_deg:.1f} deg is outside the Mach cone "
        f"(theta_m={math.degrees(theta_m):.1f} deg) -- no shockwave reaches this node"
    )

    cross = d_true * math.sin(alpha)
    along = d_true * math.cos(alpha)
    muzzle = np.array([0.0, 0.0])
    node_enu = np.array([cross, along])
    x_prime = along - cross * math.sqrt(mach * mach - 1.0)
    emission_point = np.array([0.0, x_prime])

    blast_az = bearing_between(node_enu, muzzle)
    shock_az = bearing_between(node_enu, emission_point)
    t_blast = d_true / c
    t_shock = x_prime / bullet_speed_mps + float(np.linalg.norm(node_enu - emission_point)) / c
    return blast_az, shock_az, t_blast - t_shock, node_enu, theta_m, c


def main():
    d_true = 350.0
    v_b = 880.0
    alpha_deg = 8.0  # a plausible near-axis geometry, well inside the Mach cone

    print("=" * 74)
    print("ACOUSTIC-ONLY SHOCKWAVE RANGING -- formula demonstration")
    print("(fusion-layer math, NOT a live sensor capture -- see module docstring)")
    print("=" * 74)

    blast_az, shock_az, dt_s, node_enu, theta_m, c = shockwave_geometry(alpha_deg, d_true, v_b)
    print(f"\nScenario: shooter {d_true:.0f} m away, node at miss angle "
          f"alpha={alpha_deg:.1f} deg from the line of fire")
    print(f"  assumed bullet speed  : {v_b:.0f} m/s  (Mach {v_b/c:.2f}, "
          f"theta_m={math.degrees(theta_m):.1f} deg)")
    print(f"  speed of sound        : {c:.1f} m/s")
    print(f"  blast bearing (truth) : {blast_az:.2f} deg")
    print(f"  shockwave bearing     : {shock_az:.2f} deg  "
          f"(gamma = {abs(blast_az - shock_az):.2f} deg separation from the blast bearing --")
    print(f"                           this is EXPECTED, not noise: the shockwave's DoA points")
    print(f"                           at its own Mach-cone emission point, not the muzzle)")
    print(f"  shockwave->blast dt   : {dt_s*1000:.1f} ms")

    node = NodeState(node_id=1, lat=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[0],
                     lon=ORIGIN.to_geodetic(node_enu[0], node_enu[1])[1])
    engine = FusionEngine([node], ORIGIN, config=FusionConfig(bullet_speed_mps=v_b))
    dt_ns = int(round(dt_s * 1e9))
    reports = [
        ContactReport(node_id=1, seq=1, t_event_ns=T0, modality=Modality.ACOUSTIC_SHOCKWAVE,
                      threat_class=ThreatClass.GUNSHOT, class_confidence=0.70,
                      azimuth_deg=shock_az, azimuth_sigma_deg=2.0, flags=FLAG_GPS_LOCKED),
        ContactReport(node_id=1, seq=2, t_event_ns=T0 + dt_ns, modality=Modality.ACOUSTIC,
                      threat_class=ThreatClass.GUNSHOT, class_confidence=0.85,
                      azimuth_deg=blast_az, azimuth_sigma_deg=1.5, flags=FLAG_GPS_LOCKED),
    ]

    print("\nFeeding both reports into FusionEngine.process() -- the SAME code path")
    print("a real node's contact reports go through, just fed synthetic reports")
    print("instead of ones produced by the audio pipeline:")
    tracks = engine.process(reports)
    track = tracks[0]
    error = track.range_m - d_true if track.range_m is not None else None

    print(f"\n  range method : {track.range_method}")
    print(f"  range        : {track.range_m:.1f} m  (truth {d_true:.0f} m, "
          f"error {error:+.2f} m, {abs(error)/d_true*100:.2f}%)")
    print(f"  confidence   : {track.confidence:.3f}")
    for note in track.notes:
        print(f"    - {note}")

    print("\n" + "=" * 74)
    print("This confirms the D = c*dt / f(alpha, M) closed form, and the")
    print("alpha = theta_m - gamma bearing-separation identity, are both correctly")
    print("implemented in parallax/fusion.py::_range_from_shockwave_blast.")
    print("Live audio capture of a real shockwave transient is a separate,")
    print("still-open problem -- see this file's module docstring.")
    print("=" * 74)


if __name__ == "__main__":
    main()
