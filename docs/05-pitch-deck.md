# 7-Slide Pitch

**Conclusion: allocate one slide each to the problem reframe, architecture, fusion mechanics, the acoustic flagship demo, the ML honesty section, limitations, and roadmap. Cut a dedicated "team/timeline" slide — a hackathon judging panel weighs the engineering, not the org chart.**

| # | Title | The one message | Visual |
|---|---|---|---|
| 1 | **Beyond one sensor: PARALLAX** | Standalone gunshot DoA is 1 of 246 problem statements; we built the fusion platform it plugs into | Four modality icons converging into one dashboard icon. No block diagram yet — that is slide 2 |
| 2 | **One node, one engine, four missions** | Identical hardware and fusion code; only weighting and thresholds change per mission | The four-layer architecture diagram + the mission-profile table (perimeter/convoy/patrol/urban) side by side |
| 3 | **How a bearing becomes a position** | Flash gives instant range from ONE node; two-plus acoustic bearings triangulate; bearing-only when neither applies | The three-method decision tree, annotated with the 0.14° bearing floor and the 6.1 m/° cross-range number |
| 4 | **The flagship: acoustic DoA, live** | The built module works — run the demo, show the dashboard, show the honest error against ground truth | `viz/radar.py` dashboard screenshot with the truth marker and miss-distance annotated on screen |
| 5 | **What breaks it, on purpose** | Multipath inverts a bearing; the system catches its own mistake and downgrades to bearing-only rather than lying | Side-by-side: clean 3-node fix vs. the same scenario with `--multipath`, showing the self-flagged degraded track |
| 6 | **The ML is small, honest, and named** | Physically-motivated features beat a black-box net at this data scale; here is what it actually looks at | Permutation-importance bar chart (`band_ratio_mid`, `harmonicity`, ...) with the synthetic-data disclaimer printed on the slide itself |
| 7 | **What's real, what's next** | Everything above is software + simulation; the roadmap says exactly what a fielded system still needs | Two-column "built vs. roadmap" table: shockwave path, field data collection, SAF radar, distributed sync |

**What gets cut, and why:** a dedicated team-introduction slide, a market-sizing slide, and a standalone "future work" slide beyond what fits on slide 7. Seven slides is not enough for all three plus the technical case, and the technical case is what a professor panel is actually judging.
