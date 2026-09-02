#!/usr/bin/env bash
# Set up the capture side. Runs in two phases so the installer can benchmark
# this machine between them:
#   --prereqs  build everything the benchmark needs
#   --models   fetch the model the benchmark chose, install the launcher
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"

[ -f "$ROOT/config.sh" ] || { echo "run ../install.sh first, it writes config.sh" >&2; exit 1; }
source "$ROOT/config.sh"

ln -sf ../shared/timetable.py "$DIR/timetable.py"
PHASE="${1:---prereqs}"

if [ "$PHASE" = "--models" ]; then
  model="${LECTURE_MODEL:-small.en}"
  if [ "${LECTURE_BACKEND:-cpu}" = "vulkan" ]; then
    echo "fetching the live model for whisper.cpp: $model"
    sh "$DIR/whisper.cpp/models/download-ggml-model.sh" "$model" >/dev/null
  else
    echo "fetching the live model: $model"
    "$DIR/venv/bin/python" - "$model" <<'MODELDL'
import sys
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
print(f"{sys.argv[1]} ready")
MODELDL
  fi

  mkdir -p "$HOME/.local/share/applications"
  sed "s|^Exec=.*|Exec=$DIR/toggle.sh|" "$DIR/lecture-transcribe.desktop" \
    > "$HOME/.local/share/applications/lecture-transcribe.desktop"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  mkdir -p "$VAULT/$TRANSCRIPTIONS_DIR"/{live,transcripts,audio,unfiled} "$AUDIO_SCRATCH"
  echo
  echo "done. Pin 'Lecture transcription' to your panel from the application launcher."
  exit 0
fi

# ---- phase 1: prerequisites ------------------------------------------------
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q faster-whisper numpy PyQt6

# whisper.cpp is built only when Vulkan is a candidate, so the benchmark has
# something to measure. It is not selected unless it actually wins.
if [ "${BUILD_VULKAN:-0}" = "1" ] && [ ! -x "$DIR/whisper.cpp/build/bin/whisper-cli" ]; then
  echo "building whisper.cpp with Vulkan, this takes a few minutes"
  [ -d "$DIR/whisper.cpp" ] || git clone --depth 1 \
    https://github.com/ggml-org/whisper.cpp.git "$DIR/whisper.cpp" >/dev/null 2>&1
  cmake -S "$DIR/whisper.cpp" -B "$DIR/whisper.cpp/build" \
        -DGGML_VULKAN=1 -DCMAKE_BUILD_TYPE=Release >/dev/null
  cmake --build "$DIR/whisper.cpp/build" -j "$(nproc)" >/dev/null
fi

echo "prerequisites ready"
