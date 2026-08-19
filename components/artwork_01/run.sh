
# artwork_01 component - Album artwork generation
# Python dependencies managed via `uv sync` at project root

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

log_step "Running: artwork_01"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
GLOBALS=$(ctx_get_json "$CONTEXT_FILE" globals)

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

SATURATION=$(get_param "saturation" "0.5")
WIDTH=$(get_param "width" "1000")
HEIGHT=$(get_param "height" "1000")

GLOBALS_SAT=$(get_global "$CONTEXT_FILE" saturation "")
if [[ -n "$GLOBALS_SAT" ]] && [[ "$GLOBALS_SAT" != "None" ]]; then
    SATURATION="$GLOBALS_SAT"
fi

log_info "Artwork parameters:"
log_info "  Saturation: $SATURATION"
log_info "  Size: ${WIDTH}x${HEIGHT}"

PREVIOUS_STEP_OUTPUT=""

NORM_OUTPUT=$(ctx_get "$CONTEXT_FILE" steps.normalization.output)
PROT_OUTPUT=$(ctx_get "$CONTEXT_FILE" steps.protection.output)

if [[ -n "$PROT_OUTPUT" ]] && [[ -f "$PROT_OUTPUT" ]]; then
    PREVIOUS_STEP_OUTPUT="$PROT_OUTPUT"
    log_info "Using protected audio for artwork"
elif [[ -n "$NORM_OUTPUT" ]] && [[ -f "$NORM_OUTPUT" ]]; then
    PREVIOUS_STEP_OUTPUT="$NORM_OUTPUT"
    log_info "Using normalized audio for artwork"
elif [[ -f "$OUTPUT_DIR/${INPUT_NAME}_normalized.$INPUT_EXT" ]]; then
    PREVIOUS_STEP_OUTPUT="$OUTPUT_DIR/${INPUT_NAME}_normalized.$INPUT_EXT"
elif [[ -f "$OUTPUT_DIR/${INPUT_NAME}_original.${INPUT_EXT:-wav}" ]]; then
    PREVIOUS_STEP_OUTPUT="$OUTPUT_DIR/${INPUT_NAME}_original.${INPUT_EXT:-wav}"
else
    PREVIOUS_STEP_OUTPUT="$INPUT_FILE"
fi

ARTWORK_DIR="$OUTPUT_DIR/artwork"
ARTWORK_COMPONENTS_DIR="$ARTWORK_DIR/components"

if [[ ! -f "$PREVIOUS_STEP_OUTPUT" ]]; then
    log_error "No input audio found for artwork generation"

    ctx_set_status "$CONTEXT_FILE" "artwork_01" "skipped" "no_input_audio"
    return 1
fi

log_info "Input audio: $PREVIOUS_STEP_OUTPUT"

ensure_dir "$OUTPUT_DIR"
ensure_dir "$ARTWORK_DIR"
ensure_dir "$ARTWORK_COMPONENTS_DIR"

ARTWORK_FILE="$ARTWORK_DIR/${INPUT_NAME}_artwork.png"
LOG_FILE="$OUTPUT_DIR/logs/artwork_generation.log"

ARTWORK_PY="$WORKCHAIN_ROOT/components/artwork_01/v7_album_artwork.py"

if [[ ! -f "$ARTWORK_PY" ]]; then
    log_error "Artwork script not found: $ARTWORK_PY"

    ctx_set_status "$CONTEXT_FILE" "artwork_01" "skipped" "script_not_found"
    return 1
fi

log_info "Checking artwork dependencies..."

if ! uv run --project "$WORKCHAIN_ROOT" python3 -c "import numpy" 2>/dev/null; then
    log_error "Python 'numpy' module not found. Run 'uv sync' at project root."

    ctx_set_status "$CONTEXT_FILE" "artwork_01" "skipped" "missing_dependency" "Run: uv sync"
    return 1
fi

log_info "Generating album artwork..."

if uv run --project "$WORKCHAIN_ROOT" timeout 300 python3 "$ARTWORK_PY" "$PREVIOUS_STEP_OUTPUT" --saturation $SATURATION --output_dir "$ARTWORK_DIR" --components_dir "$ARTWORK_COMPONENTS_DIR" --output_name "${INPUT_NAME}_artwork" >> "$LOG_FILE" 2>&1; then
    if [[ -f "$ARTWORK_FILE" ]]; then
        log_info "Artwork generated: $ARTWORK_FILE"
    elif [[ -f "$ARTWORK_DIR/${INPUT_NAME}_artwork.png" ]]; then
        ARTWORK_FILE="$ARTWORK_DIR/${INPUT_NAME}_artwork.png"
        log_info "Artwork generated: $ARTWORK_FILE"
    else
        log_error "Artwork file not found after generation: $ARTWORK_FILE"
        return 1
    fi

    register_output "$CONTEXT_FILE" "artwork_01" "primary_output" "$ARTWORK_FILE" "file" \
        "" \
        "completed"

    register_output "$CONTEXT_FILE" "artwork_01" "components" "$ARTWORK_COMPONENTS_DIR" "directory" \
        "{}" \
        ""

    return 0
else
    log_error "Artwork generation failed. Check log: $LOG_FILE"
    return 1
fi
