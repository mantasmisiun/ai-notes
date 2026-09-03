#!/usr/bin/env bash
# Runs the pipeline. The logic lives in pipeline.py, which Windows runs
# directly; this wrapper exists so the systemd unit written by earlier
# installers keeps working. A second copy of the stages in bash drifted from
# the Python one every time a path or a rule changed.
set -uo pipefail
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SELF/venv/bin/python" "$SELF/pipeline.py" "$@"
