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

# Clear between steps so each question starts on an empty screen, with a
# reminder of what has been decided. Long output, the benchmark especially,
# survives until the next question rather than being wiped by it.
$script:Decided = @()
function Decided($m) { $script:Decided += $m }
function Screen {
    Clear-Host
    Write-Host "ai-notes installer"
    if ($script:Decided.Count -gt 0) {
        Write-Host ($script:Decided -join "  -  ")
    }
    Write-Host ""
}
function Step($m) { Write-Host ""; Write-Host "--- $m" -ForegroundColor Cyan }
function Ask($prompt, $default) {
    $r = Read-Host "$prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($r)) { return $default }
    return $r
}

Screen

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
    # A running shell keeps the environment it started with, so newly installed
    # programs are invisible until PATH is reloaded. Reload it here rather than
    # sending the user away to start again, which is where setup was being lost.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") +
                ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    Say ""
    $stillMissing = @()
    if (-not (Have python)) { $stillMissing += "python" }
    if (-not (Have ffmpeg)) { $stillMissing += "ffmpeg" }
    if ($stillMissing.Count -gt 0) {
        Say "Installed, but $($stillMissing -join ' and ') is still not visible."
        Say "Close this window, open it again, and run the installer once more."
        Read-Host "Press Enter to close"; exit 0
    }
    Say "  installed and available, continuing"
}
Say "  all present"

# ---- what this machine will do ---------------------------------------------
# Ask the hardware, not the PATH. The presence of nvidia-smi is not evidence of
# an NVIDIA card: it can be left behind by drivers or bundled by other software,
# and on an Intel Arc laptop that made the installer claim a GPU it did not have.
$gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
          Select-Object -ExpandProperty Name)
$nvidia = @($gpus | Where-Object { $_ -match "NVIDIA|GeForce|Quadro|RTX|GTX" })

Step "Detected"
if ($gpus.Count -eq 0) { Say "  GPU     none reported" }
foreach ($g in $gpus) { Say "  GPU     $g" }

$wantProcess = 0
# Processing needs CUDA, so it needs both an NVIDIA card and a working driver.
if ($nvidia.Count -gt 0 -and (Have nvidia-smi)) {
    Say ""
    Say "That card can do the transcription and note writing as well."
    Say ""
    Say "  1) Record only, another machine writes the notes"
    Say "  2) Both: record here and produce the notes here"
    Say ""
    if ((Ask "Select" "1") -eq "2") { $wantProcess = 1 }
} elseif ($nvidia.Count -gt 0) {
    Say ""
    Say "  An NVIDIA card is present but nvidia-smi is not available, so the"
    Say "  driver is missing or too old. Recording only."
} else {
    Say ""
    Say "  No NVIDIA card, so this machine records only. Transcribing and"
    Say "  summarising need CUDA and happen on a machine that has it."
}

# ---- language --------------------------------------------------------------
Screen
Step "Lecture language"
Say "  1) English"
Say "  2) Lithuanian"
Say ""
$lang = "en"
if ((Ask "Select" "1") -eq "2") {
    $lang = "lt"
    Say ""
    Say "  Note: Lithuanian on Windows uses the stock multilingual model."
    Say "  The better Lithuanian model needs a conversion step that is Linux only."
}

# ---- vault -----------------------------------------------------------------
if ($lang -eq "lt") { Decided "Lithuanian" } else { Decided "English" }
Screen
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

# ---- environment -----------------------------------------------------------
Decided (Split-Path -Leaf $vault)
Screen
Step "Building the capture environment"
if (-not (Test-Path "$Root\capture\venv\Scripts\python.exe")) {
    python -m venv "$Root\capture\venv"
}
& "$Root\capture\venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Root\capture\venv\Scripts\pip.exe" install -q faster-whisper numpy PyQt6
Say "  done"

Step "Measuring this machine"
Say "  Trying the largest model first and falling back only if it cannot keep"
Say "  up. Models are downloaded as they are needed, so this takes a while."
Say ""

# gpu_probe reports vendor, name, FREE VRAM and whether the card is discrete
$probe = & "$Root\capture\venv\Scripts\python.exe" "$Root\shared\gpu_probe.py"
$parts = $probe -split "`t"
$vram = 0; $discrete = 0; $cuda = 0
if ($parts.Count -ge 4) {
    $vram = [int]$parts[2]
    $discrete = [int]$parts[3]
    if ($parts[0] -eq "nvidia") { $cuda = 1 }
}

$env:HAS_CUDA = "$cuda"
$env:GPU_DISCRETE = "$discrete"
$env:VRAM_MIB = "$vram"
$env:MIN_LIVE_FACTOR = "1.2"

# Stream rather than capture. Collecting the output first means nothing
# appears until the whole benchmark finishes, which on a slow machine with
# models to download is many minutes of a blank screen.
$bench = @()
& "$Root\capture\venv\Scripts\python.exe" "$Root\lib\benchmark.py" `
      $lang "$Root\samples" "$Root\.bench" 2>&1 |
    ForEach-Object { Write-Host $_; $bench += "$_" }
$resultLine = $bench | Where-Object { $_ -like "RESULT *" } | Select-Object -Last 1
$result = if ($resultLine) { "$resultLine" } else { "" }

$liveModel = ""; $chunkSecs = 12
if ($result) {
    $rp = $result -split " "
    if ($rp.Count -ge 3 -and $rp[1] -ne "none") { $liveModel = $rp[2] }
    if ($rp.Count -ge 5) { $chunkSecs = $rp[4] }
}

if (-not $liveModel) {
    Say ""
    Say "Nothing on this machine keeps up with live transcription in this"
    Say "language. Recording still works and the notes are produced later on a"
    Say "machine that can."
    Say ""
    $liveModel = "none"
}

if ($wantProcess -eq 1) {
    Step "Building the processing environment"
    if (-not (Test-Path "$Root\process\venv\Scripts\python.exe")) {
        python -m venv "$Root\process\venv"
    }
    & "$Root\process\venv\Scripts\pip.exe" install -q faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 PyQt6
    Say "  done. Install Ollama from ollama.com and run: ollama pull qwen3:8b"
    Say "  Then set OLLAMA_KEEP_ALIVE=30s as a user environment variable."
}

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
LECTURE_CHUNK_SECS="$chunkSecs"
LECTURE_ASR_MODEL="large-v3"
LECTURE_ASR_COMPUTE="float16"
LECTURE_LLM="qwen3:8b"
"@ | Set-Content -Encoding UTF8 "$Root\config.sh"
Say "  done"

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
