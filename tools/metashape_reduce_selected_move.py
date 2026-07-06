#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Metashape: selected cameras -> thin by Reduce Overlap -> move retained images.

Run in Metashape via Tools -> Run Script.

Workflow:
1. Manually mark/select the cameras to process in the active chunk.
2. Run this script.
3. Choose the target folder.
4. The script temporarily restricts processing to the selected cameras, runs the
   existing fastCreateSparse-style thinning, and moves only the retained images.
"""

import os
import shutil

import Metashape


# Edit these values if needed.
OVERLAP = 8.0
KEYPOINT_LIMIT = 10000
TIEPOINT_LIMIT = 1000
DOWNSCALE = 4
QUALITY_THRESHOLD = 0.75

# If your folder dialog renders blank, set this manually, e.g.
# TARGET_DIR = r"D:\metashape_subset"
# TARGET_DIR = "/home/creu/metashape_subset"
TARGET_DIR = ""


def get_tie_points_source():
    if hasattr(Metashape.DataSource, "TiePointsData"):
        return Metashape.DataSource.TiePointsData
    return Metashape.DataSource.TiePoints


def unique_destination(target_dir, src):
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    dst = os.path.join(target_dir, base)

    counter = 1
    while os.path.exists(dst):
        dst = os.path.join(target_dir, "{}_{:03d}{}".format(stem, counter, ext))
        counter += 1

    return dst


def get_quality(camera):
    try:
        return float(camera.meta["Image/Quality"])
    except Exception:
        return None


def selected_reduce_overlap(chunk, selected_cameras):
    """Adapted from msSparseCloud.fastCreateSparse(), restricted to selection."""
    print("Analysiere Bildqualitaet der markierten Kameras...")
    chunk.analyzeImages(selected_cameras)

    disabled_by_quality = 0
    for camera in selected_cameras:
        quality = get_quality(camera)
        if quality is not None and quality < QUALITY_THRESHOLD:
            camera.enabled = False
            disabled_by_quality += 1

    print("Wegen Qualitaet deaktiviert:", disabled_by_quality)
    print("Erzeuge Sparse Cloud fuer markierte/aktive Kameras...")
    chunk.matchPhotos(
        downscale=DOWNSCALE,
        reference_preselection=True,
        keypoint_limit=KEYPOINT_LIMIT,
        tiepoint_limit=TIEPOINT_LIMIT,
        reset_matches=True,
    )
    chunk.alignCameras(adaptive_fitting=True, reset_alignment=True)

    print("Baue grobes Modell fuer Reduce Overlap...")
    chunk.buildModel(
        surface_type=Metashape.SurfaceType.HeightField,
        source_data=get_tie_points_source(),
        interpolation=Metashape.Interpolation.EnabledInterpolation,
        face_count=Metashape.FaceCount.LowFaceCount,
    )
    chunk.smoothModel(10)

    print("Fuehre Reduce Overlap aus. OVERLAP =", OVERLAP)
    chunk.reduceOverlap(overlap=OVERLAP, use_selection=False)
    chunk.resetRegion()


def move_retained_images(retained_cameras, target_dir):
    moved = 0
    skipped = 0
    moved_paths = {}

    for camera in retained_cameras:
        src = camera.photo.path

        if src in moved_paths:
            dst = moved_paths[src]
        else:
            if not src or not os.path.exists(src):
                print("Fehlt, uebersprungen:", camera.label, src)
                skipped += 1
                continue

            dst = unique_destination(target_dir, src)
            if os.path.abspath(src) == os.path.abspath(dst):
                print("Schon im Zielordner, uebersprungen:", src)
                skipped += 1
                continue

            shutil.move(src, dst)
            moved_paths[src] = dst
            moved += 1
            print("Verschoben:", src, "->", dst)

        try:
            camera.photo.path = dst
        except Exception as exc:
            print("Projektpfad nicht aktualisiert:", camera.label, exc)

    return moved, skipped


def main():
    doc = Metashape.app.document
    chunk = doc.chunk

    if chunk is None:
        Metashape.app.messageBox("Kein aktiver Chunk vorhanden.")
        return

    selected_cameras = [
        camera for camera in chunk.cameras
        if camera.selected and camera.photo and camera.photo.path
    ]

    if not selected_cameras:
        Metashape.app.messageBox("Keine markierten Kameras mit Bildpfad gefunden.")
        return

    target_dir = TARGET_DIR
    if not target_dir:
        target_dir = Metashape.app.getExistingDirectory(
            "Zielordner fuer ausgeduennte Bilder auswaehlen"
        )
    if not target_dir:
        print("Abgebrochen: kein Zielordner.")
        return
    os.makedirs(target_dir, exist_ok=True)

    original_enabled = {camera.key: camera.enabled for camera in chunk.cameras}
    selected_keys = {camera.key for camera in selected_cameras}

    try:
        print("Markierte Kameras:", len(selected_cameras))

        # Restrict the existing fastCreateSparse-style routine to the selection.
        for camera in chunk.cameras:
            camera.enabled = camera.key in selected_keys

        selected_reduce_overlap(chunk, selected_cameras)

        retained_cameras = [
            camera for camera in selected_cameras
            if camera.enabled and camera.photo and camera.photo.path
        ]
        rejected_cameras = [
            camera for camera in selected_cameras
            if not camera.enabled
        ]

        print("Nach Ausduennung behalten:", len(retained_cameras))
        print("Nach Ausduennung deaktiviert:", len(rejected_cameras))

        moved, skipped = move_retained_images(retained_cameras, target_dir)

    finally:
        # Restore only the non-selected cameras to their previous state. The
        # selected cameras keep the reduceOverlap enabled/disabled result.
        for camera in chunk.cameras:
            if camera.key not in selected_keys:
                camera.enabled = original_enabled[camera.key]

    print("Fertig.")
    print("Markierte Kameras:", len(selected_cameras))
    print("Behalten und verschoben:", len(retained_cameras))
    print("Ausgeduennt/deaktiviert:", len(rejected_cameras))
    print("Physisch verschobene Dateien:", moved)
    print("Uebersprungen:", skipped)
    print("Zielordner:", target_dir)


main()
