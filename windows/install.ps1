# ai-notes installer for Windows.
#
# Does what install.sh does on Linux: checks prerequisites, builds the
# environment, asks the few things it cannot work out, and leaves a shortcut
# that starts and stops a recording.
#
# Run it by double-clicking install.bat, or from PowerShell:
#   .\windows\install.ps1

$ErrorActionPreference = "Stop"
# Any error stops the script. Without this the window closed before the
# message could be read, and the only report possible was "it crashed".
trap {
    Write-Host ""
    Write-Host "The installer stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.InvocationInfo.PositionMessage
    Read-Host "Press Enter to close"
    exit 1
}
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
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
# PowerShell turns any stderr line from a native program into a terminating
# error when ErrorActionPreference is Stop. Progress messages, pip notices and
# HF warnings all go to stderr, so a step can abort on text that says "this
# takes a few minutes". Run such programs with that off and judge by exit code.
function Native([string]$exe, [string[]]$argv) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $lines = @()
    & $exe @argv 2>&1 | ForEach-Object {
        # A stderr line arrives as an ErrorRecord; stringifying that gives the
        # exception's type name rather than the text. Unwrap it.
        $t = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
        if ($t.Trim()) { Write-Host "  $t"; $lines += $t }
    }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return @{ Lines = $lines; Code = $code }
}

function Ask($prompt, $default) {
    $r = Read-Host "$prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($r)) { return $default }
    return $r
}

Screen

# ---- prerequisites ---------------------------------------------------------
Step "Checking prerequisites"

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# Get-Command finds the Microsoft Store alias stub that every fresh Windows
# profile carries in WindowsApps. It prints "Python was not found" and opens
# the Store instead of running, so only a python that answers --version counts.
# A second user account, on a laptop where the first had installed Python for
# itself, was told "all present" and fell over creating the venv.
function HavePython {
    if (-not (Have python)) { return $false }
    $r = Native "python" @("--version")
    return ($r.Code -eq 0 -and (($r.Lines -join " ") -match "Python 3"))
}

$missing = @()
if (-not (HavePython)) { $missing += "Python.Python.3.12" }
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
    if (-not (HavePython)) { $stillMissing += "python" }
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
    Say "  Lithuanian uses a dedicated model, paprika-whisper-lt, which recognises"
    Say "  Lithuanian word forms far better than the stock multilingual models."
    Say "  Its output has no punctuation or capitalisation, which the summariser"
    Say "  copes with but which makes the raw transcript harder to read."
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
    $r = Native "python" @("-m", "venv", "$Root\capture\venv")
    if ($r.Code -ne 0 -or -not (Test-Path "$Root\capture\venv\Scripts\python.exe")) {
        Say ""
        Say "Python could not create the environment (exit code $($r.Code))."
        Say "Check that python --version works in a new PowerShell window."
        Read-Host "Press Enter to close"; exit 1
    }
}
& "$Root\capture\venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Root\capture\venv\Scripts\pip.exe" install -q faster-whisper numpy PyQt6
if ($nvidia.Count -gt 0) {
    # The benchmark and the live pass run from THIS venv, so the CUDA libraries
    # have to be here. Without them faster-whisper reports a missing
    # cublas64_12.dll, which reads like a driver problem and is not.
    Say "  adding CUDA libraries"
    & "$Root\capture\venv\Scripts\pip.exe" install -q nvidia-cublas-cu12 nvidia-cudnn-cu12
}
Say "  done"

# Lithuanian has one model worth using. No published CTranslate2 build exists,
# so it is converted once into the cache with a throwaway toolchain that is
# deleted afterwards. The venv-relative paths in fetch_lt_model.py cover
# Windows, so this is the same step the Linux installer runs.
$ltModel = ""
if ($lang -eq "lt") {
    Step "Preparing the Lithuanian model"
    Say "  Converting paprika-whisper-lt. This happens once and takes a few minutes."
    $r = Native "python" @("$Root\lib\fetch_lt_model.py", "$env:LOCALAPPDATA\lecture-pipeline")
    $ltModel = if ($r.Lines.Count -gt 0) { ($r.Lines | Select-Object -Last 1).Trim() } else { "" }
    if ($r.Code -ne 0 -or -not (Test-Path $ltModel)) {
        Say ""
        Say "Could not prepare the Lithuanian model. The last line above says why."
        Read-Host "Press Enter to close"; exit 1
    }
    Say "  ready: $ltModel"
}

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
$env:LECTURE_FIXED_MODEL = "$ltModel"

