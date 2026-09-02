#!/usr/bin/env bash
# Interactive installer. Detects what this machine can do, asks only what is a
# genuine choice, derives the rest, and installs only the selected halves.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$ROOT/lib/detect.sh"
source "$ROOT/lib/deps.sh"

CONF="$ROOT/config.sh"
say() { printf '%s\n' "$*"; }
ask() { local p="$1" d="${2:-}" r; read -r -p "$p${d:+ [$d]}: " r </dev/tty; printf '%s' "${r:-$d}"; }

# previous answers become the defaults, so re-running and pressing Enter is a no-op
if [ -f "$CONF" ]; then source "$CONF"; fi
d_lang="${LECTURE_LANGUAGE:-en}"
d_note="${LECTURE_NOTE_LANGUAGE:-en}"
d_live="${LECTURE_MODEL:-}"
d_llm="${LECTURE_LLM:-llama3.1:8b}"
d_vault="${VAULT:-$HOME/Documents/Obsidian}"
d_tr="${TRANSCRIPTIONS_DIR:-Transcriptions}"
d_uni="${UNIVERSITY_DIR:-University}"
d_scratch="${AUDIO_SCRATCH:-$HOME/lecture-recordings}"

say "lecture-pipeline installer"
say
say "Detected:"
say "  CPU     $CPU_NAME, $CPU_THREADS threads"
say "  GPU     ${GPU_NAME:-none}"
if [ "$HAS_CUDA" = 1 ]; then say "  VRAM    ${VRAM_MIB} MiB, CUDA available"
elif [ "$HAS_VULKAN" = 1 ]; then say "  VRAM    shared with system memory, Vulkan available"
else say "  GPU acceleration unavailable, CPU only"; fi
say

# ---- Q0: existing configuration -------------------------------------------
models_only=0
if [ -f "$CONF" ]; then
  say "An existing configuration was found for this machine."
  say
  say "  1) Change models only, keep everything else"
  say "  2) Reconfigure everything, your previous answers appear as defaults"
  say "  3) Cancel"
  say
  case "$(ask "Select" "1")" in
    1) models_only=1 ;;
    2) ;;
    *) say "cancelled"; exit 0 ;;
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
    2) want_capture=1; want_process=1 ;;
    *) want_capture=1; want_process=0 ;;
  esac
else
  say "This machine has no GPU that can accelerate transcription, so only live"
  say "transcription is offered. It will run on CPU."
  want_capture=1; want_process=0
fi
say

# ---- Q2: backend -----------------------------------------------------------
if [ "$models_only" = 1 ]; then
  backend="${LECTURE_BACKEND:-cpu}"
elif [ "$HAS_CUDA" = 1 ]; then
  say "Transcription backend:"; say
  say "  1) CUDA, faster-whisper   [recommended for this machine]"
  say "  2) CPU"; say
  case "$(ask "Select" "1")" in 2) backend=cpu ;; *) backend=cuda ;; esac
elif [ "$HAS_VULKAN" = 1 ]; then
  say "Transcription backend:"; say
  say "  1) Vulkan, whisper.cpp   [recommended for this machine]"
  say "  2) CPU, faster-whisper"; say
  say "Vulkan works on AMD, Intel and integrated graphics. On an integrated GPU"
  say "the gain over CPU is not guaranteed, because both share the same memory"
  say "bandwidth. Worth measuring rather than assuming."; say
  case "$(ask "Select" "1")" in 2) backend=cpu ;; *) backend=vulkan ;; esac
else
  say "Transcription will run on CPU."
  backend=cpu
fi

# Vulkan needs a build toolchain, not just the runtime. Check before asking
# anything else, so a missing package is not discovered halfway through a build.
if [ "$backend" = "vulkan" ]; then
  missing="$(vulkan_build_missing)"
  if [ -n "$missing" ]; then
    say
    say "Vulkan needs whisper.cpp compiled from source, and this machine is"
    say "missing:"
    for m in $missing; do say "  $m"; done
    say
    say "Install them, then run this installer again:"
    say
    say "  $(install_hint $missing)"
    say
    exit 1
  fi
