# PARALLAX — System Architecture

**PARALLAX is a distributed passive-sensor network that turns scattered detections from many cheap nodes into one continuously updated threat picture for the commander.**

Named for the geometric principle it runs on: two separated observers looking at the same distant object determine its position from the difference in their lines of sight. That is the whole system in one word, and it is the answer to "why that name?"

Gunshot direction-finding is the flagship module, not the product. The product is the fusion layer that makes many partial observations into one picture.

---

## 0. The naming and scoping decision, stated first

**Conclusion: the acoustic gunshot work is retained unchanged and demoted to one module of four.** It remains the demo, because it is the module that is actually built and testable.

The reasoning is competitive, not technical. "Microphone array DoA for gunshot detection" is one of 246 listed problem statements and will be pitched by multiple teams from an identical spec, producing near-identical block diagrams. A pitch that differentiates has to answer a question the problem statement does not ask: *what does a commander do with a bearing?* A bearing from one node is a ray. The commander needs a position, a threat type, and a reason to believe it. That is a fusion problem, and fusion is where the defensible engineering is.

---

## 1. Sensor layer — what is physically on a node

**Conclusion: one node type, one bill of materials, four mission configurations. Configuration changes weighting and thresholds, never the hardware or the code path.**

| Element | Spec | Present in profile |
|---|---|---|
| Microphone array | 6 × omnidirectional MEMS, **5 in a 0.15 m ring + 1 raised 0.15 m on a mast** | all |
| ADC | 6-channel, 48 kHz, 24-bit, single sample clock | all |
| Optical / IR muzzle-flash channel | SWIR or NIR photodiode quadrant, or a low-cost LWIR core | all |
| Passive RF receiver | 2.4 / 5.8 GHz survey, control- and video-link signature | all (duty-cycled on patrol) |
| Geophone | single-axis, buried at the obstacle | **perimeter only** |
| GNSS + PPS | position, heading, and sub-microsecond time discipline | all |
| Air temperature sensor | feeds the speed-of-sound term | all |
| FPGA + MCU | see §2 | all |

### The one physics correction to the problem statement

The PS specifies six omnidirectional microphones. It does not specify their arrangement, and the obvious arrangement — a flat hexagonal ring — **cannot observe elevation at all.** A source 30° above the horizon and its mirror image 30° below produce identical delays at every element of a planar array. Any elevation number a flat ring reports is fabricated.

Since the reference C2 UI has an elevation field, this matters. The fix costs nothing:

> **Raise one of the six microphones out of the plane.** Same six microphones, same six ADC channels, same FPGA fabric, same cost. It is a mechanical change, not an electrical one, and it makes elevation observable.

This is enforced in code: `ArrayGeometry.is_planar` is checked at solve time, the solver drops to the observable 2-D subspace for a planar array, and the contact report clears `FLAG_ELEVATION_VALID`. The system refuses to emit an elevation it cannot measure. See `tests/test_doa.py::test_planar_array_refuses_to_report_elevation`.

Elevation matters operationally for exactly one reason, and it is the urban profile's reason: it separates a shooter on a rooftop from one at street level on the same bearing.

### Aperture, and why 0.30 m

Bearing precision scales as `δθ ≈ c·δτ / L`. Bigger aperture, better bearing. The counter-argument is spatial aliasing: narrowband beamforming requires element spacing ≤ λ/2, which at 3 kHz is 5.7 cm — far smaller than our 0.30 m.

**We commit to the large aperture** because we do not use narrowband beamforming. A muzzle blast is a broadband impulsive transient, and time-domain GCC-PHAT correlation on a broadband transient produces one unambiguous peak regardless of spacing. The λ/2 constraint is a property of narrowband subspace methods (MUSIC, ESPRIT, conventional beamforming), not of broadband TDOA. Choosing the method first and the aperture second is what buys the precision.

**This is judge question #3. It is the sharpest technically literate objection available, and the answer is above.**

---

## 2. Edge layer — the FPGA/MCU split

**Conclusion: per-sample work in fabric, per-event work in software. That boundary is the architectural argument, and it is what makes the classifier field-updatable over the air.**

| Runs on **FPGA fabric** | Why there |
|---|---|
| 6-channel I²S/TDM capture, 48 kHz | Must never miss a sample |
| DC block + the PS's ~200 Hz–3 kHz bandpass (DoA branch only) | Streaming, fixed-point, deterministic |
| Rolling energy detector against a tracked noise floor | Runs on every sample |
| **200 ms circular pre-trigger buffer** | The onset is the most informative part of a transient; a post-trigger-only capture clips it and throws away exactly the evidence the classifier needs |
| 15 parallel GCC-PHAT correlators (one per mic pair) | Embarrassingly parallel, fixed cost, sized by pair count |

