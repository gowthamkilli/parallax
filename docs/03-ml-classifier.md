# The ML Component

**Conclusion: a physically-motivated 24-feature vector into calibrated gradient-boosted trees, classifying five event types from a single detected transient. Trained here on synthetic data only, which is stated on the slide, not hidden.**

Reference: [`parallax/features.py`](../parallax/features.py), [`parallax/classifier.py`](../parallax/classifier.py), [`sim/train_classifier.py`](../sim/train_classifier.py).

---

## What is classified

One detected transient window → one of:

```
GUNSHOT · VEHICLE · DRONE · PERSONNEL · NUISANCE
```

with a calibrated probability per class. **NUISANCE is a first-class label, not a reject bin.** Firecrackers, door slams, hammer strikes and thunder are the events that actually generate false alarms in the field; a model trained to *name* them, rather than to score everything else as "not gunshot", is the one that can be debugged when it gets one wrong.

**What it does not do:** identify weapon type or calibre. That claim requires calibrated free-field recordings of known weapons at known ranges, which no public dataset provides, and we do not make it.

---

## Why hand-crafted features over a CNN — the trade, and the commitment

A CNN on log-mel spectrograms will beat hand-crafted features **given tens of thousands of labelled, in-domain recordings.** We do not have those and will not have them on a hackathon timeline — the honest public gunshot corpus is a few hundred clips (below). In that regime a ~24-dimensional physically-motivated vector into depth-limited gradient-boosted trees:

- generalises better with a few hundred examples per class than a network that needs orders of magnitude more,
- trains in seconds on a laptop, no GPU,
- runs in fixed point on an MCU,
- and — decisively for a pitch — **every feature can be named.** Permutation importance tells a judge which physical property drove a decision. A judge who asks "what does the model actually look at?" gets `band_ratio_mid` and `harmonicity`, not "the sixteenth convolutional filter."

**We commit to this** for the current data regime and revisit only if the corpus reaches tens of thousands of in-domain clips.

### The feature set (24 features, four families)

| Family | Features | What they separate |
|---|---|---|
| Temporal envelope | rise/decay/duration, crest factor, secondary-peak count, decay linearity | Impulsive blast vs. slow thud vs. sustained tone |
| Statistical shape | kurtosis, skewness, zero-crossing rate, entropy | "Spiky and rare" vs. "smooth and continuous" |
| Spectral | centroid, spread, rolloff, flatness, slope, 4 band-energy ratios (20–200 / 200–1500 / 1.5–6k / 6–20 kHz) | Where the energy sits — this is what separates a gunshot from a firecracker |
| Periodicity | harmonicity (autocorrelation peak), 20–200 Hz envelope modulation | Tonal/rotating sources (drone blade-pass, engine firing rate) from impulsive ones |

On the synthetic corpus, permutation importance ranks `band_ratio_mid` (200–1500 Hz energy fraction) and `band_ratio_hi` (1.5–6 kHz) as the two strongest features by a wide margin — consistent with the physical story that a muzzle blast's energy sits lower and broader than a firecracker's sharper high-frequency crack. That the top features are exactly the ones the physical model predicts is itself informative: it means the classifier learned the physics we designed it to find, not an artefact of the synthesis. It is not proof that field audio will rank the same features the same way.

### Two filter branches (cross-reference)

Classification runs on the **full-band** signal, not the ~3 kHz-bandpassed DoA branch — the high-frequency structure that separates a blast from a firecracker lives partly above 3 kHz, and filtering before classification would discard it. See [01-architecture.md](01-architecture.md#the-one-physics-correction-to-the-problem-statement).

---

## Model and calibration

`HistGradientBoostingClassifier` (scikit-learn), max depth 4, 200 boosting rounds, wrapped in `CalibratedClassifierCV` with isotonic calibration and 3-fold internal CV.

**Calibration is not optional here.** Raw tree ensembles are overconfident — a raw 0.95 is routinely right well under 95% of the time. The fusion layer's confidence score (`docs/02-fusion-logic.md §4`) multiplies this number directly into a value a commander reads off a dashboard. An uncalibrated confidence poisons every downstream fusion weight; isotonic calibration is the cheapest fix that has an honest probabilistic interpretation.

Evaluation is **5-fold stratified cross-validation**, reported as a full confusion matrix and per-class precision/recall — not a single accuracy number. A single accuracy figure on an imbalanced five-class problem flatters and informs nobody; the confusion matrix says specifically which classes get confused for which.

---

## Training data — what is real, and what is not

**Everything `sim/train_classifier.py` trains on is synthetic: parametric signal models with randomised parameters, augmented with coloured noise, crude reverberation and level scaling. This is stated on the slide.**

Why synthesise at all, if it proves nothing about field accuracy: it proves the pipeline is complete and runnable end to end — features, training, calibration, inference, contact report — and it makes the feature design **falsifiable**. If physically-motivated features could not even separate parametric models of a blast from a firecracker, the feature design would be wrong and we would know it now, at zero data-collection cost.

### The real training path — what a fielded system would need

| Source | Content | Caveat |
|---|---|---|
| UrbanSound8K | 374 `gun_shot` clips, urban | Uncalibrated range/weapon |
| ESC-50 | 40 `gun_shot` clips | Small |
| MIVIA audio events | Scream/gunshot, surveillance-oriented | Different acoustic environment |
| DEMAND / TUT | Realistic background classes | Negatives only |

That is a **few hundred in-domain positives** — a small-data problem, and the reason for the model choice above.

**Known domain gap, stated plainly:** most public "gunshot" clips are film/TV audio or compressed phone recordings, frequently already reverberant, at unknown range with unknown weapons. A model trained on them partly learns the recording chain, not the physics. Fielding this system requires a calibrated collection campaign at known ranges with a characterised recording chain — this is real future work, not a detail to skip past.

---

## Failure modes, named

| Failure mode | Mechanism | Mitigation in this design |
|---|---|---|
| Firecracker → GUNSHOT | Both are broadband impulsive transients; a large or close firecracker can resemble a distant, muffled shot | `NUISANCE` trained as its own class on the discriminating spectral-slope/band-ratio features, not lumped as "not gunshot" |
| Domain-gap collapse | Model trained on synthetic or off-domain audio underperforms on real field recordings | Explicitly disclosed; the honest fix is a calibrated field collection campaign, not a bigger synthetic corpus |
| Low-SNR misclassification | Feature extraction degrades gracefully but not for free at long range / high background noise | Fusion layer downweights low-confidence single-node classifications rather than trusting them outright |
| Novel event types | Anything not in the training taxonomy (e.g. a mortar, a different drone class) has no home | Falls into the nearest trained class or a low-confidence `UNKNOWN`; not claimed as open-set robust |
| Reverberant smearing | Heavy multipath distorts the temporal envelope features the classifier depends on | Correlated with the acoustic bearing's own `FLAG_MULTIPATH_SUSPECT` (fusion.py); a suspect bearing and a suspect classification tend to co-occur, which is itself diagnostic |
