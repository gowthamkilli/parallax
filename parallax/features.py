"""Feature extraction for transient classification.

Design commitment: hand-crafted physical features, not raw waveform into a
deep network.

The trade is real. A CNN on log-mel spectrograms will beat hand-crafted
features given tens of thousands of labelled, in-domain recordings. We do not
have those and will not have them -- the honest public corpus for gunshots is
a few hundred clips (see docs/03-ml-classifier.md). With a few hundred
examples a 40-dimensional physically-motivated feature vector into gradient-
boosted trees generalises better, trains in seconds, runs in fixed point on an
MCU, and -- decisively for a pitch -- every feature can be named and defended
when a judge asks what the model actually looks at. We commit to that.

Two feature paths, deliberately:

  DoA path       -> bandpassed ~3 kHz, per the problem statement.
  Classify path  -> FULL BAND.

This resolves a genuine tension in the spec. A ~3 kHz bandpass keeps the
energy that matters for time-delay estimation, but it also discards the
high-frequency structure that best separates a muzzle blast from a
firecracker. Filtering before classification would throw away the evidence.
The same ADC stream feeds both; only the DoA branch is filtered.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

FEATURE_NAMES = [
    "rise_time_ms",
    "decay_time_ms",
    "duration_ms",
    "crest_factor_db",
    "kurtosis",
    "skewness",
    "zero_crossing_rate",
    "spectral_centroid_hz",
    "spectral_spread_hz",
    "spectral_rolloff95_hz",
    "spectral_flatness",
    "spectral_slope",
    "band_ratio_lo",  # 20-200 Hz   : blast overpressure tail
    "band_ratio_mid",  # 200-1500 Hz : muzzle blast core
    "band_ratio_hi",  # 1.5-6 kHz   : mechanical action, case ejection
    "band_ratio_vhi",  # 6-20 kHz    : crack / sharp edges, firecracker
    "onset_slope_db_per_ms",
    "decay_linearity",
    "n_secondary_peaks",
    "secondary_peak_ratio",
    "temporal_centroid",
    "energy_entropy",
    "harmonicity",  # separates tonal (drone, engine) from impulsive
    "modulation_20_200hz",  # blade-pass / cylinder-firing periodicity
]


def bandpass(x: np.ndarray, fs: float, low: float = 200.0, high: float = 3000.0,
             order: int = 4) -> np.ndarray:
    """The problem-statement bandpass, applied ONLY to the DoA branch."""
    nyq = fs / 2
    high = min(high, nyq * 0.98)
    sos = signal.butter(order, [low / nyq, high / nyq], btype="band", output="sos")
    return signal.sosfiltfilt(sos, x, axis=-1)


def detect_onset(x: np.ndarray, fs: float, threshold_sigma: float = 6.0,
                 noise_window_s: float = 0.05) -> int | None:
    """Sample index of the first sample exceeding N sigma of the noise floor.

    A plain energy threshold is the right detector here and a fancier one is
    not worth the FPGA fabric: a muzzle blast has a 20-40 dB onset in under a
    millisecond, which no realistic background matches. The classifier's job
    is to reject what the detector lets through, not to be the detector.
    """
    n_noise = max(int(noise_window_s * fs), 64)
    if len(x) <= n_noise:
        return None
    noise_rms = float(np.sqrt(np.mean(np.square(x[:n_noise])))) + 1e-12
    above = np.nonzero(np.abs(x) > threshold_sigma * noise_rms)[0]
    return int(above[0]) if len(above) else None


def detect_onsets(x: np.ndarray, fs: float, threshold_sigma: float = 6.0,
                  noise_window_s: float = 0.05, blanking_s: float = 0.020,
                  max_onsets: int = 2) -> list[int]:
    """Sample indices of up to ``max_onsets`` distinct transients.

    Finds the first threshold crossing exactly as ``detect_onset`` does, then
    re-arms and keeps scanning -- e.g. for a ballistic shockwave arriving
    ahead of its own muzzle blast.

    Re-arming is NOT a fixed time offset from the onset. A real blast pulse
    (and this simulator's added ringing texture -- see friedlander()'s
    `ring` term) does not decay monotonically: at clean SNR it crosses back
    above a 6-sigma threshold intermittently for the pulse's full ~15-20 ms
    settling time (the same duration WINDOW_S in sim/edge_node.py is sized
    around). A bare "wait N ms then re-arm" scheme re-arms straight into the
    middle of that ringing and manufactures a second "transient" out of one
    pulse's own tail -- this was caught empirically, not hypothesised.
    Instead, re-arming requires a full ``blanking_s`` of GENUINELY
    UNINTERRUPTED quiet (hysteresis), so it only fires again once the
    transient has actually finished. 20 ms is an ESTIMATE sized to that
    settling time; a real shockwave-to-blast gap shorter than it (which
    happens only very close to the Mach-cone edge, where the ranging
    validity gate is already marginal -- see fusion.py) will not resolve as
    two onsets. This is a real, tested limitation, not an oversight.
    """
    n_noise = max(int(noise_window_s * fs), 64)
    if len(x) <= n_noise:
        return []
    noise_rms = float(np.sqrt(np.mean(np.square(x[:n_noise])))) + 1e-12
    threshold = threshold_sigma * noise_rms
    blank_n = max(int(blanking_s * fs), 1)
    above = np.abs(x) > threshold
    n = len(x)

    onsets: list[int] = []
    cursor = 0
    while len(onsets) < max_onsets and cursor < n:
        rel = np.nonzero(above[cursor:])[0]
        if len(rel) == 0:
            break
        onset = cursor + int(rel[0])
        onsets.append(onset)

        # Scan forward for the first fully-quiet blank_n-sample window.
        i = onset
        while i < n:
            still_above = np.nonzero(above[i:i + blank_n])[0]
            if len(still_above) == 0:
                break  # blank_n consecutive quiet samples found at i
            i += int(still_above[-1]) + 1
        cursor = i + blank_n if i < n else n
    return onsets


def extract(x: np.ndarray, fs: float) -> np.ndarray:
    """Feature vector for one transient window. Returns len(FEATURE_NAMES) floats."""
    x = np.asarray(x, dtype=float)
    if x.size < 64:
        return np.zeros(len(FEATURE_NAMES))
    x = x - x.mean()
    peak = float(np.max(np.abs(x))) + 1e-12
    xn = x / peak

    envelope = np.abs(signal.hilbert(xn))
    envelope = signal.savgol_filter(envelope, max(5, int(fs * 0.0005) | 1), 2)
    envelope = np.clip(envelope, 1e-9, None)

    peak_idx = int(np.argmax(envelope))
    ms = 1000.0 / fs

    # --- temporal envelope ------------------------------------------------
    pre = envelope[: peak_idx + 1]
    rise_start = np.nonzero(pre < 0.1)[0]
    rise_time = (peak_idx - int(rise_start[-1])) * ms if len(rise_start) else peak_idx * ms

    post = envelope[peak_idx:]
    decay_end = np.nonzero(post < 0.1)[0]
    decay_time = int(decay_end[0]) * ms if len(decay_end) else len(post) * ms

    above = np.nonzero(envelope > 0.1)[0]
    duration = (int(above[-1]) - int(above[0])) * ms if len(above) > 1 else 0.0

    rms = float(np.sqrt(np.mean(np.square(xn)))) + 1e-12
    crest = 20 * np.log10(1.0 / rms)

    centred = xn / (np.std(xn) + 1e-12)
    kurtosis = float(np.mean(centred**4) - 3.0)
    skewness = float(np.mean(centred**3))
    zcr = float(np.mean(np.abs(np.diff(np.sign(xn))) > 0))

    onset_slope = (20 * np.log10(envelope[peak_idx] / envelope[max(0, peak_idx - int(fs * 0.001))])
                   ) / 1.0 if peak_idx > int(fs * 0.001) else 0.0

    log_decay = np.log(post[: max(2, int(fs * 0.02))])
    if len(log_decay) > 3:
        t = np.arange(len(log_decay))
        slope, intercept = np.polyfit(t, log_decay, 1)
        pred = slope * t + intercept
        ss_res = np.sum((log_decay - pred) ** 2)
        ss_tot = np.sum((log_decay - log_decay.mean()) ** 2) + 1e-12
        decay_linearity = float(1 - ss_res / ss_tot)
    else:
        decay_linearity = 0.0

    # Secondary envelope peaks = reflections (or a burst, or a firecracker string).
    peaks, props = signal.find_peaks(envelope, height=0.15, distance=int(fs * 0.003))
    secondary = [h for i, h in zip(peaks, props["peak_heights"]) if i != peak_idx]
    n_secondary = float(len(secondary))
    secondary_ratio = float(max(secondary) if secondary else 0.0)

    t_axis = np.arange(len(envelope))
    temporal_centroid = float(np.sum(t_axis * envelope) / (np.sum(envelope) + 1e-12) / len(envelope))

    # --- spectral ---------------------------------------------------------
    freqs, psd = signal.welch(xn, fs, nperseg=min(1024, len(xn)))
    psd = psd + 1e-20
    total = float(psd.sum())
    centroid = float(np.sum(freqs * psd) / total)
    spread = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * psd) / total))
    cumulative = np.cumsum(psd) / total
    rolloff = float(freqs[int(np.searchsorted(cumulative, 0.95))])
    flatness = float(np.exp(np.mean(np.log(psd))) / np.mean(psd))
    with np.errstate(divide="ignore"):
        log_f = np.log10(freqs + 1.0)
        spectral_slope = float(np.polyfit(log_f, 10 * np.log10(psd), 1)[0])

    def band(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        return float(psd[m].sum() / total)

    nyq = fs / 2
    band_lo = band(20, 200)
    band_mid = band(200, 1500)
    band_hi = band(1500, min(6000, nyq))
    band_vhi = band(min(6000, nyq), nyq)

    p_norm = psd / total
    entropy = float(-np.sum(p_norm * np.log(p_norm)) / np.log(len(p_norm)))

    # Harmonicity: peak of the normalised autocorrelation over 50 Hz - 2 kHz lags.
    # Computed via FFT, not np.correlate -- direct correlation is O(n^2) and on
    # a 12k-sample window it dominates the entire feature extraction cost.
    lo_lag, hi_lag = int(fs / 2000), int(fs / 50)
    if hi_lag < len(xn):
        nfft_ac = 1 << int(np.ceil(np.log2(2 * len(xn))))
        spec = np.fft.rfft(xn, nfft_ac)
        ac = np.fft.irfft(spec * np.conj(spec), nfft_ac)[: hi_lag + 1]
        harmonicity = float(np.max(ac[lo_lag:hi_lag]) / (ac[0] + 1e-12))
    else:
        harmonicity = 0.0

    # Envelope modulation in 20-200 Hz: rotor blade-pass and engine firing rate.
    env_ac_f, env_psd = signal.welch(
        envelope - envelope.mean(), fs, nperseg=min(2048, len(envelope))
    )
    m = (env_ac_f >= 20) & (env_ac_f <= 200)
    modulation = float(env_psd[m].sum() / (env_psd.sum() + 1e-20))

    return np.array([
        rise_time, decay_time, duration, crest, kurtosis, skewness, zcr,
        centroid, spread, rolloff, flatness, spectral_slope,
        band_lo, band_mid, band_hi, band_vhi,
        onset_slope, decay_linearity, n_secondary, secondary_ratio,
        temporal_centroid, entropy, harmonicity, modulation,
    ], dtype=float)
