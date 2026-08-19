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
    # -- N-wave shape, measured at the pulse's OWN timescale ----------------
    # These three exist to separate a ballistic shockwave from a firecracker,
    # which the features above do not do well: both are short, impulsive and
    # high-frequency. The physical difference is shape. A shockwave is an
    # N-wave -- a positive spike, a near-LINEAR ramp down through zero, and a
    # negative lobe of comparable magnitude. A blast or firecracker is a
    # Friedlander-ish pulse: a positive spike with EXPONENTIAL decay and a
    # shallow negative phase. Crucially these are measured over the ~100-600 us
    # the pulse actually occupies, not over the 20 ms window `decay_linearity`
    # uses, which is ~40x too long to see the shape at all.
    "nwave_symmetry",  # |negative lobe| / positive lobe; ~1 for an N-wave
    "nwave_ramp_linearity",  # R^2 of a straight-line fit peak -> trough
    "nwave_bipolar_ms",  # positive-peak to negative-trough time
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

    symmetry, ramp_linearity, bipolar_ms = _nwave_shape(xn, fs)

    return np.array([
        rise_time, decay_time, duration, crest, kurtosis, skewness, zcr,
        centroid, spread, rolloff, flatness, spectral_slope,
        band_lo, band_mid, band_hi, band_vhi,
        onset_slope, decay_linearity, n_secondary, secondary_ratio,
        temporal_centroid, entropy, harmonicity, modulation,
        symmetry, ramp_linearity, bipolar_ms,
    ], dtype=float)


def _nwave_shape(xn: np.ndarray, fs: float,
                 max_bipolar_s: float = 0.0015) -> tuple[float, float, float]:
    """Measure the N-wave signature on the RAW pulse, at its own timescale.

    Locates the largest positive excursion and the deepest negative trough that
    follows it within ``max_bipolar_s`` (1.5 ms covers small-arms N-waves with
    margin), then reports:

        symmetry        |trough| / peak      -- ~1 for an N-wave, << 1 for a
                                                blast's shallow negative phase
        ramp_linearity  R^2 of a straight line fitted peak -> trough. An
                        N-wave's ramp is near-linear (R^2 -> 1); an exponential
                        decay fits a straight line poorly.
        bipolar_ms      peak-to-trough time, i.e. roughly half the N-wave
                        duration T. Directly related to the Whitham observable.

    Returns zeros when no usable bipolar structure exists (tonal or noise-like
    inputs), which is itself informative -- a drone has no N-wave.
    """
    peak_idx = int(np.argmax(xn))
    if xn[peak_idx] <= 1e-9:
        return 0.0, 0.0, 0.0

    span = max(int(max_bipolar_s * fs), 4)
    tail = xn[peak_idx:peak_idx + span]
    if len(tail) < 4:
        return 0.0, 0.0, 0.0

    trough_rel = int(np.argmin(tail))
    if trough_rel < 2:
        return 0.0, 0.0, 0.0

    peak_val = float(xn[peak_idx])
    trough_val = float(tail[trough_rel])
    if trough_val >= 0.0:
        # No negative lobe at all: not an N-wave.
        return 0.0, 0.0, float(trough_rel * 1000.0 / fs)

    symmetry = float(np.clip(abs(trough_val) / (peak_val + 1e-12), 0.0, 4.0))

    ramp = tail[: trough_rel + 1]
    t = np.arange(len(ramp))
    slope, intercept = np.polyfit(t, ramp, 1)
    pred = slope * t + intercept
    ss_res = float(np.sum((ramp - pred) ** 2))
    ss_tot = float(np.sum((ramp - ramp.mean()) ** 2)) + 1e-12
    ramp_linearity = float(np.clip(1.0 - ss_res / ss_tot, 0.0, 1.0))

    return symmetry, ramp_linearity, float(trough_rel * 1000.0 / fs)
