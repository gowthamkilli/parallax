# Fusion Logic

This is the technical core of the system and the part a judge will probe hardest. Four problems, in order.

Reference implementation: [`parallax/fusion.py`](../parallax/fusion.py). Every claim below has a corresponding test in [`tests/test_fusion.py`](../tests/test_fusion.py).

---

## 1. Time synchronisation — the requirement is 10 ms, not 1 µs

**Conclusion: the mesh needs 10 ms clock agreement, which plain NTP already delivers. This is a consequence of one architectural choice, not of clever engineering.**

The choice: **TDOA stays inside a node.** Each node solves its own bearing from its own six microphones using its own local oscillator. Inter-microphone delays are hundreds of microseconds measured against a single crystal, so any mesh-wide clock offset cancels exactly — it is common-mode to all six channels.

The alternative was to treat the whole squad as one giant distributed array. That gives a far larger aperture and therefore much finer bearings, and it is genuinely tempting. It also requires sub-microsecond alignment across 1–2 km, because 1 µs of clock error is 0.34 m of apparent path difference. **We reject it for v1.** Not because it cannot be done, but because the sync engineering would become the project, and the fallback behaviour when sync degrades is a silently wrong bearing rather than a missing one. Local-TDOA-plus-triangulation degrades gracefully; distributed TDOA degrades deceptively.

Because bearings are local, the mesh clock only has to be good enough to **associate** events, and association windows are hundreds of milliseconds to seconds.

| Sync source | Accuracy | Consequence |
|---|---|---|
| GNSS PPS locked | < 1 µs (typ. < 100 ns) | Everything works, including future cross-node TDOA |
| PTP over the mesh | ~10–100 µs | Everything in this document works |
| NTP over the mesh | ~1–10 ms | Everything in this document works |
| Free-running TCXO | ~1 ppm → 3.6 ms/hour | Needs resync roughly hourly |

We still specify GNSS PPS because the nodes need GNSS for position anyway and PPS is free once the receiver is there. The tiering exists for GNSS-denied operation, which is a realistic condition and one a judge may well raise.

---

## 2. Association — two windows, two different physics

**Conclusion: association windows are *derived* from geometry and the speed of sound, per report pair. There is no global tuned time constant, because a global constant cannot be right for both a 50 m and a 1 km node pair.**

### 2a. Flash ↔ acoustic, same node

Light covers 400 m in 1.3 ns. Sound takes 1.17 s. So the muzzle flash is, for our purposes, coincident with the shot, and the acoustic arrival lags it by exactly the propagation time:

```
Δt = R / c        →  gate:  0 < Δt ≤ R_max / c
```

At the 400 m envelope edge that is 1.17 s; at the 3 km mesh relevance cutoff, 8.75 s. We gate at `R_max = 1200 m → 3.5 s` — wide enough to catch shots beyond the design envelope, tight enough not to sweep in unrelated events.

A **negative Δt is physically impossible** and rejects the pairing outright. Sound does not arrive before light. (`test_negative_dt_is_rejected_as_non_physical`)

Both reports must also agree in bearing to within 3σ, since both sensors look at the same muzzle from the same place.

### 2b. Acoustic ↔ acoustic, different nodes

Two nodes separated by baseline `B` hear the same shot at times differing by at most `B/c`, achieved when the shooter is collinear with both:

```
|t₁ − t₂| ≤ B / c + clock_error
```

Nodes 1 km apart → 2.92 s window. Nodes 50 m apart → 146 ms window. **The window comes from that specific pair's baseline**, so a tight pair rejects far more aggressively than a distant one. A fixed global window cannot produce that behaviour, and would have to be sized for the worst case, which means it would be far too loose for every close pair. (`test_association_window_scales_with_node_baseline`)

A second gate then applies: the bearings must **plausibly cross**. The crossing point must lie within the 3 km relevance cutoff and must be *in front of* both rays — a back-bearing crossing is geometrically valid and physically meaningless. (`test_back_bearings_do_not_associate`)

