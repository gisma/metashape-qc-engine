# Orthomosaic Stability Workflow — Manual

Dieses Manual beschreibt den Standardablauf für wiederholbare UAV-Orthomosaik-Experimente mit Metashape und anschließender Stabilitätsanalyse.

Der Workflow hat drei Arbeitsstufen:


1. Einzelner Metashape-Ortho-Lauf
2. Varianten × Replikate mit dem Reproducibility Runner
3. Canonical-Grid-Stabilitätsanalyse


Die vollständigen YAML- und Parameterdetails stehen im Anhang:
[Parameter and File Reference](orthomosaic_stability_reference.md)

## 1. Projektstruktur

Jeder Datensatz bekommt einen eigenen Projektordner.

```text
PROJECT_ROOT/
  input-images/
  runs/
```

Die Bilddaten liegen ausschließlich in:

```text
PROJECT_ROOT/input-images/
```

Alle erzeugten Produkte liegen unter:

```text
PROJECT_ROOT/runs/
```

Beispiel:

```text
/datadisk/data/uav/MOF_repro_test_recovered/
  input-images/
    DJI_....JPG
    DJI_....JPG
    ...
  runs/
```

`input-images/` ist der saubere Eingabeordner für Metashape. Dort liegen nur die Bilder, die verarbeitet werden sollen. `runs/` enthält Metashape-Projekte, Orthomosaike, Logs, Manifeste und Stabilitätsprodukte.

Die zentrale Steuerdatei für den Datensatz ist:

```text
config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml
```

Sie verweist auf `input-images/` und auf die Ausgabeordner unter `runs/`.

Die Variantenmatrix ist:

```text
config/experiments/repro_variants_mesh_regularization.csv
```

Sie definiert die drei Standardvarianten `flat_mesh`, `moderate_mesh` und `light_mesh`.

## 2. Einzelner Metashape-Ortho-Lauf

Minimaler Default-Aufruf:

```bash
cd ~/dev/metashape-qc-engine

METASHAPE_DIR="/home/creu/apps/metashape-pro" \
scripts/run_metashape_workflow.sh config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml
```

Dieser Lauf führt genau die Base-YAML aus. Er erzeugt einen einzelnen Metashape-Lauf ohne Varianten und ohne Wiederholungen.

Der Einzelrun dient dazu, zu prüfen, ob die Basissteuerung funktioniert: Bilder werden geladen, Photos werden ausgerichtet, Tiepoints werden gefiltert, Kameras werden optimiert, ein Mesh aus Tiepoints wird gebaut, geglättet und als Projektionsfläche für ein Orthomosaik verwendet.

Der Default ist bewusst mesh-basiert:

```text
TiePointsData -> smoothed mesh -> mesh orthomosaic
```

Depth Maps, Dense Cloud und DEM/DSM sind im Standard deaktiviert. Der aktuelle Test fragt nicht nach der besten Dense-Rekonstruktion, sondern nach der Stabilität der Orthoprojektion über eine regularisierte Mesh-Oberfläche.

Die wichtigste Default-Entscheidung ist:

```yaml
buildOrthomosaic:
  surface: ["Mesh"]
```

und:

```yaml
buildModel:
  source_data: Metashape.TiePointsData
```

Das Orthomosaik wird also nicht aus einem DSM erzeugt, sondern aus einem Mesh, das aus Tiepoints gebaut und geglättet wird.

Die Ausgabe des Einzelruns landet in den Pfaden aus der Base-YAML:

```text
PROJECT_ROOT/runs/single_run/psx/
PROJECT_ROOT/runs/single_run/output/
```

## 3. Varianten × Replikate

Minimaler Default-Aufruf:

```bash
cd ~/dev/metashape-qc-engine

EXP=/datadisk/data/uav/MOF_repro_test_recovered/runs/experiment_mesh_variants_reps5

python3 python/reproducibility_runner.py \
  config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml \
  --variants config/experiments/repro_variants_mesh_regularization.csv \
  --reps 5 \
  --experiment-dir "$EXP" \
  --metashape-dir /home/creu/apps/metashape-pro
```

