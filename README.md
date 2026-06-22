# metashape-qc-engine

## Project purpose

`metashape-qc-engine` is a product-analysis workflow for reproducible Agisoft Metashape orthomosaic candidate selection. It prepares candidate matrices, runs repeated Metashape builds, analyzes orthomosaic stability on a canonical grid, records support diagnostics, and writes a selected-product trace for review.

The workflow measures internal repeated-build stability and support persistence. It does not by itself establish absolute geometric accuracy, external truth, cross-date accuracy, platform comparison, or change-detection suitability.

## Current workflow

For one image set, `metashape-qc prepare` writes run-local control files from a preset and variants template. `metashape-qc run-analysis` executes the candidate x replicate matrix through the Metashape runtime bridge. `metashape-qc resume-analysis` continues an interrupted run directory by skipping successful work and rerunning failed or missing work. `metashape-qc evaluate` runs or reuses the analyzer, writes support and stability summaries, creates threshold review products, and records `selected_product.json`.

## Current command sequence

```bash
metashape-qc prepare \
  --image-dir "/path/to/input-images" \
  --product-id "product_id" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/path/to/runs"
```

`prepare` prints the concrete `metashape-qc run-analysis` command for the generated run directory.

```bash
metashape-qc run-analysis "<run_dir>/config.yml" \
  --variants "<run_dir>/variants.csv" \
  --reps 5 \
  --run-dir "<run_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

```bash
metashape-qc resume-analysis "<run_dir>/config.yml" \
  --variants "<run_dir>/variants.csv" \
  --reps 5 \
  --run-dir "<run_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

```bash
metashape-qc evaluate "<run_dir>"
```

## Current reference benchmark

The current reference benchmark is the MOF Alignment-Mesh-Ortho reference matrix:

- Image directory: `/datadisk/data/uav/MOF_repro_test_recovered/input-images`
- Preset: `config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json`
- Matrix: alignment downscale, adaptive fitting, mesh face count, mesh smoothing iterations, and requested orthomosaic pixel size
- Size: `48` processing candidates x `5` replicates = `240` Metashape runs

`buildOrthomosaic.orthoRes` is the requested orthomosaic pixel size / sampling resolution passed to Metashape. It is not a direct measure of geometric accuracy or true scene detail.

Dense Cloud, Depth Maps, Point Cloud, DSM/DEM quality, 3D reconstruction quality, GCP/checkpoint validation, cross-date accuracy, platform comparison, and change-detection suitability are outside the current MOF reference benchmark.

`config/experiments/presets/mesh_facecount_smoothing_3x3.json` remains useful as a small starter/example preset, but it is not the current reference benchmark.

## Documentation map

- [WORKFLOW_CHAIN.md](WORKFLOW_CHAIN.md): active architecture and runtime chain.
- [docs/quick_workflow.md](docs/quick_workflow.md): concise operational command guide.
- [docs/orthomosaic_stability_manual.md](docs/orthomosaic_stability_manual.md): maintained interpretation and workflow manual.
- [docs/product_manifest_contract.md](docs/product_manifest_contract.md): manifest, evaluator, threshold review, and selected-product contract.
- [docs/current_system_reference.md](docs/current_system_reference.md): code-derived current system reference.
- [docs/rationale_and_paper_argument_register.md](docs/rationale_and_paper_argument_register.md): rationale and paper argument register.
- [docs/legacy_document_mining_report.md](docs/legacy_document_mining_report.md): mining guidance for legacy material.
- [config/experiments/README.md](config/experiments/README.md): preset and matrix reference.

## Repository layout

- `metashape_qc_engine/`: thin installable CLI wrapper exposing `metashape-qc`.
- `python/`: Metashape workflow, preparation, reproducibility runner, analyzer, and evaluator scripts.
- `scripts/`: shell bridge for launching the workflow inside the Metashape runtime environment.
- `config/`: runtime YAML configs, experiment presets, variant templates, and legacy config material.
- `docs/`: active documentation, reference contracts, audit notes, and upstream/background material.
- `R/`: retained AM2-style helper scripts and compatibility material; not the current primary product-analysis path.
- `calibration/`: retained calibration CSV input/reference files.
- `prior-versions/`: archived workflow code for older Metashape compatibility/reference cases.

## License and attribution

This repository is distributed under the BSD 3-Clause License.

It contains adapted components from the UC Davis / AM2 / automate-metashape code base. Original copyright, author, license, and disclaimer notices are retained in `LICENSE`; project-specific attribution and scope notes are provided in `NOTICE.md`.
