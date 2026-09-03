#!/usr/bin/env bash
# Recover a .pcm left behind by a power cut: transcribe it and file the audio.
# Usage: recover.sh ~/lecture-recordings/2026-09-02\ 1151.pcm
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../config.sh"
NOTES="$VAULT/$TRANSCRIPTIONS_DIR"
raw="$1"
stamp=$(basename "$raw" .pcm)
wav="/tmp/$stamp.wav"

ffmpeg -loglevel error -y -f s16le -ar 16000 -ac 1 -i "$raw" "$wav"
mkdir -p "$NOTES/auto/audio"
ffmpeg -loglevel error -y -f s16le -ar 16000 -ac 1 -i "$raw" \
       -c:a libopus -b:a 24k "$NOTES/auto/audio/$stamp.ogg"

note="$NOTES/$stamp Lecture (recovered).md"
{
  echo "---"; echo "type: lecture-transcript"; echo "status: recovered"; echo "---"
  echo; echo "# Lecture $stamp (recovered)"; echo
} > "$note"

"$DIR/venv/bin/python" - "$wav" "$note" <<'PY'
import sys
from faster_whisper import WhisperModel
wav, note = sys.argv[1], sys.argv[2]
m = WhisperModel("medium.en", device="cpu", compute_type="int8", cpu_threads=8)
segs, _ = m.transcribe(wav, language="en", vad_filter=True)
with open(note, "a", encoding="utf-8") as f:
    for s in segs:
        f.write(s.text.strip() + " ")
        f.flush()
PY

echo >> "$note"
echo >> "$note"
echo "---" >> "$note"
echo >> "$note"
echo "## Recording" >> "$note"
echo >> "$note"
echo "![[$TRANSCRIPTIONS_DIR/auto/audio/$stamp.ogg]]" >> "$note"
rm -f "$wav" "$raw"
echo "recovered: $note"
