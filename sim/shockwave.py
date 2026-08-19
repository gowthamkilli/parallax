"""Forward shockwave sensor model: trajectory -> what one node observes.

SIMULATED. Given a bullet trajectory (shooter position, aim direction, muzzle
velocity) and a node position, this computes the observables the node would
measure: the blast bearing (to the shooter), the crack bearing (to the point on
the flight path whose Mach cone sweeps the node), their split, the blast-crack
timing gap, and the N-wave duration. It also decides whether the node is even
inside the crack-thump regime at all -- the predicate that splits scenario (a)
(ranged) from scenario (b) (bearing only, range null).

This is the inverse of parallax.ballistics.solve_crack_thump: this file makes
the observables, the solver consumes them, and the demo compares the recovered
(R, d, M) against the truth stored here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from parallax.ballistics import (
    BallisticObservables,
    DEFAULT_BULLET_LENGTH_M,
    MAX_CRACK_THUMP_MISS_M,
    MAX_CRACK_THUMP_RANGE_M,
    speed_of_sound,
    timing_dt_s,
    whitham_duration_s,
)

# Re-exported under the names this module has always used, so nothing calling
# sim.shockwave.MAX_CRACK_MISS_M/MAX_CRACK_RANGE_M breaks. The values now live
# in parallax/ballistics.py -- the single source of truth -- so this module and
# parallax/fusion.py's association window can never drift apart.
MAX_CRACK_MISS_M = MAX_CRACK_THUMP_MISS_M
MAX_CRACK_RANGE_M = MAX_CRACK_THUMP_RANGE_M


def _azimuth(delta_e: float, delta_n: float) -> float:
    return math.degrees(math.atan2(delta_e, delta_n)) % 360.0


@dataclass
class Trajectory:
    shooter_enu: np.ndarray          # (east, north) metres
    aim_deg: float                   # compass direction the bullet travels
    muzzle_velocity_ms: float = 700.0
    bullet_length_m: float = DEFAULT_BULLET_LENGTH_M

    @property
    def aim_unit(self) -> np.ndarray:
        a = math.radians(self.aim_deg)
        return np.array([math.sin(a), math.cos(a)])


@dataclass
class NodeTruth:
    node_enu: np.ndarray
    true_range_m: float
    true_miss_m: float
    true_mach: float
    true_blast_bearing_deg: float
    true_crack_bearing_deg: float
    in_crack_thump_range: bool
    reason: str = ""


def node_observables(traj: Trajectory, node_enu: np.ndarray, temp_c: float = 20.0,
                     bearing_sigma_deg: float = 1.0, split_sigma_deg: float = 1.5,
                     dt_sigma_s: float = 0.003, T_sigma_s: float = 30e-6,
                     rng: np.random.Generator | None = None
                     ) -> tuple[BallisticObservables, NodeTruth]:
    """Compute one node's (noisy) observables and the underlying truth.

    ``rng`` seeds the measurement noise added to the ideal observables. Pass
    None for a noiseless (truth) reading, useful in tests.
    """
    node_enu = np.asarray(node_enu, dtype=float)
    c = speed_of_sound(temp_c)
    mach = traj.muzzle_velocity_ms / c

    vec = node_enu - traj.shooter_enu
    along = float(np.dot(vec, traj.aim_unit))            # L, along-track
    perp_vec = vec - along * traj.aim_unit
    miss = float(np.linalg.norm(perp_vec))               # d
    rng_straight = float(np.linalg.norm(vec))            # R

    blast_bearing = _azimuth(-vec[0], -vec[1])           # node -> shooter

    # Decide the crack-thump regime.
    reason = ""
    in_range = True
    if mach <= 1.0:
        in_range, reason = False, "subsonic round: no shockwave"
    elif along <= 0.0:
        in_range, reason = False, "node behind the muzzle: outside the cone"
    elif miss > MAX_CRACK_MISS_M:
        in_range, reason = False, f"miss {miss:.0f} m exceeds crack reach {MAX_CRACK_MISS_M:.0f} m"
    elif rng_straight > MAX_CRACK_RANGE_M:
        in_range, reason = False, f"range {rng_straight:.0f} m exceeds crack range {MAX_CRACK_RANGE_M:.0f} m"

    if in_range:
        mu = math.asin(1.0 / mach)
        x_e = along - miss / math.tan(mu)                # emission point along-track
        if x_e < 0.0:
            in_range, reason = False, "emission point behind muzzle: outside the cone"

    if not in_range:
        # Scenario (b): only the muzzle blast is usable. No crack observables.
        truth = NodeTruth(
            node_enu=node_enu, true_range_m=rng_straight, true_miss_m=miss,
            true_mach=mach, true_blast_bearing_deg=blast_bearing,
            true_crack_bearing_deg=float("nan"), in_crack_thump_range=False,
            reason=reason,
        )
        obs = BallisticObservables(
            blast_bearing_deg=_noise(blast_bearing, bearing_sigma_deg, rng),
            bearing_split_deg=0.0, dt_s=0.0, nwave_duration_s=0.0,
            blast_bearing_sigma_deg=bearing_sigma_deg,
        )
        return obs, truth

    # Scenario (a): full crack-thump geometry.
    mu = math.asin(1.0 / mach)
    x_e = along - miss / math.tan(mu)
    emission = traj.shooter_enu + x_e * traj.aim_unit
    crack_vec = emission - node_enu
    crack_bearing = _azimuth(crack_vec[0], crack_vec[1])
    split = abs((crack_bearing - blast_bearing + 180.0) % 360.0 - 180.0)

    dt = timing_dt_s(rng_straight, miss, mach, c)
    T = whitham_duration_s(mach, miss, traj.bullet_length_m, c)

    truth = NodeTruth(
        node_enu=node_enu, true_range_m=rng_straight, true_miss_m=miss,
        true_mach=mach, true_blast_bearing_deg=blast_bearing,
        true_crack_bearing_deg=crack_bearing, in_crack_thump_range=True,
        reason="crack-thump geometry valid",
    )
    obs = BallisticObservables(
        blast_bearing_deg=_noise(blast_bearing, bearing_sigma_deg, rng),
        bearing_split_deg=max(_noise(split, split_sigma_deg, rng), 1e-3),
        dt_s=max(_noise(dt, dt_sigma_s, rng), 1e-4),
        nwave_duration_s=max(_noise(T, T_sigma_s, rng), 1e-6),
        blast_bearing_sigma_deg=bearing_sigma_deg,
        bearing_split_sigma_deg=split_sigma_deg,
        dt_sigma_s=dt_sigma_s,
        nwave_duration_sigma_s=T_sigma_s,
    )
    return obs, truth


def _noise(value: float, sigma: float, rng: np.random.Generator | None) -> float:
    return value if rng is None else float(value + rng.normal(0.0, sigma))
