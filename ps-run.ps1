 $ErrorActionPreference = "Stop"

  Set-Location "C:\Users\creu\Documents\proj\metashape-qc-engine"

  $IMAGE_DIR = "D:\UAV-DATA\MOF\2024\auswahl"
  $PRODUCT_ID = "MOF_09072024_core"
  $REPS = 5

  $L1A_ROOT = "D:\UAV-DATA\MOF\2024\level1a_runs"
  $L1A_RUN = Join-Path $L1A_ROOT "${PRODUCT_ID}_alignment_mesh_ortho_reference_reps${REPS}"
  $L1B_RUN = "D:\UAV-DATA\MOF\2024\level1b_runs\${PRODUCT_ID}_level1b"

  $env:OTB_ROOT = "C:\Users\creu\Documents\otb"
  $env:SAGA_ROOT = "C:\Users\creu\AppData\Local\Programs\OSGeo4W\apps\saga\saga_cmd.exe"

  $QC = Join-Path $PWD ".conda-env\Scripts\metashape-qc.exe"

  if (-not (Test-Path $QC)) {
      throw "metashape-qc.exe fehlt: $QC"
  }

  # Level 1A vorbereiten
  $PrepareArgs = @(
      "prepare"
      "--image-dir", $IMAGE_DIR
      "--product-id", $PRODUCT_ID
      "--preset", "config\experiments\presets\mof_alignment_mesh_ortho_reference_v1.json"
      "--reps", $REPS
      "--output-root", $L1A_ROOT
  )

  & $QC @PrepareArgs
  if ($LASTEXITCODE -ne 0) { throw "Level-1A prepare failed: $LASTEXITCODE" }

  # Level 1A ausführen
  $AnalysisArgs = @(
      "run-analysis"
      "$L1A_RUN\config.yml"
      "--variants", "$L1A_RUN\variants.csv"
      "--reps", $REPS
      "--run-dir", $L1A_RUN
  )

  & $QC @AnalysisArgs
  if ($LASTEXITCODE -ne 0) { throw "Level-1A run-analysis failed: $LASTEXITCODE" }

  # Level 1A auswerten
  & $QC evaluate $L1A_RUN
  if ($LASTEXITCODE -ne 0) { throw "Level-1A evaluation failed: $LASTEXITCODE" }

  # Ausgewähltes Orthomosaik übernehmen
  $SelectionFile = Join-Path $L1A_RUN "selected_product.json"
  if (-not (Test-Path $SelectionFile)) {
      throw "Auswahldatei fehlt: $SelectionFile"
  }

  $SelectedProduct = Get-Content $SelectionFile -Raw | ConvertFrom-Json
  $ORTHO = $SelectedProduct.product_modes.median_ortho.path

  if (-not (Test-Path $ORTHO -PathType Leaf)) {
      throw "Selected Level-1A orthomosaic missing: $ORTHO"
  }

  # Level 1B starten
  $env:ORTHO = $ORTHO
  $env:RUN_ROOT = $L1B_RUN
  $env:OVERWRITE = "0"

  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
      "metashape_qc_engine\run_level1b_dumb_with_user_header.ps1"

  if ($LASTEXITCODE -ne 0) {
      throw "Level-1B failed: $LASTEXITCODE"
  }