| Runs on **MCU / soft core** | Why there |
|---|---|
| Plane-wave least-squares bearing solve (a 15×3 `lstsq`) | Once per event, not per sample |
| Full-band feature extraction (24 features) | Floating point is acceptable at event rate |
| Gradient-boosted-tree inference | **Retraining must not mean re-synthesising a bitstream** |
| Optical timestamping + local flash/acoustic pairing | Cross-modality, event rate |
| Contact report assembly, CRC-16, mesh transmit | Event rate |

The classifier is on the MCU specifically so it can be updated over the air. A model baked into fabric is a model that can never be corrected after the first false-alarm complaint from the field.

### Two filter branches, deliberately

The PS's ~3 kHz bandpass is retained exactly as specified — **on the DoA branch only.** The classification branch takes the full-band signal.

This resolves a genuine tension in the spec. The bandpass keeps the energy that matters for time-delay estimation, but it also discards high-frequency structure that is among the best discriminators between a muzzle blast and a firecracker (a firecracker's energy skews notably higher). Filtering before classification throws away the evidence. Same ADC stream, one branch filtered, one not. No spec deviation, no lost information.

### The contact report — 42 bytes, on the wire

| Field | Type | Bytes |
|---|---|---|
| `node_id`, `seq` | u16 × 2 | 4 |
| `t_event_ns` (UTC ns at onset) | u64 | 8 |
| `modality`, `threat_class`, `class_confidence` | u8 × 3 | 3 |
| `azimuth` (0.01°), `azimuth_sigma` (0.1°) | u16, u8 | 3 |
| `elevation` (0.01°), `elevation_sigma` (0.1°) | i16, u8 | 3 |
| `range_m`, `range_sigma_m` | u16 × 2 | 4 |
| `peak_spl_db`, `snr_db` | u8 × 2 | 2 |
| `node_lat`, `node_lon` (1e-7 deg) | i32 × 2 | 8 |
| `node_alt_m`, `node_heading` | i16, u16 | 4 |
| `flags`, `crc16` | u8, u16 | 3 |
| | **total** | **42** |

The bandwidth argument, quantified rather than asserted:

```
raw audio    48 kHz × 6 ch × 24 bit = 6.912 Mbit/s per node, continuously
contact rpt  42 bytes                = 336 bit per event
ratio        one second of audio ≈ 20,600 contact reports
```

That ratio — not any claim about clever compression — is why edge classification is non-negotiable on a radio-constrained mesh. Enforced by `tests/test_fusion.py::test_bandwidth_argument_holds`.

`flags` carries `RANGE_IS_MEASURED`, `ELEVATION_VALID`, `GPS_LOCKED`, `SATURATED`, `MULTIPATH_SUSPECT`. Every one exists so a node can tell HQ *what it does not know.*

---

## 3. Fusion layer

Full treatment in **[02-fusion-logic.md](02-fusion-logic.md)**. In one paragraph: reports are clustered by a physically-derived spatio-temporal gate (association windows come from node baselines and the speed of sound, not from tuned constants), ranged by whichever of three methods the available evidence supports, and scored by an explicit five-term confidence product. A flash and its own acoustic arrival become **one** track with two modalities and higher confidence — never two threats.

---

## 4. C2 / presentation layer

**Conclusion: the localisation code emits structured data and never touches a display; the renderer consumes that data and never touches a waveform.**

This is a locked design decision and it earns its keep three ways: the algorithm is testable headlessly in CI, the same track stream drives the HQ wall screen and the wrist unit without a second implementation, and the display can be re-skinned without recompiling anything that computes a bearing.

Concretely: `sim/run_demo.py` writes `out/tracks.json`; `viz/radar.py` reads it. Neither imports the other.

Layout follows the reference UI:

| Region | Content |
|---|---|
| Top banner | Large **AZIMUTH / ELEVATION / RANGE** readout, plus **TYPE** and **CONF**, plus the range *method* |
| Left | Polar radar dial: bearing needle, concentric range rings, and a **1σ bearing wedge** — uncertainty is drawn, not hidden |
| Centre | Plan/GIS view: node icons, bearing rays from every contributing node, fix marker, **1σ error ellipse** |
| Bottom | Event table: `# │ Node │ Modality │ Type │ Az │ σ │ Elev │ Range │ Conf │ T+ms`, newest highlighted |
| Footer | Link health, packet count, profile, and a standing `SIMULATED DATA` marker |
| Left rail | `DIAL │ GIS │ LIST │ SETTINGS │ START` |

Two departures from the reference, both deliberate:

- **A `threat type` column**, per the brief. Not every event is gunfire, and a dashboard that assumes it is will mislabel a drone.
- **Bearing-only contacts render as a dashed ray with no range marker and the label `BEARING ONLY`.** The reference UI has a range field; when range is not observable we leave it empty rather than filling it with a guess. A commander who learns the range field is sometimes fiction stops trusting the range field.

**Wrist unit** — the same track stream, reduced to what a soldier can read at a glance while moving: bearing needle, coarse range ring, threat-type glyph, confidence as needle thickness. No table. This is a human-factors decision, and it is the reason the algorithm/renderer split exists at all.
