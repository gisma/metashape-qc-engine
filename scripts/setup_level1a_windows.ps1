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
function Resolve-MetashapeExecutable {
    $Candidates = @()

    if ($env:METASHAPE_DIR) {
        if (Test-Path $env:METASHAPE_DIR -PathType Leaf) {
            $Candidates += $env:METASHAPE_DIR
        } elseif (Test-Path $env:METASHAPE_DIR -PathType Container) {
            $Candidates += (Join-Path $env:METASHAPE_DIR "metashape.exe")
            $Candidates += (Join-Path $env:METASHAPE_DIR "MetashapePro.exe")
        }
    }

    $OnPath = Get-Command metashape.exe -ErrorAction SilentlyContinue
    if ($OnPath) { $Candidates += $OnPath.Source }

    $ProgramRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) |
        Where-Object { $_ -and (Test-Path $_ -PathType Container) }
    foreach ($Root in $ProgramRoots) {
        $Candidates += (Join-Path $Root "Agisoft\Metashape Pro\metashape.exe")
        $Candidates += (Join-Path $Root "Agisoft\Metashape\metashape.exe")
    }

    $RegistryRoots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($RegistryRoot in $RegistryRoots) {
        $Products = Get-ItemProperty $RegistryRoot -ErrorAction SilentlyContinue |
            Where-Object {
                $_.PSObject.Properties["DisplayName"] -and
                [string]$_.PSObject.Properties["DisplayName"].Value -like "Agisoft Metashape*"
            }
        foreach ($Product in $Products) {
            $InstallLocation = $Product.PSObject.Properties["InstallLocation"]
            if ($InstallLocation -and $InstallLocation.Value) {
                $Candidates += (Join-Path ([string]$InstallLocation.Value) "metashape.exe")
                $Candidates += (Join-Path ([string]$InstallLocation.Value) "MetashapePro.exe")
            }
            $DisplayIcon = $Product.PSObject.Properties["DisplayIcon"]
            if ($DisplayIcon -and $DisplayIcon.Value) {
                $IconPath = ([string]$DisplayIcon.Value -replace ',\d+$', '').Trim('"')
                $Candidates += $IconPath
            }
        }
    }

    return $Candidates |
        Where-Object { $_ -and (Test-Path $_ -PathType Leaf) } |
        Select-Object -First 1
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

$Found = Resolve-MetashapeExecutable
if ($Found) {
    $WindowsLauncher = Join-Path $RepoRoot "scripts\run_metashape_workflow.ps1"
    if (Test-Path $WindowsLauncher -PathType Leaf) {
        $MetashapeStatus = "OK"
        Ok "Agisoft Metashape executable: $Found"
        Ok "native Windows launcher: $WindowsLauncher"
    } else {
        Missing "native Windows launcher: $WindowsLauncher"
    }
} else {
    Missing "Agisoft Metashape executable via METASHAPE_DIR, PATH, Program Files, or uninstall registry"
}

Write-Host "`nLevel-1A Windows setup summary"
Write-Host "  Conda environment: $EnvDir"
Write-Host "  Python package/CLI: $PythonStatus"
Write-Host "  Base Python imports: $ImportStatus"
Write-Host "  GDAL Python bindings: $GdalStatus"
Write-Host "  Agisoft Metashape: $MetashapeStatus"
Write-Host "  Native workflow launcher: $MetashapeStatus"
Write-Host "  Activate later with: conda activate `"$EnvDir`""
Write-Host "  This script does not install Agisoft Metashape."

if ($PythonStatus -ne "OK" -or $ImportStatus -ne "OK" -or $GdalStatus -ne "OK") { exit 1 }