fi
say

# ---- Q3: language ----------------------------------------------------------
if [ "$models_only" = 1 ]; then
  lang="$d_lang"; note_lang="$d_note"
else
  say "Lecture language:"; say
  say "  1) English   [recommended, dedicated models are faster and more accurate]"
  say "  2) Lithuanian"
  say "  3) Other, enter a two-letter code"; say
  case "$(ask "Select" "1")" in
    2) lang=lt ;;
    3) lang="$(ask "Two-letter code" "en")" ;;
    *) lang=en ;;
  esac

  note_lang="$lang"
  if [ "$lang" != "en" ]; then
    say
    say "Note: outside English, only the multilingual models exist. They are the"
    say "same size and speed but noticeably weaker, and the gap is widest at the"
    say "small sizes used for live transcription."
    if [ "$want_process" = 1 ]; then
      say
      say "What language should the notes be written in?"; say
      say "  1) Same as the lecture"
      say "  2) English  [recommended]"; say
      say "Local models write noticeably better English than most other languages"
      say "at this size, so an English note is often more accurate."; say
      case "$(ask "Select" "2")" in 1) note_lang="$lang" ;; *) note_lang=en ;; esac
    fi
  fi
fi
suffix=""; [ "$lang" = "en" ] && suffix=".en"
say

# ---- Q4: live model --------------------------------------------------------
if [ "$want_capture" = 1 ]; then
  say "Live transcription model:"; say
  case "$backend" in
    cuda)
      say "  1) small    [recommended]  fast, adequate for following along"
      say "  2) medium                  better, still real time on a GPU"
      say "  3) large-v3                best, may fall behind on a busy machine"; say
      case "$(ask "Select" "1")" in 2) live=medium$suffix ;; 3) live=large-v3 ;; *) live=small$suffix ;; esac ;;
    vulkan)
      say "  1) small    [recommended]  should keep up"
      say "  2) medium                  worth testing, may fall behind"; say
      say "Vulkan on integrated graphics shares memory bandwidth with the CPU, so"
      say "medium is a genuine experiment rather than a safe upgrade."; say
      case "$(ask "Select" "1")" in 2) live=medium$suffix ;; *) live=small$suffix ;; esac ;;
    *)
      say "  1) base     faster, rougher"
      say "  2) small    [recommended]  real time on 8 cores"
      say "  3) medium                  will not keep up on most CPUs"; say
      case "$(ask "Select" "2")" in 1) live=base$suffix ;; 3) live=medium$suffix ;; *) live=small$suffix ;; esac ;;
  esac
  say
else
  live="${d_live:-small$suffix}"
fi

# ---- Q5: accurate model, derived not asked ---------------------------------
asr_model=""; asr_compute=""
if [ "$want_process" = 1 ]; then
  if [ "$VRAM_MIB" -ge 6000 ]; then      asr_model=large-v3; asr_compute=float16
  elif [ "$VRAM_MIB" -ge 4000 ]; then    asr_model=large-v3; asr_compute=int8_float16
  elif [ "$VRAM_MIB" -gt 0 ]; then       asr_model=medium;   asr_compute=int8_float16
  else                                   asr_model=medium;   asr_compute=int8_float16
  fi
  say "Accurate transcription model: $asr_model ($asr_compute)"
  if [ "$VRAM_MIB" -gt 0 ]; then
    say "  Chosen for ${VRAM_MIB} MiB of VRAM. Nothing waits on this stage, so the"
    say "  largest model that fits is used."
  else
    say "  Chosen for shared memory. Nothing waits on this stage."
  fi
  say
fi

