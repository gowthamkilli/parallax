"""Binary gunshot / not-gunshot detector -- the gate in front of the ranging.

This is the decision that protects the map. Nothing downstream -- no crack-thump
solve, no bearing, no marker on a commander's display -- happens unless this
model says the transient was a gunshot.

MODEL
    Gradient-boosted trees (HistGradientBoostingClassifier) over the same 24
    physical features as the multiclass classifier, wrapped in isotonic
    calibration so the probability means something. See parallax/classifier.py
    for the full argument on why trees rather than a CNN in this data regime.

THRESHOLD
    Argmax (implicitly p >= 0.5) is not the right operating point for an alarm
    that competes for a commander's attention. The threshold is explicit and
    tunable, and the training script prints the recall/false-positive trade at
    several values so the choice is made with the curve in front of you rather
    than by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .features import FEATURE_NAMES, extract

# Default operating point, chosen off the threshold sweep the training script
# prints rather than left at argmax. 0.70 holds the same detection rate as 0.60
# while cutting the false-positive rate, so it is free accuracy. The asymmetry
# behind preferring the lower FPR: a shot missed by one node is usually caught
# by another, whereas a false marker is seen by every team at once.
DEFAULT_THRESHOLD = 0.70


@dataclass
class Detection:
    is_gunshot: bool
    probability: float
    threshold: float

    def to_dict(self) -> dict:
        return {
            "is_gunshot": bool(self.is_gunshot),
            "probability": round(float(self.probability), 4),
            "threshold": round(float(self.threshold), 2),
        }


class GunshotDetector:
    def __init__(self, seed: int = 0, threshold: float = DEFAULT_THRESHOLD):
        self.seed = seed
        self.threshold = threshold
        self._model = None
        self._importances: dict | None = None

    # -- training ---------------------------------------------------------
    def fit(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Train on binary labels (1 = gunshot). Returns an operational metrics dict.

        Reports the two error rates that actually matter for an alarm -- false
        positive rate and false negative rate -- plus a threshold sweep, rather
        than a single accuracy number that would hide both.
        """
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.inspection import permutation_importance
        from sklearn.metrics import confusion_matrix, roc_auc_score
        from sklearn.model_selection import StratifiedKFold, cross_val_predict

        base = HistGradientBoostingClassifier(
            max_depth=4, max_iter=200, learning_rate=0.08,
            l2_regularization=1.0, random_state=self.seed,
        )
        self._model = CalibratedClassifierCV(base, method="isotonic", cv=3)

        folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=self.seed)
        proba = cross_val_predict(self._model, X, y, cv=folds, method="predict_proba")[:, 1]

        self._model.fit(X, y)

        importance = permutation_importance(
            self._model, X, y, n_repeats=5, random_state=self.seed
        )
        self._importances = {
            name: float(score)
            for name, score in sorted(
                zip(FEATURE_NAMES, importance.importances_mean), key=lambda kv: -kv[1]
            )
        }

        sweep = []
        for thresh in (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
            sweep.append({"threshold": thresh, **_rates(y, proba >= thresh)})

        rates = _rates(y, proba >= self.threshold)
        cm = confusion_matrix(y, proba >= self.threshold, labels=[0, 1]).tolist()
        return {
            "confusion_matrix": cm,  # [[TN, FP], [FN, TP]]
            "threshold": self.threshold,
            "roc_auc": float(roc_auc_score(y, proba)),
            "n_train": int(len(y)),
            "n_positive": int(np.sum(y)),
            "threshold_sweep": sweep,
            "top_features": dict(list(self._importances.items())[:8]),
            **rates,
        }

    # -- inference --------------------------------------------------------
    def predict_features(self, feature_vector: np.ndarray) -> Detection:
        if self._model is None:
            raise RuntimeError("detector is not trained")
        p = float(self._model.predict_proba(feature_vector.reshape(1, -1))[0, 1])
        return Detection(is_gunshot=p >= self.threshold, probability=p,
                         threshold=self.threshold)

    def predict_audio(self, x: np.ndarray, fs: float) -> Detection:
        return self.predict_features(extract(x, fs))

    # -- persistence ------------------------------------------------------
    def save(self, path: str | Path) -> None:
        import pickle

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump({"model": self._model, "importances": self._importances,
                         "threshold": self.threshold}, fh)

    @classmethod
    def load(cls, path: str | Path) -> "GunshotDetector":
        import pickle

        with open(path, "rb") as fh:
            blob = pickle.load(fh)
        obj = cls(threshold=blob.get("threshold", DEFAULT_THRESHOLD))
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


def _rates(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Recall, precision, and the two error rates, from raw counts."""
    y_true = np.asarray(y_true).astype(bool)
    y_pred = np.asarray(y_pred).astype(bool)
    tp = int(np.sum(y_true & y_pred))
    tn = int(np.sum(~y_true & ~y_pred))
    fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred))
    return {
        "recall": tp / max(tp + fn, 1),
        "precision": tp / max(tp + fp, 1),
        "false_positive_rate": fp / max(fp + tn, 1),
        "false_negative_rate": fn / max(fn + tp, 1),
        "fpr": fp / max(fp + tn, 1),
    }
