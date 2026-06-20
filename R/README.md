# R adapter / legacy AM2 helpers

This directory contains R-side helper scripts inherited from or compatible with the AM2 / automate-metashape workflow style.

The primary runtime core of `metashape-qc-engine` is Python-based. The R scripts are retained to support existing AM2-style configuration and project-preparation workflows, especially for users who organize Metashape processing from R or RStudio.

These scripts should be treated as an adapter / compatibility layer. New core functionality should normally be implemented in the Python engine first and only exposed to R through a thin adapter when needed.
