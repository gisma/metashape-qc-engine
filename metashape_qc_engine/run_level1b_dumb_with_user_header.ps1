[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvDir = Join-Path $RepoRoot ".conda-env"
$EnvPython = Join-Path $EnvDir "python.exe"
$Ortho = $env:ORTHO
$RunRoot = $env:RUN_ROOT
$Overwrite = $env:OVERWRITE

if (-not $Ortho) { throw "Set ORTHO to the input orthomosaic path." }
if (-not $RunRoot) { throw "Set RUN_ROOT to the Level-1B output directory." }
if (-not (Test-Path $Ortho -PathType Leaf)) { throw "ORTHO does not exist: $Ortho" }
if (-not (Test-Path $EnvPython -PathType Leaf)) {
    throw "Windows conda environment is missing: $EnvDir. Run scripts/setup_level1b_windows.ps1 first."
}

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
    foreach ($Root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }) {
        foreach ($Name in @("otbenv.ps1", "otbenv.bat")) {
            $Candidates += Get-ChildItem -Path $Root -Filter $Name -Recurse -Depth 2 -File -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName
        }
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
    $CommandLine = "call `"$BatchFile`" >nul && set"
    $Lines = & $env:ComSpec /d /s /c $CommandLine
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
        if (Test-Path $env:SAGA_ROOT -PathType Leaf) {
            $Candidates += $env:SAGA_ROOT
        } else {
            $Candidates += (Join-Path $env:SAGA_ROOT "saga_cmd.exe")
            $Candidates += (Join-Path $env:SAGA_ROOT "saga_cmd")
        }
    }
    $OnPath = Get-Command saga_cmd.exe -ErrorAction SilentlyContinue
    if ($OnPath) { $Candidates += $OnPath.Source }
    foreach ($Root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }) {
        $Candidates += (Join-Path $Root "SAGA-GIS\saga_cmd.exe")
        $Candidates += (Join-Path $Root "SAGA GIS\saga_cmd.exe")
    }
    return $Candidates | Where-Object { $_ -and (Test-Path $_ -PathType Leaf) } | Select-Object -First 1
}

$CondaPath = "$EnvDir;$EnvDir\Scripts;$EnvDir\Library\bin"
$BasePath = "$CondaPath;$env:PATH"
$BasePythonPath = $env:PYTHONPATH
$env:PATH = $BasePath

$OtbEnv = Resolve-OtbEnvironmentScript
if (-not $OtbEnv) {
    throw "Could not find otbenv.ps1 or otbenv.bat. Set OTB_ROOT to the extracted Windows OTB package root."
}
Import-OtbEnvironment $OtbEnv
$env:LEVEL1B_OTB_PATH_ORIG = $env:PATH
$SavedOtbVariables = @{
    "OTB_APPLICATION_PATH" = "LEVEL1B_OTB_APPLICATION_PATH_ORIG"
    "GDAL_DATA" = "LEVEL1B_OTB_GDAL_DATA_ORIG"
    "PROJ_LIB" = "LEVEL1B_OTB_PROJ_LIB_ORIG"
}
foreach ($Name in $SavedOtbVariables.Keys) {
    $Value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($Value) {
        [Environment]::SetEnvironmentVariable($SavedOtbVariables[$Name], $Value, "Process")
    }
}

# Restore the clean conda Python runtime. The saved LEVEL1B_OTB_* values are
# injected only into otbcli subprocesses by level1b_otb_env.py.
$env:PATH = $BasePath
if ($BasePythonPath) { $env:PYTHONPATH = $BasePythonPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
foreach ($Name in @("OTB_APPLICATION_PATH", "GDAL_DATA", "PROJ_LIB")) {
    Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
}

$SagaExe = Resolve-SagaExecutable
if (-not $SagaExe) {
    throw "Could not find saga_cmd.exe. Set SAGA_ROOT to the SAGA installation directory."
}
$env:LEVEL1B_SAGA_PATH_ORIG = "$(Split-Path -Parent $SagaExe);$BasePath"

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$ShellLog = Join-Path $RunRoot "level1b_chain.log"
$RunnerArgs = @("--rgb-ortho", $Ortho, "--out-dir", $RunRoot)
if ($Overwrite -eq "1") { $RunnerArgs += "--overwrite" }

Write-Host "Level-1B Windows runner"
Write-Host "ORTHO=$Ortho"
Write-Host "RUN_ROOT=$RunRoot"
Write-Host "OTB_ENV=$OtbEnv"
Write-Host "SAGA_CMD=$SagaExe"
Write-Host "PYTHON=$EnvPython"

& $EnvPython -m metashape_qc_engine.level1b_dumb_runner @RunnerArgs 2>&1 |
    Tee-Object -FilePath $ShellLog -Append
exit $LASTEXITCODE