# ---- Q6: summariser --------------------------------------------------------
llm="$d_llm"
if [ "$want_process" = 1 ]; then
  say "Model for writing the notes:"; say
  if [ "$note_lang" = "en" ]; then
    say "  1) Llama 3.1    [recommended]  strong English, weaker on other languages"
    say "  2) Gemma                       better multilingual coverage"
    say "  3) Qwen                        better multilingual coverage"
  else
    say "  1) Llama 3.1                   strong English, weaker elsewhere"
    say "  2) Gemma        [recommended]  better multilingual coverage"
    say "  3) Qwen         [recommended]  better multilingual coverage"
  fi
  say "  4) Other, enter an Ollama tag yourself"; say
  say "The installer picks the largest size that fits and pulls it. These can be"
  say "changed later by running this installer again and choosing"
  say "\"Change models only\"; nothing else is touched."; say
  default_family=1; [ "$note_lang" != "en" ] && default_family=2
  case "$(ask "Select" "$default_family")" in
    2) fam=gemma ;;
    3) fam=qwen ;;
    4) fam=other ;;
    *) fam=llama ;;
  esac
  big=0; [ "$VRAM_MIB" -ge 10000 ] && big=1
  case "$fam" in
    llama) llm="llama3.1:8b" ;;
    gemma) llm="gemma2:9b" ;;
    qwen)  llm=$([ "$big" = 1 ] && echo "qwen2.5:14b" || echo "qwen2.5:7b") ;;
    other) llm="$(ask "Ollama tag" "$d_llm")" ;;
  esac
  say "Summariser: $llm"; say
fi

# ---- Q7: paths -------------------------------------------------------------
if [ "$models_only" = 1 ]; then
  vault="$d_vault"; tr_dir="$d_tr"; uni_dir="$d_uni"; scratch="$d_scratch"
else
  say "Point this at the ROOT of your Obsidian vault, the folder containing .obsidian"
  vault="$(ask "Vault path" "$d_vault")"; vault="${vault/#\~/$HOME}"
  if [ ! -d "$vault" ]; then
    [ "$(ask "$vault does not exist. Create it? (y/n)" "n")" = "y" ] || { say "stopping"; exit 1; }
    mkdir -p "$vault"
  elif [ ! -d "$vault/.obsidian" ]; then
    say "warning: no .obsidian folder there, so that may not be a vault root."
    [ "$(ask "Continue anyway? (y/n)" "n")" = "y" ] || exit 1
  fi
  tr_dir="$(ask "Folder for pipeline state, inside the vault" "$d_tr")"
  uni_dir="$(ask "Folder holding one directory per module" "$d_uni")"
  scratch="$(ask "Scratch space for raw audio, OUTSIDE the vault" "$d_scratch")"
  scratch="${scratch/#\~/$HOME}"
fi

# ---- write config ----------------------------------------------------------
cat > "$CONF" <<CONF
# Written by install.sh. Paths and model choices, no secrets.
VAULT="$vault"
TRANSCRIPTIONS_DIR="$tr_dir"
UNIVERSITY_DIR="$uni_dir"
AUDIO_SCRATCH="$scratch"

WANT_CAPTURE=$want_capture
WANT_PROCESS=$want_process
LECTURE_BACKEND="$backend"

LECTURE_LANGUAGE="$lang"
LECTURE_NOTE_LANGUAGE="$note_lang"

LECTURE_MODEL="$live"
LECTURE_ASR_MODEL="$asr_model"
LECTURE_ASR_COMPUTE="$asr_compute"
LECTURE_LLM="$llm"
CONF
say "wrote config.sh"

# ---- vault layout ----------------------------------------------------------
mkdir -p "$vault/$tr_dir"/{live,transcripts,audio,unfiled} "$scratch"
"$ROOT/lib/example-module.sh" "$vault/$uni_dir"

# ---- components ------------------------------------------------------------
[ "$want_capture" = 1 ] && { say; say "--- capture ---";    "$ROOT/capture/install.sh"; }
[ "$want_process" = 1 ] && { say; say "--- processing ---"; "$ROOT/process/install.sh"; }

say
if [ "$want_capture" = 1 ] && [ "$want_process" = 1 ]; then
  say "Both halves are on this machine. Processing refuses to start while a"
  say "recording is in progress, so the two never compete for the GPU."
  say
fi
say "Add this line to each of your real module timetables, once:"
say "  ![[Lectures/_index]]"
say
say "To compare summarisers later: run this installer, choose \"Change models"
say "only\", then delete a marker in ~/.local/state/lecture-notes/ to have that"
say "lecture re-summarised from the same transcript."
