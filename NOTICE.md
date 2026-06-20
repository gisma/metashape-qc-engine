# Notice

This repository is developed as `metashape-qc-engine`, a Python-first quality-control and reproducibility engine for Agisoft Metashape workflows.

It contains adapted components from the UC Davis / AM2 / automate-metashape code base, distributed under the BSD 3-Clause License. The original copyright and license notice are retained in `LICENSE`.

Upstream-derived or adapted runtime components include, at minimum:

- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py`
- `python/read_yaml.py`
- `scripts/run_metashape_workflow.sh`

Substantial additions developed in `metashape-qc-engine` include:

- reproducibility experiment control
- variant and replicate execution
- orthomosaic stability analysis
- support-aware evaluation reporting
- controlled product-generation logic

The names of the original copyright holders and contributors are not used to endorse this derived project.
