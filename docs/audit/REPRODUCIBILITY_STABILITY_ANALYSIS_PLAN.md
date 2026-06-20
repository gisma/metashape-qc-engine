# Reproducibility-driven Orthomosaic Stability Analysis

This document defines the next development phase after the successful Ortho+ mesh orthomosaic integration.

The central tool is not the orthomosaic build itself, but the reproducibility analysis of repeated builds. The workflow should identify spatial image regions that remain stable across repeated Metashape builds and separate them from regions that vary because of the photogrammetric build process.

## Current technical base

The repository now has:

- a working procedural automate-metashape workflow,
- a working Metashape runtime bootstrap,
- a working mesh-based Ortho+ path,
- a working reproducibility runner for repeated builds.

The Ortho+ path is a build route. The reproducibility analysis is the methodological core.

## Methodological idea

Repeated Metashape builds are treated as samples from the processing pipeline. A single orthomosaic is not interpreted as the final truth. Instead, several formally identical builds are compared to identify the reproducible orthomosaic support.

The target products are:

- median orthomosaic,
- valid-count layer,
- robust deviation layer,
- local similarity / correlation layer,
- stability score,
- stable mask,
- unstable mask.

## Forest orthomosaic hypothesis

Older forest workflows often produced the best visual orthomosaics by strongly smoothing or flattening the mesh. This can be interpreted as projection-surface regularization. The mesh no longer represented individual canopy structure, but a stable terrain/canopy hull for orthoprojection.

The working hypothesis is:

- strong surface regularization increases forest orthomosaic reproducibility but reduces local detail,
- newer Metashape versions may require less aggressive mesh regularization,
- this question is mainly about projection-surface regularization, not tiepoint optimization.

## Experimental factor

The first experimental axis is mesh / projection-surface regularization.

Initial variants:

- flat_mesh: low face count, strong smoothing,
- moderate_mesh: current Ortho+ default,
- light_mesh: less smoothing, more structure,
- dense_dsm: classic dense-cloud / DSM route.

## Architecture

automate-metashape remains the build engine.

reproducibility_runner.py becomes the experiment engine.

A later stability analyzer will read the manifest and compute raster-based stability products outside Metashape.

MetashapeTools remains a reference for reproducibility, sparse-cloud optimization, and diagnostic exports. It is not imported directly.
