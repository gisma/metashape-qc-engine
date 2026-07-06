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
function Resolve-OtbEnvironmentScript {
    $Candidates = @()
    if ($env:OTB_ROOT) {
        $Candidates += (Join-Path $env:OTB_ROOT "otbenv.ps1")
        $Candidates += (Join-Path $env:OTB_ROOT "otbenv.bat")
        $Candidates += (Join-Path $env:OTB_ROOT "bin\otbenv.ps1")
        $Candidates += (Join-Path $env:OTB_ROOT "bin\otbenv.bat")
    }
    foreach ($Name in @("otbenv.ps1", "otbenv.bat")) {
        $OnPath = Get-Command $Name -ErrorAction SilentlyContinue
        if ($OnPath) { $Candidates += $OnPath.Source }
    }
    return $Candidates | Where-Object { $_ -and (Test-Path $_ -PathType Leaf) } | Select-Object -First 1
}

function Import-OtbEnvironment([string]$EnvironmentScript) {
    if ([IO.Path]::GetExtension($EnvironmentScript) -ieq ".ps1") {
        . $EnvironmentScript
    } else {
        Import-BatchEnvironment $EnvironmentScript
    }
}

function Import-BatchEnvironment([string]$BatchFile) {
    $Lines = & $env:ComSpec /d /s /c "call `"$BatchFile`" >nul && set"
    if ($LASTEXITCODE -ne 0) { throw "OTB environment script failed: $BatchFile" }
    foreach ($Line in $Lines) {
        if ($Line -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
        }
    }
}

function Resolve-SagaExecutable {
    $Candidates = @()
    if ($env:SAGA_ROOT) {
        if (Test-Path $env:SAGA_ROOT -PathType Leaf) { $Candidates += $env:SAGA_ROOT }
        else { $Candidates += (Join-Path $env:SAGA_ROOT "saga_cmd.exe") }
    }
    $OnPath = Get-Command saga_cmd.exe -ErrorAction SilentlyContinue
    if ($OnPath) { $Candidates += $OnPath.Source }
    foreach ($Root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }) {
        $Candidates += (Join-Path $Root "SAGA-GIS\saga_cmd.exe")
        $Candidates += (Join-Path $Root "SAGA GIS\saga_cmd.exe")
    }
    return $Candidates | Where-Object { $_ -and (Test-Path $_ -PathType Leaf) } | Select-Object -First 1
}

function Resolve-CondaExecutable {
    $Command = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }

    $Candidates = @(
        (Join-Path $env:USERPROFILE "miniforge3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "miniforge3\Scripts\conda.exe"),
        (Join-Path $env:ProgramData "miniforge3\Scripts\conda.exe")
    )
    return $Candidates | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
}

$CondaCommand = Resolve-CondaExecutable
if (-not $CondaCommand) {
    $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $Winget) {
        throw "Neither Conda nor winget was found. Install Miniforge from https://conda-forge.org/download/ and rerun this script."
    }

    Write-Host "Conda not found; installing Miniforge with winget."
    & $Winget.Source install --id CondaForge.Miniforge3 --exact --source winget --accept-package-agreements --accept-source-agreements
    $WingetExitCode = $LASTEXITCODE
    $CondaCommand = Resolve-CondaExecutable
    if (-not $CondaCommand) {
        throw "Miniforge installation did not expose conda.exe (winget exit $WingetExitCode). Reopen PowerShell or install from https://conda-forge.org/download/, then rerun."
    }
}
Ok "Conda executable: $CondaCommand"

$Packages = @("python=3.12", "pip", "numpy", "pyyaml", "rasterio", "gdal", "matplotlib")
if (Test-Path $EnvPython -PathType Leaf) {
    & $CondaCommand install --yes --prefix $EnvDir --channel conda-forge @Packages
    if ($LASTEXITCODE -ne 0) { throw "Could not update conda environment at $EnvDir" }
    Ok "updated conda environment at $EnvDir"
} else {
    & $CondaCommand create --yes --prefix $EnvDir --channel conda-forge @Packages
    if ($LASTEXITCODE -ne 0) { throw "Could not create conda environment at $EnvDir" }
    Ok "created conda environment at $EnvDir"
}

$env:PATH = "$EnvDir;$EnvDir\Scripts;$EnvDir\Library\bin;$env:PATH"

& $EnvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "editable project installation failed" }

& $EnvPython -c "import matplotlib, numpy, rasterio, yaml"
if ($LASTEXITCODE -eq 0) { Ok "Python imports: numpy, yaml, rasterio, matplotlib" }
else { $ImportStatus = "MISSING"; Missing "Python imports: numpy, yaml, rasterio, matplotlib" }

& $EnvPython -c "from osgeo import gdal, ogr, osr; print(gdal.VersionInfo())"
if ($LASTEXITCODE -eq 0) { $GdalStatus = "OK"; Ok "GDAL Python bindings: osgeo.gdal, osgeo.ogr, osgeo.osr" }
else { Missing "conda-forge GDAL Python bindings" }

$OtbEnv = Resolve-OtbEnvironmentScript
if ($OtbEnv) {
    Import-OtbEnvironment $OtbEnv
    Ok "OTB environment: $OtbEnv"
} else {
    $OtbStatus = "MISSING"
    Missing "otbenv.ps1 or otbenv.bat; set OTB_ROOT to the extracted Windows OTB package root"
}

$MissingOtb = @()
foreach ($Name in @("BandMathX", "DimensionalityReduction", "HaralickTextureExtraction", "ComputeImagesStatistics")) {
    $Tool = Find-Tool @("otbcli_$Name", "otbcli_$Name.bat", "otbcli_$Name.exe")
    if ($Tool) { Ok "otbcli_${Name}: $Tool" }
    else { $OtbStatus = "MISSING"; $MissingOtb += "otbcli_$Name"; Missing "otbcli_$Name" }
}

$Saga = Resolve-SagaExecutable
if ($Saga) { $SagaStatus = "OK"; Ok "saga_cmd: $Saga" }
else { Missing "saga_cmd.exe; set SAGA_ROOT to the SAGA installation directory" }

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
Write-Host "  Conda environment: $EnvDir"
Write-Host "  Python package: $PythonStatus"
Write-Host "  Python imports: $ImportStatus"
Write-Host "  GDAL Python bindings: $GdalStatus"
Write-Host "  OTB CLI tools: $OtbStatus $($MissingOtb -join ' ')"
Write-Host "  SAGA Seeded Region Growing: $SagaStatus"
Write-Host "  GDAL CLI tools: $GdalCliStatus $($MissingGdal -join ' ')"
Write-Host "  Rscript: $RscriptStatus"
Write-Host "  R packages: $RPackagesStatus $($MissingR -join ' ')"
Write-Host "  Native workflow wrapper: metashape_qc_engine\run_level1b_dumb_with_user_header.ps1"
Write-Host "  Activate later with: conda activate `"$EnvDir`""
Write-Host "  This script does not install SAGA, OTB, R, or Agisoft Metashape."

if ($PythonStatus -ne "OK" -or $ImportStatus -ne "OK" -or $GdalStatus -ne "OK") { exit 1 }
