#!/usr/bin/env bash
# Interactive installer. Works out what this machine can do, asks what you want
# on it, and sets up only that.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MIN_VRAM_MIB=6000        # below this, accurate transcription is not worth offering

say()  { printf '%s\n' "$*"; }
ask()  { local p="$1" d="${2:-}" r; read -r -p "$p${d:+ [$d]}: " r; printf '%s' "${r:-$d}"; }

# ---- what can this machine do? --------------------------------------------
vram=0
if command -v nvidia-smi >/dev/null 2>&1; then
  vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits \
         2>/dev/null | tr -d ' ' | sort -n | tail -1 || echo 0)
fi

say "lecture-pipeline installer"
say
if [ "${vram:-0}" -ge "$MIN_VRAM_MIB" ]; then
  say "Found an NVIDIA GPU with ${vram} MiB. This machine can do both halves."
  say
  say "  1) Live transcription only        record lectures, rough live note"
  say "  2) Processing only                accurate transcript, AI summary, filing"
  say "  3) Both on this machine"
  say
  choice=$(ask "Select" "1")
else
  if [ "${vram:-0}" -gt 0 ]; then
    say "Found an NVIDIA GPU with only ${vram} MiB, under the ${MIN_VRAM_MIB} MiB needed."
  else
    say "No usable NVIDIA GPU found on this machine."
  fi
  say "Only live transcription is offered here. Run the installer again on a"
  say "machine with a GPU to add the processing half."
  say
  choice=1
fi

case "$choice" in
  1) want_capture=1; want_process=0 ;;
  2) want_capture=0; want_process=1 ;;
  3) want_capture=1; want_process=1 ;;
  *) say "not a valid choice"; exit 1 ;;
esac

# ---- where is the vault? ---------------------------------------------------
say
say "Point this at the ROOT of your Obsidian vault, the folder containing .obsidian"
vault=$(ask "Vault path" "$HOME/Documents/Obsidian")
vault="${vault/#\~/$HOME}"

if [ ! -d "$vault" ]; then
  yn=$(ask "$vault does not exist. Create it? (y/n)" "n")
  [ "$yn" = "y" ] || { say "stopping"; exit 1; }
  mkdir -p "$vault"
elif [ ! -d "$vault/.obsidian" ]; then
  say "warning: no .obsidian folder there, so that may not be a vault root."
  yn=$(ask "Continue anyway? (y/n)" "n")
  [ "$yn" = "y" ] || exit 1
fi

transcriptions=$(ask "Folder for pipeline state, inside the vault" "Transcriptions")
university=$(ask   "Folder holding one directory per module" "University")
scratch=$(ask      "Scratch space for raw audio, OUTSIDE the vault" "$HOME/lecture-recordings")
scratch="${scratch/#\~/$HOME}"

cat > "$ROOT/config.sh" <<CONF
# Written by install.sh. Paths only, no secrets.
VAULT="$vault"
TRANSCRIPTIONS_DIR="$transcriptions"
UNIVERSITY_DIR="$university"
AUDIO_SCRATCH="$scratch"
CONF
say
say "wrote config.sh"

# ---- vault layout ----------------------------------------------------------
mkdir -p "$vault/$transcriptions"/{live,transcripts,audio,unfiled}
mkdir -p "$scratch"

example="$vault/$university/EXAMPLE001 Example Module"
if [ ! -d "$example" ]; then
  mkdir -p "$example/Lectures"
  cat > "$example/Timetable EXAMPLE001 Example Module.md" <<'TT'
This module folder is an example of the layout the pipeline expects. Copy the
shape for your real modules, then delete this one.

The folder name is `<CODE> <Module Name>`. The code is everything before the
first space and is what appears in note frontmatter.

Only the second table is read. A date is written once per day and carries
forward to the rows beneath it. Columns after the fourth are ignored, so you can
add your own.

| Starting Date | Last Lecture | Exam Date  |
| ------------- | ------------ | ---------- |
| 01-01-2000    | 01-01-2000   | 01-01-2000 |

| Date       | Start time | End time | Type     |
| ---------- | ---------- | -------- | -------- |
| 01-01-2000 | 09:00      | 10:30    | Theory   |
|            | 10:45      | 12:15    | Practice |

![[Lectures/_index]]
TT
  cat > "$example/Lectures/_index.md" <<'IX'
---
type: lecture-index
note: generated file, edits will be overwritten
---

*No lectures processed yet.*
IX
  say "created an example module at $university/EXAMPLE001 Example Module"
fi

# ---- components ------------------------------------------------------------
[ "$want_capture" = 1 ] && { say; say "--- capture ---"; "$ROOT/capture/install.sh"; }
[ "$want_process" = 1 ] && { say; say "--- processing ---"; "$ROOT/process/install.sh"; }

if [ "$want_capture" = 1 ] && [ "$want_process" = 1 ]; then
  say
  say "Both halves are on this machine. Processing will refuse to start while a"
  say "recording is in progress, so the two never compete for the GPU."
fi

say
say "Add this line to each of your real module timetables, once:"
say "  ![[Lectures/_index]]"
