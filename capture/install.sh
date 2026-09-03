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
ps_python() { [ -x "$DIR/venv/bin/python" ] && echo "$DIR/venv/bin/python" || echo python3; }
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

  # Ask at login about anything a closed lid or a shutdown interrupted.
  if [ "${WANT_PROCESS:-0}" = "1" ]; then
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/ai-notes-resume.desktop" <<AUTOSTART
[Desktop Entry]
Type=Application
Name=Finish lecture transcriptions
Exec=$(ps_python) $DIR/resume.py
Terminal=false
X-GNOME-Autostart-Delay=20
AUTOSTART
  fi

  mkdir -p "$HOME/.local/share/applications"
  sed "s|^Exec=.*|Exec=$(ps_python) $DIR/record.py|" "$DIR/lecture-transcribe.desktop" \
    > "$HOME/.local/share/applications/lecture-transcribe.desktop"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  mkdir -p "$VAULT/$TRANSCRIPTIONS_DIR"/{live,transcripts,audio,unfiled} "$AUDIO_SCRATCH"
  echo
  echo "done. Pin 'Lecture transcription' to your panel from the application launcher."
  exit 0
fi

# ---- phase 1: prerequisites ------------------------------------------------
# A venv records an absolute interpreter path in every script it installs, so
# it stops working the moment the project is moved or renamed. Check it runs
# before trusting it, and rebuild it if not. Models are cached elsewhere, so
# this costs a pip install rather than a download.
if [ -d "$DIR/venv" ] && ! "$DIR/venv/bin/python" -c "pass" 2>/dev/null; then
  echo "the existing venv points at a path that no longer exists, rebuilding"
  rm -rf "$DIR/venv"
fi

python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q faster-whisper numpy PyQt6

# The benchmark and the live pass run from this venv, so an NVIDIA machine
# needs the CUDA libraries here too, not only in the processing one.
if [ "${HAS_CUDA:-0}" = "1" ]; then
  echo "  adding CUDA libraries"
  "$DIR/venv/bin/pip" install -q nvidia-cublas-cu12 nvidia-cudnn-cu12
fi

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
