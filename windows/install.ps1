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

# The previous answers, so a re-run offers them as defaults and "Change models
# only" can keep everything else, as install.sh does.
$Conf = "$Root\config.sh"
$PrevCfg = @{}
if (Test-Path $Conf) {
    foreach ($line in (Get-Content $Conf -Encoding UTF8)) {
        if (-not $line.TrimStart().StartsWith("#") -and $line -match '^\s*([A-Z_]+)="?(.*?)"?\s*$') {
            $PrevCfg[$Matches[1]] = $Matches[2]
        }
    }
}
function Prev($key, $default) {
    if ($PrevCfg.ContainsKey($key) -and $PrevCfg[$key]) { return $PrevCfg[$key] }
    return $default
}

# A native program's stdout without echoing it, and without its stderr
# aborting the script (see Native).
function Quiet([string]$exe, [string[]]$argv) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $out = & $exe @argv 2>$null } catch { $out = @() }
    $ErrorActionPreference = $prev
    return @($out)
}

function OllamaUp {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:11434/api/version" | Out-Null
        return $true
    } catch { return $false }
}

# The Windows build is a tray app that runs the server; the bare CLI is the
# fallback when the app is not where the installer puts it.
function StartOllama {
    $app = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process $app }
    else { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden }
    for ($i = 0; $i -lt 30 -and -not (OllamaUp); $i++) { Start-Sleep 1 }
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

$modelsOnly = 0
if ($PrevCfg.Count -gt 0) {
    Say ""
    Say "An existing configuration was found for this machine."
    Say ""
    Say "  1) Change models only, keep everything else"
    Say "  2) Reconfigure everything, your previous answers appear as defaults"
    Say "  3) Cancel"
    Say ""
    switch (Ask "Select" "1") {
        "1" { $modelsOnly = 1 }
        "2" { }
        default { Say "cancelled"; exit 0 }
    }
}

