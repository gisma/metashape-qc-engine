# Level-1b documentation set

Generated from the uploaded documentation bundle `level1_doc_bundle` on 2026-06-26 14:30.

This set contains three separate manuals:

1. [`LEVEL1B_USER_MANUAL.md`](LEVEL1B_USER_MANUAL.md) — operational start/run/check documentation.
2. [`LEVEL1B_TECHNICAL_REFERENCE.md`](LEVEL1B_TECHNICAL_REFERENCE.md) — modules, functions, dataclasses, arguments and outputs.
3. [`LEVEL1B_CONCEPTUAL_MANUAL.md`](LEVEL1B_CONCEPTUAL_MANUAL.md) — methodological rationale, formulas and ecological/UAV-scale interpretation.

Current bundle state:

```text
M metashape_qc_engine/level1b_scale_distribution.py
 M tests/test_level1b_scale_distribution.py
?? metashape_qc_engine/level1b_candidate_stability.py
?? tests/test_level1b_candidate_stability.py
```

Changed tracked files reported by the bundle:

```text
metashape_qc_engine/level1b_scale_distribution.py
tests/test_level1b_scale_distribution.py
```

Latest run root in the bundle:

```text
/datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_20260626T154455
```

Important status note: the latest bundled chain run completed Steps 1–8 and failed at Step 9 because the driver imported `run_candidate_stability_step`; the module exports `run_candidate_stability`. The user manual documents the corrected Step-9 call and a resume path.
