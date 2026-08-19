"""Train the BINARY gunshot / not-gunshot detector.

    python -m sim.train_gunshot_detector

WHY A SEPARATE BINARY MODEL
---------------------------
The 5-class TransientClassifier answers "what kind of event is this?". The
operational question in front of the ranging pipeline is narrower and harsher:
"do I spend a range solve on this, and do I put a marker on the commander's
map?". That is a binary decision with ASYMMETRIC costs:

    false negative -> a real shot is dropped. Nobody is warned.
    false positive -> the map lights up on a door slam. Cry wolf twice and the
                      display gets ignored, which is the same as switching it
                      off.

A binary model lets us report and tune the two error rates directly, and lets
us set an explicit decision threshold rather than accepting whatever argmax
falls out of a five-way softmax. It also lets NUISANCE (firecracker, door slam)
carry its proper weight: those are the hard negatives, and in the 5-class
framing their cost is diluted across four other labels.

WHAT THE MODEL IS
-----------------
Same 24 physical features, same gradient-boosted trees, same isotonic
calibration as the multiclass model (see parallax/classifier.py for why trees
and not a CNN in this data regime). The difference is the label map:

    GUNSHOT                                   -> 1
    VEHICLE, DRONE, PERSONNEL, NUISANCE       -> 0

READ THIS BEFORE QUOTING ANY NUMBER
-----------------------------------
The corpus is SYNTHETIC -- parametric signal models, augmented with noise and
reverberation. Cross-validated scores measure whether the feature set separates
the MODELS. They are not a claim about field detection accuracy. See
docs/03-ml-classifier.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from parallax.contact import ThreatClass
from parallax.detector import GunshotDetector
from sim.train_classifier import build_corpus


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n-per-class", type=int, default=240)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("out/gunshot_detector.pkl"))
    parser.add_argument("--metrics", type=Path, default=Path("out/gunshot_detector_metrics.json"))
    args = parser.parse_args()

    print(f"Building SYNTHETIC corpus: {args.n_per_class} per class x 5 classes")
    X, y_multi = build_corpus(args.n_per_class, args.seed)
    y = (y_multi == int(ThreatClass.GUNSHOT)).astype(int)
    print(f"  feature matrix {X.shape}   positives {int(y.sum())} / {len(y)}")

    detector = GunshotDetector(seed=args.seed)
    metrics = detector.fit(X, y)
    detector.save(args.out)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    cm = metrics["confusion_matrix"]  # [[TN, FP], [FN, TP]]
    print("\n5-fold cross-validated confusion matrix (SYNTHETIC DATA):")
    print("                 pred NOT   pred GUNSHOT")
    print(f"  true NOT       {cm[0][0]:>9d}  {cm[0][1]:>13d}")
    print(f"  true GUNSHOT   {cm[1][0]:>9d}  {cm[1][1]:>13d}")

    print("\nOperational rates (SYNTHETIC DATA -- not a field figure):")
    print(f"  detection rate (recall) : {metrics['recall']:.4f}")
    print(f"  precision               : {metrics['precision']:.4f}")
    print(f"  false positive rate     : {metrics['false_positive_rate']:.4f}")
    print(f"  false negative rate     : {metrics['false_negative_rate']:.4f}")
    print(f"  ROC AUC                 : {metrics['roc_auc']:.4f}")
    print(f"  decision threshold      : {metrics['threshold']:.2f}")

    print("\nThreshold sweep (how the two error rates trade off):")
    print("  thresh    recall     FPR   precision")
    for row in metrics["threshold_sweep"]:
        print(f"    {row['threshold']:.2f}   {row['recall']:.4f}  {row['fpr']:.4f}   "
              f"{row['precision']:.4f}")

    print("\n" + detector.importance_report())
    print(f"\nsaved model   -> {args.out}")
    print(f"saved metrics -> {args.metrics}")
    print("\nREMINDER: synthetic separability, NOT field detection accuracy.")


if __name__ == "__main__":
    main()