One subtlety worth stating because it is a real edge case: near-parallel bearings have no crossing point, but that is a statement about geometry, not about whether it is the same event. Two closely-spaced nodes bearing consistently on a distant shot **should** associate; they simply cannot produce a fix. So on a singular crossing we fall back to a bearing-agreement test, form the track, and let it honestly report itself as bearing-only.

### 2c. How double-counting is prevented

**Association is by physical event, not by report. Reports enter tracks; tracks are what the dashboard counts.**

A track carrying an optical and an acoustic report from the same node is *one contact with two modalities and higher confidence* — never two contacts. Clustering is single-linkage over the pairwise compatibility relation, so all reports describing one event land in one cluster regardless of arrival order. (`test_flash_acoustic_dt_gives_range_from_a_single_node` asserts exactly one track results.)

Threat class also gates association: a drone and a gunshot are not the same event even if simultaneous. (`test_different_threat_classes_do_not_merge`)

---

## 3. Ranging — three methods, ranked, and we never fabricate a fourth

**Conclusion: range comes from flash/acoustic Δt when optical is available, from triangulation when ≥2 nodes with good crossing geometry are available, and otherwise is not reported at all.**

### (a) Flash/acoustic Δt — single node, best method

```
R = c · Δt
```

**This is the single strongest argument for adding the optical channel, and it is the centrepiece of the whole design.** It produces a *ranged* fix from **one node**, which no amount of acoustic processing on a 0.30 m array can do. It also survives the two cases that most damage the acoustic-only story:

- **Suppressors** kill the muzzle blast but not the flash.
- **A lone patrol node** has no second node to triangulate with — which is exactly the dismounted-patrol profile's normal condition.

Worked example at the middle of the envelope: `Δt = 1.020 s`, `c = 343.2 m/s` → `R = 350 m`.

**Error budget** — the interesting result is that it is limited by *air temperature*, not by electronics:

| Term | Magnitude at 350 m | Note |
|---|---|---|
| Onset-detection jitter (5 ms, **ESTIMATE**) | ±1.7 m | Electronics |
| Optical readout jitter (~1 ms, **ESTIMATE**) | ±0.3 m | Electronics |
| Speed of sound, ±3 °C residual (**ESTIMATE**) | ±1.8 m | Physics |
| Speed of sound, if you *assume* 20 °C and it is 35 °C | **±9 m** | The mistake to avoid |

`c` moves ~0.6 m/s per °C. Assuming 20 °C on a 35 °C day is a 2.6% range error. So the node carries a thermometer and feeds measured temperature into `c`. Combined σ ≈ **±2.5 m at 350 m (ESTIMATE)**.

### (b) Triangulation — ≥2 bearings

Weighted least squares minimising the sum of squared perpendicular distances from the estimated point to every bearing ray:

```
minimise  Σᵢ wᵢ ‖ (I − uᵢuᵢᵀ)(x − oᵢ) ‖²        wᵢ = 1/σᵢ²
```

Linear in `x`, closed form, no initial guess and no local minima. The 1/σ² weighting lets a tight optical bearing (σ ≈ 0.6°) dominate a smeared acoustic one (σ ≈ 3°) automatically.

**Crossing angle governs everything.** Below 15–30° (profile-dependent) the error ellipse stretches out along the bearing axis and the "fix" is not a fix. We test the crossing angle explicitly and **refuse to emit a position** when it is too shallow, saying so in the track notes. (`test_shallow_crossing_angle_degrades_to_bearing_only`)

Cross-range error is the useful sanity number: `error ≈ R·tan(σ)`. At 350 m, **1° = 6.1 m, 3° = 18.3 m.**

### (c) Bearing only — and no range at all

**A muzzle blast alone carries no range information.** Received amplitude depends on weapon, calibre, charge, barrel orientation relative to the array, terrain, foliage, humidity and wind. An amplitude-derived range is a guess dressed as a measurement, and the system refuses to emit one. (`test_single_acoustic_node_reports_no_range`)

