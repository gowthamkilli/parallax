"""Live two-screen judge/soldier demo app.

Judge screen: click-to-place enemy position + category presets, drives the
real EdgeNode -> FusionEngine pipeline (blast + triangulation only -- see
pipeline.py). Soldier screen: bearing dial + readout banner only, polling
the same local state.

Run with:  python -m demo_app.server
"""
