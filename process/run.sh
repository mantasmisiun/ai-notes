#!/usr/bin/env bash
# Lecture pipeline. Level-triggered: works out what state each recording is in
# and advances exactly one of them, so it is correct after a reboot, a missed
# run, or an interruption.
set -uo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SELF/../config.sh"
STATE="$HOME/.local/state/lecture-notes"
LOG="$STATE/run.log"
LOCK="$STATE/run.lock"

NOTES="$VAULT/$TRANSCRIPTIONS_DIR"
UNI="$VAULT/$UNIVERSITY_DIR"

MIN_FREE_MIB=7000        # room for whisper large-v3 or an 8B model
KEEP_AUDIO_DAYS=7        # audio is the only irreplaceable artefact

mkdir -p "$STATE" "$NOTES"/{live,transcripts,audio,unfiled}
log() { printf '%s  %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

exec 9>"$LOCK"
if ! flock -n 9; then
  log "skip: another run holds the lock"
  exit 0
fi

# If capture is installed on this same machine, never process during a
# recording: the two would compete for the GPU and the live transcript is the
# one with a person waiting on it.
CAPTURE_PID="$SELF/../capture/run.pid"
if [ -f "$CAPTURE_PID" ] && kill -0 "$(cat "$CAPTURE_PID")" 2>/dev/null; then
  log "defer: a recording is in progress"
  exit 0
fi

read -r free util < <(nvidia-smi --query-gpu=memory.free,utilization.gpu \
  --format=csv,noheader,nounits | head -1 | tr -d ',')

# Utilisation is deliberately not part of the decision: a browser playing video
# pins it near 100% while using almost no VRAM. Free memory is what determines
# whether a model fits.
if [ "$free" -lt "$MIN_FREE_MIB" ]; then
  log "defer: only ${free} MiB free, ${util}% util"
  exit 0
fi

export LECTURE_LANGUAGE LECTURE_ASR_MODEL

shopt -s nullglob

# ---- stage 1: transcribe ---------------------------------------------------
for audio in "$NOTES/audio"/*.ogg "$NOTES/audio"/*.mp3 \
             "$NOTES/audio"/*.m4a "$NOTES/audio"/*.wav; do
  stamp=$(basename "${audio%.*}")
  transcript="$NOTES/transcripts/$stamp.md"
  [ -f "$transcript" ] && continue

  log "transcribe: starting $stamp (${free} MiB free)"
  if "$SELF/venv/bin/python" "$SELF/transcribe.py" "$audio" "$transcript" \
       >> "$LOG" 2>&1; then
    log "transcribe: done $stamp"
  else
    log "transcribe: FAILED $stamp"
    rm -f "$transcript.tmp"
  fi
  exit 0
done

# ---- stage 2: summarise ----------------------------------------------------
for transcript in "$NOTES/transcripts"/*.md; do
  stamp=$(basename "$transcript" .md)
  marker="$STATE/$stamp.done"
  [ -f "$marker" ] && continue

  log "summarise: starting $stamp"
  out=$(LECTURE_OLLAMA_HOST=127.0.0.1:11434 \
        "$SELF/venv/bin/python" "$SELF/summarise.py" \
        "$transcript" "$stamp" "$VAULT" 2>&1 | tee -a "$LOG" \
        | sed -n 's/^NOTE_PATH=//p')

  if [ -n "$out" ] && [ -f "$out" ]; then
    printf '%s\n' "$out" > "$marker"
    log "summarise: done $stamp -> $out"
    python3 "$SELF/reindex.py" "$VAULT" >> "$LOG" 2>&1
  else
    log "summarise: FAILED $stamp"
  fi
  exit 0
done

# ---- stage 3: retire the rough live note -----------------------------------
# Guarded on note size so a truncated summary never triggers a deletion.
for marker in "$STATE"/*.done; do
  stamp=$(basename "$marker" .done)
  note=$(cat "$marker")
  [ -f "$note" ] || continue
  for live in "$NOTES/live/$stamp"*.md; do
    if [ "$(stat -c %s "$note")" -gt 400 ]; then
      rm -f "$live"
      log "finalise: removed live note for $stamp"
    else
      log "finalise: SKIPPED $stamp, note too small to trust"
    fi
  done
done

# ---- stage 4: retention ----------------------------------------------------
now=$(date +%s)
for marker in "$STATE"/*.done; do
  stamp=$(basename "$marker" .done)
  age_days=$(( (now - $(stat -c %Y "$marker")) / 86400 ))
  [ "$age_days" -lt "$KEEP_AUDIO_DAYS" ] && continue
  for a in "$NOTES/audio/$stamp".*; do
    rm -f "$a"
    log "retention: deleted $(basename "$a") after ${age_days}d"
  done
done

log "idle: nothing to do (${free} MiB free)"
