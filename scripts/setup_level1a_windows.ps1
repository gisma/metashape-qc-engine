[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$PythonStatus = "OK"
$ImportStatus = "OK"
$GdalStatus = "MISSING"
$MetashapeStatus = "MISSING"

function Ok([string]$Text) { Write-Host "OK: $Text" }
function Missing([string]$Text) { Write-Warning "MISSING: $Text" }

Set-Location $RepoRoot
$Py = Get-Command py -ErrorAction SilentlyContinue
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Py -and -not $Python) {
    throw "Python 3 not found; make py.exe or python.exe available on PATH."
}

if (-not (Test-Path $VenvPython -PathType Leaf)) {
    if ($Py) { & $Py.Source -3 -m venv $VenvDir }
    else { & $Python.Source -m venv $VenvDir }
    if ($LASTEXITCODE -ne 0) { throw "Could not create venv at $VenvDir" }
    Ok "created Python venv at $VenvDir"
} else {
    Ok "using existing Python venv at $VenvDir"
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $VenvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "editable project installation failed" }

$Cli = Join-Path $VenvDir "Scripts\metashape-qc.exe"
if (Test-Path $Cli -PathType Leaf) { Ok "metashape-qc: $Cli" }
else { $PythonStatus = "MISSING"; Missing "metashape-qc.exe in venv" }

& $VenvPython -c "import numpy, rasterio, yaml"
if ($LASTEXITCODE -eq 0) { Ok "Python imports: numpy, yaml, rasterio" }
else { $ImportStatus = "MISSING"; Missing "Python imports: numpy, yaml, rasterio" }

& $VenvPython -c "from osgeo import gdal"
if ($LASTEXITCODE -eq 0) { $GdalStatus = "OK"; Ok "GDAL Python binding: osgeo.gdal" }
else { Missing "osgeo.gdal; Level-1A analysis/evaluation cannot run" }

$Candidates = @()
if ($env:METASHAPE_DIR) {
    $Candidates += (Join-Path $env:METASHAPE_DIR "metashape.exe")
    $Candidates += (Join-Path $env:METASHAPE_DIR "MetashapePro.exe")
}
$OnPath = Get-Command metashape.exe -ErrorAction SilentlyContinue
if ($OnPath) { $Candidates += $OnPath.Source }
$Found = $Candidates | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
if ($Found) {
    $MetashapeStatus = "FOUND_NOT_WIRED"
    Ok "Agisoft Metashape executable: $Found"
    Missing "current production launcher is Bash-based and calls metashape.sh; native Windows execution is not wired"
} else {
    Missing "Agisoft Metashape executable via METASHAPE_DIR or PATH"
}

Write-Host "`nLevel-1A Windows setup summary"
Write-Host "  Python venv/package: $PythonStatus"
Write-Host "  Base Python imports: $ImportStatus"
Write-Host "  GDAL Python bindings: $GdalStatus"
Write-Host "  Agisoft Metashape: $MetashapeStatus"
Write-Host "  Native workflow launcher: UNRESOLVED (current launcher uses Bash/metashape.sh)"
Write-Host "  This script does not install Agisoft Metashape or GDAL system software."

if ($PythonStatus -ne "OK" -or $ImportStatus -ne "OK") { exit 1 }
