"""Synthetic acoustic scenario generator.

EVERYTHING IN THIS FILE IS SIMULATED. No hardware was built and no field
recordings were made. This is stated plainly here, in the README, and on the
slide, because a simulated result presented as a measurement is the fastest
way to lose a technical audience.

What is physically modelled
---------------------------
* Muzzle blast waveform: Friedlander blast wave,
      p(t) = P0 (1 - t/T) exp(-t/T),
  the standard analytical form for a free-field blast overpressure -- sharp
  onset, exponential decay, negative-pressure phase. This is the correct
  shape for a muzzle blast at range; it is NOT a recording of a real weapon.
* Spherical spreading: 1/r amplitude, i.e. -6 dB per doubling of distance.
* Atmospheric absorption: frequency-dependent, approximated as a first-order
  lowpass whose cutoff falls with range. Real absorption follows ISO 9613-1
  and depends on humidity; this is a deliberate simplification and is an
  ESTIMATE.
* Exact per-microphone propagation delay from the true source position --
  spherical wavefront, not a plane wave. The DoA solver assumes a plane wave,
  so the resulting wavefront-curvature error is genuine model mismatch that
  the estimator has to absorb, exactly as it would in the field.
* Additive background noise at a configurable SNR.
* Optional specular reflection: a delayed, attenuated copy arriving from a
  different bearing. This is the multipath case, and it is the one that
  breaks bearings.

What is NOT modelled
--------------------
* The supersonic ballistic shockwave (the "crack"). Excluded from v1 by
  design; only the muzzle blast is generated.
* Wind-driven refraction, ground impedance, terrain shadowing, temperature
  gradients. All of these matter in the field. See docs/04-limitations.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from parallax.doa import ArrayGeometry, C_SOUND, ring_plus_mast
from parallax.fusion import speed_of_sound


@dataclass
class SimNode:
    node_id: int
    enu: np.ndarray  # (east, north) metres
    heading_deg: float = 0.0
    geometry: ArrayGeometry = field(default_factory=ring_plus_mast)
    has_optical: bool = True
    alt_m: float = 0.0
    temp_c: float = 20.0

    def mic_positions_enu(self) -> np.ndarray:
        """Rotate the body-frame array into the ENU world frame."""
        theta = math.radians(self.heading_deg)
        rot = np.array([
            [math.cos(theta), math.sin(theta), 0.0],
            [-math.sin(theta), math.cos(theta), 0.0],
            [0.0, 0.0, 1.0],
        ])
        world = self.geometry.positions @ rot.T
        return world + np.array([self.enu[0], self.enu[1], self.alt_m])


@dataclass
class Shot:
    """One gunshot at a known truth position and time."""

    enu: np.ndarray
    t_shot_s: float = 0.0
    height_m: float = 1.5
    source_spl_db: float = 155.0  # peak SPL at 1 m for a typical rifle (ESTIMATE)
    visible_flash: bool = True


def friedlander(fs: float, duration_s: float = 0.06, tau_s: float = 0.0011,
                rng: np.random.Generator | None = None) -> np.ndarray:
    """Friedlander blast waveform. tau ~1.1 ms is representative of small arms."""
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    p = (1.0 - t / tau_s) * np.exp(-t / tau_s)
    # Real muzzle blasts are not clean analytic pulses: barrel and mount
    # resonances add structure. A little coloured ringing keeps the classifier
    # from learning "is it exactly a Friedlander curve".
    if rng is not None:
        sos = signal.butter(2, [400 / (fs / 2), 2500 / (fs / 2)], btype="band", output="sos")
        ring = signal.sosfilt(sos, rng.standard_normal(n)) * np.exp(-t / (3 * tau_s))
        p = p + 0.12 * ring / (np.max(np.abs(ring)) + 1e-12)
    return p / (np.max(np.abs(p)) + 1e-12)


def _atmospheric_lowpass(x: np.ndarray, fs: float, distance_m: float) -> np.ndarray:
    """Range-dependent high-frequency loss. Simplified; an ESTIMATE."""
    cutoff = float(np.clip(20000.0 * math.exp(-distance_m / 900.0), 800.0, fs / 2 * 0.95))
    sos = signal.butter(2, cutoff / (fs / 2), btype="low", output="sos")
    return signal.sosfilt(sos, x)


def render_node_audio(
    node: SimNode,
    shot: Shot,
    fs: float = 48_000.0,
    duration_s: float = 0.5,
    snr_db: float = 25.0,
    temp_c: float = 20.0,
    reflection: dict | None = None,
    capture_start_s: float | None = None,
    pre_roll_s: float = 0.08,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, float, float]:
    """Render audio at one node.

    Returns (audio[n_mics, n_samples], capture_start_s, peak_spl_db), where
    ``capture_start_s`` is the absolute time of sample 0 of the returned
    buffer. A real node records continuously; this renders the slice that
    matters. If ``capture_start_s`` is not given it is placed ``pre_roll_s``
    before the first arrival, so the buffer contains a genuine noise-only
    region for the detector's floor estimate -- which is what the FPGA's
    circular pre-trigger buffer provides in hardware.

    Delays are computed per microphone from the true 3-D geometry, so the
    wavefront is spherical. Fractional-sample delays are applied in the
    frequency domain, which is what makes sub-degree bearings recoverable at
    all -- rounding to the nearest sample would cap accuracy at ~1.4 deg.
    """
    rng = rng or np.random.default_rng(0)
    c = speed_of_sound(temp_c)
    n_samples = int(duration_s * fs)

    source = np.array([shot.enu[0], shot.enu[1], shot.height_m])
    mics = node.mic_positions_enu()
    distances = np.linalg.norm(mics - source, axis=1)
    arrival_times = shot.t_shot_s + distances / c

    if capture_start_s is None:
        capture_start_s = float(arrival_times.min()) - pre_roll_s
    arrival_times = arrival_times - capture_start_s

    pulse = friedlander(fs, rng=rng)
    audio = np.zeros((node.geometry.n_mics, n_samples))

    reference = float(distances.mean())
    # Peak SPL at the array, spherical spreading from a 1 m reference.
    peak_spl = shot.source_spl_db - 20 * math.log10(max(reference, 1.0))

    for i, (distance, t_arrival) in enumerate(zip(distances, arrival_times)):
        shaped = _atmospheric_lowpass(pulse, fs, distance)
        amplitude = 1.0 / max(distance, 1.0)
        audio[i] = _place(shaped * amplitude, t_arrival, n_samples, fs)

        if reflection is not None:
            # A specular return: extra path length, attenuation, and a
            # completely different arrival bearing.
            image = np.array([reflection["enu"][0], reflection["enu"][1], shot.height_m])
            image_distance = float(np.linalg.norm(mics[i] - image))
            extra = (image_distance - distance) / c
            audio[i] += _place(
                _atmospheric_lowpass(pulse, fs, image_distance)
                * reflection.get("coefficient", 0.7) / max(image_distance, 1.0),
                t_arrival + max(extra, 0.0),
                n_samples,
                fs,
            )

    signal_rms = float(np.sqrt(np.mean(np.square(audio[audio != 0]))) if np.any(audio) else 1e-9)
    noise_rms = signal_rms / (10 ** (snr_db / 20))
    # Pink-ish background: real ambient noise is not white and white noise
    # flatters GCC-PHAT, which whitens by design.
    noise = rng.standard_normal(audio.shape)
    sos = signal.butter(1, 500 / (fs / 2), btype="low", output="sos")
    noise = 0.6 * signal.sosfilt(sos, noise, axis=-1) + 0.4 * noise
    noise *= noise_rms / (np.sqrt(np.mean(np.square(noise))) + 1e-12)

    return audio + noise, float(capture_start_s), peak_spl


def _place(pulse: np.ndarray, t_s: float, n_samples: int, fs: float) -> np.ndarray:
    """Insert ``pulse`` at time ``t_s`` with sub-sample (fractional) precision."""
    out = np.zeros(n_samples)
    n0 = int(math.floor(t_s * fs))
    frac = t_s * fs - n0
    if n0 >= n_samples or n0 + len(pulse) <= 0:
        return out

    # Fractional delay via linear-phase shift in the frequency domain.
    nfft = 1 << int(math.ceil(math.log2(len(pulse) * 2)))
    spectrum = np.fft.rfft(pulse, nfft)
    freqs = np.fft.rfftfreq(nfft)
    shifted = np.fft.irfft(spectrum * np.exp(-2j * np.pi * freqs * frac), nfft)[: len(pulse)]

    lo, hi = max(0, n0), min(n_samples, n0 + len(pulse))
    out[lo:hi] = shifted[lo - n0: hi - n0]
    return out


def default_squad(spacing_m: float = 220.0) -> list[SimNode]:
    """Three nodes on a shallow arc -- a realistic dismounted-patrol layout.

    Deliberately NOT an equilateral triangle. Real squads string out along an
    axis of advance, which produces poor crossing angles for anything directly
    ahead. If the demo used a perfect triangle it would flatter the geometry
    and hide the profile's actual weakness.
    """
    return [
        SimNode(node_id=1, enu=np.array([-spacing_m, 0.0]), heading_deg=0.0),
        SimNode(node_id=2, enu=np.array([0.0, 40.0]), heading_deg=0.0),
        SimNode(node_id=3, enu=np.array([spacing_m, 0.0]), heading_deg=0.0),
    ]
