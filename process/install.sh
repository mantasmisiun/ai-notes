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
# cuBLAS and cuDNN 9 are needed by CTranslate2 at runtime; the driver alone
# does not provide them.
"$DIR/venv/bin/pip" install -q faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12

asr="${LECTURE_ASR_MODEL:-large-v3}"
prec="${LECTURE_ASR_COMPUTE:-float16}"
echo "fetching the accurate model: $asr ($prec)"
"$DIR/venv/bin/python" - "$asr" "$prec" <<'PY'
import sys
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cuda", compute_type=sys.argv[2])
print(f"{sys.argv[1]} ready on GPU")
PY

# Never inherit OLLAMA_HOST. It is commonly set in a shell profile to point at
# another machine, and the pipeline must talk to the local daemon it just
# checked for. summarise.py does the same for the same reason.
export OLLAMA_HOST="${LECTURE_OLLAMA_HOST:-127.0.0.1:11434}"

llm="${LECTURE_LLM:-llama3.1:8b}"
echo "pulling the summariser: $llm"

if ! curl -fsS --max-time 5 "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1; then
  echo >&2
  echo "Cannot reach Ollama at $OLLAMA_HOST." >&2
  echo "Start it with:  sudo systemctl start ollama" >&2
  echo "or set LECTURE_OLLAMA_HOST if it runs somewhere else." >&2
  exit 1
fi

if ! ollama pull "$llm"; then
  echo >&2
  echo "Ollama is running but '$llm' could not be pulled, so the tag is likely" >&2
  echo "wrong. Model names move; check ollama.com/library and re-run the" >&2
  echo "installer, choosing Other to enter a tag yourself." >&2
  exit 1
fi

mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/state/lecture-notes"
sed "s|^ExecStart=.*|ExecStart=$DIR/run.sh|" "$ROOT/systemd/lecture-notes.service" \
  > "$HOME/.config/systemd/user/lecture-notes.service"
cp "$ROOT/systemd/lecture-notes.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now lecture-notes.timer

echo
echo "done. Set OLLAMA_KEEP_ALIVE short so the model releases VRAM between runs:"
echo "  sudo systemctl edit ollama   ->   Environment=\"OLLAMA_KEEP_ALIVE=30s\""
