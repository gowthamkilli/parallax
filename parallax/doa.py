"""Direction-of-arrival from a small aperture microphone array.

Method: GCC-PHAT time-delay estimation on every microphone pair, then a
weighted least-squares plane-wave fit for the arrival direction.

Why GCC-PHAT and not MUSIC / narrowband beamforming
---------------------------------------------------
A muzzle blast is a broadband impulsive transient, not a narrowband tone.
Time-domain correlation of a broadband transient produces one unambiguous
peak regardless of element spacing. Narrowband subspace methods would impose
the d <= lambda/2 spatial-aliasing constraint: at 3 kHz that is 5.7 cm, which
would force a tiny aperture and therefore poor angular precision, since
bearing error scales as c*dt/aperture. Broadband TDOA lets us take a 30 cm
aperture and the precision that comes with it. This trade is the reason the
array can be physically small and still bear well.

Plane-wave model
----------------
For microphones at positions p_i and a source in unit direction u (pointing
FROM the array TO the source), a microphone displaced toward the source hears
the wavefront earlier:

    t_i = t_0 - (p_i . u) / c

so for the pairwise delay D_ij = t_j - t_i (which is what gcc_phat returns):

    (p_i - p_j) . u = c * D_ij

This is linear in u. Stack all 15 pairs of a 6-element array, solve by
least squares, normalise. No iteration, no local minima, no initial guess --
which is exactly what you want in fixed-point on an FPGA.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

C_SOUND = 343.0  # m/s at 20 C, dry air. Varies ~0.6 m/s per degree C.


@dataclass(frozen=True)
class ArrayGeometry:
    """Microphone positions in the node body frame, metres.

    Axes: x = right, y = forward (node boresight), z = up.
    """

    positions: np.ndarray  # (n_mics, 3)
    name: str = "array"

    @property
    def n_mics(self) -> int:
        return int(self.positions.shape[0])

    @property
    def aperture_m(self) -> float:
        """Largest inter-element spacing -- the term that sets angular precision."""
        best = 0.0
        for i in range(self.n_mics):
            for j in range(i + 1, self.n_mics):
                best = max(best, float(np.linalg.norm(self.positions[i] - self.positions[j])))
        return best

    @property
    def is_planar(self) -> bool:
        """Planar arrays cannot observe elevation. This matters -- see below."""
        centred = self.positions - self.positions.mean(axis=0)
        singular_values = np.linalg.svd(centred, compute_uv=False)
        return bool(singular_values[-1] < 1e-3 * max(singular_values[0], 1e-9))


def planar_ring(n_mics: int = 6, radius: float = 0.15) -> ArrayGeometry:
    """The literal problem-statement array: 6 omnis in a flat ring.

    Azimuth-only. Elevation is NOT observable and any elevation number a
    planar array reports is fabricated -- the up/down mirror image produces
    identical delays at every element.
    """
    angles = np.arange(n_mics) * 2 * np.pi / n_mics
    positions = np.stack(
        [radius * np.sin(angles), radius * np.cos(angles), np.zeros(n_mics)], axis=1
    )
    return ArrayGeometry(positions, name=f"planar_ring_{n_mics}x{radius:.2f}m")


def ring_plus_mast(radius: float = 0.15, mast_height: float = 0.15) -> ArrayGeometry:
    """RECOMMENDED. 5 omnis in a ring + 1 raised on a short mast.

    Same 6 microphones, same 6 ADC channels, same FPGA fabric, same cost.
    Raising one element out of plane breaks the up/down ambiguity and makes
    elevation observable. This is a mechanical change, not an electrical one,
    and it is the cheapest capability the design has available.
    """
    angles = np.arange(5) * 2 * np.pi / 5
    ring = np.stack(
        [radius * np.sin(angles), radius * np.cos(angles), np.zeros(5)], axis=1
    )
    mast = np.array([[0.0, 0.0, mast_height]])
    return ArrayGeometry(
        np.vstack([ring, mast]), name=f"ring5_plus_mast_{radius:.2f}m_{mast_height:.2f}m"
    )


def gcc_phat(
    x: np.ndarray,
    y: np.ndarray,
    fs: float,
    max_delay_s: float | None = None,
    interp: int = 1,
) -> tuple[float, float]:
    """Generalised cross-correlation with phase transform.

    Returns (delay_s, peak_sharpness) where ``delay_s`` is the delay of ``y``
    relative to ``x``: y(t) ~= x(t - delay).

    PHAT whitens the cross-spectrum, discarding magnitude and keeping only
    phase. That is what makes it robust in reverberant environments: a strong
    specular reflection inflates magnitude at some frequencies but the direct
    path still dominates the phase alignment. It is not immune to multipath --
    nothing is -- but it degrades far more gracefully than plain correlation.

    ``peak_sharpness`` is the ratio of the main peak to the next-highest local
    peak. Values near 1 mean the direct path is not cleanly dominant -- either
    a reflection is competing with it, or the SNR is low enough that noise
    peaks rival the true arrival. Both cases make the bearing untrustworthy in
    the same way, so both raise FLAG_MULTIPATH_SUSPECT and inflate the
    reported sigma rather than silently emitting a confident wrong bearing.
    """
    n = len(x) + len(y)
    nfft = 1 << int(math.ceil(math.log2(n)))

    X = np.fft.rfft(x, nfft)
    Y = np.fft.rfft(y, nfft)
    R = np.conj(X) * Y
    magnitude = np.abs(R)
    # Regularised PHAT: a pure 1/|R| blows up on empty bins.
    R = R / (magnitude + 1e-12 * magnitude.max() + 1e-20)

    cc = np.fft.irfft(R, nfft * interp)
    fs_i = fs * interp
    max_shift = int(nfft * interp // 2)
    if max_delay_s is not None:
        max_shift = min(max_shift, int(math.ceil(max_delay_s * fs_i)) + 2)

    cc = np.concatenate([cc[-max_shift:], cc[: max_shift + 1]])
    peak = int(np.argmax(np.abs(cc)))

    sharpness = _peak_sharpness(np.abs(cc), peak)
    shift = _parabolic_refine(np.abs(cc), peak) - max_shift
    return float(shift / fs_i), sharpness


def _parabolic_refine(values: np.ndarray, peak: int) -> float:
    """Sub-sample peak location by fitting a parabola to the 3 samples at the peak.

    At 48 kHz one sample is 20.8 us. Parabolic interpolation typically recovers
    ~0.1 sample at high SNR (an ESTIMATE, degrading with noise), i.e. ~2 us,
    which is what makes sub-degree bearing arithmetically possible.
    """
    if peak <= 0 or peak >= len(values) - 1:
        return float(peak)
    a, b, c = values[peak - 1], values[peak], values[peak + 1]
    denom = a - 2 * b + c
    if abs(denom) < 1e-20:
        return float(peak)
    return float(peak + 0.5 * (a - c) / denom)


def _peak_sharpness(values: np.ndarray, peak: int) -> float:
    """Ratio of the main peak to the highest peak OUTSIDE its own main lobe.

    The main lobe must be excluded by walking out to the first local minimum
    on each side, not by a fixed guard band. Its width is set by the signal
    bandwidth, and after the problem statement's ~200 Hz-3 kHz bandpass the
    lobe is roughly 1/BW = 357 us wide -- about 17 samples at 48 kHz, and 68
    at interp=4. A fixed few-sample guard would measure the main lobe's own
    shoulder as the "competing" peak and report sharpness ~= 1 for every
    input, which makes the multipath flag fire constantly and the sigma
    saturate. Walking to the local minimum is parameter-free and correct at
    any bandwidth or interpolation factor.
    """
    n = len(values)
    left = peak
    while left > 0 and values[left - 1] <= values[left]:
        left -= 1
    right = peak
    while right < n - 1 and values[right + 1] <= values[right]:
        right += 1

    # A near-zero main peak (dead/disconnected channel, or a window pulled
    # before any real signal arrived) means there is no coherent correlation
    # at all -- not a maximally sharp one. Falling through to the ratio below
    # would divide ~0 by ~0's floor and return +inf, which estimate_doa then
    # reads as the BEST possible peak quality and drives sigma toward zero:
    # exactly backwards. Report the worst-case sharpness instead.
    if values[peak] <= 1e-20:
        return 1.0

    masked = values.copy()
    masked[left:right + 1] = 0.0
    second = float(masked.max())
    if second <= 1e-20:
        return float("inf")
    return float(values[peak] / second)


@dataclass
class DoAResult:
    azimuth_deg: float
    elevation_deg: float
    azimuth_sigma_deg: float
    elevation_valid: bool
    residual_us: float  # RMS TDOA residual of the plane-wave fit
    multipath_suspect: bool
    unit_vector: np.ndarray
    n_pairs: int


def estimate_doa(
    channels: np.ndarray,
    geometry: ArrayGeometry,
    fs: float,
    c: float = C_SOUND,
    interp: int = 4,
    sharpness_threshold: float = 1.35,
) -> DoAResult:
    """Full DoA estimate from a windowed multichannel transient.

    ``channels`` is (n_mics, n_samples), already onset-aligned and bandpassed.

    The reported ``azimuth_sigma_deg`` is derived from the *residual of the
    plane-wave fit*, not asserted. If the measured delays are mutually
    consistent the residual is small and we claim a tight bearing; if a
    reflection has corrupted one pair the residual grows and the bearing
    self-reports as loose. The fusion layer then downweights it automatically.
    """
    n_mics = geometry.n_mics
    if channels.shape[0] != n_mics:
        raise ValueError(f"expected {n_mics} channels, got {channels.shape[0]}")

    max_delay = geometry.aperture_m / c * 1.5
    rows, rhs, sharpnesses = [], [], []
    for i in range(n_mics):
        for j in range(i + 1, n_mics):
            delay, sharp = gcc_phat(
                channels[i], channels[j], fs, max_delay_s=max_delay, interp=interp
            )
            rows.append(geometry.positions[i] - geometry.positions[j])
            rhs.append(c * delay)
            sharpnesses.append(sharp)

    a_mat = np.asarray(rows)
    b_vec = np.asarray(rhs)

    # A planar array has a rank-deficient A: the z column is all zeros, so the
    # z component of u is unconstrained. Solve in the observable subspace only
    # and report elevation as invalid rather than inventing a value.
    planar = geometry.is_planar
    if planar:
        a_solve = a_mat[:, :2]
    else:
        a_solve = a_mat

    solution, *_ = np.linalg.lstsq(a_solve, b_vec, rcond=None)
    if planar:
        u = np.array([solution[0], solution[1], 0.0])
    else:
        u = np.asarray(solution, dtype=float)

    norm = np.linalg.norm(u)
    if norm < 1e-12:
        raise ValueError("degenerate DoA solution; no coherent wavefront")
    u = u / norm

    residual = b_vec - a_mat @ u
    residual_rms_s = float(np.sqrt(np.mean(np.square(residual))) / c)

    # Two independent error sources, combined in quadrature.
    #
    # (i) FIT RESIDUAL -- how mutually inconsistent the 15 measured delays are.
    #     Catches geometry error, wavefront curvature, and one bad pair.
    #
    # (ii) PEAK QUALITY -- how cleanly each correlation peak stands out.
    #     The residual alone is blind to a failure mode that matters: at low
    #     SNR every pair can be wrong in a mutually *consistent* way, so the
    #     fit closes tightly on a confidently incorrect bearing. Peak
    #     sharpness (main peak / next-highest peak) detects that directly and
    #     is the term that makes sigma respond to SNR rather than only to
    #     inconsistency.
    sharpness = float(np.median(sharpnesses))
    tau_quality_s = 0.25 / fs / max(sharpness - 1.0, 0.05)
    tau_total_s = math.hypot(residual_rms_s, tau_quality_s)

    # Propagate delay uncertainty into an angular sigma through the array
    # aperture: d(theta) ~= c * d(tau) / aperture. This is the broadside
    # (best) case, so treat it as a floor, and inflate it for endfire geometry.
    sigma_rad = c * tau_total_s / max(geometry.aperture_m, 1e-6)
    # Endfire inflation: sensitivity falls off as sin(theta) from the baseline.
    horizontal = math.hypot(u[0], u[1])
    sigma_rad /= max(horizontal, 0.25)
    sigma_deg = float(np.clip(math.degrees(sigma_rad), 0.05, 25.0))

    azimuth = math.degrees(math.atan2(u[0], u[1])) % 360.0
    elevation = math.degrees(math.asin(np.clip(u[2], -1.0, 1.0)))

    return DoAResult(
        azimuth_deg=azimuth,
        elevation_deg=0.0 if planar else elevation,
        azimuth_sigma_deg=sigma_deg,
        elevation_valid=not planar,
        residual_us=residual_rms_s * 1e6,
        multipath_suspect=bool(sharpness < sharpness_threshold),
        unit_vector=u,
        n_pairs=len(rows),
    )


def theoretical_bearing_floor_deg(
    aperture_m: float, fs: float, sub_sample_fraction: float = 0.1, c: float = C_SOUND
) -> float:
    """Best achievable broadside bearing precision for an aperture and sample rate.

    d(theta) = c * d(tau) / L, with d(tau) = sub_sample_fraction / fs.

    For L = 0.30 m, fs = 48 kHz, 0.1-sample interpolation:
        d(tau) = 2.08 us  ->  d(theta) = 0.14 deg

    This is a FLOOR, not a performance claim. It assumes high SNR, no
    multipath, exact geometry and a perfectly known speed of sound. Realised
    accuracy in the simulator is 1-3 deg; see docs/04-limitations.md.
    """
    d_tau = sub_sample_fraction / fs
    return float(math.degrees(c * d_tau / aperture_m))
