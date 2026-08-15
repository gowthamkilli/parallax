# Honest Limitations

**A pitch that pre-empts the obvious criticism is stronger than one that hides it. This section states plainly what PARALLAX does not do.**

---

## What this system is

A **software prototype and simulation**, built to demonstrate a fusion architecture and its reasoning. No hardware was built. No field recordings were made. Every waveform, every classifier training example, and every accuracy figure in this repository comes from a physically-motivated but synthetic model, generated and clearly labelled as such in [`sim/`](../sim/).

## What it is not

A fielded, validated, or accuracy-certified detection system. Any number in this document that reads like a measurement is either a **derivation from stated physics** (marked with the formula it follows) or an **explicit ESTIMATE** — never a field result, because there are no field results.

---

## Per-modality limits, stated without euphemism

| Modality | Fails when | Why |
|---|---|---|
| **Acoustic array** | Urban multipath; strong wind; the shooter behind cover from all nodes | A hard facade can reflect a blast strongly enough to invert the apparent bearing (§5 of [02-fusion-logic.md](02-fusion-logic.md)); wind shear refracts the wavefront, which the plane-wave model does not account for |
| **Optical/IR flash** | Daylight (weak SNR against sky glare); foliage or defilade breaks line of sight; the muzzle is oriented away from every node | It is a line-of-sight sensor. No amount of processing recovers a flash that never reached a photodiode |
| **Passive RF** | The threat platform does not transmit (a passive drone glider) or uses frequency-hopping/LPI links | Only detects what it can hear; do not oversell as a general drone detector |
| **Seismic** | **Beyond ~20–40 m for footsteps, ~100–200 m for vehicles (soil-dependent), at ANY range in this design** | It is explicitly a perimeter-profile confirmation layer only, never a primary sensor at the 300–400 m envelope. We do not propose it as a primary detector, per the design constraints |
| **All acoustic methods** | The shockwave-only case: subsonic ammunition, or a shot far enough off-axis that only the crack (not muzzle blast) reaches the array | v1 has no supersonic-crack path by design; a subsonic round produces no crack at all, so the system depends entirely on the muzzle blast, which is directional and weaker off-axis |

---

## What the fusion layer will not do

- **It will not report a range from acoustic bearing alone.** Amplitude-derived range is a guess dressed as a measurement (§3c, fusion logic doc), and the system refuses to emit one. This is a deliberate reduction in apparent capability, not an oversight.
- **It will not resolve a 2-bearing conflict.** With exactly two nodes disagreeing and no majority, it degrades to bearing-only and says so, rather than guessing which bearing is the reflection.
- **It will not average away a Δt/triangulation disagreement.** When the two ranging methods disagree beyond their combined uncertainty, the track is flagged `METHODS DISAGREE` rather than silently blended.
- **It does not do distributed cross-node TDOA.** Bearings are solved locally per node specifically so the mesh clock requirement stays at 10 ms instead of 1 µs (§1, fusion logic doc). This trades away the larger effective aperture a fully distributed array could offer.

---

## Accuracy — every number, sourced

| Claim | Basis | Status |
|---|---|---|
| Bearing precision floor ≈ 0.14° | `δθ = c·δτ/L`, L = 0.30 m, 0.1-sample sub-sample interpolation at 48 kHz | **Derived floor**, not an achieved figure — assumes high SNR, no multipath, exact geometry |
| Realised bearing error in simulation, 1–3° | End-to-end simulator run, single node, moderate SNR | **Simulated result on synthetic data**, not a field measurement |
| Cross-range error 6.1 m per degree at 350 m | `R·tan(σ)` | **Derived**, exact given the stated inputs |
| Flash/acoustic range error ≈ ±2.5 m at 350 m | Timing jitter (±5 ms detector, ±1 ms optical) + thermal term (±3°C residual), combined in quadrature | **ESTIMATE** — both input uncertainties are estimates themselves |
| Temperature-assumption error: 9 m at 350 m if 15°C off | `c(T)` derivative | **Derived**, given the stated temperature error |
| Classifier recall 96–100% per class | 5-fold CV on the synthetic training corpus | **Synthetic-data result only.** Explicitly NOT a field detection accuracy claim — see [03-ml-classifier.md](03-ml-classifier.md) |
| Detection range envelope, 300–400 m | Stated design target, not derived from a specific SPL/SNR link budget in this document | **Design target / assumption**, consistent with published free-field small-arms SPL figures at range, not independently derived here |

We did not compute a full free-field SPL attenuation link budget (source SPL, spherical/atmospheric loss, background noise floor, required SNR) to independently justify the 300–400 m figure from first principles. That is a real gap and the honest answer if a judge asks "where does 350 m come from": it is the problem statement's implied operating envelope, treated as a design target, not a number we derived.

---

## What would be different with more time

- A genuine free-field SPL/SNR link budget deriving detection range from first principles, rather than treating it as a target.
- Real recordings — even a small calibrated set at known range would let the classifier's synthetic-data numbers be honestly compared against something.
- ISO 9613-1 atmospheric absorption in the simulator instead of the current simplified first-order lowpass.
- A distributed-consensus story for when HQ is not reachable (explicitly out of scope here — see the locked design decisions).
- The supersonic shockwave path, which supersonic ammunition produces independently of the muzzle blast and which is common in the real world we excluded from v1.
