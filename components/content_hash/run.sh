#!/bin/bash

# content_hash — reproducible provenance for the source audio.
#
# Extracted from the old `catalog` component, where the hashing was buried alongside
# LUFS-specific catalogue formatting. A digest is useful on its own and belongs in its own
# step: it is content-addressed identity, and it is the one claim in this system a verifier
# can check perfectly by redoing the work.
#
# stdlib hashlib only. No ffmpeg, no venv, nothing to install.

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi

CONTEXT_FILE="$1"
STEP_CONFIG="$2"

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

log_step "Running: content_hash"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)

get_param() {
    local param_name="$1"
    local default="${2:-}"

    local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["'\'']\(.*\)["'\'']$/\1/')

    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

ALGORITHM=$(get_param "algorithm" "sha256")
ID_PREFIX=$(get_param "id_prefix" "")
ID_LENGTH=$(get_param "id_length" "8")

RECORD_FILE="$OUTPUT_DIR/content_hash/content_hash.json"
ensure_dir "$(dirname "$RECORD_FILE")"

log_info "Input: $INPUT_FILE"
log_info "Algorithm: $ALGORITHM"
log_debug "id_prefix: '${ID_PREFIX}'  id_length: $ID_LENGTH"

# Hash the source in chunks so a large file never has to fit in memory. Paths can contain
# apostrophes and spaces, so everything crosses into python through the environment rather
# than through string interpolation.
if ! WC_SRC="$INPUT_FILE" WC_OUT="$RECORD_FILE" WC_ALGO="$ALGORITHM" \
     WC_PREFIX="$ID_PREFIX" WC_IDLEN="$ID_LENGTH" python3 - <<'PYEOF'
import hashlib
import json
import os
import sys

src = os.environ["WC_SRC"]
out = os.environ["WC_OUT"]
algo = (os.environ.get("WC_ALGO") or "sha256").lower()
prefix = os.environ.get("WC_PREFIX") or ""
try:
    idlen = int(float(os.environ.get("WC_IDLEN") or 8))
except ValueError:
    print("id_length is not a number: %r" % os.environ.get("WC_IDLEN"), file=sys.stderr)
    sys.exit(1)

try:
    h = hashlib.new(algo)
except ValueError:
    print("unsupported algorithm %r — see hashlib.algorithms_available" % algo, file=sys.stderr)
    sys.exit(1)

n = 0
try:
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
except OSError as e:
    print("cannot read source: %s" % e, file=sys.stderr)
    sys.exit(1)

if n == 0:
    # Honest failure: hashing an empty file succeeds arithmetically and means nothing.
    print("source is zero bytes — refusing to emit a digest of nothing", file=sys.stderr)
    sys.exit(1)

digest = h.hexdigest()
record = {
    "algorithm": algo,
    "digest": digest,
    "bytes_hashed": n,
    "short_id": prefix + digest[:idlen],
    "id_length": idlen,
    "source_name": os.path.basename(src),
}
with open(out, "w") as f:
    json.dump(record, f, indent=2)
print("%s %s (%d bytes) -> %s" % (algo, digest[:16], n, record["short_id"]), file=sys.stderr)
PYEOF
then
    log_error "content_hash failed to compute a digest for: $INPUT_FILE"
    register_output "$CONTEXT_FILE" "content_hash" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"hash_failed\"}" \
        "failed"
    return 1
fi

# Honest output check — never report success without the declared output.
if [[ ! -f "$RECORD_FILE" ]]; then
    log_error "content_hash did not produce its record: $RECORD_FILE"
    register_output "$CONTEXT_FILE" "content_hash" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"missing_primary_output\"}" \
        "failed"
    return 1
fi

SHORT_ID=$(P="$RECORD_FILE" python3 -c "import json,os;print(json.load(open(os.environ['P']))['short_id'])")

register_output "$CONTEXT_FILE" "content_hash" "primary_output" "$RECORD_FILE" "json" \
    "{\"algorithm\": \"$ALGORITHM\", \"short_id\": \"$SHORT_ID\"}" \
    "completed"

log_info "content_hash completed: $SHORT_ID"
return 0
