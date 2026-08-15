"""Train the transient classifier on a SYNTHETIC corpus.

READ THIS BEFORE QUOTING ANY NUMBER THIS SCRIPT PRINTS.

The corpus generated here is synthetic: parametric signal models with
randomised parameters, augmented with noise, reverberation and level scaling.
It is NOT field-recorded audio. Cross-validated scores on synthetic data
measure whether the feature set and model can separate the *models*, and they
say almost nothing about field performance. Reporting them as detection
accuracy would be dishonest, and the README and slide deck both say so.

Why synthesise at all, then? Two reasons that do hold up:
  1. It proves the pipeline is complete and runnable end to end -- features,
     training, calibration, inference, and the contact report that comes out.
  2. It makes the feature set falsifiable. If the physically-motivated
     features could not even separate parametric models of a blast from a
     firecracker, the feature design would be wrong and we would know now.

THE REAL TRAINING PATH (what we would do with a term, not a weekend):
  * UrbanSound8K       -- 374 'gun_shot' clips, urban, uncalibrated
  * ESC-50             -- 40 'gun_shot' clips
  * MIVIA audio events -- scream/gunshot surveillance corpus
  * DEMAND / TUT       -- realistic background for negatives
  * Augmentation       -- convolve with measured room/terrain impulse
                          responses, add background at 0-30 dB SNR, randomise
                          level and band-limiting
  That is a few hundred in-domain positives. It is a small-data problem, and
  that fact is what drives the model choice in classifier.py.

  Known domain gap: most public 'gunshot' clips are film/TV or urban phone
  recordings, heavily compressed, often already reverberant, and recorded at
  unknown range with unknown weapons. A model trained on them learns the
  recording chain as much as the physics. Any field deployment needs a
  calibrated collection at known ranges.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from scipy import signal

from parallax.classifier import TransientClassifier, save_metrics
from parallax.contact import ThreatClass
from parallax.features import extract

FS = 48_000.0
DURATION_S = 0.25


def _noise_bed(n: int, rng: np.random.Generator, colour: float = 0.7) -> np.ndarray:
    white = rng.standard_normal(n)
    sos = signal.butter(1, 300 / (FS / 2), btype="low", output="sos")
    return colour * signal.sosfilt(sos, white) + (1 - colour) * white


def _reverb(x: np.ndarray, rng: np.random.Generator, rt60_s: float) -> np.ndarray:
    """Exponentially decaying sparse impulse response: crude but the right shape."""
    n = int(rt60_s * FS)
    if n < 8:
        return x
    ir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    ir[0] = 1.0
    ir = ir / np.linalg.norm(ir)
    return signal.fftconvolve(x, ir)[: len(x)]


def gunshot(rng):
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    tau = rng.uniform(0.0007, 0.0018)  # calibre / charge dependent
    x = (1 - t / tau) * np.exp(-t / tau)
    sos = signal.butter(2, [rng.uniform(300, 600) / (FS / 2), rng.uniform(1800, 3200) / (FS / 2)],
                        btype="band", output="sos")
    x = x + 0.15 * signal.sosfilt(sos, rng.standard_normal(n)) * np.exp(-t / (4 * tau))
    return _reverb(x, rng, rng.uniform(0.15, 0.9))


def firecracker(rng):
    """The hard negative. Deliberately made HARD, not a strawman.

    A firecracker is also an impulsive blast. It differs by being physically
    smaller: shorter positive-phase duration, energy skewed higher in
    frequency, and no barrel resonance. Sometimes several in a string.
    """
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    x = np.zeros(n)
    for _ in range(rng.integers(1, 4)):
        tau = rng.uniform(0.00025, 0.0008)  # shorter than a muzzle blast
        offset = int(rng.uniform(0, 0.08) * FS)
        pulse = (1 - t / tau) * np.exp(-t / tau) * rng.uniform(0.5, 1.0)
        x[offset:] += pulse[: n - offset]
    sos = signal.butter(2, 900 / (FS / 2), btype="high", output="sos")
    x = 0.65 * x + 0.35 * signal.sosfilt(sos, x)
    return _reverb(x, rng, rng.uniform(0.1, 0.8))


def door_slam(rng):
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    tau = rng.uniform(0.004, 0.015)  # much slower decay, low frequency
    x = np.exp(-t / tau) * np.sin(2 * np.pi * rng.uniform(60, 200) * t)
    x += 0.3 * np.exp(-t / (tau / 3)) * rng.standard_normal(n)
    return _reverb(x, rng, rng.uniform(0.2, 1.0))


def vehicle(rng):
    """Diesel engine: firing-order harmonics on a broadband rumble."""
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    f0 = rng.uniform(18, 60)  # firing rate, Hz
    x = np.zeros(n)
    for h in range(1, 9):
        x += (1.0 / h) * np.sin(2 * np.pi * f0 * h * t + rng.uniform(0, 6.28))
    sos = signal.butter(2, 400 / (FS / 2), btype="low", output="sos")
    x = x / np.max(np.abs(x)) + 0.4 * signal.sosfilt(sos, rng.standard_normal(n))
    x *= 1 + 0.3 * np.sin(2 * np.pi * rng.uniform(2, 8) * t)  # load variation
    return x


def drone(rng):
    """Multirotor: strong blade-pass tone plus harmonics, amplitude modulated."""
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    bpf = rng.uniform(90, 220)
    x = np.zeros(n)
    for h in range(1, 7):
        x += (0.9 ** h) * np.sin(2 * np.pi * bpf * h * t + rng.uniform(0, 6.28))
    x += 0.25 * rng.standard_normal(n) * (1 + 0.5 * np.sin(2 * np.pi * bpf * t))
    return x


def personnel(rng):
    """Footfalls: low-level, irregular, slow-rising, low crest factor."""
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    x = np.zeros(n)
    for _ in range(rng.integers(1, 3)):
        offset = int(rng.uniform(0, 0.15) * FS)
        tau = rng.uniform(0.01, 0.04)
        thud = np.exp(-t / tau) * (0.6 + 0.4 * rng.standard_normal(n))
        sos = signal.butter(2, 350 / (FS / 2), btype="low", output="sos")
        thud = signal.sosfilt(sos, thud) * rng.uniform(0.3, 1.0)
        x[offset:] += thud[: n - offset]
    return _reverb(x, rng, rng.uniform(0.1, 0.5))


GENERATORS = {
    ThreatClass.GUNSHOT: [gunshot],
    ThreatClass.NUISANCE: [firecracker, door_slam],
    ThreatClass.VEHICLE: [vehicle],
    ThreatClass.DRONE: [drone],
    ThreatClass.PERSONNEL: [personnel],
}


def build_corpus(n_per_class: int = 240, seed: int = 7):
    rng = np.random.default_rng(seed)
    X, y = [], []
    for threat, generators in GENERATORS.items():
        for i in range(n_per_class):
            x = generators[i % len(generators)](rng)
            x = x / (np.max(np.abs(x)) + 1e-12)
            # Augmentation: SNR 0-30 dB, and random overall level.
            snr = rng.uniform(0, 30)
            noise = _noise_bed(len(x), rng)
            noise *= (np.sqrt(np.mean(x**2)) / (10 ** (snr / 20))) / (
                np.sqrt(np.mean(noise**2)) + 1e-12
            )
            x = (x + noise) * rng.uniform(0.1, 1.0)
            X.append(extract(x, FS))
            y.append(int(threat))
    return np.asarray(X), np.asarray(y)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-per-class", type=int, default=240)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("out/classifier.pkl"))
    parser.add_argument("--metrics", type=Path, default=Path("out/classifier_metrics.json"))
    args = parser.parse_args()

    print(f"Building SYNTHETIC corpus: {args.n_per_class} per class x {len(GENERATORS)} classes")
    X, y = build_corpus(args.n_per_class, args.seed)
    print(f"  feature matrix {X.shape}")

    clf = TransientClassifier(seed=args.seed)
    metrics = clf.fit(X, y)
    clf.save(args.out)
    save_metrics(metrics, args.metrics)

    names = metrics["class_order"]
    print("\n5-fold cross-validated confusion matrix (SYNTHETIC DATA):")
    print("            " + "".join(f"{n[:7]:>9s}" for n in names))
    for name, row in zip(names, metrics["confusion_matrix"]):
        print(f"  {name:<10s}" + "".join(f"{v:>9d}" for v in row))

    print("\nPer-class recall (SYNTHETIC DATA -- not a field figure):")
    for name in names:
        r = metrics["report"][name]
        print(f"  {name:<12s} recall {r['recall']:.3f}   precision {r['precision']:.3f}")

    print("\n" + clf.importance_report())
    print(f"\nsaved model   -> {args.out}")
    print(f"saved metrics -> {args.metrics}")
    print("\nREMINDER: these scores describe separability of synthetic signal")
    print("models. They are NOT a claim about field detection accuracy.")


if __name__ == "__main__":
    main()
