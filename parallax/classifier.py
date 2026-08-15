"""Transient classifier: gradient-boosted trees over physical features.

WHAT IS CLASSIFIED
    A detected transient window -> one of
    {GUNSHOT, VEHICLE, DRONE, PERSONNEL, NUISANCE}
    with a calibrated probability. NUISANCE is a first-class label, not a
    reject bin: firecrackers, door slams, hammer strikes and thunder are the
    events that actually generate false alarms, so the model is trained to
    name them rather than to score them as "not gunshot".

WHAT IT DOES NOT DO
    It does not identify weapon type or calibre. That claim needs calibrated
    free-field recordings of known weapons at known ranges, which no public
    dataset provides. See docs/03-ml-classifier.md.

MODEL CHOICE
    HistGradientBoostingClassifier, ~24 features, depth-limited. Beats a CNN
    in the low-data regime we are actually in, trains in seconds on a laptop,
    and is directly inspectable -- permutation importance tells a judge which
    physical property drove a decision. If the corpus ever reaches tens of
    thousands of in-domain clips, revisit; until then this is the right call.

CALIBRATION
    Raw tree ensembles are overconfident. We wrap in isotonic calibration so
    that the confidence number the fusion layer consumes actually means
    something. An uncalibrated 0.95 that is right 70% of the time poisons
    every downstream fusion weight.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .contact import ThreatClass
from .features import FEATURE_NAMES, extract

CLASS_ORDER = [
    ThreatClass.GUNSHOT,
    ThreatClass.VEHICLE,
    ThreatClass.DRONE,
    ThreatClass.PERSONNEL,
    ThreatClass.NUISANCE,
]


@dataclass
class Prediction:
    threat_class: ThreatClass
    confidence: float
    probabilities: dict


class TransientClassifier:
    def __init__(self, seed: int = 0):
        self.seed = seed
        self._model = None
        self._importances: dict | None = None

    # -- training ---------------------------------------------------------
    def fit(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Train with isotonic calibration and stratified cross-validation.

        Returns a metrics dict. We report per-class recall and the confusion
        matrix, NOT a single accuracy figure -- accuracy on an imbalanced
        five-class problem is a number that flatters and informs nobody.
        """
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
        from sklearn.metrics import confusion_matrix, classification_report
        from sklearn.inspection import permutation_importance

        base = HistGradientBoostingClassifier(
            max_depth=4, max_iter=200, learning_rate=0.08,
            l2_regularization=1.0, random_state=self.seed,
        )
        self._model = CalibratedClassifierCV(base, method="isotonic", cv=3)

        folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=self.seed)
        y_pred = cross_val_predict(self._model, X, y, cv=folds)
        labels = [int(c) for c in CLASS_ORDER]
        names = [c.name for c in CLASS_ORDER]

        self._model.fit(X, y)

        importance = permutation_importance(
            self._model, X, y, n_repeats=5, random_state=self.seed
        )
        self._importances = {
            name: float(score)
            for name, score in sorted(
                zip(FEATURE_NAMES, importance.importances_mean),
                key=lambda kv: -kv[1],
            )
        }

        return {
            "confusion_matrix": confusion_matrix(y, y_pred, labels=labels).tolist(),
            "class_order": names,
            "report": classification_report(
                y, y_pred, labels=labels, target_names=names,
                output_dict=True, zero_division=0,
            ),
            "n_train": int(len(y)),
            "top_features": dict(list(self._importances.items())[:8]),
        }

    # -- inference --------------------------------------------------------
    def predict_features(self, feature_vector: np.ndarray) -> Prediction:
        if self._model is None:
            raise RuntimeError("classifier is not trained")
        probabilities = self._model.predict_proba(feature_vector.reshape(1, -1))[0]
        classes = [ThreatClass(int(c)) for c in self._model.classes_]
        best = int(np.argmax(probabilities))
        return Prediction(
            threat_class=classes[best],
            confidence=float(probabilities[best]),
            probabilities={c.name: float(p) for c, p in zip(classes, probabilities)},
        )

    def predict_audio(self, x: np.ndarray, fs: float) -> Prediction:
        return self.predict_features(extract(x, fs))

    # -- persistence ------------------------------------------------------
    def save(self, path: str | Path) -> None:
        import pickle

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump({"model": self._model, "importances": self._importances}, fh)

    @classmethod
    def load(cls, path: str | Path) -> "TransientClassifier":
        import pickle

        obj = cls()
        with open(path, "rb") as fh:
            blob = pickle.load(fh)
        obj._model = blob["model"]
        obj._importances = blob.get("importances")
        return obj

    def importance_report(self) -> str:
        if not self._importances:
            return "(not trained)"
        lines = ["feature                    permutation importance"]
        for name, score in list(self._importances.items())[:10]:
            lines.append(f"  {name:<26s} {score:+.4f}")
        return "\n".join(lines)


def save_metrics(metrics: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
