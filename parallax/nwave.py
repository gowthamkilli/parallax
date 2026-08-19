"""N-wave (ballistic crack) synthesis and measurement.

The supersonic bullet's shockwave arrives at the sensor as an "N-wave": a sharp
positive overpressure spike, a near-linear ramp down through zero, and a
negative-pressure tail that steps back to ambient -- the shape of the letter N.
Its total duration T is the observable that Whitham's relation turns into miss
distance (see parallax.ballistics).

This module does two jobs:
  * synth  -- generate an ideal N-wave, and a single-channel crack+thump capture,
              for the simulator and the tests.
  * measure -- recover the two arrival times (crack, then thump) and the N-wave
              duration T from a captured channel. This is the "what the FPGA
              front end extracts" step, kept deliberately simple: energy-onset
              picking with a refractory gap, which is all the crack-thump method
              needs and all that fits in fabric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal


# --------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------
def synth_nwave(fs: float, duration_T_s: float, amplitude: float = 1.0) -> np.ndarray:
    """Ideal N-wave of total duration ``duration_T_s``.

    N(t) = A(1 - 2t/T) on [0, T]: starts at +A, linear through zero at T/2,
    reaches -A at T. The discontinuity back to ambient is the classic N shape.
    """
    n = max(int(duration_T_s * fs), 2)
    t = np.arange(n) / fs
    return amplitude * (1.0 - 2.0 * t / duration_T_s)


def _friedlander(fs: float, tau_s: float = 0.0011, duration_s: float = 0.03) -> np.ndarray:
    """Muzzle-blast (thump) pulse. Same analytic form the scenario uses."""
    n = max(int(duration_s * fs), 2)
    t = np.arange(n) / fs
    p = (1.0 - t / tau_s) * np.exp(-t / tau_s)
    return p / (np.max(np.abs(p)) + 1e-12)


def synth_crack_thump_channel(fs: float, t_crack_s: float, t_blast_s: float,
                              nwave_T_s: float, crack_amp: float = 1.0,
                              thump_amp: float = 0.9, snr_db: float = 30.0,
                              pad_s: float = 0.05, rng=None) -> np.ndarray:
    """One microphone channel containing a crack then a thump, plus noise.

    Times are relative to the start of the returned buffer after ``pad_s`` of
    lead-in noise, so an onset detector has a genuine noise-only region for its
    floor estimate -- exactly what the FPGA pre-trigger buffer provides.
    """
    rng = rng or np.random.default_rng(0)
    total = t_blast_s + pad_s * 2 + 0.05
    n = int(total * fs)
    x = np.zeros(n)

    def place(pulse, t_s, amp):
        i0 = int((t_s + pad_s) * fs)
        i1 = min(n, i0 + len(pulse))
        if 0 <= i0 < n:
            x[i0:i1] += amp * pulse[: i1 - i0]

    place(synth_nwave(fs, nwave_T_s), t_crack_s, crack_amp)
    place(_friedlander(fs), t_blast_s, thump_amp)

    sig_rms = float(np.sqrt(np.mean(np.square(x[x != 0])))) if np.any(x) else 1.0
    noise = rng.standard_normal(n) * sig_rms / (10 ** (snr_db / 20))
    return x + noise


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------
@dataclass
class CrackThumpMeasurement:
    t_crack_s: float | None
    t_blast_s: float | None
    dt_s: float | None
    nwave_duration_s: float | None
    has_crack: bool


def _envelope(x: np.ndarray, fs: float) -> np.ndarray:
    env = np.abs(signal.hilbert(x))
    win = max(5, int(fs * 0.0003) | 1)
    return signal.savgol_filter(env, win, 2)


def measure_crack_thump(x: np.ndarray, fs: float, noise_window_s: float = 0.04,
                        threshold_sigma: float = 6.0,
                        refractory_s: float = 0.003) -> CrackThumpMeasurement:
    """Recover (t_crack, t_blast, dt, T) from a single captured channel.

    Two impulsive onsets separated by more than ``refractory_s`` are read as
    crack (first) then thump (second). One onset -> no separable crack, so the
    node will fall back to bearing-only ranging. The N-wave duration T is the
    width of the first transient's envelope above 20% of its own peak.
    """
    env = _envelope(x, fs)
    n_noise = max(int(noise_window_s * fs), 64)
    if len(env) <= n_noise:
        return CrackThumpMeasurement(None, None, None, None, False)

    floor = float(np.sqrt(np.mean(np.square(env[:n_noise])))) + 1e-12
    thr = threshold_sigma * floor
    above = env > thr
    if not np.any(above):
        return CrackThumpMeasurement(None, None, None, None, False)

    # Onset = rising edge of a run above threshold, with a refractory gap so a
    # single transient's ringing is not counted as multiple events.
    onsets = []
    gap = int(refractory_s * fs)
    i = 0
    n = len(env)
    while i < n:
        if above[i]:
            onsets.append(i)
            j = i
            while j < n and (above[j] or (j - i) < gap):
                j += 1
                if j < n and above[j]:
                    i = j
            i = max(i + gap, j)
        else:
            i += 1

    if not onsets:
        return CrackThumpMeasurement(None, None, None, None, False)

    if len(onsets) == 1:
        # Single arrival: cannot separate a crack. Bearing-only downstream.
        return CrackThumpMeasurement(
            t_crack_s=None, t_blast_s=onsets[0] / fs, dt_s=None,
            nwave_duration_s=None, has_crack=False,
        )

    t_crack = onsets[0] / fs
    t_blast = onsets[1] / fs
    dt = t_blast - t_crack

    # N-wave duration: measured on the RAW signal, not the smoothed envelope.
    # The N-wave is only ~200-500 us wide -- a dozen-odd samples at 48 kHz -- so
    # the envelope's savgol smoothing (a comparable width) would blur it and
    # overstate T. Take the raw bipolar pulse in a tight window after the crack
    # onset and measure the span above 25% of its peak magnitude.
    win = int(0.0015 * fs)                       # 1.5 ms is ample for small arms
    seg_end = min(onsets[0] + win, onsets[1], len(x))
    seg = np.abs(x[onsets[0]:seg_end])
    if len(seg) < 3:
        T = None
    else:
        peak = float(seg.max())
        mask = np.nonzero(seg > 0.25 * peak)[0]
        T = float((mask[-1] - mask[0]) / fs) if len(mask) > 1 else None

    return CrackThumpMeasurement(t_crack, t_blast, dt, T, dt > 0 and T is not None)
