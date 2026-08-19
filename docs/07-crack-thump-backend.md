# Crack-Thump Ballistic Backend

*The single-node range/direction/speed engine, and how it maps onto the field
pipeline. Backend + algorithm only — the JavaScript front end is a separate,
later deliverable and everything here is designed to feed it over JSON.*

> **SIMULATED.** No hardware was built and no field recordings were made. Every
> waveform is a physically-motivated synthetic model; every number is either
> derived from stated physics or marked as an estimate.

---

## 1. What this backend adds

The original PARALLAX repo deliberately excluded the supersonic ballistic
shockwave (the "crack") and ranged only via optical flash/acoustic timing or
multi-node triangulation. This backend adds the **crack-thump method**: a single
node that hears both the ballistic crack and the muzzle thump can recover the
shooter's **range**, the bullet's **speed**, and the **miss distance** — all at
once, **without assuming what weapon was fired.**

That last property is the point. Amplitude-based ranging depends on weapon,
calibre, barrel orientation and terrain, so it is a guess dressed as a
measurement. The crack-thump method reads the bullet's Mach number straight off
the geometry, so it is ammunition-agnostic.

---

## 2. The physics, in four observables

A supersonic bullet drags a cone-shaped shockwave behind it. The cone half-angle
(the Mach angle `μ`) depends only on speed: `sin μ = 1/M`. When the crack reaches
a sensor it arrives from a **different bearing** than the muzzle blast, and the
angle between them is very nearly the Mach angle.

| Observable | Source | Constrains |
|---|---|---|
| Blast (thump) bearing | second arrival | direction to shooter |
| Crack bearing | first arrival | Mach angle `μ` (via the split) |
| `Δt` = t_blast − t_crack | timing | range `R` |
| N-wave duration `T` | crack waveform | miss distance `d` |

Three unknowns (`R`, `d`, `M`), four observables → **overdetermined**, which is
what makes it robust.

**The three relationships**

```
1.  Bearing split:   α = μ − arctan(d/R),      sin μ = 1/M
2.  Timing:          Δt = (R/c)(1 − 1/M) + (d/c)[ √(M²−1)/M − M ]
3.  Whitham (N-wave): T ≈ 1.82 · M · d^(1/4) · l / [ c · (M²−1)^(3/8) ]
```

The quarter-power on `d` in (3) is why **miss distance is the least accurate
output** — an honest, documented weakness, not hidden.

**The inverse solve** (`parallax/ballistics.py::_solve_core`) seeds the
`arctan(d/R)` correction at zero (`μ ≈ α`) and alternates Whitham (`d`) and
timing (`R`) until `R` stops moving. It converges in **two passes**.

Worked example, reproduced verbatim by `tests/test_ballistics.py`:
5.56×45 at `R=300 m`, `d=10 m`, `M=2.04` → forward gives `μ=29.4°`, `α=27.4°`,
`Δt=0.412 s`, `T=287 µs`; the inverse recovers `R≈300 m`, `d≈10 m`, `M≈2.04`.

---

## 3. The two field scenarios

```
                     GUNSHOT (muzzle blast + ballistic shockwave)
                                    │
                                    ▼
                              MICROPHONE(S)               sim/scenario.py (thump)
                                    │                     sim/shockwave.py (crack geometry)
                                    ▼
                             LOCAL PROCESSING             parallax/nwave.py   (measure Δt, T)
                          (extract observables)           parallax/doa.py     (bearings)
                                    │
                                    ▼
                          CRACK-THUMP SOLVER              parallax/ballistics.py
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                                ▼
       (a) IN crack-thump range           (b) OUT of crack-thump range
       direction + distance + latlon      direction only, distance = NULL
                    │                                │
                    └───────────────┬────────────────┘
                                    ▼
                              LCD DISPLAY   +   HQ RELAY            parallax/localize.py
                                                   │
                                                   ▼
                                    BROADCAST BEST FIX TO ALL TEAMS
```

- **(a) In range** — node produces a full geolocated fix. `parallax/localize.py`
  projects `node lat/lon + bearing + range → shooter lat/lon`.
- **(b) Out of range** (subsonic round, behind the muzzle, or miss distance
  beyond crack reach) — direction is still shown, `distance_m` is `null`, no
  lat/lon can be placed from one bearing. This is exactly the "null until a
  closer team catches it" behaviour in the field pipeline.
- **HQ relay** (`localize_network`) — when several teams report one shot, HQ
  picks the best fix (a crack-thump range if *any* team had one, else a
  cross-bearing triangulation from ≥2 teams) and broadcasts that single fix to
  everyone, including teams that only heard a bearing.

