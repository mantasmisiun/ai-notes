# ai-notes installer for Windows.
#
# Does what install.sh does on Linux: checks prerequisites, builds the
# environment, asks the few things it cannot work out, and leaves a shortcut
# that starts and stops a recording.
#
# Run it by double-clicking install.bat, or from PowerShell:
#   .\windows\install.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Say($m) { Write-Host $m }
function Step($m) { Write-Host ""; Write-Host "--- $m" -ForegroundColor Cyan }
function Ask($prompt, $default) {
    $r = Read-Host "$prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($r)) { return $default }
    return $r
}

Clear-Host
Say "ai-notes installer"
Say ""

# ---- prerequisites ---------------------------------------------------------
Step "Checking prerequisites"

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

$missing = @()
if (-not (Have python)) { $missing += "Python.Python.3.12" }
if (-not (Have ffmpeg)) { $missing += "Gyan.FFmpeg" }

# CTranslate2's wheels are built with MSVC and fail with a misleading
# "cannot find ctranslate2.dll" without the redistributable.
$vc = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
if (-not $vc) { $missing += "Microsoft.VCRedist.2015+.x64" }

if ($missing.Count -gt 0) {
    if (-not (Have winget)) {
        Say "Missing: $($missing -join ', ')"
        Say "winget is not available on this machine, so install those by hand and re-run."
        Read-Host "Press Enter to close"; exit 1
    }
    foreach ($pkg in $missing) {
        Say "  installing $pkg"
        winget install --accept-source-agreements --accept-package-agreements -e --id $pkg | Out-Null
    }
    Say ""
    Say "Prerequisites installed. PowerShell must be restarted to see them."
    Say "Close this window, open it again, and run the installer once more."
    Read-Host "Press Enter to close"; exit 0
}
Say "  all present"

# ---- what this machine will do ---------------------------------------------
$hasNvidia = Have nvidia-smi
$wantProcess = 0
if ($hasNvidia) {
    Step "This machine has an NVIDIA GPU"
    Say "  1) Record only, another machine writes the notes"
    Say "  2) Both: record here and produce the notes here"
    Say ""
    if ((Ask "Select" "1") -eq "2") { $wantProcess = 1 }
} else {
    Step "No NVIDIA GPU found, so this machine records only"
    Say "  Transcribing and summarising happen on a machine with one."
}

# ---- language --------------------------------------------------------------
Step "Lecture language"
Say "  1) English"
Say "  2) Lithuanian"
Say ""
$lang = "en"; $liveModel = "small.en"
if ((Ask "Select" "1") -eq "2") {
    $lang = "lt"; $liveModel = "small"
    Say ""
    Say "  Note: Lithuanian on Windows uses the stock multilingual model."
    Say "  The better Lithuanian model needs a conversion step that is Linux only."
}

# ---- vault -----------------------------------------------------------------
Step "Where is your Obsidian vault"
Say "  The folder containing .obsidian. Everything else is created inside it."
Say "  On a borrowed machine, point this somewhere scratch."
Say ""
$vault = Ask "Vault path" "$HOME\Documents\ai-notes-vault"
$vault = $vault.TrimEnd('\')
if (-not (Test-Path $vault)) {
    if ((Ask "$vault does not exist. Create it? (y/n)" "y") -ne "y") { exit 1 }
    New-Item -ItemType Directory -Force $vault | Out-Null
}
$vaultFwd = $vault -replace '\\', '/'
$scratch = "$env:LOCALAPPDATA\lecture-pipeline" -replace '\\', '/'

# ---- config ----------------------------------------------------------------
Step "Writing config.sh"
@"
# Written by windows/install.ps1. Paths and model choices, no secrets.
VAULT="$vaultFwd"
TRANSCRIPTIONS_DIR="Transcriptions"
UNIVERSITY_DIR="University"
AUDIO_SCRATCH="$scratch"

WANT_CAPTURE=1
WANT_PROCESS=$wantProcess
LECTURE_BACKEND="cpu"

LECTURE_LANGUAGE="$lang"
LECTURE_NOTE_LANGUAGE="$lang"

LECTURE_MODEL="$liveModel"
LECTURE_ASR_MODEL="large-v3"
LECTURE_ASR_COMPUTE="float16"
LECTURE_LLM="qwen3:8b"
"@ | Set-Content -Encoding UTF8 "$Root\config.sh"
Say "  done"

# ---- environment -----------------------------------------------------------
Step "Building the capture environment"
if (-not (Test-Path "$Root\capture\venv\Scripts\python.exe")) {
    python -m venv "$Root\capture\venv"
}
& "$Root\capture\venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Root\capture\venv\Scripts\pip.exe" install -q faster-whisper numpy PyQt6
Say "  done"

Step "Fetching the live model ($liveModel)"
Say "  a few hundred MB, this takes a minute"
& "$Root\capture\venv\Scripts\python.exe" -c @"
from faster_whisper import WhisperModel
WhisperModel('$liveModel', device='cpu', compute_type='int8')
"@
Say "  done"

if ($wantProcess -eq 1) {
    Step "Building the processing environment"
    if (-not (Test-Path "$Root\process\venv\Scripts\python.exe")) {
        python -m venv "$Root\process\venv"
    }
    & "$Root\process\venv\Scripts\pip.exe" install -q faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 PyQt6
    Say "  done. Install Ollama from ollama.com and run: ollama pull qwen3:8b"
    Say "  Then set OLLAMA_KEEP_ALIVE=30s as a user environment variable."
}

# ---- vault layout and a shortcut -------------------------------------------
Step "Preparing the vault and a shortcut"
foreach ($d in @("live", "transcripts", "audio", "unfiled", "raw notes")) {
    New-Item -ItemType Directory -Force "$vault\Transcriptions\$d" | Out-Null
}
New-Item -ItemType Directory -Force "$vault\University" | Out-Null

$launcher = "$Root\windows\record.bat"
@"
@echo off
cd /d "%~dp0.."
capture\venv\Scripts\pythonw.exe capture\record.py
"@ | Set-Content -Encoding ASCII $launcher

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$HOME\Desktop\Record lecture.lnk")
$lnk.TargetPath = $launcher
$lnk.WorkingDirectory = $Root
$lnk.Description = "Start or stop a lecture recording"
$lnk.Save()
Say "  shortcut on your Desktop: Record lecture"

Write-Host ""
Write-Host "================================================================"
Write-Host ""
Say "To record: double-click 'Record lecture' on your Desktop."
Say "A red dot appears in the system tray while it is recording."
Say "Double-click the same shortcut again to stop."
Say ""
Say "Transcript and your notes appear in:"
Say "  $vault\Transcriptions\live"
Say "Type in the 'my notes' file, never in the transcript."
Say ""
Read-Host "Press Enter to close"
