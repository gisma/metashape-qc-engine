[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ConfigFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ConfigPath = (Resolve-Path $ConfigFile).Path
$WorkflowScript = Join-Path $RepoRoot "python\metashape_workflow.py"
$VendorPath = Join-Path $RepoRoot "python\vendor"

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

if (-not (Test-Path $WorkflowScript -PathType Leaf)) {
    throw "Metashape workflow script not found: $WorkflowScript"
}

$MetashapeExe = Resolve-MetashapeExecutable
if (-not $MetashapeExe) {
    throw "Could not find metashape.exe via METASHAPE_DIR, PATH, Program Files, or uninstall registry."
}

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$VendorPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $VendorPath
}

Write-Host "METASHAPE_EXE=$MetashapeExe"
Write-Host "WORKFLOW_SCRIPT=$WorkflowScript"
Write-Host "CONFIG_FILE=$ConfigPath"

& $MetashapeExe -r $WorkflowScript $ConfigPath
exit $LASTEXITCODE
