import Metashape
import os
import shutil

# Auswahlmodus:
# "selected" = nur aktuell selektierte/rosa Kameras kopieren
# "enabled"  = alle aktivierten Kameras kopieren
MODE = "selected"

doc = Metashape.app.document
chunk = doc.chunk

target_dir = Metashape.app.getExistingDirectory("Zielordner für Bildkopien auswählen")

if not target_dir:
    print("Abgebrochen: kein Zielordner gewählt.")
else:
    copied = 0
    skipped = 0

    for cam in chunk.cameras:
        if not cam.photo:
            continue

        if MODE == "selected" and not cam.selected:
            continue

        if MODE == "enabled" and not cam.enabled:
            continue

        src = cam.photo.path

        if not src or not os.path.exists(src):
            print("Fehlt:", cam.label, src)
            skipped += 1
            continue

        base = os.path.basename(src)
        name, ext = os.path.splitext(base)
        dst = os.path.join(target_dir, base)

        # Falls identische Dateinamen aus verschiedenen Ordnern kommen
        i = 1
        while os.path.exists(dst):
            dst = os.path.join(target_dir, f"{name}_{i:03d}{ext}")
            i += 1

        shutil.copy2(src, dst)
        copied += 1

    print("Fertig.")
    print("Kopiert:", copied)
    print("Übersprungen:", skipped)
    print("Zielordner:", target_dir)
