#!/usr/bin/env bash
# Interactive installer. Detects what this machine can do, asks only what is a
# genuine choice, measures the rest, and installs only the selected halves.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$ROOT/lib/detect.sh"
source "$ROOT/lib/deps.sh"

CONF="$ROOT/config.sh"
MIN_LIVE_FACTOR="${MIN_LIVE_FACTOR:-1.2}"
say() { printf '%s\n' "$*"; }
ask() { local p="$1" d="${2:-}" r; read -r -p "$p${d:+ [$d]}: " r </dev/tty; printf '%s' "${r:-$d}"; }

write_config() {
  cat > "$CONF" <<CONF
# Written by install.sh. Paths and model choices, no secrets.
VAULT="$vault"
TRANSCRIPTIONS_DIR="$tr_dir"
UNIVERSITY_DIR="$uni_dir"
AUDIO_SCRATCH="$scratch"

WANT_CAPTURE=$want_capture
WANT_PROCESS=$want_process
LECTURE_BACKEND="${backend:-cpu}"

LECTURE_LANGUAGE="$lang"
LECTURE_NOTE_LANGUAGE="$note_lang"

LECTURE_MODEL="${live:-}"
LECTURE_ASR_MODEL="${asr_model:-}"
LECTURE_ASR_COMPUTE="${asr_compute:-}"
LECTURE_LLM="${llm:-}"
CONF
}

if [ -f "$CONF" ]; then source "$CONF"; fi
d_lang="${LECTURE_LANGUAGE:-en}"; d_note="${LECTURE_NOTE_LANGUAGE:-en}"
d_llm="${LECTURE_LLM:-llama3.1:8b}"; d_vault="${VAULT:-$HOME/Documents/Obsidian}"
d_tr="${TRANSCRIPTIONS_DIR:-Transcriptions}"; d_uni="${UNIVERSITY_DIR:-University}"
d_scratch="${AUDIO_SCRATCH:-$HOME/lecture-recordings}"

say "lecture-pipeline installer"; say
say "Detected:"
say "  CPU     $CPU_NAME, $CPU_THREADS threads"
say "  GPU     ${GPU_NAME:-none}"
if   [ "$HAS_CUDA"   = 1 ]; then say "  VRAM    ${VRAM_MIB} MiB, CUDA available"
elif [ "$HAS_VULKAN" = 1 ]; then say "  VRAM    shared with system memory, Vulkan available"
else say "  GPU acceleration unavailable, CPU only"; fi
say

# ---- Q0: existing configuration -------------------------------------------
models_only=0
if [ -f "$CONF" ]; then
  say "An existing configuration was found for this machine."; say
  say "  1) Change models only, keep everything else"
  say "  2) Reconfigure everything, your previous answers appear as defaults"
  say "  3) Cancel"; say
  case "$(ask "Select" "1")" in
    1) models_only=1 ;; 2) ;; *) say "cancelled"; exit 0 ;;
  esac
  say
fi

# ---- Q1: components --------------------------------------------------------
if [ "$models_only" = 1 ]; then
  want_capture="${WANT_CAPTURE:-1}"; want_process="${WANT_PROCESS:-0}"
elif [ "$HAS_CUDA" = 1 ] && [ "$VRAM_MIB" -ge 6000 ]; then
  say "What should this machine do?"; say
  say "  1) Live transcription only"
  say "  2) Processing only, accurate transcript and AI notes"
  say "  3) Both  [recommended for this machine]"; say
  case "$(ask "Select" "3")" in
    1) want_capture=1; want_process=0 ;;
    2) want_capture=0; want_process=1 ;;
    *) want_capture=1; want_process=1 ;;
  esac
elif [ "$HAS_VULKAN" = 1 ]; then
  say "What should this machine do?"; say
  say "  1) Live transcription only  [recommended for this machine]"
  say "  2) Both, with transcription on Vulkan"; say
  say "Processing on Vulkan is slower than CUDA and less tested. Option 1 is the"
  say "safe choice if another machine has an NVIDIA card."; say
  case "$(ask "Select" "1")" in
    2) want_capture=1; want_process=1 ;; *) want_capture=1; want_process=0 ;;
  esac
else
  say "This machine has no GPU that can accelerate transcription, so only live"
  say "transcription is offered. It will run on CPU."
  want_capture=1; want_process=0
fi
say

# ---- Q2: language ----------------------------------------------------------
if [ "$models_only" = 1 ]; then
  lang="$d_lang"; note_lang="$d_note"
