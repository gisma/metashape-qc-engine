# Metashape GUI launcher strategy

## Principle

The GUI is a thin launcher over the `metashape-qc` CLI.

It must not reimplement variant generation, runner, evaluator, analyzer, or workflow logic. The GUI should collect user inputs, apply guard checks, call the CLI, and open generated outputs.

## Menu entries

- Configure Launcher
- Probe Orthomosaic Sampling
- Prepare Product Analysis
- Run Product Analysis
- Resume Product Analysis
- Evaluate Product Analysis
- Run Resolution Sensitivity
- Open Run Folder
- Open Evaluation Report
- Open Selected Product Trace

## Required GUI inputs

- image directory
- product id
- output root
- run directory
- preset/profile
- reps
- project_crs
- optional camera_crs
- optional Metashape directory
- optional fixed orthoRes
- optional advanced factor overrides

## GUI guards

Refuse prepare or run actions if `project_crs` is missing or still `USER_MUST_SET_PROJECT_CRS`.

Hide dataset-specific old presets from the generic preset list.

Generic probe must run with `reps=1` and no variants.

Reference preset must contain exactly one `orthoRes` per run.

Resolution sensitivity must create separate run directories per sampling stratum.

## User config

Future user configuration location:

```text
~/.config/metashape-qc-engine/gui_config.json
```

This file stores user paths and preferences only. It must not store shipped dataset defaults.

## Installation strategy

Future installation concept:

1. Install the `metashape-qc-engine` CLI.
2. Copy or load a future Metashape GUI launcher script.
3. Configure the CLI path, output root, Metashape directory, and `project_crs`.
4. Launch the menu from Metashape.

This describes the intended integration direction and does not claim that a plugin currently exists.

## Non-claims and boundaries

The GUI launcher preserves the same analysis boundary as the CLI.

Outputs support internal stability review only. They do not establish external accuracy, checkpoint validation, cross-date accuracy, change-detection suitability, platform comparison, or true scene detail.
