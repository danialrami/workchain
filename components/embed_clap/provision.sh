# provision.sh — set up embed_clap's heavy venv on the ingest host. Run once (or after deps change).
#   cd components/embed_clap && bash provision.sh
set -euo pipefail
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$COMPONENT_DIR"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
# CPU/MPS torch is fine on the M4 Max; laion-clap pulls transformers/torchaudio.
./.venv/bin/pip install "numpy>=1.26" soundfile laion-clap torch
echo "provisioned embed_clap/.venv — first run downloads the 630k-audioset-best checkpoint (~2GB) to the HF cache."
