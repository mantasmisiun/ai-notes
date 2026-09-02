#!/usr/bin/env bash
# Tap once to start a lecture transcription, tap again to stop.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../config.sh"
NOTES="$VAULT/$TRANSCRIPTIONS_DIR"
UNI="$VAULT/$UNIVERSITY_DIR"
AUDIO="$AUDIO_SCRATCH"
PIDF="$DIR/run.pid"        # transcription worker
TRAYF="$DIR/tray.pid"      # blinking tray icon
NAGF="$DIR/nag.pid"        # periodic reminder
REMIND_EVERY=300           # seconds between reminders

stop_pidfile() {           # $1 = pid file
  [ -f "$1" ] || return 0
  local p; p=$(cat "$1")
  kill -TERM "$p" 2>/dev/null
  rm -f "$1"
}

# ---- already running: stop everything -------------------------------------
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  stop_pidfile "$NAGF"
  stop_pidfile "$TRAYF"
  stop_pidfile "$PIDF"
  notify-send -a "Lecture" -i media-playback-stop \
    "Transcription stopped" "Writing the last chunk."
  exit 0
fi

# stale files from a crash
rm -f "$PIDF" "$TRAYF" "$NAGF"

# ---- start ----------------------------------------------------------------
mkdir -p "$NOTES"/{live,transcripts,audio,unfiled} "$AUDIO"
stamp=$(date '+%Y-%m-%d %H%M')

# Ask the timetables which lecture this is. Used for the name and frontmatter
# only; the file stays in live/ so the desktop has one place to look.
IFS=$'\t' read -r mod_folder mod_code mod_type < <(
  python3 "$DIR/timetable.py" --lookup "$UNI" "$stamp" 2>/dev/null)
mod_folder="${mod_folder:-}"; mod_code="${mod_code:-}"; mod_type="${mod_type:-}"

if [ -n "$mod_code" ]; then
  note="$NOTES/live/$stamp $mod_code $mod_type.md"
  label="$mod_code $mod_type"
else
  note="$NOTES/live/$stamp.md"
  label="unscheduled"
fi
raw="$AUDIO/$stamp.pcm"
ogg="$NOTES/audio/$stamp.ogg"

{
  echo "---"
  echo "stamp: \"$stamp\""
  echo "date: $(date '+%Y-%m-%d')"
  echo "time: $(date '+%H:%M')"
  echo "type: lecture-live"
  [ -n "$mod_code" ] && echo "module: $mod_code"
  [ -n "$mod_folder" ] && echo "module_folder: \"$mod_folder\""
  [ -n "$mod_type" ] && echo "session: $mod_type"
  echo "---"
  echo
  echo "# $stamp $label"
  echo
} > "$note"

# systemd-inhibit keeps the machine awake: a closed lid mid-lecture would
# otherwise suspend the capture and end the recording.
export LECTURE_LANGUAGE LECTURE_MODEL

nohup systemd-inhibit \
  --what=sleep:idle:handle-lid-switch \
  --who="Lecture transcription" --why="Recording a lecture" \
  "$DIR/venv/bin/python" "$DIR/worker.py" "$note" "$raw" "$ogg" "$VAULT" \
  >> "$DIR/worker.log" 2>&1 &
echo $! > "$PIDF"

nohup python3 "$DIR/indicator.py" >> "$DIR/tray.log" 2>&1 &
echo $! > "$TRAYF"

# periodic reminder, replacing itself rather than stacking up
(
  started=$(date +%s)
  id=$(notify-send -a "Lecture" -i media-record -p -t 0 \
        "Recording $label" "$(basename "$note")")
  while sleep "$REMIND_EVERY"; do
    el=$(( $(date +%s) - started ))
    notify-send -a "Lecture" -i media-record -r "$id" -t 0 \
      "Still recording" "$(printf '%02d:%02d elapsed. Click the tray dot to stop.' \
        $((el/60)) $((el%60)))"
  done
) &
echo $! > "$NAGF"
