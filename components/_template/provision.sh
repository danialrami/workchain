#!/bin/bash
# Optional provision recipe — make this component's declared `requirements:` present.
# Idempotent (safe to re-run). Referenced from step.yaml (requirements.<class>.provision) and
# run by `workchain add` / `doctor`. A light component (ffmpeg only) needs nothing here;
# a heavy component creates its venv / installs packages / downloads models below.
set -euo pipefail
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Heavy (Python) example — uncomment and adapt:
# python3 -m venv "$COMPONENT_DIR/.venv"                 # use Python 3.10 for ML deps
# "$COMPONENT_DIR/.venv/bin/pip" install -r "$COMPONENT_DIR/requirements.txt"
# "$COMPONENT_DIR/.venv/bin/some-tool" --download-model ... --dir "$COMPONENT_DIR/models"

echo "template: nothing to provision (light component)"