else
  say "Lecture language:"; say
  say "  1) English"
  say "  2) Lithuanian"
  say "  3) Other, enter a code and choose models manually"; say
  case "$(ask "Select" "1")" in
    2) lang=lt ;; 3) lang="$(ask "Two-letter code" "en")" ;; *) lang=en ;;
  esac
  note_lang="$lang"
  if [ "$lang" != "en" ] && [ "$want_process" = 1 ]; then
    say
    say "What language should the notes be written in?"; say
    say "  1) Same as the lecture"
    say "  2) English  [recommended]"; say
    say "Local models write noticeably better English than most other languages"
    say "at this size, so an English note is often more accurate."; say
    case "$(ask "Select" "2")" in 1) note_lang="$lang" ;; *) note_lang=en ;; esac
  fi
fi
say

# ---- Q3: paths -------------------------------------------------------------
if [ "$models_only" = 1 ]; then
  vault="$d_vault"; tr_dir="$d_tr"; uni_dir="$d_uni"; scratch="$d_scratch"
else
  say "Point this at the ROOT of your Obsidian vault, the folder containing"
  say ".obsidian. Everything else is created inside it automatically."
  say
  vault="$(ask "Obsidian vault" "$d_vault")"
  vault="${vault/#\~/$HOME}"
  vault="${vault%/}"                      # a trailing slash doubles every path
  if [ ! -d "$vault" ]; then
    [ "$(ask "$vault does not exist. Create it? (y/n)" "n")" = "y" ] || { say "stopping"; exit 1; }
    mkdir -p "$vault"
  elif [ ! -d "$vault/.obsidian" ]; then
    say "warning: no .obsidian folder there, so that may not be a vault root."
    [ "$(ask "Continue anyway? (y/n)" "n")" = "y" ] || exit 1
  fi
  tr_dir="Transcriptions"
  uni_dir="University"
  scratch="$DEFAULT_SCRATCH"
fi
say

# first pass: the component installers need the paths before they can run
backend="${LECTURE_BACKEND:-cpu}"; live=""; asr_model=""; asr_compute=""; llm="$d_llm"
write_config
mkdir -p "$vault/$tr_dir"/{live,transcripts,audio,unfiled} "$scratch"
"$ROOT/lib/example-module.sh" "$vault/$uni_dir"

# ---- measure, rather than ask, which backend and live model to use ---------
if [ "$want_capture" = 1 ] && [ "$models_only" = 1 ]; then
  live="${LECTURE_MODEL:-}"
  say "Keeping the measured live model: ${live:-none}"
  say
elif [ "$want_capture" = 1 ]; then
  build_vulkan=0
  if [ "$HAS_VULKAN" = 1 ]; then
    missing="$(vulkan_build_missing)"
    if [ -n "$missing" ]; then
      say "Vulkan could be measured, but this machine is missing:"
      for m in $missing; do say "  $m"; done
      say
      say "Install them and re-run to include Vulkan in the benchmark:"
      say "  $(install_hint $missing)"
      say
      say "Continuing with CPU only."; say
    else
      build_vulkan=1
    fi
  fi

  say "--- preparing to benchmark this machine ---"
  BUILD_VULKAN=$build_vulkan "$ROOT/capture/install.sh" --prereqs
  say

  wcpp=""; [ "$build_vulkan" = 1 ] && wcpp="$ROOT/capture/whisper.cpp"
  bench_lang="$lang"; [ -f "$ROOT/samples/sample-$lang.ogg" ] || bench_lang=en
  out="$(HAS_CUDA=$HAS_CUDA MIN_LIVE_FACTOR=$MIN_LIVE_FACTOR \
        "$ROOT/capture/venv/bin/python" "$ROOT/lib/benchmark.py" \
        "$bench_lang" "$ROOT/samples" "$ROOT/.bench" "$wcpp" | tee /dev/tty)"
  result="$(printf '%s\n' "$out" | sed -n 's/^RESULT //p')"
  backend="$(printf '%s' "$result" | cut -d' ' -f1)"
  live="$(printf '%s' "$result"    | cut -d' ' -f2)"
  say

  if [ "$backend" = "none" ]; then
    say "Live transcription in this language needs ${MIN_LIVE_FACTOR}x or better,"
    say "and this machine does not reach it. Smaller models are fast enough but"
    say "their quality is too poor to be worth reading."; say
    say "  1) Record audio only, no live transcript"
    say "     The recording still works. The accurate transcript and notes are"
    say "     produced later on the processing machine, which is where the"
    say "     quality comes from anyway."
    say "  2) Switch to English"
    say "     Only if your lectures are actually in English. An English model on"
    say "     other speech produces confident nonsense."
    say "  3) Cancel"; say
    case "$(ask "Select" "1")" in
      2) lang=en; note_lang=en; backend=cpu; live="small.en"
         say "Switched to English. Re-run the installer to benchmark it." ;;
      3) say "cancelled"; exit 0 ;;
      *) backend=none; live="" ;;
    esac
    say
  fi