Dieser Schritt ist das eigentliche Reproducibility-Experiment.

Der Runner nimmt die Base-YAML und erzeugt daraus mehrere konkrete YAML-Dateien: eine pro Variante und Replikat. Jede dieser generierten YAMLs hat eigene Ausgabeordner, eigene Projektordner und einen eigenen `run_name`.

Mit dem Default-Setup entstehen:

```text
3 Varianten × 5 Replikate = 15 Metashape-Läufe
```

Die drei Default-Varianten testen die Regularisierung der Projektionsfläche:

```text
flat_mesh      stark geglättetes, einfaches Mesh
moderate_mesh  mittlere Mesh-Regularisierung
light_mesh     detailreicheres, schwach geglättetes Mesh
```

Der wichtigste Parameter ist dabei:

```yaml
buildModel:
  noiterations: ...
```

Er steuert die Glättung des Meshes.

Der zweite wichtige Parameter ist:

```yaml
buildModel:
  face_count: ...
```

Er steuert die Mesh-Komplexität.

Die Standardvarianten sind so gesetzt, dass sie eine einfache Achse abbilden:

```text
stark regularisiert -> mittel regularisiert -> schwach regularisiert
```

Das Ergebnis des Runners ist ein Experimentordner:

```text
PROJECT_ROOT/runs/experiment_mesh_variants_reps5/
  manifest.csv
  variants/
    flat_mesh/
    moderate_mesh/
    light_mesh/
```

Die wichtigste Datei ist:

```text
manifest.csv
```

Sie ist das Inhaltsverzeichnis des Experiments. Sie sagt, welche Variante und welches Replikat zu welchem Metashape-Projekt, welchem Log und welchem exportierten Orthomosaik gehört.

## 4. Stabilitätsanalyse

Minimaler Default-Aufruf:

```bash
python3 python/ortho_stability_analyzer.py \
  "$EXP/manifest.csv" \
  --output-dir "$EXP/stability_union" \
  --grid-mode union \
  --bands 3 \
  --stable-rmse-threshold 15 \
  --overwrite
```

Der Analyzer liest die `manifest.csv` und verwendet alle erfolgreichen Orthomosaik-Exports.

Metashape-Orthomosaike aus wiederholten Läufen können leicht unterschiedliche Rasterausdehnungen haben. Deshalb werden sie vor dem Vergleich auf ein gemeinsames Analyse-Raster gebracht. Dieses Raster heißt Canonical Grid.

Der Default ist:

```text
--grid-mode union
```

`union` bedeutet: Das gemeinsame Raster umfasst die gesamte Ausdehnung aller Orthomosaike. Dadurch bleiben auch wechselnde Randbereiche und unterschiedlicher Bildsupport sichtbar.

Für RGB-Orthomosaike ist der Default:

```text
--bands 3
```

Die ersten drei Bänder werden als RGB analysiert.

Die Stabilitätsmaske wird mit folgender Schwelle erzeugt:

```text
--stable-rmse-threshold 15
```

Ein Pixel gilt als stabil, wenn er in allen Replikaten gültig ist und seine RMSE-Abweichung vom Median-Orthomosaik höchstens 15 DN beträgt. Bei 8-bit-RGB liegt die Bildskala bei 0–255.

Die wichtigsten Analyzer-Produkte sind:

```text
valid_count.tif
median_ortho.tif
mad_rgb.tif
rmse_to_median.tif
stable_mask_rmse15.tif
unstable_mask_rmse15.tif
summary.csv
```

`valid_count.tif` zeigt, in wie vielen Replikaten ein Pixel gültigen Bildsupport hatte.

`median_ortho.tif` ist das robuste Median-Orthomosaik einer Variante.

`mad_rgb.tif` zeigt robuste Abweichungen vom Medianbild.

`rmse_to_median.tif` zeigt RMSE-Abweichungen vom Medianbild.

