#!/usr/bin/env bash
# Try a different live transcription model; it is kept only if it keeps up here.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/capture/venv/bin/python" "$DIR/switch_model.py" "$@"