The dial draws a dashed ray labelled `BEARING ONLY`. The range field stays empty.

This is a deliberate product decision with a cost: the wrist unit shows "bearing + probable range", and in this case there is no range to show. We accept the reduced display, because the alternative — a plausible-looking fake range — teaches the user that the range field is fiction, and then the *real* ranges stop being believed too.

### When (a) and (b) both fire

Both are computed. The **triangulated position** is kept (it is a 2-D fix; Δt gives only a scalar), the **Δt range** is used for the range readout (it is tighter), and the disagreement between them is recorded in the track notes as a free health check. If they disagree by more than 3σ combined, the track is flagged `METHODS DISAGREE — treat position as suspect` rather than quietly averaged. Two methods disagreeing is information; averaging it away destroys that information.

---

## 4. Confidence scoring

**Conclusion: an explicit five-term product, not a learned score.**

The trade: a learned combiner would in principle capture interactions a hand-built score misses. But there is no labelled multi-node multi-modal fusion corpus, so it could only be fitted to our own simulator — it would learn the simulator's quirks and mean nothing in the field, while carrying the false authority of "the model decided". An explicit product is honest about being a heuristic and is defensible line by line to a judge. **We commit to the explicit score** and revisit only when real field data exists.

```
confidence = detection × corroboration × spatial × geometry × multipath
```

| Term | Definition | Rationale |
|---|---|---|
| `detection` | best modality-weighted classifier confidence in the cluster | The evidence itself |
| `corroboration` | `1 − 0.45·0.5^(n_modalities−1)` | Two *physically different* sensors agreeing is much stronger evidence than two of the same. An optical flash and an acoustic blast share no failure mode |
| `spatial` | `1 − 0.35·0.6^(n_nodes−1)` | Independent viewpoints, diminishing returns |
| `geometry` | scales with CEP; 0.8 for a Δt range; **0.45 for bearing-only** | A ray is worth less than a fix, and the score must say so |
| `multipath` | 0.75 if any contributing node raised `FLAG_MULTIPATH_SUSPECT` | The node's own self-doubt propagates |

Modality weights are profile-tunable and encode honest trust: optical 1.0, acoustic 0.85 (0.6 in urban, 0.7 in convoy), RF 0.6, **seismic 0.35 and never a primary fix**.

Each mission profile sets its own alert threshold: perimeter 0.45 (a false alarm costs a look), convoy 0.70 (a convoy that halts on every false alarm stops moving), urban 0.65, patrol 0.55.

---

## 5. Conflicting bearings — the urban failure mode

**Conclusion: three defences, applied in order, and the last one is to stop and report a ray.**

In a street canyon a hard façade can reflect a blast strongly enough that the array bears on the reflection rather than the direct path. This inverts the apparent bearing and it is the single most damaging failure this system has.

1. **The node self-reports it.** GCC-PHAT peak sharpness — main peak over next-highest peak — falls toward 1 when a reflection competes with the direct path. Below threshold, the node raises `FLAG_MULTIPATH_SUSPECT` *and* inflates its own reported σ. The same mechanism catches low SNR, where noise peaks rival the true arrival; both make a bearing untrustworthy in the same way. (`test_bearing_degrades_with_snr_not_silently`)

2. **Weighted least squares.** A self-declared loose bearing carries 1/σ² weight and a flagged one is inflated a further ×2, so it cannot drag the fix.

3. **Robust outlier rejection.** With **≥3 bearings** we drop the single worst-residual bearing and refit. If the residual collapses, the dropped bearing was the reflection. (`test_outlier_bearing_is_rejected_with_three_nodes` — one bearing corrupted by 40°, fix still lands within 60 m.)

**With exactly 2 conflicting bearings there is no majority and no way to tell which is lying.** We degrade to bearing-only on the higher-confidence node and say so in the track notes. Reporting a confident wrong position is worse than reporting an honest ray — a commander acting on a wrong position is worse off than one who knows they only have a direction.
