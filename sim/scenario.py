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

* Ballistic shockwave (the "crack"), when ``Shot.trajectory_bearing_deg`` is
  set: a Mach-cone tangency solution gives each mic its own shockwave arrival
  time and emission-point distance, ahead of the muzzle blast. Only rendered
  for mics within the Mach cone (angular offset from the line of fire <=
  theta_m = asin(1/M)); mics outside it get no shockwave pulse at all, which
  is physically correct. The waveform itself reuses the Friedlander helper
  with a much shorter tau as a stand-in for a proper N-wave -- an ESTIMATE,
  not a claim about the true shockwave shape.

What is NOT modelled
--------------------
* Bullet deceleration (constant speed assumed) and per-weapon-class muzzle
  velocities.
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
    # Ballistic shockwave. None = not modelled (backward compatible default);
    # set both to render a second, earlier transient per mic.
    trajectory_bearing_deg: float | None = None  # compass bearing of bullet travel
    bullet_speed_mps: float = 880.0  # ESTIMATE: typical 5.56mm muzzle velocity, no drag


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

    source = np.array([shot.enu[0], shot.enu[1], shot.height_m])
    mics = node.mic_positions_enu()
    delta = mics - source
    distances = np.linalg.norm(delta, axis=1)
    arrival_times_abs = shot.t_shot_s + distances / c

    # -- ballistic shockwave, per mic (Mach-cone tangency solution) --------
    # See docs/02-fusion-logic.md and parallax/fusion.py's
    # _range_from_shockwave_blast docstring for the derivation. Only mics
    # within the Mach cone (angular offset from the line of fire <= theta_m)
    # get a shockwave pulse at all -- the rest hear only the blast.
    shock_times_abs = None
    shock_emission_dist = None
    if shot.trajectory_bearing_deg is not None and shot.bullet_speed_mps > c:
        theta = math.radians(shot.trajectory_bearing_deg)
        traj_dir = np.array([math.sin(theta), math.cos(theta), 0.0])
        mach = shot.bullet_speed_mps / c
        theta_m = math.asin(1.0 / mach)

        along = delta @ traj_dir
        cross_vec = delta - np.outer(along, traj_dir)
        cross_dist = np.linalg.norm(cross_vec, axis=1)
        alpha = np.arctan2(cross_dist, along)
        valid = alpha <= theta_m

        x_prime = along - cross_dist * math.sqrt(mach * mach - 1.0)
        emission_dist = cross_dist * mach
        t_shock = shot.t_shot_s + x_prime / shot.bullet_speed_mps + emission_dist / c
        shock_times_abs = np.where(valid, t_shock, np.nan)
        shock_emission_dist = np.where(valid, emission_dist, np.nan)

    if capture_start_s is None:
        earliest = float(arrival_times_abs.min())
        if shock_times_abs is not None and np.any(~np.isnan(shock_times_abs)):
            earliest = min(earliest, float(np.nanmin(shock_times_abs)))
        capture_start_s = earliest - pre_roll_s

    # A real node's buffer is sized generously in hardware; the simulator
    # must not silently truncate a real detection to save memory. The
    # shockwave-to-blast gap can be a large fraction of a second at
    # realistic ranges (it is NOT small like the flash/acoustic gap it
    # otherwise resembles), so a fixed duration_s sized for a single pulse
    # can clip the blast out of the buffer entirely once a shockwave is
    # also being rendered -- extend past the caller's requested duration_s
    # rather than let that happen.
    latest = float(arrival_times_abs.max())
    required_s = (latest - capture_start_s) + 0.05
    n_samples = max(int(duration_s * fs), int(math.ceil(required_s * fs)))

    arrival_times = arrival_times_abs - capture_start_s
    shock_times = shock_times_abs - capture_start_s if shock_times_abs is not None else None

    pulse = friedlander(fs, rng=rng)
    # Shorter, higher-frequency stand-in for a true N-wave shockwave -- an
    # ESTIMATE, not a claim about the exact shockwave shape (see module
    # docstring).
    shock_pulse = friedlander(fs, duration_s=0.01, tau_s=0.00015, rng=rng) \
        if shock_times_abs is not None else None
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

        if shock_pulse is not None and not math.isnan(shock_emission_dist[i]):
            s_distance = float(shock_emission_dist[i])
            s_shaped = _atmospheric_lowpass(shock_pulse, fs, s_distance)
            s_amplitude = 1.0 / max(s_distance, 1.0)
            audio[i] += _place(s_shaped * s_amplitude, float(shock_times[i]), n_samples, fs)

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
