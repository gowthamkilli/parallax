"""Crack-thump ballistic solver: single-node range, miss distance and speed.

THIS IS THE FLAGSHIP RANGING ALGORITHM.

A supersonic bullet drags a cone-shaped shockwave behind it, like a boat's
wake. The half-angle of that cone (the Mach angle mu) is set purely by how fast
the bullet is travelling relative to sound: sin(mu) = 1 / M. When that shock
"crack" reaches a sensor it arrives from a *different* bearing than the muzzle
"thump", and the split between the two bearings is very nearly the Mach angle.
So a single node that can hear both arrivals reads the bullet's speed straight
off the array -- with no assumption about what weapon was fired. That is the
property that kills the ammunition-dependence problem that plagues
amplitude-based ranging.

The four observables and what they constrain
--------------------------------------------
    blast (thump) bearing   -> direction to the shooter
    crack bearing           -> Mach angle mu (via the bearing split)
    dt = t_blast - t_crack  -> range R (timing)
    N-wave duration T       -> miss distance d (Whitham)

Three unknowns (R, d, M), four observables: the system is OVERDETERMINED, which
is what makes it robust. We never need to assume the weapon or the ammunition.

The three governing relationships
---------------------------------
1. Bearing split:   alpha = mu - arctan(d / R),   with  sin(mu) = 1 / M
   d is usually small vs R, so the arctan correction is only a degree or two
   and alpha ~= mu. We still solve the correction by iteration below.

2. Timing:  dt = (R/c)(1 - 1/M) + (d/c)[ sqrt(M^2 - 1)/M - M ]
   The first term dominates; the second is a small side-miss correction.

3. Whitham N-wave duration:
       T ~= 1.82 * M * d^(1/4) * l / [ c * (M^2 - 1)^(3/8) ]
   with l the bullet length. Note the QUARTER power on d -- this is a weak
   estimator, and it is the honest reason miss distance is the least accurate
   of the three outputs.

The inverse solve (what the node actually computes)
---------------------------------------------------
Given alpha, dt, T and an assumed bullet length l:
    mu  <- alpha + arctan(d/R)      (d, R from the previous pass; 0 / inf first)
    M   <- 1 / sin(mu)
    d   <- invert Whitham for d given M, T
    R   <- invert timing for R given M, d, dt
Repeat. It converges in two passes for realistic geometry (see the worked
example in tests/test_ballistics.py, which reproduces R=300 m, d~10 m, M~2.04
from alpha=27.4 deg, dt=0.412 s, T=287 us).

Everything here is closed-form physics/geometry. Nothing is learned, nothing is
fitted to a simulator, and every number can be defended line by line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# Speed of sound at 20 C, dry air. Callers pass a temperature-corrected value
# from parallax.fusion.speed_of_sound() when they have a measured temperature.
C_SOUND = 343.0

# Representative projectile LENGTHS (not cartridge lengths), metres. Whitham's
# relation uses the length of the body generating the N-wave. These are
# ESTIMATES good to ~10%; the quarter-power on l in the duration means even a
# 20% length error moves the miss-distance estimate by only ~5%.
BULLET_LENGTHS_M = {
    "5.56x45": 0.023,   # ~23 mm, SS109 / M855 class
    "7.62x39": 0.0265,
    "7.62x51": 0.032,
    "9x19": 0.015,       # pistol, usually subsonic -- no crack at all
    "generic": 0.025,
}
DEFAULT_BULLET_LENGTH_M = BULLET_LENGTHS_M["generic"]

# Below this Mach number the crack-thump range solve is geometrically valid
# but numerically fragile (see the note in solve_crack_thump). Empirically
# derived from sim/stress_test.py's random sweep, not a claim from theory.
TRANSONIC_MACH_FLOOR = 1.15

# Beyond this lateral miss the N-wave has decayed too far to detect reliably for
# small arms; beyond this straight range likewise. Both are ESTIMATES. Lives
# here (not in sim/) so parallax/fusion.py can use it for the shockwave/blast
# association window without the parallax package depending on sim.
MAX_CRACK_THUMP_MISS_M = 150.0
MAX_CRACK_THUMP_RANGE_M = 800.0


def speed_of_sound(temp_c: float = 20.0) -> float:
    """c(T) = 331.3 * sqrt(1 + T/273.15) m/s. Dominant term in dt-based range."""
    return 331.3 * math.sqrt(1.0 + temp_c / 273.15)


def mach_angle_deg(mach: float) -> float:
    """Half-angle of the Mach cone: mu = arcsin(1/M). Requires M > 1."""
    if mach <= 1.0:
        raise ValueError(f"subsonic Mach {mach:.3f}: no shock cone exists")
    return math.degrees(math.asin(1.0 / mach))


# --------------------------------------------------------------------------
# Forward model -- generate the observables a sensor would see. Used by the
# simulator and by the tests, and to seed the error-propagation Monte Carlo.
# --------------------------------------------------------------------------
def whitham_duration_s(mach: float, miss_distance_m: float,
                       bullet_length_m: float, c: float = C_SOUND) -> float:
    """Whitham N-wave positive-phase duration T for a passing bullet."""
    if mach <= 1.0:
        raise ValueError("Whitham duration is defined only for M > 1")
    d = max(miss_distance_m, 1e-3)
    return (1.82 * mach * d ** 0.25 * bullet_length_m
            / (c * (mach ** 2 - 1.0) ** 0.375))


def timing_dt_s(range_m: float, miss_distance_m: float, mach: float,
                c: float = C_SOUND) -> float:
    """Blast-minus-crack arrival gap dt for a shot at (R, d) with speed M*c."""
    if mach <= 1.0:
        raise ValueError("crack-thump timing is defined only for M > 1")
    root = math.sqrt(mach ** 2 - 1.0)
    return (range_m / c) * (1.0 - 1.0 / mach) + (miss_distance_m / c) * (root / mach - mach)


def forward_observables(range_m: float, miss_distance_m: float, mach: float,
                        bullet_length_m: float = DEFAULT_BULLET_LENGTH_M,
                        c: float = C_SOUND) -> dict:
    """Everything a perfect sensor would measure for a known (R, d, M) shot.

    Returns mach angle, bearing split alpha, blast/crack arrival times, dt and
    the N-wave duration T. This is the generator the inverse solver is tested
    against, and what sim/scenario.py uses to place the crack correctly.
    """
    mu = math.radians(mach_angle_deg(mach))
    alpha = mu - math.atan2(miss_distance_m, range_m)
    t_blast = range_m / c
    dt = timing_dt_s(range_m, miss_distance_m, mach, c)
    t_crack = t_blast - dt
    return {
        "mach": mach,
        "mach_angle_deg": math.degrees(mu),
        "bearing_split_deg": math.degrees(alpha),
        "t_blast_s": t_blast,
        "t_crack_s": t_crack,
        "dt_s": dt,
        "nwave_duration_s": whitham_duration_s(mach, miss_distance_m, bullet_length_m, c),
    }


# --------------------------------------------------------------------------
# Observables in / solution out.
# --------------------------------------------------------------------------
@dataclass
class BallisticObservables:
    """What a single node measured for one shot. Sensor-count agnostic.

    ``bearing_split_deg`` (alpha) is the angle between the crack bearing and the
    blast bearing. A 6-mic array measures both bearings directly; a 2-mic team
    measures each bearing as a TDOA cone and takes the difference. Either way
    the solver only needs the split, the timing gap and the N-wave duration.
    """

    blast_bearing_deg: float          # compass bearing to the shooter (thump)
    bearing_split_deg: float          # alpha = crack..blast angle -> Mach angle
    dt_s: float                       # t_blast - t_crack, must be > 0
    nwave_duration_s: float           # T, positive-phase duration of the crack

    # 1-sigma measurement uncertainties (used for the accuracy estimate).
    blast_bearing_sigma_deg: float = 1.0
    bearing_split_sigma_deg: float = 1.5
    dt_sigma_s: float = 0.003
    nwave_duration_sigma_s: float = 30e-6

    def has_crack(self) -> bool:
        """A usable crack needs a positive split and a positive timing gap."""
        return (self.bearing_split_deg > 0.0 and self.dt_s > 0.0
                and self.nwave_duration_s > 0.0)


@dataclass
class BallisticSolution:
    shooter_bearing_deg: float
    range_m: float | None
    miss_distance_m: float | None
    mach: float | None
    converged: bool
    iterations: int
    range_sigma_m: float | None = None
    miss_distance_sigma_m: float | None = None
    mach_sigma: float | None = None
    accuracy_pct: float = 0.0          # headline confidence: distance if ranged, else direction
    direction_accuracy_pct: float = 0.0  # confidence in shooter_bearing_deg alone
    distance_accuracy_pct: float | None = None  # confidence in range_m alone; None if unranged
    method: str = "crack_thump"
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "shooter_bearing_deg": _round(self.shooter_bearing_deg, 2),
            "range_m": _round(self.range_m, 1),
            "range_sigma_m": _round(self.range_sigma_m, 1),
            "miss_distance_m": _round(self.miss_distance_m, 1),
            "miss_distance_sigma_m": _round(self.miss_distance_sigma_m, 1),
            "mach": _round(self.mach, 3),
            "mach_sigma": _round(self.mach_sigma, 3),
            "converged": self.converged,
            "iterations": self.iterations,
            "accuracy_pct": _round(self.accuracy_pct, 1),
            "direction_accuracy_pct": _round(self.direction_accuracy_pct, 1),
            "distance_accuracy_pct": _round(self.distance_accuracy_pct, 1),
            "method": self.method,
            "notes": list(self.notes),
        }


def _invert_whitham_d(nwave_T_s: float, mach: float, bullet_length_m: float,
                      c: float) -> float:
    """Recover miss distance d from the N-wave duration (inverse of Whitham)."""
    root_term = (mach ** 2 - 1.0) ** 0.375
    quarter = nwave_T_s * c * root_term / (1.82 * mach * bullet_length_m)
    return float(np.clip(quarter ** 4, 0.05, 2000.0))


def _invert_timing_R(dt_s: float, miss_distance_m: float, mach: float,
                     c: float) -> float:
    """Recover range R from the blast-crack gap (inverse of the timing eqn)."""
    root = math.sqrt(mach ** 2 - 1.0)
    side = (miss_distance_m / c) * (root / mach - mach)
    denom = 1.0 - 1.0 / mach
    return (dt_s - side) * c / denom


def _solve_core(bearing_split_deg: float, dt_s: float, nwave_T_s: float,
                bullet_length_m: float, c: float, max_iter: int = 8,
                tol_m: float = 0.5) -> tuple[float, float, float, bool, int]:
    """The bare iterative inverse. Returns (R, d, M, converged, iterations).

    Seeds the arctan(d/R) correction at zero (mu = alpha), then alternates
    Whitham (d) and timing (R) until R stops moving. Raises ValueError if the
    geometry is non-physical (split too large -> implied subsonic).
    """
    alpha = math.radians(bearing_split_deg)
    if alpha <= 0.0:
        raise ValueError("non-positive bearing split: no shock geometry")

    d, R = 0.0, float("inf")
    converged = False
    used = 0
    for used in range(1, max_iter + 1):
        correction = math.atan2(d, R) if math.isfinite(R) else 0.0
        mu = alpha + correction
        if mu >= math.pi / 2:
            raise ValueError("implied Mach angle >= 90 deg: geometry invalid")
        mach = 1.0 / math.sin(mu)
        if mach <= 1.0:
            raise ValueError("implied subsonic Mach: no crack solution")
        d = _invert_whitham_d(nwave_T_s, mach, bullet_length_m, c)
        R_new = _invert_timing_R(dt_s, d, mach, c)
        if R_new <= 0.0:
            raise ValueError("non-physical negative range from timing")
        if math.isfinite(R) and abs(R_new - R) < tol_m:
            R = R_new
            converged = True
            break
        R = R_new

    mu = alpha + (math.atan2(d, R) if math.isfinite(R) else 0.0)
    mach = 1.0 / math.sin(mu)
    return R, d, mach, converged, used


def solve_crack_thump(obs: BallisticObservables,
                      bullet_length_m: float = DEFAULT_BULLET_LENGTH_M,
                      c: float = C_SOUND,
                      n_monte_carlo: int = 200,
                      seed: int = 0) -> BallisticSolution:
    """Full single-node solve with uncertainty propagation.

    Scenario (a): a usable crack is present -> range, miss distance, Mach and an
    accuracy percentage are all produced.

    Scenario (b): no usable crack (subsonic pass, out of the cone's reach, or
    the crack could not be separated) -> range is None, only the blast bearing
    is reported. This is the "distance = null, direction only" case the field
    pipeline degrades to until a better-placed node catches the shot.

    The accuracy percentage is derived, not asserted: it comes from a Monte
    Carlo that perturbs every observable by its stated 1-sigma and measures how
    much the range estimate actually moves. A tight, well-conditioned geometry
    earns a high number; a shallow one honestly reports a low one.
    """
    notes: list[str] = []

    direction_accuracy = _direction_accuracy(obs.blast_bearing_sigma_deg)

    if not obs.has_crack():
        notes.append("no usable ballistic crack -> bearing only, range unknown")
        return BallisticSolution(
            shooter_bearing_deg=obs.blast_bearing_deg % 360.0,
            range_m=None, miss_distance_m=None, mach=None,
            converged=False, iterations=0,
            accuracy_pct=direction_accuracy,
            direction_accuracy_pct=direction_accuracy,
            distance_accuracy_pct=None,
            method="bearing_only", notes=notes,
        )

    try:
        R, d, mach, converged, iters = _solve_core(
            obs.bearing_split_deg, obs.dt_s, obs.nwave_duration_s,
            bullet_length_m, c,
        )
    except ValueError as exc:
        notes.append(f"crack-thump solve failed ({exc}) -> bearing only")
        return BallisticSolution(
            shooter_bearing_deg=obs.blast_bearing_deg % 360.0,
            range_m=None, miss_distance_m=None, mach=None,
            converged=False, iterations=0,
            accuracy_pct=direction_accuracy,
            direction_accuracy_pct=direction_accuracy,
            distance_accuracy_pct=None,
            method="bearing_only", notes=notes,
        )

    # -- uncertainty by Monte Carlo perturbation of the observables ----------
    rng = np.random.default_rng(seed)
    ranges, misses, machs = [], [], []
    for _ in range(max(n_monte_carlo, 0)):
        split_s = obs.bearing_split_deg + rng.normal(0, obs.bearing_split_sigma_deg)
        dt_s = obs.dt_s + rng.normal(0, obs.dt_sigma_s)
        T_s = obs.nwave_duration_s + rng.normal(0, obs.nwave_duration_sigma_s)
        if split_s <= 0 or dt_s <= 0 or T_s <= 0:
            continue
        try:
            Ri, di, Mi, _, _ = _solve_core(split_s, dt_s, T_s, bullet_length_m, c)
        except (ValueError, ZeroDivisionError):
            continue
        if 0 < Ri < 5000 and 0 < di < 2000:
            ranges.append(Ri); misses.append(di); machs.append(Mi)

    if len(ranges) >= 10:
        range_sigma = float(np.std(ranges))
        miss_sigma = float(np.std(misses))
        mach_sigma = float(np.std(machs))
    else:
        range_sigma = miss_sigma = mach_sigma = None
        notes.append("insufficient Monte Carlo support for a sigma estimate")

    distance_accuracy = _range_accuracy(R, range_sigma, converged)
    if not converged:
        notes.append("solver hit iteration cap without full convergence")
    if mach < TRANSONIC_MACH_FLOOR:
        # Near M=1 the timing equation's (1 - 1/M) term -> 0, so ordinary
        # bearing-split sensor noise (a degree or two) blows up into a huge
        # relative range error even though the geometry is nominally solvable.
        # Confirmed empirically: mean range error collapses from >300% to
        # single digits once M exceeds ~1.3 (see sim/stress_test.py). The
        # Monte-Carlo accuracy_pct already reflects this to some extent, but
        # the note makes the specific cause legible rather than just a number.
        notes.append(
            f"near-transonic Mach ({mach:.2f}): range estimate is unreliable -- "
            "small bearing-split noise causes disproportionately large range error"
        )

    return BallisticSolution(
        shooter_bearing_deg=obs.blast_bearing_deg % 360.0,
        range_m=R, miss_distance_m=d, mach=mach,
        converged=converged, iterations=iters,
        range_sigma_m=range_sigma, miss_distance_sigma_m=miss_sigma,
        mach_sigma=mach_sigma, accuracy_pct=distance_accuracy,
        direction_accuracy_pct=direction_accuracy,
        distance_accuracy_pct=distance_accuracy,
        method="crack_thump", notes=notes,
    )


def _range_accuracy(range_m: float, range_sigma_m: float | None,
                    converged: bool) -> float:
    """Map range and its 1-sigma to a 0..100 confidence.

    100 * (1 - sigma_R / R), floored so a wide-but-still-useful fix never reads
    as zero, and shaved a little when the solver did not fully converge.
    """
    if range_sigma_m is None or range_m <= 0:
        base = 60.0
    else:
        base = 100.0 * (1.0 - min(range_sigma_m / range_m, 1.0))
    base = float(np.clip(base, 10.0, 99.0))
    if not converged:
        base *= 0.85
    return round(base, 1)


def _direction_accuracy(bearing_sigma_deg: float) -> float:
    """Confidence in the shooter bearing alone, from its own sigma. Bounded 20..95.

    Computed unconditionally -- direction is measured (not solved), so its
    accuracy never depends on whether a crack was usable.
    """
    val = 100.0 * (1.0 - min(bearing_sigma_deg / 30.0, 1.0))
    return round(float(np.clip(val, 20.0, 95.0)), 1)


def _round(value, digits):
    return None if value is None else round(float(value), digits)
