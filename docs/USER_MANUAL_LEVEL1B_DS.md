# Level‑1B Candidate Stability and Segment Selection – User Manual

## Praxisblock / Quickstart

The Level‑1B DS workflow takes a single **RGB orthomosaic** and automatically
selects the most stable segmentation scale.  It runs a chain of pre‑processing
steps, candidate‑scale evaluation, a local midpoint handoff, and finally
materialises the selected segments as a **GPKG vector layer** together with
quality‑information JSON.

The workflow is implemented in the module
`metashape_qc_engine.level1b_dumb_runner` and does **not** require the full
metashape‑reproducibility experiment infrastructure.

## Beispielaufruf / Example invocation