---

## 4. The 6-mic vs 2-mic question

The SIH problem statement specifies a **6-microphone array**; the deployment
concept mounts only **2 microphones per team** (on two soldiers, spread apart).
These are reconciled by **decoupling the solver from the sensor**:

`solve_crack_thump()` consumes *observables* — `blast_bearing`, `bearing_split`,
`Δt`, `T` — and does not care how they were produced. A 6-mic array measures the
two bearings directly; a 2-mic team measures each bearing as a TDOA cone and
takes the difference. The ballistic inversion is identical either way, so the
sensing front end stays swappable without touching the ranging maths.

---

## 4b. The classifier gate (gunshot vs. everything else)

The crack-thump solver is **pure geometry**. Hand it a firecracker's timings and
it will return a confident, precise, entirely fictional range. So a trained
binary detector sits in front of it, and nothing downstream — no solve, no
bearing, no marker on a commander's map — runs unless the gate passes.

```
audio ──▶ window on first onset ──▶ BINARY DETECTOR ──▶ gunshot? ──▶ crack-thump solve
                                                            │
                                                            └── no ──▶ stop. no marker.
```

**Model** (`parallax/detector.py`): gradient-boosted trees over the 27 physical
features, isotonic-calibrated, labels `GUNSHOT → 1` and
`{VEHICLE, DRONE, PERSONNEL, NUISANCE} → 0`. Trained by
`python -m sim.train_gunshot_detector`.

**Why binary and not the 5-class model:** the operational question is a binary
one with asymmetric costs — a false negative drops a real shot, a false positive
lights up the map on a door slam and teaches everyone to ignore the display. A
binary framing lets both error rates be reported and tuned directly, and stops
NUISANCE's cost being diluted across four other labels.

**Threshold** is explicit (default **0.70**), chosen off the sweep the training
script prints rather than left at argmax. 0.70 holds the same detection rate as
0.60 at a lower false-positive rate.

**Measured (SYNTHETIC data — not a field figure):**

| metric | value |
|---|---|
| detection rate (recall) | 0.983 |
| false positive rate | 0.024 |
| false negative rate | 0.017 |
| ROC AUC | 0.986 |

### The N-wave shape features, and why they were needed

The first build of this gate scored **real supersonic gunshots at p ≈ 0.28** and
dropped them. The cause was a genuine train/inference gap: the GUNSHOT class
contained only *muzzle blast* audio, but the edge pipeline windows on the **first
onset**, and for any supersonic round that first arrival is the **ballistic
crack** — an N-wave, which looks nothing like a Friedlander blast. The model had
never seen one.

Two fixes:

1. `sim/train_classifier.py::gunshot_crack` adds the N-wave to the GUNSHOT class,
   so it covers both arrivals a real shot can present.
2. Three new features in `parallax/features.py` measure the N-wave signature **at
   the pulse's own timescale** (~150–600 µs), which nothing in the original 24
   did — `decay_linearity` fits over 20 ms, roughly 40× too long to see the shape
   at all:

   | feature | physical meaning |
   |---|---|
   | `nwave_symmetry` | \|negative lobe\| / positive lobe — ≈1 for a shockwave, ≪1 for a blast's shallow negative phase |
   | `nwave_ramp_linearity` | R² of a straight line fitted peak→trough — an N-wave ramps linearly, an exponential decay does not |
   | `nwave_bipolar_ms` | peak-to-trough time ≈ T/2, directly related to the Whitham observable |

`nwave_symmetry` now ranks in the detector's top-3 permutation importances, so it
is carrying real weight rather than padding the vector.

**Honest note:** firecracker vs. ballistic crack is the hardest pair here (both
are short, impulsive, high-frequency) and it accounts for essentially all of the
residual false-positive rate. That is the known hard problem in acoustic gunshot
detection, not an artifact — see `docs/03-ml-classifier.md`.

---

## 5. Module map

