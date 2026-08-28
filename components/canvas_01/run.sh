
# canvas_01 component - Spotify Canvas generation
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

log_step "Running: canvas_01"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)

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

LOOP_COUNT=$(get_param "loop_count" "8")

log_info "Canvas parameters:"
log_info "  Loop count: $LOOP_COUNT"

ARTWORK_PATH=$(ctx_get "$CONTEXT_FILE" steps.artwork_01.output)
CANVAS_DIR="$OUTPUT_DIR/canvas"

if [[ -z "$ARTWORK_PATH" ]] || [[ ! -f "$ARTWORK_PATH" ]]; then
    log_error "No artwork found from previous step. Canvas requires artwork_01 step to run first."

    ctx_set_status "$CONTEXT_FILE" "canvas_01" "skipped" "artwork_not_available" "artwork_01 step must run before canvas_01"
    return 1
fi

log_info "Input artwork: $ARTWORK_PATH"

ensure_dir "$OUTPUT_DIR"
ensure_dir "$CANVAS_DIR"

ARTWORK_BASENAME=$(basename "$ARTWORK_PATH" .png | sed 's/_artwork$//')
CANVAS_FILE="$CANVAS_DIR/${ARTWORK_BASENAME}_canvas.gif"
LOG_FILE="$OUTPUT_DIR/logs/canvas_generation.log"

CANVAS_PY="$WORKCHAIN_ROOT/components/canvas_01/canvas_generator.py"

if [[ ! -f "$CANVAS_PY" ]]; then
    log_error "Canvas script not found: $CANVAS_PY"
    return 1
fi

log_info "Checking canvas dependencies..."

if ! uv run --project "$WORKCHAIN_ROOT" python3 -c "import PIL" 2>/dev/null; then
    log_error "Python 'PIL/Pillow' module not found. Run 'uv sync' at project root."

    ctx_set_status "$CONTEXT_FILE" "canvas_01" "skipped" "missing_dependency" "Run: uv sync"
    return 1
fi

log_info "Generating canvas..."

if uv run --project "$WORKCHAIN_ROOT" python3 "$CANVAS_PY" "$ARTWORK_PATH" --output_dir "$CANVAS_DIR" >> "$LOG_FILE" 2>&1; then
    log_info "Canvas generated: $CANVAS_FILE"

    register_output "$CONTEXT_FILE" "canvas_01" "primary_output" "$CANVAS_FILE" "file" \
        "{\"loop_count\": $LOOP_COUNT}" \
        "completed"

    STATIC_PREVIEW="$CANVAS_DIR/${ARTWORK_BASENAME}_canvas_static.png"
    MP4_VERSION="$CANVAS_DIR/${ARTWORK_BASENAME}_canvas.mp4"

    if [[ -f "$STATIC_PREVIEW" ]]; then
        register_output "$CONTEXT_FILE" "canvas_01" "static_preview" "$STATIC_PREVIEW" "file" "{}" ""
    fi

    if [[ -f "$MP4_VERSION" ]]; then
        register_output "$CONTEXT_FILE" "canvas_01" "mp4_version" "$MP4_VERSION" "file" "{}" ""
    fi

    return 0
else
    log_error "Canvas generation failed. Check log: $LOG_FILE"
    return 1
fi