$wantCapture = 1
$wantProcess = 0
# Processing needs CUDA, so it needs both an NVIDIA card and a working driver.
$dRole = "1"
if ((Prev "WANT_PROCESS" "0") -eq "1") { $dRole = if ((Prev "WANT_CAPTURE" "1") -eq "0") { "2" } else { "3" } }
if ($modelsOnly -eq 1) {
    $wantCapture = [int](Prev "WANT_CAPTURE" "1")
    $wantProcess = [int](Prev "WANT_PROCESS" "0")
} elseif ($nvidia.Count -gt 0 -and (Have nvidia-smi)) {
    Say ""
    Say "That card can do the transcription and note writing as well."
    Say ""
    Say "  1) Record only, another machine writes the notes"
    Say "  2) Processing only: write the notes for recordings made elsewhere"
    Say "  3) Both: record here and produce the notes here"
    Say ""
    switch (Ask "Select" $dRole) {
        "2" { $wantCapture = 0; $wantProcess = 1 }
        "3" { $wantProcess = 1 }
    }
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
$lang = Prev "LECTURE_LANGUAGE" "en"
$noteLang = Prev "LECTURE_NOTE_LANGUAGE" "en"
if ($modelsOnly -eq 0) {
    Screen
    Step "Lecture language"
    Say "  1) English"
    Say "  2) Lithuanian"
    Say ""
    $dLang = if ($lang -eq "lt") { "2" } else { "1" }
    $lang = "en"
    if ((Ask "Select" $dLang) -eq "2") {
        $lang = "lt"
        Say ""
        Say "  Lithuanian uses a dedicated model, Azuolas (akisviete/azuolas-whisper-lt),"
        Say "  trained on about 9,800 hours of Lithuanian. It recognises word forms and"
        Say "  legal and technical terms far better than any other model tested. Its"
        Say "  output has no punctuation or capitalisation, which the summariser copes"
        Say "  with but which makes the raw transcript harder to read."
    }
    $noteLang = "en"
    if ($lang -ne "en") {
        Say ""
        Say "Language of the notes:"
        Say ""
        Say "  1) Same as the lecture"
        Say "  2) English  [recommended]"
        Say ""
        if ((Ask "Select" "2") -eq "1") { $noteLang = $lang }
    }
}

# ---- vault -----------------------------------------------------------------
if ($lang -eq "lt") { Decided "Lithuanian" } else { Decided "English" }
$vault = (Prev "VAULT" "$HOME\Documents\ai-notes-vault") -replace '/', '\'
if ($modelsOnly -eq 0) {
    Screen
    Step "Where is your Obsidian vault"
    Say "  The folder containing .obsidian. Everything else is created inside it."
    Say "  On a borrowed machine, point this somewhere scratch."
    Say ""
    $vault = Ask "Vault path" $vault
}
$vault = $vault.TrimEnd('\')
if (-not (Test-Path $vault)) {
    if ((Ask "$vault does not exist. Create it? (y/n)" "y") -ne "y") { exit 1 }
    New-Item -ItemType Directory -Force $vault | Out-Null
}
$vaultFwd = $vault -replace '\\', '/'
$scratch = "$env:LOCALAPPDATA\lecture-pipeline" -replace '\\', '/'

# ---- note model ------------------------------------------------------------
$llm = Prev "LECTURE_LLM" "gemma3:12b"
if ($wantProcess -eq 1) {
    $vramTotal = 0
    # @() because PowerShell unwraps a one-line result into a plain string, and
    # $v[0] of "12288" is "1": a 12 GB card was sized as 1 MiB.
    $v = @(Quiet "nvidia-smi" @("--query-gpu=memory.total", "--format=csv,noheader,nounits"))
    if ($v.Count -gt 0 -and "$($v[0])".Trim() -match '^\d+$') { $vramTotal = [int]"$($v[0])".Trim() }
    # Each family at the largest size whose Q4 weights fit with 1.5 GB to
    # spare, as in install.sh. Ollama spills what does not fit to the CPU:
    # slower, not fatal.
    $room = $vramTotal - 1500
    if ($room -ge 16200)    { $gemma = "gemma3:27b"; $gemmaGb = "17" }
    elseif ($room -ge 7730) { $gemma = "gemma3:12b"; $gemmaGb = "8.1" }
    else                    { $gemma = "gemma3:4b";  $gemmaGb = "3.3" }
    if ($room -ge 8870) { $qwen = "qwen3:14b"; $qwenGb = "9.3" }
    else                { $qwen = "qwen3:8b";  $qwenGb = "5.2" }
    $llama = "llama3.1:8b"; $llamaGb = "4.9"

    Screen
    Step "Model for writing the notes"
    Say "  Sizes are chosen for this card's $vramTotal MiB. A model slightly too"
    Say "  large spills into system RAM and runs slower, but still works."
    Say ""
    Say ("  1) {0,-12} {1} GB  [recommended]" -f $gemma, $gemmaGb)
    Say "                          Accurate, well-organised prose. Handles names,"
    Say "                          quotes in other languages and Lithuanian well."
    Say "                          Can smooth over small specifics."
    if ($gemma -eq "gemma3:4b") {
    Say "                          The 12b (8.1 GB) is too large for this card."
    }
    Say ("  2) {0,-12} {1} GB" -f $qwen, $qwenGb)
    Say "                          Keeps the most specifics: numbers, dates, exact"
    Say "                          quotes. Terser prose, more often misattributes who"
    Say "                          said what. Thinks before writing, so it is slower."
    Say ("  3) {0,-12} {1} GB" -f $llama, $llamaGb)
    Say "                          Fluent English, small and fast. Summarises rather"
    Say "                          than takes notes: drops detail and can merge"
    Say "                          separate statements into one. English only."
    Say "  4) Other, enter an Ollama tag yourself"
    Say ""
    Say "  These can be changed later by re-running this installer and choosing"
    Say "  ""Change models only""; nothing else is touched."
    Say ""
    switch (Ask "Select" "1") {
        "2" { $llm = $qwen }
        "3" { $llm = $llama }
        "4" { $llm = Ask "Ollama tag" $llm }
        default { $llm = $gemma }
    }
    Decided "notes: $llm"
}

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
& "$Root\capture\venv\Scripts\pip.exe" install -q faster-whisper numpy PyQt6 pypdf
if ($nvidia.Count -gt 0) {
    # The benchmark and the live pass run from THIS venv, so the CUDA libraries
    # have to be here. Without them faster-whisper reports a missing
    # cublas64_12.dll, which reads like a driver problem and is not.
    Say "  adding CUDA libraries"
    & "$Root\capture\venv\Scripts\pip.exe" install -q nvidia-cublas-cu12 nvidia-cudnn-cu12
}
Say "  done"

# Lithuanian has one model worth using, Azuolas, downloaded ready-made: the
# same step the Linux installer runs. float16 (2.9 GB) for a processing card
# with 6 GB or more, where the accurate pass wants the precision; int8 (1.5 GB)
# otherwise, which fits a 4 GB laptop card and which its author measured only
# 0.08 WER points behind.
$ltModel = ""
if ($lang -eq "lt") {
    Step "Preparing the Lithuanian model"
    $ltArgs = @("$Root\lib\fetch_lt_model.py", "$env:LOCALAPPDATA\lecture-pipeline")
    if ($wantProcess -eq 1 -and $vramTotal -ge 6000) { $ltArgs += "--float16" }
    $r = Native "python" $ltArgs
    $ltModel = if ($r.Lines.Count -gt 0) { ($r.Lines | Select-Object -Last 1).Trim() } else { "" }
    if ($r.Code -ne 0 -or -not (Test-Path $ltModel)) {
        Say ""
        Say "Could not prepare the Lithuanian model. The last line above says why."
        Read-Host "Press Enter to close"; exit 1
    }
    Say "  ready: $ltModel"
    # The live fallback: a card that cannot run Azuolas live gets paprika-v3's
    # live text rather than none. Not fatal if it fails; audio only remains.
    $ltFallback = ""
    if ($wantCapture -eq 1) {
        $r = Native "python" @("$Root\lib\fetch_lt_model.py", "$env:LOCALAPPDATA\lecture-pipeline", "--model", "paprika")
        $f = if ($r.Lines.Count -gt 0) { ($r.Lines | Select-Object -Last 1).Trim() } else { "" }
        if ($r.Code -eq 0 -and $f -and (Test-Path $f)) { $ltFallback = $f; Say "  live fallback: $ltFallback" }
    }
}

# The benchmark picks the live model, so a machine that only processes skips it.
$liveModel = ""; $chunkSecs = 12; $windowSecs = 30; $backend = "cpu"
if ($wantCapture -eq 1) {
    Step "Measuring this machine"
    Say "  Trying the largest model first and falling back only if it cannot keep"
    Say "  up. Models are downloaded as they are needed, so this takes a while."
    Say ""

    # gpu_probe reports vendor, name, total VRAM, whether the card is discrete, and free VRAM
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
    $env:VRAM_FREE_MIB = if ($parts.Count -ge 5) { $parts[4] } else { "$vram" }
    $env:MIN_LIVE_FACTOR = "1.2"
    # best first, "|" between them: Azuolas, then paprika-v3 if it cannot keep up
    $env:LECTURE_FIXED_MODEL = if ($ltFallback) { "$ltModel|$ltFallback" } else { "$ltModel" }

    # Stream rather than capture. Collecting the output first means nothing
    # appears until the whole benchmark finishes, which on a slow machine with
    # models to download is many minutes of a blank screen.
    $r = Native "$Root\capture\venv\Scripts\python.exe" @("$Root\lib\benchmark.py", $lang, "$Root\samples", "$Root\.bench")
    $bench = $r.Lines
    # The result line is tab-separated, so a wildcard with a space after RESULT
    # never matched it. That silently turned every measured model into "none".
    $resultLine = $bench | Where-Object { $_ -match "^RESULT`t" } | Select-Object -Last 1
    $result = if ($resultLine) { "$resultLine" } else { "" }

    if ($result) {
        $rp = $result -split "`t"
        # fields: RESULT, backend, model, factor, interval, window
        if ($rp.Count -ge 3 -and $rp[1] -ne "none") { $liveModel = $rp[2]; $backend = $rp[1] }
        if ($rp.Count -ge 5) { $chunkSecs = $rp[4] }
        if ($rp.Count -ge 6) { $windowSecs = $rp[5] }
    }
    # the config is parsed as KEY="value" with forward slashes; keep a path usable
    if ($liveModel -and (Test-Path $liveModel)) { $liveModel = $liveModel -replace '\\', '/' }
}

if ($wantCapture -eq 1 -and -not $liveModel) {
    Say ""
    Say "Nothing on this machine keeps up with live transcription in this"
    Say "language. Recording still works and the notes are produced later on a"
    Say "machine that can."
    Say ""
}
if (-not $liveModel) { $liveModel = "none" }

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
    & "$Root\process\venv\Scripts\pip.exe" install -q faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 PyQt6 pypdf openpyxl
    # The Linux installer's systemd timer, as a scheduled task. pythonw, so the
    # run every minute does not flash a console window; it logs to run.log.
    $sched = & "$Root\process\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'$Root\shared'); import platform_support as p; print(p.register_periodic('lecture-notes', [r'$Root\process\venv\Scripts\pythonw.exe', r'$Root\process\pipeline.py'], 1))"
    Say "  $sched"

    # ---- Ollama, as process/install.sh does on Linux ----
    Step "Ollama and the note model"
    if (-not (Have ollama) -and (Have winget)) {
        Say "  installing Ollama"
        winget install --accept-source-agreements --accept-package-agreements -e --id Ollama.Ollama | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") +
                    ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    }
    if (-not (Have ollama)) {
        Say ""
        Say "Ollama is not installed and could not be installed here. Install it"
        Say "from ollama.com, then run this installer again and choose"
        Say """Change models only""."
        Read-Host "Press Enter to close"; exit 1
    }
    # Never a remote Ollama from a profile: the pipeline talks to this one.
    $env:OLLAMA_HOST = "127.0.0.1:11434"
    # Release the card 30 s after each summary, or the next transcription never
    # finds free VRAM. Ollama reads this at start, so a running one restarts.
    $env:OLLAMA_KEEP_ALIVE = "30s"
    if ([System.Environment]::GetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "User") -ne "30s") {
        [System.Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "30s", "User")
        if (OllamaUp) {
            Say "  restarting Ollama so it releases the card between runs"
            Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
            Start-Sleep 2
        }
    }
    if (-not (OllamaUp)) { StartOllama }
    if (-not (OllamaUp)) {
        Say ""
        Say "Cannot reach Ollama at 127.0.0.1:11434. Start the Ollama app from the"
        Say "Start menu, then run this installer again and choose ""Change models only""."
        Read-Host "Press Enter to close"; exit 1
    }
    Say "  pulling $llm, several GB the first time"
    $r = Native "ollama" @("pull", $llm)
    if ($r.Code -ne 0) {
        Say ""
        Say "Ollama is running but '$llm' could not be pulled, so the tag is likely"
        Say "wrong. Model names move; check ollama.com/library and run this installer"
        Say "again, choosing Other to enter a tag yourself."
        Read-Host "Press Enter to close"; exit 1
    }
    Say "  ready: $llm"
}

# ---- config ----------------------------------------------------------------
# Azuolas is a full large-v3, so float16 needs the same 6 GB as stock large-v3.
# Its author found 22-second pieces cut at silences about 4 WER points better
# than one long pass, so Lithuanian is transcribed that way.
$asrModel = "large-v3"; $asrCompute = "float16"; $asrChunk = 0
if ($ltModel) {
    $asrModel = ($ltModel -replace '\\', '/')
    $asrCompute = if ($vramTotal -ge 6000) { "float16" } else { "int8_float16" }
    $asrChunk = 22
}
Step "Saving your choices"
@"
# Written by windows/install.ps1. Paths and model choices, no secrets.
VAULT="$vaultFwd"
TRANSCRIPTIONS_DIR="Transcriptions"
UNIVERSITY_DIR="University"
AUDIO_SCRATCH="$scratch"

WANT_CAPTURE=$wantCapture
WANT_PROCESS=$wantProcess
LECTURE_BACKEND="$backend"

LECTURE_LANGUAGE="$lang"
LECTURE_NOTE_LANGUAGE="$noteLang"

LECTURE_MODEL="$liveModel"
LECTURE_CHUNK_SECS="$chunkSecs"
LECTURE_WINDOW_SECS="$windowSecs"
LECTURE_ASR_MODEL="$asrModel"
LECTURE_ASR_COMPUTE="$asrCompute"
LECTURE_ASR_CHUNK_SECS="$asrChunk"
LECTURE_LLM="$llm"
"@ | Set-Content -Encoding UTF8 "$Root\config.sh"

# ---- the document watcher: a note for a file in Files within a minute ------
$watch = & "$Root\capture\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'$Root\shared'); import platform_support as p; print(p.register_periodic('ai-notes-documents', [r'$Root\capture\venv\Scripts\pythonw.exe', r'$Root\process\document.py', r'$vault'], 1))"
Say "  $watch"

# ---- vault layout and a shortcut -------------------------------------------
Step "Preparing the vault and a shortcut"
# generated folders under auto\, the user's my notes beside them
foreach ($d in @("auto\live", "auto\transcripts", "auto\audio", "auto\unfiled", "my notes")) {
    New-Item -ItemType Directory -Force "$vault\Transcriptions\$d" | Out-Null
}
New-Item -ItemType Directory -Force "$vault\University" | Out-Null

if ($wantCapture -eq 1) {
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
}

Write-Host ""
Write-Host "================================================================"
Write-Host ""
if ($wantCapture -eq 1) {
    Say "To record: double-click 'Transcribe' on your Desktop."
    Say "A window with a flashing red light stays on top while it records."
    Say "Press Stop recording, or double-click the shortcut again."
    Say ""
    Say "While recording, two files appear:"
    Say "  $vault\Transcriptions\live         the live transcript, rewritten as it goes"
    Say "  $vault\Transcriptions\my notes    yours: write here, fill in the table to file it"
    Say ""
} else {
    Say "This machine writes the notes. Every minute it looks for new recordings"
    Say "in $vault\Transcriptions\auto\audio and turns them into notes."
    Say ""
    Say "Progress is logged to $env:LOCALAPPDATA\lecture-notes\state\run.log"
    Say "Check the task with:  schtasks /Query /TN lecture-notes"
    Say ""
}
Read-Host "Press Enter to close"
