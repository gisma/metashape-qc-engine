# Level-1b documentation set

Updated on 2026-06-26 after the Step-9 response-surface implementation.

This documentation set contains three manuals:

1. [`LEVEL1B_USER_MANUAL.md`](LEVEL1B_USER_MANUAL.md) — operational start/run/check documentation.
2. [`LEVEL1B_TECHNICAL_REFERENCE.md`](LEVEL1B_TECHNICAL_REFERENCE.md) — modules, dataclasses, run functions, outputs and current Step-9 API.
3. [`LEVEL1B_CONCEPTUAL_MANUAL.md`](LEVEL1B_CONCEPTUAL_MANUAL.md) — methodological rationale, scale-domain logic, response-surface analysis and formulas.

Current documentation policy:

```text
Step 6 remains as implemented.
The manuals do not request or describe further Step-6 code changes.
The current update is a documentation update for the new active Step-9 response-surface workflow.
```

Current active Step-9 implementation:

```text
metashape_qc_engine.level1b_candidate_response_surface
Level1BCandidateResponseSurfaceConfig
run_candidate_response_surface_step
```

Legacy/Audit Step-9 implementation:

```text
metashape_qc_engine.legacy.level1b_candidate_stability_hoover_archive
```

The active Step 9 no longer uses full OTB Hoover comparison as the default criterion. Hoover is retained only as archived legacy/audit logic. The current driver Step-9 block is documented as `step9_candidate_response_surface`.

Important source status for this manual update:

```text
Step 6 is left unchanged.
Step 9 is documented as candidate-scale response surface analysis.
Existing one-scale segmentation remains the segmentation backend.
No final vector layer or selected final scale is produced by Level-1b.
```
