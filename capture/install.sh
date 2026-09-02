#!/usr/bin/env bash
# Set up the capture side on a laptop. Idempotent.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"

[ -f "$ROOT/config.sh" ] || { echo "run ../install.sh first, it writes config.sh" >&2; exit 1; }
source "$ROOT/config.sh"

ln -sf ../shared/timetable.py "$DIR/timetable.py"

case "${LECTURE_BACKEND:-cpu}" in
  vulkan)
    echo "The Vulkan backend is selected but not implemented yet." >&2
    echo "Re-run the installer and choose CPU until it lands." >&2
    exit 1 ;;
esac

python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q faster-whisper numpy

model="${LECTURE_MODEL:-small.en}"
echo "fetching the live model: $model"
"$DIR/venv/bin/python" - "$model" <<'PY'
import sys
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
print(f"{sys.argv[1]} ready")
PY

mkdir -p "$HOME/.local/share/applications"
sed "s|^Exec=.*|Exec=$DIR/toggle.sh|" "$DIR/lecture-transcribe.desktop" \
  > "$HOME/.local/share/applications/lecture-transcribe.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

mkdir -p "$VAULT/$TRANSCRIPTIONS_DIR"/{live,transcripts,audio,unfiled} "$AUDIO_SCRATCH"

echo
echo "done. Pin 'Lecture transcription' to your panel from the application launcher."
