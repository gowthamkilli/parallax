"""Simulated edge node: what actually runs on the FPGA + MCU.

The split, and why it falls where it does:

  FPGA FABRIC (streaming, hard real time, no OS)
    - 6-channel I2S/TDM ADC capture at 48 kHz
    - DC block + the problem-statement ~200 Hz-3 kHz bandpass (DoA branch)
    - Rolling energy detector: onset when |x| > N sigma of a tracked floor
    - Circular pre-trigger buffer (200 ms) so the transient's leading edge is
      captured, not clipped -- the onset is the most informative part and a
      post-trigger-only capture throws it away
    - 15 parallel GCC-PHAT correlators (one per microphone pair)
  Everything above is fixed-point, deterministic, and sized by the pair count.
  It is on the FPGA because it must never miss a sample.

  MCU / SOFT CORE (event rate, ~1 Hz worst case, floating point acceptable)
    - Plane-wave least-squares solve for the bearing (a 15x3 lstsq)
    - Full-band feature extraction (24 features)
    - Gradient-boosted-tree inference
    - Optical channel timestamping and fusion of the local flash/acoustic pair
    - Contact report assembly, CRC, mesh transmit
  It is on the MCU because it runs once per event, not once per sample, and
  because retraining a classifier should never mean re-synthesising a bitstream.

That boundary -- per-sample work in fabric, per-event work in software -- is
the entire architectural argument, and it is what makes the classifier
field-updatable over the air.
"""

from __future__ import annotations

import math

import numpy as np

from parallax.contact import (
    ContactReport,
    Modality,
    ThreatClass,
    FLAG_ELEVATION_VALID,
    FLAG_GPS_LOCKED,
    FLAG_MULTIPATH_SUSPECT,
)
from parallax.doa import estimate_doa
from parallax.features import bandpass, detect_onsets

PRE_TRIGGER_S = 0.003
# GCC-PHAT correlates over the WHOLE window with equal per-bin weight (that
# is the point of the PHAT whitening). If the window is much longer than the
# transient itself, the noise-only samples contribute cross-correlation
# variance on equal footing with the signal, and at realistic SNR the true
# peak drowns. A muzzle blast's usable energy is over inside ~15-20 ms
# (tau ~1-2 ms, decays negligible after ~15 tau); 25 ms leaves margin for
# reflections without diluting the correlation with hundreds of ms of noise.
WINDOW_S = 0.025


