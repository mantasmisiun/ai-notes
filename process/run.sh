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
MAX_SUMMARISE_TRIES=2    # then ask, rather than pinning the GPU forever
RETRY_BACKOFF_SECS=300

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
#
# record.py holds an flock for the life of a recording, so trying to take it is
# the test. It replaced a PID file when capture was ported, and this check was
# left looking for the old file, which meant it never fired.
RECORD_LOCK="${XDG_STATE_HOME:-$HOME/.local/state}/lecture-pipeline/record.lock"
if [ -e "$RECORD_LOCK" ] && ! flock -n "$RECORD_LOCK" -c true 2>/dev/null; then
  log "defer: a recording is in progress on this machine"
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

# Everything summarise.py and transcribe.py read from the environment. Sourcing
# config.sh makes these shell variables; without export the child processes
# never see them and fall back to their defaults. LECTURE_LLM was missing, so
# every summary ran on the default model regardless of what was configured.
export LECTURE_LANGUAGE LECTURE_NOTE_LANGUAGE
export LECTURE_ASR_MODEL LECTURE_ASR_COMPUTE
export LECTURE_LLM LECTURE_NUMCTX LECTURE_CHUNK_WORDS
export LECTURE_REQUEST_DEADLINE LECTURE_MAX_PREDICT
export TRANSCRIPTIONS_DIR UNIVERSITY_DIR

shopt -s nullglob

# ---- stage 1: transcribe ---------------------------------------------------
for audio in "$NOTES/audio"/*.ogg "$NOTES/audio"/*.mp3 \
             "$NOTES/audio"/*.m4a "$NOTES/audio"/*.wav; do
  stamp=$(basename "${audio%.*}")
  transcript="$NOTES/transcripts/$stamp.md"
  [ -f "$transcript" ] && continue

  # Recording finished is signalled by the audio file existing at all: the
  # worker writes it only when it stops.
  #
  # Across machines it also has to finish ARRIVING, and nothing about the file
  # itself can tell you that. Modification time is preserved by sync tools, so
  # a file still being written already looks old. And a truncated Opus stream
  # is a valid Opus stream, by design, so it decodes perfectly: a 4 KB fragment
  # of a 548 KB recording passed both an ffprobe and a full ffmpeg decode.
  #
  # So watch it change instead. Two consecutive ticks at the same size means it
  # has stopped growing. Costs one extra minute and is sync-agnostic.
  size_now=$(stat -c %s "$audio")
  size_file="$STATE/$stamp.size"
  size_prev=$(cat "$size_file" 2>/dev/null || echo "")
  if [ "$size_now" = "0" ]; then
    # An empty file is not arriving, it is stuck. Sync created the entry and
    # never delivered the content. Say so once rather than every minute.
    if [ ! -f "$size_file.stuck" ]; then
      : > "$size_file.stuck"
      log "STUCK: $stamp is 0 bytes here. Sync has not delivered the audio."
      log "       Check it is not empty on the recording machine, and that the"
      log "       vault is syncing binaries to this one."
    fi
    continue
  fi
  rm -f "$size_file.stuck"

  if [ "$size_now" != "$size_prev" ]; then
    printf '%s' "$size_now" > "$size_file"
    log "waiting: $stamp is still arriving (${size_now} bytes)"
    continue
  fi

  log "transcribe: starting $stamp (${free} MiB free)"
  if "$SELF/venv/bin/python" "$SELF/transcribe.py" "$audio" "$transcript" \
       >> "$LOG" 2>&1; then
    log "transcribe: done $stamp"
    rm -f "$STATE/$stamp.size"
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
  # A marker claims a note was written. If that note has since been deleted the
  # claim is false, so redo the work rather than skipping it forever. Delete the
  # transcript too if you want a recording dropped for good.
  if [ -f "$marker" ]; then
    if [ -f "$(cat "$marker")" ]; then
      continue
    fi
    log "note for $stamp is gone, re-summarising"
    rm -f "$marker"
  fi

  # Given up on, by you, after it failed twice.
  [ -f "$STATE/$stamp.ignored" ] && continue

  # Back off between attempts. Retrying a failing summary every minute pins the
  # GPU indefinitely, which is worse than waiting.
  if [ -f "$STATE/$stamp.retry_after" ] &&
     [ "$(date +%s)" -lt "$(cat "$STATE/$stamp.retry_after")" ]; then
    continue
  fi

  log "summarise: starting $stamp"
  out=$(LECTURE_OLLAMA_HOST=127.0.0.1:11434 \
        "$SELF/venv/bin/python" "$SELF/summarise.py" \
        "$transcript" "$stamp" "$VAULT" 2>&1 | tee -a "$LOG" \
        | sed -n 's/^NOTE_PATH=//p')

  if [ -n "$out" ] && [ -f "$out" ]; then
    printf '%s\n' "$out" > "$marker"
    log "summarise: done $stamp -> $out"
    rm -f "$STATE/$stamp.fails" "$STATE/$stamp.retry_after"
    python3 "$SELF/reindex.py" "$VAULT" >> "$LOG" 2>&1
  else
    fails=$(( $(cat "$STATE/$stamp.fails" 2>/dev/null || echo 0) + 1 ))
    printf '%s' "$fails" > "$STATE/$stamp.fails"
    if [ "$fails" -lt "$MAX_SUMMARISE_TRIES" ]; then
      printf '%s' "$(( $(date +%s) + RETRY_BACKOFF_SECS ))" > "$STATE/$stamp.retry_after"
      log "summarise: FAILED $stamp (attempt $fails), retrying in $((RETRY_BACKOFF_SECS / 60)) min"
    else
      log "summarise: FAILED $stamp twice, asking what to do"
      out=$("$SELF/venv/bin/python" "$SELF/failed_dialog.py" "$stamp" \
            "$(tail -1 "$LOG" | cut -c22-)" 2>/dev/null)
      if [ "$out" = "IGNORE" ]; then
        : > "$STATE/$stamp.ignored"
        log "ignoring $stamp from now on"
      fi
      rm -f "$STATE/$stamp.fails" "$STATE/$stamp.retry_after"
    fi
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
    # your own notes are yours; only the machine-written transcript is retired
    case "$live" in *" my notes.md") continue ;; esac
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
