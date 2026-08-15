"""Geodesy and bearing geometry for the fusion layer.

Everything downstream of the sensor node works in a local East-North-Up (ENU)
tangent plane anchored at a scenario-defined origin. Over a 3 km mesh the
flat-earth approximation costs well under a metre, which is an order of
magnitude below our bearing-driven error, so it is not the limiting term.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# WGS84 mean radius. Good enough for a tangent plane a few km across.
_EARTH_R = 6_371_008.8


@dataclass(frozen=True)
class LocalFrame:
    """ENU tangent plane anchored at (lat0, lon0)."""

    lat0: float
    lon0: float

    def to_enu(self, lat: float, lon: float) -> np.ndarray:
        """Geodetic degrees -> (east, north) metres."""
        dlat = math.radians(lat - self.lat0)
        dlon = math.radians(lon - self.lon0)
        east = dlon * _EARTH_R * math.cos(math.radians(self.lat0))
        north = dlat * _EARTH_R
        return np.array([east, north], dtype=float)

    def to_geodetic(self, east: float, north: float) -> tuple[float, float]:
        """(east, north) metres -> geodetic degrees."""
        lat = self.lat0 + math.degrees(north / _EARTH_R)
        lon = self.lon0 + math.degrees(
            east / (_EARTH_R * math.cos(math.radians(self.lat0)))
        )
        return lat, lon


def unit_from_azimuth(az_deg: float) -> np.ndarray:
    """Compass azimuth (0 deg = North, clockwise positive) -> ENU unit vector."""
    a = math.radians(az_deg)
    return np.array([math.sin(a), math.cos(a)], dtype=float)


def azimuth_from_unit(u: np.ndarray) -> float:
    """ENU vector -> compass azimuth in [0, 360)."""
    return math.degrees(math.atan2(u[0], u[1])) % 360.0


def wrap_deg(delta: float) -> float:
    """Wrap an angular difference into (-180, +180]."""
    return (delta + 180.0) % 360.0 - 180.0


def bearing_between(origin: np.ndarray, target: np.ndarray) -> float:
    """Compass azimuth from origin to target, both ENU."""
    d = np.asarray(target, dtype=float) - np.asarray(origin, dtype=float)
    return azimuth_from_unit(d)


def triangulate(
    origins: np.ndarray,
    azimuths_deg: np.ndarray,
    sigmas_deg: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares intersection of N bearing lines in the ENU plane.

    Each line is the ray from ``origins[i]`` along ``azimuths_deg[i]``. The
    classic closed form minimises the sum of squared *perpendicular* distances
    from the estimated point to every line:

        minimise  sum_i || (I - u_i u_i^T)(x - o_i) ||^2

    which is linear in x. Weighting each term by 1/sigma_i^2 lets a tight
    optical bearing dominate a smeared acoustic one.

    Returns (point_enu, covariance_2x2). Covariance is the inverse of the
    normal matrix scaled by the residual variance -- an *estimate* of the
    fix quality, not a calibrated figure.
    """
    origins = np.atleast_2d(np.asarray(origins, dtype=float))
    azimuths_deg = np.atleast_1d(np.asarray(azimuths_deg, dtype=float))
    n = len(azimuths_deg)
    if n < 2:
        raise ValueError("triangulation needs at least two bearings")

    if sigmas_deg is None:
        weights = np.ones(n)
    else:
        s = np.clip(np.asarray(sigmas_deg, dtype=float), 1e-3, None)
        weights = 1.0 / s**2

    a_mat = np.zeros((2, 2))
    b_vec = np.zeros(2)
    for o, az, w in zip(origins, azimuths_deg, weights):
        u = unit_from_azimuth(az)
        # Projector onto the direction perpendicular to the bearing ray.
        p = np.eye(2) - np.outer(u, u)
        a_mat += w * p
        b_vec += w * p @ o

    # Near-parallel bearings make a_mat singular: the crossing angle is the
    # thing that actually determines whether a fix exists at all.
    if np.linalg.cond(a_mat) > 1e8:
        raise np.linalg.LinAlgError("bearings are near-parallel; no usable fix")

    point = np.linalg.solve(a_mat, b_vec)

    residuals = []
    for o, az in zip(origins, azimuths_deg):
        u = unit_from_azimuth(az)
        d = point - o
        residuals.append(np.linalg.norm(d - np.dot(d, u) * u))
    dof = max(n - 2, 1)
    sigma_sq = float(np.sum(np.square(residuals)) / dof)
    cov = np.linalg.inv(a_mat) * max(sigma_sq, 1e-6)
    return point, cov


def cep50_from_cov(cov: np.ndarray) -> float:
    """Circular error probable (50%) in metres from a 2x2 position covariance.

    Uses the standard Rayleigh approximation CEP50 ~= 1.1774 * sqrt(lambda_min
    * lambda_max) valid for moderately eccentric error ellipses. This is an
    ESTIMATE; strongly elongated ellipses (near-parallel bearings) violate the
    approximation and we report the ellipse axes instead.
    """
    eigenvalues = np.linalg.eigvalsh(cov)
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    return float(1.1774 * math.sqrt(math.sqrt(eigenvalues[0] * eigenvalues[1]) ** 2))


def error_ellipse(cov: np.ndarray, n_sigma: float = 1.0) -> tuple[float, float, float]:
    """(semi_major_m, semi_minor_m, orientation_deg) of the error ellipse."""
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.clip(eigenvalues[order], 0.0, None)
    major_axis = eigenvectors[:, order[0]]
    orientation = azimuth_from_unit(major_axis)
    return (
        float(n_sigma * math.sqrt(eigenvalues[0])),
        float(n_sigma * math.sqrt(eigenvalues[1])),
        orientation,
    )


def cross_range_error(range_m: float, bearing_sigma_deg: float) -> float:
    """Linear cross-range uncertainty at a given range for a bearing sigma.

    The single most useful sanity number in the whole system: at 350 m, one
    degree of bearing error is 6.1 m of cross-range error.
    """
    return float(range_m * math.tan(math.radians(bearing_sigma_deg)))