class EdgeNode:
    def __init__(self, sim_node, frame, classifier=None, profile=None, seq0: int = 0):
        self.node = sim_node
        self.frame = frame
        self.classifier = classifier
        self.profile = profile
        self.seq = seq0
        lat, lon = frame.to_geodetic(sim_node.enu[0], sim_node.enu[1])
        self.lat, self.lon = lat, lon

    # -- FPGA: detect ------------------------------------------------------
    def detect(self, audio: np.ndarray, fs: float) -> list[int]:
        threshold = self.profile.detector_threshold_sigma if self.profile else 6.0
        # Detector runs on the bandpassed reference channel, per the PS.
        # Up to two onsets: a ballistic shockwave (if present) arrives ahead
        # of the muzzle blast as a distinct transient.
        reference = bandpass(audio[0], fs)
        return detect_onsets(reference, fs, threshold_sigma=threshold)

    # -- FPGA + MCU: bearing ----------------------------------------------
    def bearing(self, audio: np.ndarray, fs: float, onset: int):
        # Filter the FULL buffer first, THEN window -- not the other way
        # round. sosfiltfilt needs settling context on both sides; filtering
        # an already-short window makes the pad-edge transient fall at the
        # exact same sample offset on every channel (the window bounds are
        # shared across mics), and after PHAT whitening that shared artifact
        # becomes a spurious, highly coherent zero-lag correlation peak that
        # can outweigh the true, genuinely time-shifted arrival. Filtering
        # in fabric operates on the continuous stream for exactly this
        # reason; the simulator has to match that or it measures its own
        # windowing artifact instead of the acoustics.
        filtered_full = bandpass(audio, fs)  # DoA branch only
        lo = max(0, onset - int(PRE_TRIGGER_S * fs))
        hi = min(audio.shape[1], lo + int(WINDOW_S * fs))
        filtered = filtered_full[:, lo:hi]
        window = audio[:, lo:hi]
        return estimate_doa(filtered, self.node.geometry, fs), window

    # -- MCU: classify -----------------------------------------------------
    def classify(self, window: np.ndarray, fs: float):
        if self.classifier is None:
            return ThreatClass.GUNSHOT, 0.75
        # Full band, deliberately -- see features.py.
        prediction = self.classifier.predict_audio(window[0], fs)
        return prediction.threat_class, prediction.confidence

    # -- MCU: emit ---------------------------------------------------------
    def make_acoustic_report(self, audio, fs, t_capture_start_s, peak_spl_db,
                             snr_db, t0_ns: int) -> list[ContactReport]:
        """One report per detected onset (0, 1, or 2 -- see detect_onsets).

        When exactly two onsets fire, the earlier one is the ballistic
        shockwave and the later is the muzzle blast: the shockwave always
        outruns the blast to a given point (it travels supersonic for part
        of its path), so onset order is a reliable modality label, not a
        guess. A single onset is treated as the blast, exactly as before --
        this preserves the existing single-transient behaviour unchanged.
        """
        onsets = self.detect(audio, fs)
        inflation = self.profile.bearing_sigma_inflation if self.profile else 1.0
        reports: list[ContactReport] = []

        for idx, onset in enumerate(onsets):
            try:
                doa, window = self.bearing(audio, fs, onset)
            except (ValueError, np.linalg.LinAlgError):
                # A degenerate DoA solve (near-zero solution norm, typically
                # at very low SNR) is a "no usable bearing" outcome, exactly
                # like a missed detector trigger -- not a crash. The energy
                # detector can fire on a transient too weak for GCC-PHAT to
                # resolve a coherent wavefront from; skip this onset, not
                # the whole node.
                continue

            is_shockwave = idx == 0 and len(onsets) == 2
            if is_shockwave:
                # Not run through the trained classifier: it is tuned on
                # blast-shaped transients, not N-waves, and would likely
                # emit a meaningless label. A supersonic shockwave preceding
                # a blast is itself an unambiguous gunshot signature in this
                # simulator, so hardcode it -- same treatment as the optical
                # report's threat_class.
                modality = Modality.ACOUSTIC_SHOCKWAVE
                threat, confidence = ThreatClass.GUNSHOT, 0.70
            else:
                modality = Modality.ACOUSTIC
                threat, confidence = self.classify(window, fs)

            sigma = doa.azimuth_sigma_deg * inflation
            flags = FLAG_GPS_LOCKED
            if doa.elevation_valid:
                flags |= FLAG_ELEVATION_VALID
            if doa.multipath_suspect:
                flags |= FLAG_MULTIPATH_SUSPECT

            # Bearing is body-frame; rotate into true north by node heading.
            azimuth = (doa.azimuth_deg + self.node.heading_deg) % 360.0

            self.seq += 1
            t_event_ns = int(t0_ns + (t_capture_start_s + onset / fs) * 1e9)
            reports.append(ContactReport(
                node_id=self.node.node_id,
                seq=self.seq,
                t_event_ns=t_event_ns,
                modality=modality,
                threat_class=threat,
                class_confidence=confidence,
                azimuth_deg=azimuth,
                azimuth_sigma_deg=sigma,
                elevation_deg=doa.elevation_deg,
                elevation_sigma_deg=sigma * 1.5 if doa.elevation_valid else 0.0,
                range_m=0.0,  # neither acoustic transient alone carries range
                range_sigma_m=0.0,
                peak_spl_db=peak_spl_db,
                snr_db=snr_db,
                node_lat=self.lat,
                node_lon=self.lon,
                node_alt_m=self.node.alt_m,
                node_heading_deg=self.node.heading_deg,
                flags=flags,
            ))
        return reports

    def make_optical_report(self, true_bearing_deg: float, t_shot_ns: int,
                            sigma_deg: float = 0.6, confidence: float = 0.82,
                            rng=None) -> ContactReport:
        """Optical/IR muzzle-flash detection.

        Modelled, not measured. Justification for the parameters used:
          sigma 0.6 deg  -- an optical bearing is set by pixel pitch and
                            focal length, not by wavelength-scale timing. A
                            modest 640x512 LWIR core over a 40 deg field is
                            0.06 deg/pixel, so 0.6 deg is ~10 pixels of
                            centroiding slop. Conservative. (ESTIMATE.)
          latency 0      -- light crosses 400 m in 1.3 ns. Sensor readout
                            latency (order 1 ms) is modelled as jitter below,
                            not as propagation.
        Detection is NOT assumed: bright daylight, foliage, defilade and a
        muzzle pointed away all suppress the flash. The scenario decides
        whether an optical report exists at all.
        """
        rng = rng or np.random.default_rng(0)
        self.seq += 1
        jitter_ns = int(rng.normal(0, 1e6))  # ~1 ms readout jitter
        return ContactReport(
            node_id=self.node.node_id,
            seq=self.seq,
            t_event_ns=int(t_shot_ns + jitter_ns),
            modality=Modality.OPTICAL_IR,
            threat_class=ThreatClass.GUNSHOT,
            class_confidence=confidence,
            azimuth_deg=(true_bearing_deg + rng.normal(0, sigma_deg)) % 360.0,
            azimuth_sigma_deg=sigma_deg,
            elevation_deg=0.0,
            elevation_sigma_deg=sigma_deg,
            range_m=0.0,
            range_sigma_m=0.0,
            snr_db=20.0,
            node_lat=self.lat,
            node_lon=self.lon,
            node_alt_m=self.node.alt_m,
            node_heading_deg=self.node.heading_deg,
            flags=FLAG_GPS_LOCKED | FLAG_ELEVATION_VALID,
        )