| Module | Role |
|---|---|
| `parallax/detector.py` | Binary gunshot/not-gunshot model + explicit decision threshold. **The gate.** |
| `parallax/pipeline.py` | Windows the capture, runs the gate, and ranges only on a pass. |
| `sim/train_gunshot_detector.py` | Trains the gate; prints FPR/FNR/ROC-AUC and the threshold sweep. |
| `sim/run_detect_demo.py` | Gated demo: gunshot ranged, nuisances rejected before the solver. |
| `parallax/ballistics.py` | Crack-thump forward model + iterative inverse + Monte-Carlo accuracy. **Sensor-agnostic.** |
| `parallax/nwave.py` | Synthesise / measure the N-wave; recover `Δt` and `T` from one channel. |
| `sim/shockwave.py` | Forward sensor model: trajectory → per-node observables + ground truth; the scenario-(a)/(b) predicate. |
| `parallax/localize.py` | Observables → geolocated shooter (lat/lon) + accuracy; single-node and HQ-network fusion. |
| `parallax/api.py` | JSON-in / JSON-out boundary for the JavaScript front end. |
| `sim/run_ballistic_demo.py` | End-to-end demo of both scenarios and the HQ relay. |
| `tests/test_ballistics.py`, `tests/test_localize_api.py` | Pin the worked example and the JSON contract. |

---

## 6. JSON API contract (for the JS front end)

`parallax/api.process_node_report(payload) -> dict` and
`process_network(payload) -> dict`. Everything crossing the boundary is plain
JSON — no numpy, no Python-only types.

**Input (single node)**
```json
{
  "node": { "id": 2, "lat": 28.6139, "lon": 77.2090, "temp_c": 20 },
  "measurement": {
    "blast_bearing_deg": 42.0,
    "bearing_split_deg": 27.4,
    "dt_s": 0.412,
    "nwave_duration_s": 0.000287,
    "sigmas": { "blast_bearing_deg": 1.0, "bearing_split_deg": 1.5,
                "dt_s": 0.003, "nwave_duration_s": 3e-5 }
  },
  "bullet": "5.56x45"
}
```
Omit `bearing_split_deg` / `dt_s` / `nwave_duration_s` (or send `0`) to signal
"no separable crack" — the response degrades to scenario (b).

**Output — PERMANENT contract, exactly these five fields, nothing more**
```json
{
  "ok": true,
  "fix": {
    "direction": "N42.0E",           // quadrant compass bearing, not raw degrees
    "distance_m": 300.1,             // null in scenario (b)
    "latitude": 28.616949,           // null if no range
    "longitude": 77.211075,
    "accuracy_pct": 87.3
  }
}
```
`direction` is surveying quadrant-bearing notation (`parallax.geometry.compass_bearing`):
`"N42.0E"` = 42° east of north, `"S30.0W"` = 30° west of south; the four
cardinals print bare (`"N"`, `"E"`, `"S"`, `"W"`).

This is the locked output shape for `process_node_report` and
`process_network` alike (via `parallax/api.py::_slim_fix`) — the richer
internal fields (`mach`, `miss_distance_m`, `range_sigma_m`,
`in_crack_thump_range`, `method`, `notes`) still exist on `GeoContact` /
`BallisticSolution` for Python callers (`localize_single_node`,
`localize_network`, the demo scripts), they are just not part of what
crosses the JSON boundary to the front end. Do not add fields back onto this
response without an explicit request — the JS side is meant to be able to
depend on exactly this shape.

Bad input returns `{ "ok": false, "error": "..." }` rather than raising, so the
front end always gets a body it can branch on.

---

## 7. Accuracy percentage

Derived, not asserted. `solve_crack_thump()` runs a Monte-Carlo that perturbs
every observable by its stated 1-σ and measures how far the range estimate
actually moves; `accuracy_pct = clip(100·(1 − σ_R/R))`, shaved if the solver did
not fully converge. Tight, well-conditioned geometry earns a high number; a
shallow one honestly reports a low one. Verified to respond to input noise:
`σ_split 0.5°→4°` moves accuracy `96%→89%` as `σ_R` grows `11→33 m`.

---

## 8. What is and isn't modelled

**Modelled:** Friedlander muzzle blast, ideal N-wave crack, Mach-cone emission
geometry, spherical spreading, the crack-thump regime predicate, temperature-
corrected speed of sound, and honest error propagation.

**Not modelled (documented gaps):** velocity decay along the trajectory (a
constant-`M` approximation — a refinement, not a change of method), atmospheric
refraction / ground effects on the crack, and the actual wireless broadcast
transport (the HQ relay produces the JSON that a real mesh would carry, but the
radio layer itself is out of scope). See also `docs/04-limitations.md`.

---

## 9. Integration with the distributed fusion engine

Sections 1–8 describe the crack-thump solver as a **standalone** path
(`parallax/localize.py`), separate from the original multi-node
`parallax/fusion.py`. That separation was a real gap: a solver that reports a
range unquestioned, with no other node able to check it, is exactly the
"beautiful-looking wrong distance" failure mode a physics-only ranging method
risks. The two paths are now joined.

**What changed, precisely:**

