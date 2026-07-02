• ## Urteil

  Ja — besonders Level‑1B lässt sich deutlich vereinfachen, ohne die wissenschaftliche Funktion zu
  verändern.

  Nicht die Rasterverarbeitung ist das Hauptproblem. Der größte Ballast entsteht durch mehrfach
  abgesicherte Übergaben:

  1. Funktion liefert ein Ergebnis-Dictionary.
  2. Funktion schreibt einen Report.
  3. Funktion schreibt zusätzlich ein Step-Manifest.
  4. Runner liest dieses Manifest wieder.
  5. Runner vergleicht Rückgabestatus und Manifeststatus.
  6. Runner extrahiert Artefaktpfade aus dem Manifest.
  7. Runner prüft erneut die Existenz dieser Artefakte.

  Das ist für einen stabilen, einzeln betriebenen Applied-Science-Workflow unnötig.

  ## Was fachlich bleiben muss

  ### Level‑1A

  Der sinnvolle Kern ist bereits relativ klar:

  prepare
    → Varianten + Konfiguration
  run/resume
    → Metashape-Replikate + Versuchstabelle
  evaluate
    → Stabilitätsanalyse + Produktauswahl

  manifest.csv sollte bleiben. Es ist keine künstliche Framework-Schicht, sondern die tatsächliche
  Versuchstabelle aus Variante × Replikat. Resume und Auswertung lesen diese Tabelle direkt:

  - Schreiben und Resume: python/reproducibility_runner.py:302
  - Analyse: python/ortho_stability_analyzer.py:99
  - Produktauswahl: python/evaluate_ortho_stability.py:1285

  Behalten werden sollten:

  - Replikatkonfigurationen
  - manifest.csv
  - Launcher-Logs
  - Orthomosaike
  - Stabilitätsraster
  - summary.csv
  - selected_product.json

  Level‑1A hat keinen vergleichbaren allgemeinen Manifest-Overhead wie Level‑1B.

  ### Level‑1B

  Der wissenschaftliche Kern ist ebenfalls klar:

  Maske
  → Proxykanäle
  → Skalierung
  → räumliche Skalen
  → ranger
  → Perturbationen
  → Segmentierungsfamilien
  → Step-9a Bewertung
  → Step-9b Midpoint/Handoff
  → Step-10 Materialisierung und Evidenz

  Die sinnvollen modularen Erweiterungspunkte sind:

  - Kanal-/Proxy-Erzeugung
  - Skalierung
  - Skalenableitung
  - Perturbationsgenerator
  - Segmentierungsbackend
  - Response-Surface-Metriken
  - Ranking/Handoff
  - finale Evidenzstatistik

  Dafür braucht es keine Plugin-Architektur. Einfache Python-Funktionen mit klaren Ein- und
  Ausgaben genügen.

  ## Der entbehrliche Level‑1B-Überbau

  ### 1. Allgemeine Step-Manifeste

  Der Runner liest nach praktisch jedem Schritt ein zusätzliches Manifest und prüft dessen Status
  und Artefakte:

  - Hilfslogik: metashape_qc_engine/level1b_dumb_runner.py:85
  - Beispiel Maske: metashape_qc_engine/level1b_dumb_runner.py:175
  - Beispiel Step‑9a: metashape_qc_engine/level1b_dumb_runner.py:380
  - Beispiel Step‑10: metashape_qc_engine/level1b_dumb_runner.py:490

  Das Manifest-Framework selbst steht in metashape_qc_engine/level1b_step_manifest.py:8.

  Nach aktueller Suche konsumiert nur der Runner diese allgemeinen Step-Manifeste. Die
  wissenschaftlichen Folgeschritte lesen überwiegend die eigentlichen Dateien.

  Diese Schicht kann vollständig verschwinden. Der Runner kann unmittelbar verwenden:

  result = run_step(config)
  if result["status"] != "ok":
      raise RuntimeError(...)
  next_input = Path(result["output_path"])

  Ein vorhandener fachlicher Report pro Schritt reicht als Resume- und Prüfartefakt.

  ### 2. Zu viele Statusbegriffe

  Level‑1B enthält mehr als hundert statusähnliche Zeichenketten. Viele beschreiben nicht
  wissenschaftliche Zustände, sondern Absicherungen von Absicherungen.

  Für den normalen Lauf reichen grundsätzlich:

  ok
  failed
  user_choice_required

  Zusätzliche fachliche Diagnosen gehören als reason oder warnings in den Report, nicht als neue
  Workflow-Zustandsmaschine.

  ### 3. Step‑10 serialisiert dieselben Daten mehrfach

  Step‑10 besitzt bereits ein sinnvolles kanonisches Objekt:

  - finalist_evidence.json
  - Lesen/Schreiben: metashape_qc_engine/level1b_materialization.py:14

  Danach werden dieselben Zeilen jedoch erneut als mehrere JSON- und CSV-Dateien geschrieben und
  zusätzlich manifestiert:

  metashape_qc_engine/level1b_materialization.py:248

  Praktisch ausreichend wäre:

  finalist_evidence.json          # kanonische Daten
  finalist_evidence.csv           # optional für Menschen/QGIS/R
  selected_labels.tif
  selected_segments.gpkg
  exactextractr_stats.csv
  quality_info.json
  figures/

  Materialisierung, Abbildungen und exactextractr können alle dasselbe finalist_evidence.json
  lesen.

  ### 4. Step‑9 ist wissenschaftlicher Kern und Kontrollsystem zugleich

  metashape_qc_engine/level1b_candidate_response_surface.py:1 hat 3428 Zeilen und enthält
  gleichzeitig:

  - Segmentierungsausführung
  - Resume
  - Legacy-Resume
  - Retention-Audit
  - Dateibereinigung
  - Populationsstatistik
  - räumliche Statistik
  - Score
  - Ranking
  - Scale Gate
  - Step‑9b Preflight
  - Midpoint-Erzeugung
  - Handoff
  - CSV/JSON-Ausgabe
  - Manifest-Ausgabe

  Das ist der größte Entwicklungsklotz.

  Nicht neu abstrahieren, sondern schlicht entlang der realen Arbeit teilen:

  level1b_segmentation_runs.py
  level1b_response_metrics.py
  level1b_step9.py
  level1b_step9b.py

  Dabei bleiben die reinen wissenschaftlichen Funktionen separat testbar.

  ### 5. Berichte enthalten programmatische Selbstverteidigung

  Der One-Scale-Report enthält zahlreiche Felder wie:

  - no_scale_selection_performed
  - no_zonal_statistics_performed
  - no_python_raster_processing
  - downstream_vector_product_status
  - vectorization_status

  Siehe metashape_qc_engine/level1b_one_scale_segmentation.py:612.

  Das dokumentiert frühere Prompt-Grenzen, nicht den wissenschaftlichen Lauf. Ein Run-Report
  braucht stattdessen:

  run_id
  candidate/group
  parameters
  input stack
  mask
  command
  status
  output labels
  failure reason

  ### 6. Parallelformate ohne klare Autorität

  Step‑9 schreibt viele Tabellen parallel als JSON und CSV:

  metashape_qc_engine/level1b_candidate_response_surface.py:3181

  Das ist nur sinnvoll, wenn beide Formate tatsächlich gebraucht werden. Pro Tabelle sollte
  gelten:

  - ein kanonisches Maschinenformat;
  - optional ein daraus erzeugter menschlicher Export.

  Nicht beide als gleichwertige Workflow-Eingaben behandeln.

  ### 7. Legacy- und Alternativpfade liegen im aktiven Code

  Beispiele:

  - Legacy-Resume: metashape_qc_engine/level1b_candidate_response_surface.py:2620
  - alter 5-Band/TEX-Fallback: metashape_qc_engine/level1b_scale_distribution.py:212
  - Hoover-/Candidate-Stability-Code wird vom normalen Runner nicht aufgerufen.

  Wenn nur ein dokumentierter Produktionsweg gewünscht ist, sollten solche Pfade nicht dauerhaft
  im aktiven Modul verbleiben. Alte Runs können mit einem Git-Tag und der damaligen Version lesbar
  bleiben.

  ## Shell und R

  ### Shell

  Der Level‑1B-Wrapper ist zwar mit 118 Zeilen relativ lang, aber die OTB-/Python-
  Umgebungstrennung ist praktisch notwendig:

  metashape_qc_engine/run_level1b_dumb_with_user_header.sh:14

  Diese Logik würde ich nicht als AI-Framework-Ballast entfernen. Sie löst einen realen Konflikt
  zwischen OTB-Bibliotheken und dem Python-GDAL der virtuellen Umgebung.

  ### R

  Im normalen Level‑1B-Lauf wird nur dieses R-Skript tatsächlich aufgerufen:

  R/level1b_step10_exactextractr_segment_stats.R:1

  Der Aufruf erfolgt hier:

  metashape_qc_engine/level1b_materialization.py:1043

  Das R-Skript ist direkt, nachvollziehbar und fachlich sinnvoll. Es ist kein Vereinfachungsziel.

  Die übrigen R-Skripte sind nach aktueller Code-Suche keine Bestandteile des normalen Level‑1A-
  oder Level‑1B-Runners. Sie sollten aus der aktiven Workflow-Darstellung herausgenommen werden,
  ohne sie zwingend sofort zu löschen.

  ## Sinnvolles Zielbild

  ### Level‑1A

  metashape-qc prepare
  metashape-qc run-analysis / resume-analysis
  metashape-qc evaluate

  Ein zentraler Laufindex: manifest.csv.

  ### Level‑1B

  Shell: nur Umgebung und Logging
  Python-Runner: nur lineare Aufrufreihenfolge
  wissenschaftliche Module: Berechnung
  ein Report pro schwerem Schritt
  ein kanonischer Evidenzdatensatz
  finale Raster/Vektor/Statistikprodukte

  Keine:

  - allgemeinen Step-Manifeste,
  - doppelten Statusabgleiche,
  - Schema-Frameworks,
  - Aliaslisten,
  - automatischen Fallbackpfade,
  - versteckten Legacy-Reader,
  - vollständigen Step-Rückgaben im Chain-Report.

  ## Erwartbare Reduktion

  Ohne wissenschaftliche Änderungen halte ich für realistisch:

  - Runner: etwa halb so groß;
  - Step‑10-Kontroll-/Serialisierungscode: deutlich mehr als ein Drittel weniger;
  - Step‑9: erhebliche Verständlichkeitssteigerung durch Trennung, auch wenn die
    wissenschaftlichen Berechnungen bleiben;

  - insgesamt im aktiven Level‑1B-Pfad wahrscheinlich etwa 25–35 % weniger Code;
  - wesentlich größere Reduktion der mentalen Komplexität als der reinen Zeilenzahl.

  ## Sichere Reihenfolge

  1. Einen aktuellen vollständigen Referenzlauf mit dem neuen 6-Band-Stack festhalten.
  2. Allgemeine Level‑1B-Step-Manifeste entfernen; direkte Rückgaben und feste Pfade verwenden.
  3. Step‑10 auf finalist_evidence.json als einzige interne Wahrheit reduzieren.
  4. Reports auf wissenschaftlich und operativ relevante Felder kürzen.
  5. Step‑9 nach Ausführung, Metriken und Step‑9b trennen.
  6. Legacy-/Fallbackpfade aus dem aktiven Produktionscode herausnehmen.
  7. Erst danach redundante CSV/JSON-Exporte reduzieren.
  8. Level‑1A anschließend nur leicht bereinigen; manifest.csv und Resume-Struktur behalten.

  Kurz: Ja, dramatisch vereinfachbar. Level‑1B ist wissenschaftlich modular genug, aber operativ
  von einem unnötigen Contract-/Manifest-/Statusgerüst umschlossen. Dieses Gerüst kann weg, ohne
  die Methodik anzutasten. Es wurden keine Dateien verändert.