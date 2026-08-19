
# Catalog component - Generate catalog information

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

log_step "Running: catalog"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)

SOURCE_AUDIO=""
for step in "protection" "normalization"; do
    STEP_OUTPUT=$(ctx_get "$CONTEXT_FILE" steps.$step.output)
    if [[ -n "$STEP_OUTPUT" ]] && [[ -f "$STEP_OUTPUT" ]]; then
        SOURCE_AUDIO="$STEP_OUTPUT"
        break
    fi
done

if [[ -z "$SOURCE_AUDIO" ]] || [[ ! -f "$SOURCE_AUDIO" ]]; then
    SOURCE_AUDIO="$INPUT_FILE"
fi

if [[ ! -f "$SOURCE_AUDIO" ]]; then
    log_error "No source audio found for catalog generation"
    return 1
fi

CATALOG_DIR="$OUTPUT_DIR/catalog"
ensure_dir "$OUTPUT_DIR"
ensure_dir "$CATALOG_DIR"

CATALOG_FILE="$CATALOG_DIR/catalog_info.txt"

log_info "Generating catalog information..."

# Content hash via python3 hashlib (always available) — no external shasum/sha256sum needed.
INPUT_HASH=$(SRC="$SOURCE_AUDIO" python3 -c "
import hashlib, os
h = hashlib.sha256()
with open(os.environ['SRC'], 'rb') as f:
    for chunk in iter(lambda: f.read(1 << 20), b''):
        h.update(chunk)
print(h.hexdigest())
" 2>/dev/null)

if [[ -z "$INPUT_HASH" ]]; then
    log_error "Failed to compute content hash for: $SOURCE_AUDIO"
    register_output "$CONTEXT_FILE" "catalog" "primary_output" "$CATALOG_FILE" "file" \
        "{\"error\": \"hash_failed\"}" "failed"
    return 1
fi
CATALOG_NUMBER="lufs-${INPUT_HASH:0:8}"

cat > "$CATALOG_FILE" << EOF
CATALOG INFORMATION
==================
Generated: $(date '+%Y-%m-%d %H:%M:%S')

Source Audio: $(basename "$SOURCE_AUDIO")
Catalog Number: $CATALOG_NUMBER

Full SHA256 Hash: $INPUT_HASH

Processing Steps:
EOF

__WC_CF="$CONTEXT_FILE" python3 << 'PYEOF' >> "$CATALOG_FILE"
import json, os
with open(os.environ['__WC_CF']) as f:
    ctx = json.load(f)
for step_name, step_data in ctx.get('steps', {}).items():
    if isinstance(step_data, dict) and 'status' in step_data:
        print('- {}: {}'.format(step_name, step_data.get('status', 'unknown')))
PYEOF

log_info "Catalog generated: $CATALOG_FILE"
log_info "Catalog number: $CATALOG_NUMBER"

# Register output using standardized schema
register_output "$CONTEXT_FILE" "catalog" "primary_output" "$CATALOG_FILE" "file" \
    "{\"catalog_number\": \"$CATALOG_NUMBER\", \"hash\": \"$INPUT_HASH\"}" \
    "completed"

return 0
