#!/usr/bin/env bash
# Set up the capture side on a laptop. Idempotent.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"

[ -f "$ROOT/config.sh" ] || { echo "copy config.sh.example to config.sh first" >&2; exit 1; }
source "$ROOT/config.sh"

ln -sf ../shared/timetable.py "$DIR/timetable.py"

python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q faster-whisper numpy

echo "fetching the live model, this is a few hundred MB"
"$DIR/venv/bin/python" - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("small.en", device="cpu", compute_type="int8")
print("model ready")
PY

mkdir -p "$HOME/.local/share/applications"
sed "s|^Exec=.*|Exec=$DIR/toggle.sh|" "$DIR/lecture-transcribe.desktop" \
  > "$HOME/.local/share/applications/lecture-transcribe.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

mkdir -p "$VAULT/$TRANSCRIPTIONS_DIR"/{live,transcripts,audio,unfiled} "$AUDIO_SCRATCH"

echo
echo "done. Pin 'Lecture transcription' to your panel from the application launcher."
