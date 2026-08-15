# Anticipated Judge Questions

The six hardest, with direct answers. Each links to the fuller treatment.

---

### 1. "You claim 300–400 m detection range. Where does that number come from?"

**It is the design's operating target, not a derived figure — say so directly.** We did not run a full free-field SPL/attenuation/noise-floor link budget to derive it from first principles; it reflects the problem statement's implied envelope. What *is* derived from first principles: bearing precision at that range (0.14° floor from array aperture and sample rate) and the resulting cross-range error (6.1 m per degree at 350 m). See [04-limitations.md](04-limitations.md).

### 2. "Your classifier gets 96%+ recall. That sounds like a solved problem — why isn't this deployed already?"

**Because that number is measured on synthetic data, and we say so on the slide, not just in the appendix.** It shows the feature set can separate parametric models of the five classes; it says nothing about field performance, where the honest public gunshot corpus is a few hundred clips, mostly off-domain (film audio, compressed phone recordings). The real gap is a calibrated field-recording campaign, not more synthetic data. See [03-ml-classifier.md](03-ml-classifier.md).

### 3. "Why is your microphone aperture 30 cm when the spatial-aliasing limit at 3 kHz is 5.7 cm?"

**Because we use broadband GCC-PHAT time-delay estimation, not narrowband beamforming.** The λ/2 constraint applies to narrowband subspace methods (MUSIC, conventional beamforming); a muzzle blast is a broadband impulsive transient, and time-domain correlation of a broadband signal produces one unambiguous peak regardless of spacing. The larger aperture is what buys sub-degree bearing precision. See [01-architecture.md §1](01-architecture.md).

### 4. "How do you stop a flash and its own acoustic detection from being counted as two threats?"

**Association is by physical event, not by report.** A track is a cluster of reports that pass a physically-derived compatibility gate (temporal window from range/speed-of-sound, bearing agreement, threat-class match); the dashboard counts tracks, never raw reports. One node's flash+acoustic pair becomes one track with two modalities and higher confidence. Enforced in code and tested explicitly (`test_flash_acoustic_dt_gives_range_from_a_single_node` asserts exactly one track). See [02-fusion-logic.md §2c](02-fusion-logic.md).

### 5. "What happens when two nodes give you contradictory bearings?"

**Three defences in order, and the system knows when to stop.** The node self-flags low peak-sharpness (competing correlation peaks) and inflates its own reported uncertainty; triangulation weights every bearing by 1/σ²; with three or more bearings, the single worst-residual one is dropped and the fix refit. With exactly two bearings and no majority, **we do not guess** — the track degrades to bearing-only on the higher-confidence node, and the notes say why. A confidently wrong position is worse than an honest ray. See [02-fusion-logic.md §5](02-fusion-logic.md).

### 6. "This is a software-only submission. What proof do you have that any of this actually works?"

**A runnable, tested pipeline — not a paper design.** `python -m sim.run_demo` renders physically-modelled synthetic gunshot audio (Friedlander blast wave, spherical spreading, atmospheric loss, additive noise, optional multipath), runs it through the identical GCC-PHAT → feature-extraction → classification → fusion code that would run on real hardware, and produces a dashboard with a marked ground truth and reported miss distance. 32 unit tests cover the DoA solver's sign convention, the fusion layer's association logic, and several cases where the system is required to *refuse* to produce a number. Nothing is hard-coded to the answer; the error is shown, not hidden.
