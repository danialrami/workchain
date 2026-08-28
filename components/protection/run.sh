
# Protection component - Audio perturbation for AI protection
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

log_step "Running: protection"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
INPUT_EXT=$(ctx_get "$CONTEXT_FILE" input_ext)
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

STRENGTH=$(get_param "strength" "0.4")

GLOBALS_STRENGTH=$(get_global "$CONTEXT_FILE" protection_strength "")
if [[ -n "$GLOBALS_STRENGTH" ]] && [[ "$GLOBALS_STRENGTH" != "None" ]]; then
    STRENGTH="$GLOBALS_STRENGTH"
fi

log_info "Protection parameters:"
log_info "  Strength: $STRENGTH"

NORMALIZED_FILE=""
if [[ -f "$OUTPUT_DIR/${INPUT_NAME}_normalized.$INPUT_EXT" ]]; then
    NORMALIZED_FILE="$OUTPUT_DIR/${INPUT_NAME}_normalized.$INPUT_EXT"
    log_info "Using normalized audio from previous step"
elif [[ -f "$OUTPUT_DIR/${INPUT_NAME}_original.$INPUT_EXT" ]]; then
    NORMALIZED_FILE="$OUTPUT_DIR/${INPUT_NAME}_original.$INPUT_EXT"
    log_info "Using original audio (normalization was skipped or failed)"
else
    NORMALIZED_FILE="$INPUT_FILE"
    log_info "Using input file directly"
fi

if [[ -z "$NORMALIZED_FILE" ]] || [[ ! -f "$NORMALIZED_FILE" ]]; then
    log_error "No input audio found for protection"

    ctx_set_status "$CONTEXT_FILE" "protection" "skipped" "no_input_audio" "No audio file found for protection"
    return 1
fi

log_info "Input to protection: $NORMALIZED_FILE"

ensure_dir "$OUTPUT_DIR"
ensure_dir "$OUTPUT_DIR/protected"
ensure_dir "$OUTPUT_DIR/logs"

PROTECTED_FILE="$OUTPUT_DIR/protected/${INPUT_NAME}_protected.$INPUT_EXT"
LOG_FILE="$OUTPUT_DIR/logs/protection.log"
REPORT_FILE="$OUTPUT_DIR/logs/protection_report.html"

PROTECT_PY="$WORKCHAIN_ROOT/components/protection/protect_audio.py"
PSYAC_UTILS="$WORKCHAIN_ROOT/components/protection/psyac_utils_v3.py"
ANALYZER_PY="$WORKCHAIN_ROOT/components/protection/audio-frequency-content-analyzer.py"

if [[ ! -f "$PROTECT_PY" ]]; then
    log_error "Protection script not found: $PROTECT_PY"

    ctx_set_status "$CONTEXT_FILE" "protection" "skipped" "script_not_found"
    return 1
fi

log_info "Checking Python dependencies..."

if ! uv run --project "$WORKCHAIN_ROOT" python3 -c "import soundfile" 2>/dev/null; then
    log_error "Python 'soundfile' module not found. Run 'uv sync' at project root."

    ctx_set_status "$CONTEXT_FILE" "protection" "skipped" "missing_dependency_soundfile" "Run: uv sync"
    return 1
fi

if ! uv run --project "$WORKCHAIN_ROOT" python3 -c "import numpy" 2>/dev/null; then
    log_error "Python 'numpy' module not found."
    ctx_set_status "$CONTEXT_FILE" "protection" "skipped" "missing_dependency_numpy" "Run: uv sync"
    return 1
fi

log_info "Running audio protection..."

if uv run --project "$WORKCHAIN_ROOT" python3 "$PROTECT_PY" "$NORMALIZED_FILE" --output_file "$PROTECTED_FILE" --strength $STRENGTH --output_dir "$OUTPUT_DIR/protected" --report_file "$REPORT_FILE" --log_file "$LOG_FILE" >> "$LOG_FILE" 2>&1; then
    log_info "Protection completed: $PROTECTED_FILE"

    register_output "$CONTEXT_FILE" "protection" "protected_audio" "$PROTECTED_FILE" "file" \
        "{\"strength\": $STRENGTH}" \
        "completed"

    if [[ -f "$REPORT_FILE" ]]; then
        register_output "$CONTEXT_FILE" "protection" "protection_report" "$REPORT_FILE" "file" \
            "{}" \
            ""
    fi

    return 0
else
    log_error "Protection failed. Check log: $LOG_FILE"

    if [[ -f "$NORMALIZED_FILE" ]]; then
        ensure_dir "$OUTPUT_DIR/protected"
        cp "$NORMALIZED_FILE" "$PROTECTED_FILE"
        log_warn "Copied original as protected (protection failed)"
    fi

    return 1
fi
