
# Component: fx_with_params
# Description: FX with parameters

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# CRITICAL: Don't overwrite global variables!
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh" 2>/dev/null || true
    source "$WORKCHAIN_ROOT/lib/common-utils.sh" 2>/dev/null || true
fi

CONTEXT_FILE="$1"
STEP_CONFIG="$2"

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

log_step "Running: fx_with_params"

# Get input/output paths from context
INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
INPUT_EXT=$(ctx_get "$CONTEXT_FILE" input_ext)

# Parameter getter function
get_param() {
    local param_name="$1"
    local default="${2:-}"

    local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["\'']\(.*\)["\'']$/\1/')

    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

PRESET="$(get_param "preset" "default_preset")"
STRENGTH="$(get_param "strength" "0.5")"

log_info "fx_with_params parameters:"
log_info "  preset: $PRESET"
log_info "  strength: $STRENGTH"

# Detect input from previous steps (if dependencies exist)


# Output file path
OUTPUT_FILE="$OUTPUT_DIR/${INPUT_NAME}_fx_with_params.$INPUT_EXT"
ensure_dir "$(dirname "$OUTPUT_FILE")"
ensure_dir "$OUTPUT_DIR/logs"

LOG_FILE="$OUTPUT_DIR/logs/fx_with_params.log"

# Check dependencies


# Honest scaffold boundary: this component is not implemented yet. Keep the sentinel in the
# executable path, not only in the README, so a fresh scaffold can never claim a render.
WORKCHAIN_NOT_IMPLEMENTED=1
if [[ "$WORKCHAIN_NOT_IMPLEMENTED" == "1" ]]; then
    log_error "fx_with_params is not implemented — no audio output was produced"
    register_output "$CONTEXT_FILE" "fx_with_params" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\":\"not_implemented\"}" \
        "failed"
    return 1
fi

# TODO: replace this block with a real, contract-backed effect before removing the sentinel.
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$INPUT_FILE" "$OUTPUT_FILE" || {
    log_error "fx_with_params processing failed"
    register_output "$CONTEXT_FILE" "fx_with_params" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\":\"processing_failed\"}" \
        "failed"
    return 1
}
register_output "$CONTEXT_FILE" "fx_with_params" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"preset\":\"$PRESET\",\"strength\":$STRENGTH}" \
    "completed"
return 0
