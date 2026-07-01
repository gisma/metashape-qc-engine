# Level‑1B Candidate Stability and Segment Selection – User Manual

## Praxisblock / Quickstart

This workflow evaluates and selects the most stable segmentation scale for an RGB orthomosaic.
It runs a fully automated chain of pre‑processing, candidate‑scale evaluation, a local midpoint
handoff, and final materialisation of the selected segments as a **GPKG vector layer** together
with quality‑information JSON.

The workflow is implemented in the module
`metashape_qc_engine.level1b_dumb_runner` and does *not* require the full
metashape‑reproducibility experiment infrastructure.

## Beispielaufruf / Example invocation