# Stream rather than capture. Collecting the output first means nothing
# appears until the whole benchmark finishes, which on a slow machine with
# models to download is many minutes of a blank screen.
$r = Native "$Root\capture\venv\Scripts\python.exe" @("$Root\lib\benchmark.py", $lang, "$Root\samples", "$Root\.bench")
$bench = $r.Lines
# The result line is tab-separated, so a wildcard with a space after RESULT
# never matched it. That silently turned every measured model into "none".
$resultLine = $bench | Where-Object { $_ -match "^RESULT`t" } | Select-Object -Last 1
$result = if ($resultLine) { "$resultLine" } else { "" }

$liveModel = ""; $chunkSecs = 12; $backend = "cpu"
if ($result) {
    $rp = $result -split "`t"
    # fields: RESULT, backend, model, factor, interval, window
    if ($rp.Count -ge 3 -and $rp[1] -ne "none") { $liveModel = $rp[2]; $backend = $rp[1] }
    if ($rp.Count -ge 5) { $chunkSecs = $rp[4] }
}
# the config is parsed as KEY="value" with forward slashes; keep a path usable
if ($liveModel -and (Test-Path $liveModel)) { $liveModel = $liveModel -replace '\\', '/' }

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
        $r = Native "python" @("-m", "venv", "$Root\process\venv")
        if ($r.Code -ne 0 -or -not (Test-Path "$Root\process\venv\Scripts\python.exe")) {
            Say ""
            Say "Python could not create the environment (exit code $($r.Code))."
            Say "Check that python --version works in a new PowerShell window."
            Read-Host "Press Enter to close"; exit 1
        }
    }
    & "$Root\process\venv\Scripts\pip.exe" install -q faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 PyQt6
    Say "  done. Install Ollama from ollama.com and run: ollama pull qwen3:8b"
    Say "  Then set OLLAMA_KEEP_ALIVE=30s as a user environment variable."
}

# ---- config ----------------------------------------------------------------
$asrModel = "large-v3"; $asrCompute = "float16"
if ($ltModel) { $asrModel = ($ltModel -replace '\\', '/'); $asrCompute = "int8" }
Step "Saving your choices"
@"
# Written by windows/install.ps1. Paths and model choices, no secrets.
VAULT="$vaultFwd"
TRANSCRIPTIONS_DIR="Transcriptions"
UNIVERSITY_DIR="University"
AUDIO_SCRATCH="$scratch"

WANT_CAPTURE=1
WANT_PROCESS=$wantProcess
LECTURE_BACKEND="$backend"

LECTURE_LANGUAGE="$lang"
LECTURE_NOTE_LANGUAGE="$lang"

LECTURE_MODEL="$liveModel"
LECTURE_CHUNK_SECS="$chunkSecs"
LECTURE_ASR_MODEL="$asrModel"
LECTURE_ASR_COMPUTE="$asrCompute"
LECTURE_LLM="qwen3:8b"
"@ | Set-Content -Encoding UTF8 "$Root\config.sh"

# ---- vault layout and a shortcut -------------------------------------------
Step "Preparing the vault and a shortcut"
# generated folders under auto\, the user's raw notes beside them
foreach ($d in @("auto\live", "auto\transcripts", "auto\audio", "auto\unfiled", "raw notes")) {
    New-Item -ItemType Directory -Force "$vault\Transcriptions\$d" | Out-Null
}
New-Item -ItemType Directory -Force "$vault\University" | Out-Null

# The shortcut points straight at the console-less interpreter. A .bat in
# between opened a cmd window that sat there for the whole recording, and the
# worker and ffmpeg each opened one more; those are suppressed in record.py.
$pyw = "$Root\capture\venv\Scripts\pythonw.exe"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$HOME\Desktop\Transcribe.lnk")
$lnk.TargetPath = $pyw
$lnk.Arguments = "`"$Root\capture\record.py`""
$lnk.WorkingDirectory = $Root
$lnk.IconLocation = "$Root\windows\transcribe.ico,0"
$lnk.Description = "Start or stop a lecture recording"
$lnk.Save()
Remove-Item "$HOME\Desktop\Record lecture.lnk" -ErrorAction SilentlyContinue
Remove-Item "$Root\windows\record.bat" -ErrorAction SilentlyContinue
Say "  shortcut on your Desktop: Transcribe"

Write-Host ""
Write-Host "================================================================"
Write-Host ""
Say "To record: double-click 'Transcribe' on your Desktop."
Say "A window with a flashing red light stays on top while it records."
Say "Press Stop recording, or double-click the shortcut again."
Say ""
Say "While recording, two files appear:"
Say "  $vault\Transcriptions\live         the live transcript, rewritten as it goes"
Say "  $vault\Transcriptions\raw notes    yours: write here, fill in the table to file it"
Say ""
Read-Host "Press Enter to close"