fi

# ---- accurate model, derived from VRAM rather than asked -------------------
if [ "$want_process" = 1 ]; then
  if   [ "$VRAM_MIB" -ge 6000 ]; then asr_model=large-v3; asr_compute=float16
  elif [ "$VRAM_MIB" -ge 4000 ]; then asr_model=large-v3; asr_compute=int8_float16
  else                                asr_model=medium;   asr_compute=int8_float16
  fi
  say "Accurate transcription model: $asr_model ($asr_compute)"
  say "  Nothing waits on this stage, so the largest model that fits is used."
  say

  say "Model for writing the notes:"; say
  if [ "$note_lang" = "en" ]; then
    say "  1) Llama 3.1    [recommended]  strong English, weaker elsewhere"
    say "  2) Gemma                       better multilingual coverage"
    say "  3) Qwen                        better multilingual coverage"
  else
    say "  1) Llama 3.1                   strong English, weaker elsewhere"
    say "  2) Gemma        [recommended]  better multilingual coverage"
    say "  3) Qwen         [recommended]  better multilingual coverage"
  fi
  say "  4) Other, enter an Ollama tag yourself"; say
  say "These can be changed later by re-running this installer and choosing"
  say "\"Change models only\"; nothing else is touched."; say
  dflt=1; [ "$note_lang" != "en" ] && dflt=2
  case "$(ask "Select" "$dflt")" in
    2) llm="gemma2:9b" ;;
    3) llm=$([ "$VRAM_MIB" -ge 10000 ] && echo "qwen2.5:14b" || echo "qwen2.5:7b") ;;
    4) llm="$(ask "Ollama tag" "$d_llm")" ;;
    *) llm="llama3.1:8b" ;;
  esac
  say "Summariser: $llm"; say
fi

write_config

[ "$want_capture" = 1 ] && { say; say "--- capture ---";    "$ROOT/capture/install.sh" --models; }
[ "$want_process" = 1 ] && { say; say "--- processing ---"; "$ROOT/process/install.sh"; }

say
say "================================================================"
say

if [ "$want_capture" = 1 ] && [ -n "$live" ]; then
  case "$OS_NAME" in
    Linux)
      say "To record a lecture"
      say
      say "  Search your applications for 'Lecture transcription'. Right click it"
      say "  and choose Pin to Task Manager to keep it on the panel."
      say
      say "  Tap once to start. A red dot blinks in the system tray for as long"
      say "  as it is recording."
      say
      say "  Tap the launcher again, or click the red dot, to stop."
      ;;
    Darwin|MINGW*|MSYS*|CYGWIN*)
      say "Capture is not yet supported on $OS_NAME."
      say
      say "The recording wrapper uses systemd, flock and PulseAudio capture,"
      say "which have no equivalent here. Transcription and summarising are"
      say "portable and do work; only the capture half is Linux-only."
      ;;
  esac
  say
  say "  Transcript and your notes appear in:"
  say "    $tr_dir/live/"
  say "  Type in the 'my notes' file, never in the transcript. It is appended"
  say "  to every few seconds and your edits would be lost."
  say
  say "  Using $live on $backend."
elif [ "$want_capture" = 1 ]; then
  say "Recording audio only, with no live transcript, as chosen."
fi

if [ "$want_process" = 1 ]; then
  say
  say "Processing runs by itself"
  say
  say "  A timer checks every minute and works through anything new. It defers"
  say "  while you are gaming or recording, so it never competes for the GPU."
  say
  say "  Watch it with:   journalctl --user -fu lecture-notes"
  say "  Or read:         ~/.local/state/lecture-notes/run.log"
  say "  Stop it with:    systemctl --user stop lecture-notes.timer"
fi

say
say "One manual step: add this line to each module timetable, once."
say
say "  ![[Sessions/_index]]"
say
say "Re-run this installer any time to try a different model. Choose"
say "'Change models only' and nothing else is touched."