`stable_mask_rmse15.tif` markiert stabile Bereiche.

`unstable_mask_rmse15.tif` markiert instabile Bereiche.

`summary.csv` fasst die Stabilität je Variante tabellarisch zusammen.

## 5. Ergebnis lesen

Eine Variante ist stabiler, wenn sie insgesamt:

```text
mehr vollständigen Bildsupport hat
geringere MAD-Werte hat
geringere RMSE-Werte hat
einen höheren stabilen Support-Anteil hat
einen niedrigeren instabilen Support-Anteil hat
```

Die wichtigsten Summary-Spalten sind:

```text
full_support_fraction
mean_mad_rgb
p95_mad_rgb
mean_rmse_to_median
p95_rmse_to_median
stable_fraction_support_rmse
unstable_fraction_support_rmse
```

Die Werte messen Reproduzierbarkeit des Orthomosaikprodukts. Sie beweisen keine absolute geometrische Richtigkeit. Eine Variante kann reproduzierbar sein und trotzdem geometrisch falsch liegen. Für geometrische Genauigkeit braucht es eine eigene Validierung.

Für die QGIS-Sichtung sind diese Layer zentral:

```text
median_ortho.tif
valid_count.tif
rmse_to_median.tif
stable_mask_rmse15.tif
unstable_mask_rmse15.tif
```

`median_ortho.tif` dient als Hintergrund. `rmse_to_median.tif` zeigt Abweichungshotspots. `valid_count.tif` zeigt den stabilen oder instabilen Bildsupport. Die Masken trennen stabile und instabile Bereiche.

## 6. Default ändern

Die meisten Einstellungen bleiben unverändert. Normalerweise werden nur diese Punkte angepasst:

`photo_path`
zeigt auf den `input-images/`-Ordner des aktuellen Datensatzes.

`output_path` und `project_path`
zeigen auf Unterordner von `runs/`.

`run_name`
benennt Datensatz und Workflow.

`project_crs`
setzt das Zielkoordinatensystem der Exporte.

`orthoRes`
setzt die Orthomosaik-Auflösung.

`--reps`
setzt die Zahl der Wiederholungen.

`--stable-rmse-threshold`
setzt die Schwelle für stabile Pixel.

Die komplette Parameterreferenz steht im Anhang:
[Parameter and File Reference](orthomosaic_stability_reference.md)


## Auswertung

Nach Abschluss der Metashape-Replikate wird die Auswertung mit einem einzigen Evaluationsskript gestartet:

```bash
cd ~/dev/metashape-qc-engine

python3 python/evaluate_ortho_stability.py \
  /datadisk/data/uav/MOF_repro_test_recovered/runs/experiment_mesh_variants_reps5
```

Das Skript führt den Stability Analyzer aus, wertet die `summary.csv` aus und schreibt einen kompakten Auswertungsreport.

Die Ergebnisse liegen anschließend im Ordner:

```text
PROJECT_ROOT/runs/experiment_mesh_variants_reps5/stability_union/
```

Die wichtigsten Dateien sind:

```text
evaluation_report.md
summary_key_metrics.tsv
qgis_layers.txt
summary.csv
```

`evaluation_report.md` enthält die kompakte Bewertung der Varianten.

`summary_key_metrics.tsv` enthält die wichtigsten Kennwerte in reduzierter Tabellenform.

`qgis_layers.txt` listet die relevanten Rasterprodukte für die räumliche Sichtung.

`summary.csv` enthält die vollständige Ergebnistabelle des Analyzers.

Die Default-Bewertung sortiert die Varianten nach folgender Logik:

```text
1. höherer stabiler Support-Anteil
2. niedrigeres p95-RMSE zum Median-Orthomosaik
3. niedrigeres mittleres RMSE zum Median-Orthomosaik
4. höherer vollständiger Bildsupport
```

Diese Bewertung beschreibt die Reproduzierbarkeit des Orthomosaikprodukts. Sie ersetzt keine unabhängige geometrische Validierung.
