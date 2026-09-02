#!/usr/bin/env bash
# Set up the processing side on the machine with the GPU. Idempotent.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"

[ -f "$ROOT/config.sh" ] || { echo "run ../install.sh first, it writes config.sh" >&2; exit 1; }
source "$ROOT/config.sh"

command -v nvidia-smi >/dev/null || { echo "no nvidia-smi, this side needs a GPU" >&2; exit 1; }
command -v ollama     >/dev/null || { echo "install ollama first: https://ollama.com" >&2; exit 1; }

ln -sf ../shared/timetable.py "$DIR/timetable.py"

python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
# cuBLAS and cuDNN 9 are needed by CTranslate2 at runtime; the driver alone
# does not provide them.
"$DIR/venv/bin/pip" install -q faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12

echo "fetching the accurate model, about 3 GB"
"$DIR/venv/bin/python" - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("large-v3", device="cuda", compute_type="float16")
print("model ready on GPU")
PY

ollama pull "${LECTURE_LLM:-llama3.1:8b}"

mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/state/lecture-notes"
sed "s|^ExecStart=.*|ExecStart=$DIR/run.sh|" "$ROOT/systemd/lecture-notes.service" \
  > "$HOME/.config/systemd/user/lecture-notes.service"
cp "$ROOT/systemd/lecture-notes.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now lecture-notes.timer

echo
echo "done. Set OLLAMA_KEEP_ALIVE short so the model releases VRAM between runs:"
echo "  sudo systemctl edit ollama   ->   Environment=\"OLLAMA_KEEP_ALIVE=30s\""