- **`Modality.SHOCKWAVE`** (`parallax/contact.py`) is a distinct modality from
  `Modality.ACOUSTIC`. A node that hears both the crack and the blast now
  emits **two** contact reports, not one — mirroring how `OPTICAL_IR` and
  `ACOUSTIC` already pair up for flash/acoustic ranging. `ContactReport` also
  carries `nwave_duration_s` (in-memory/JSON only — seed for a future wire
  field, not yet spent from the fixed 42-byte record; see the field's
  docstring for why).
- **Association** (`FusionEngine._max_lag_s` / `_compatible`) gates a node's
  own SHOCKWAVE↔ACOUSTIC pair by the crack-thump method's own reach
  (`MAX_CRACK_THUMP_RANGE_M`, not the much larger flash/acoustic envelope),
  and — critically — does **not** require their bearings to agree. The crack
  and blast are *supposed* to arrive from different bearings; that split is
  the Mach-angle signal itself, not a disagreement to reject.
- **Ranging is now three independent sources**, gathered before any is
  chosen: flash/acoustic `dt`, ballistic crack-thump
  (`FusionEngine._range_from_ballistic_crack_thump`), and triangulation. A new
  `FusionEngine._combine_range_estimates` cross-validates whichever fired —
  pairwise agreement within `range_disagreement_sigma` combined sigma fuses
  them by inverse-variance weighting (tighter source, more say); disagreement
  is recorded explicitly in the track's notes and the single tightest
  estimate is used, never a blend of a good and a bad one. This generalises
  the two-source disagreement check that already existed for flash/acoustic
  vs. triangulation — same principle, now open to a third source.
- **The reported bearing is never the crack bearing.** The crack points at a
  location on the bullet's flight path, not at the shooter, so
  `_build_track` explicitly excludes `SHOCKWAVE` reports from the "primary"
  bearing selection (`FusionEngine._build_track`, `bearing_candidates`).
- **Modality weights** (`parallax/fusion.py::FusionConfig`,
  `parallax/profiles.py`) give `SHOCKWAVE` its own tunable weight per mission
  profile — deliberately **not** hardcoded to imply a high-confidence gunshot
  by itself. What actually earns confidence is the existing corroboration
  scoring (`FusionEngine._score`): independent modalities and independent
  nodes agreeing, which now naturally includes the crack as one more
  physics-supported vote rather than an assumed one.
- **`parallax/doa.py::estimate_doa`** gained one bounded round of outlier-pair
  rejection (`_fit_plane_wave`): if a single correlation pair among the
  `n·(n−1)/2` measured is a clear outlier (>4× the RMS of the rest) and enough
  pairs remain to stay comfortably overdetermined, it is dropped and the fit
  refit once. Single-pass and bounded on purpose — this is an FPGA-adjacent
  path, not a place for unbounded iterative search.

**Demo:** `python -m sim.run_hybrid_demo --range 300 --miss 10 --mach 2.04`
builds one node's SHOCKWAVE+ACOUSTIC pair and a second node's ACOUSTIC-only
report, and runs them through the real `FusionEngine`. The two independent
range estimates (ballistic crack-thump and triangulation) land within a metre
of each other and fuse; the printed track shows `range_method:
ballistic_crack_thump+triangulation` and the note `range sources agree: ...
-> fused 300 +/- 1 m`.

**Tests:** `tests/test_fusion.py` — `test_shockwave_and_blast_same_node_...`,
`test_ballistic_and_triangulation_agree_and_fuse`,
`test_ballistic_and_triangulation_disagreement_is_flagged`.
`tests/test_doa.py` — `test_fit_plane_wave_rejects_one_bad_pair`,
`test_estimate_doa_survives_one_saturated_mic`.

**Still not done** (scoped out of this pass, not forgotten): the simulator's
`sim/scenario.py` still does not synthesise shockwave *audio* end-to-end
through `sim/edge_node.py` — `Modality.SHOCKWAVE` reports reaching
`FusionEngine` today are built either directly (as in `run_hybrid_demo.py` and
the fusion tests) or via the idealised truth geometry in `sim/shockwave.py`,
not by running real 15-pair GCC-PHAT independently on a detected crack window
the way `sim/edge_node.py` already does for the blast. Wiring that up —
detecting the crack's onset in the raw multichannel capture and solving its
own DoA the same way the blast's is solved — is the natural next step toward
the "DOA independently for each onset" idea, and is what would let
`sim/run_demo.py`'s existing end-to-end audio path exercise this integration
too, not just direct `ContactReport` construction.
