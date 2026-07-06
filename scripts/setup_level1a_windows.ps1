[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvDir = Join-Path $RepoRoot ".conda-env"
$EnvPython = Join-Path $EnvDir "python.exe"
$PythonStatus = "OK"
$ImportStatus = "OK"
$GdalStatus = "MISSING"
$MetashapeStatus = "MISSING"

function Ok([string]$Text) { Write-Host "OK: $Text" }
function Missing([string]$Text) { Write-Warning "MISSING: $Text" }

Set-Location $RepoRoot
$Conda = Get-Command conda.exe -ErrorAction SilentlyContinue
if (-not $Conda) { $Conda = Get-Command conda -ErrorAction SilentlyContinue }
if (-not $Conda) {
    throw "Conda was not found. Install Miniforge/Conda and reopen PowerShell. Native Windows GDAL Python bindings are installed from conda-forge."
}
$CondaCommand = $Conda.Source

$Packages = @("python=3.12", "pip", "numpy", "pyyaml", "rasterio", "gdal")
if (Test-Path $EnvPython -PathType Leaf) {
    & $CondaCommand install --yes --prefix $EnvDir --channel conda-forge @Packages
    if ($LASTEXITCODE -ne 0) { throw "Could not update conda environment at $EnvDir" }
    Ok "updated conda environment at $EnvDir"
} else {
    & $CondaCommand create --yes --prefix $EnvDir --channel conda-forge @Packages
    if ($LASTEXITCODE -ne 0) { throw "Could not create conda environment at $EnvDir" }
    Ok "created conda environment at $EnvDir"
}

# Make this local environment's GDAL DLLs and command-line tools visible to
# import checks without changing the machine-wide Windows environment.
$env:PATH = "$EnvDir;$EnvDir\Scripts;$EnvDir\Library\bin;$env:PATH"

& $EnvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "editable project installation failed" }

$Cli = Join-Path $EnvDir "Scripts\metashape-qc.exe"
if (Test-Path $Cli -PathType Leaf) { Ok "metashape-qc: $Cli" }
else { $PythonStatus = "MISSING"; Missing "metashape-qc.exe in $EnvDir\Scripts" }

& $EnvPython -c "import numpy, rasterio, yaml"
if ($LASTEXITCODE -eq 0) { Ok "Python imports: numpy, yaml, rasterio" }
else { $ImportStatus = "MISSING"; Missing "Python imports: numpy, yaml, rasterio" }

& $EnvPython -c "from osgeo import gdal, ogr, osr; print(gdal.VersionInfo())"
if ($LASTEXITCODE -eq 0) { $GdalStatus = "OK"; Ok "GDAL Python bindings: osgeo.gdal, osgeo.ogr, osgeo.osr" }
else { Missing "conda-forge GDAL Python bindings" }

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
Write-Host "  Conda environment: $EnvDir"
Write-Host "  Python package/CLI: $PythonStatus"
Write-Host "  Base Python imports: $ImportStatus"
Write-Host "  GDAL Python bindings: $GdalStatus"
Write-Host "  Agisoft Metashape: $MetashapeStatus"
Write-Host "  Native workflow launcher: UNRESOLVED (current launcher uses Bash/metashape.sh)"
Write-Host "  Activate later with: conda activate `"$EnvDir`""
Write-Host "  This script does not install Agisoft Metashape."

if ($PythonStatus -ne "OK" -or $ImportStatus -ne "OK" -or $GdalStatus -ne "OK") { exit 1 }
