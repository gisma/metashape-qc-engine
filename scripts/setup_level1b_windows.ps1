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
$OtbStatus = "OK"
$SagaStatus = "MISSING"
$GdalCliStatus = "OK"
$RscriptStatus = "MISSING"
$RPackagesStatus = "MISSING"

function Ok([string]$Text) { Write-Host "OK: $Text" }
function Missing([string]$Text) { Write-Warning "MISSING: $Text" }
function Find-Tool([string[]]$Names) {
    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) { return $Command.Source }
    }
    return $null
}

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
& $VenvPython -m pip install -e . matplotlib
if ($LASTEXITCODE -ne 0) { throw "editable project/matplotlib installation failed" }

& $VenvPython -c "import matplotlib, numpy, rasterio, yaml"
if ($LASTEXITCODE -eq 0) { Ok "Python imports: numpy, yaml, rasterio, matplotlib" }
else { $ImportStatus = "MISSING"; Missing "Python imports: numpy, yaml, rasterio, matplotlib" }

& $VenvPython -c "from osgeo import gdal, ogr, osr"
if ($LASTEXITCODE -eq 0) {
    $GdalStatus = "OK"
    Ok "GDAL Python bindings: osgeo.gdal, osgeo.ogr, osgeo.osr"
} else {
    $GdalConfig = Find-Tool @("gdal-config", "gdal-config.exe")
    if ($GdalConfig) {
        $Version = (& $GdalConfig --version).Trim()
        Write-Host "Trying GDAL==$Version from gdal-config."
        & $VenvPython -m pip install "GDAL==$Version"
        if ($LASTEXITCODE -eq 0) {
            & $VenvPython -c "from osgeo import gdal, ogr, osr"
            if ($LASTEXITCODE -eq 0) { $GdalStatus = "OK" }
        }
    }
    if ($GdalStatus -ne "OK") { Missing "GDAL Python bindings; no unversioned fallback attempted" }
}

$MissingOtb = @()
foreach ($Name in @("BandMathX", "DimensionalityReduction", "HaralickTextureExtraction", "ComputeImagesStatistics")) {
    $Tool = Find-Tool @("otbcli_$Name", "otbcli_$Name.bat", "otbcli_$Name.exe")
    if ($Tool) { Ok "otbcli_${Name}: $Tool" }
    else { $OtbStatus = "MISSING"; $MissingOtb += "otbcli_$Name"; Missing "otbcli_$Name" }
}

$Saga = Find-Tool @("saga_cmd", "saga_cmd.exe")
if ($Saga) { $SagaStatus = "OK"; Ok "saga_cmd: $Saga" }
else { Missing "saga_cmd" }

$MissingGdal = @()
foreach ($Name in @("gdal_edit.py", "ogr2ogr")) {
    $Candidates = if ($Name -eq "ogr2ogr") { @("ogr2ogr", "ogr2ogr.exe") } else { @("gdal_edit.py") }
    $Tool = Find-Tool $Candidates
    if ($Tool) { Ok "${Name}: $Tool" }
    else { $GdalCliStatus = "MISSING"; $MissingGdal += $Name; Missing $Name }
}

$MissingR = @()
$Rscript = Find-Tool @("Rscript", "Rscript.exe")
if ($Rscript) {
    $RscriptStatus = "OK"
    Ok "Rscript: $Rscript"
    foreach ($Package in @("sf", "terra", "exactextractr", "jsonlite", "readr")) {
        & $Rscript -e "quit(status=if (requireNamespace('$Package', quietly=TRUE)) 0 else 1)"
        if ($LASTEXITCODE -eq 0) { Ok "R package: $Package" }
        else { $MissingR += $Package; Missing "R package: $Package" }
    }
    if ($MissingR.Count -eq 0) { $RPackagesStatus = "OK" }
} else {
    Missing "Rscript"
}
if ($RPackagesStatus -ne "OK") {
    Write-Host 'Rscript -e ''install.packages(c("sf","terra","exactextractr","jsonlite","readr"))'''
}

Write-Host "`nLevel-1B Windows setup summary"
Write-Host "  Python venv/package: $PythonStatus"
Write-Host "  Python imports: $ImportStatus"
Write-Host "  GDAL Python bindings: $GdalStatus"
Write-Host "  OTB CLI tools: $OtbStatus $($MissingOtb -join ' ')"
Write-Host "  SAGA Seeded Region Growing: $SagaStatus"
Write-Host "  GDAL CLI tools: $GdalCliStatus $($MissingGdal -join ' ')"
Write-Host "  Rscript: $RscriptStatus"
Write-Host "  R packages: $RPackagesStatus $($MissingR -join ' ')"
Write-Host "  Native workflow wrapper: UNRESOLVED (current normal wrapper is Bash-based)"
Write-Host "  This script does not install SAGA, OTB, GDAL CLI tools, or R."

if ($PythonStatus -ne "OK" -or $ImportStatus -ne "OK") { exit 1 }
