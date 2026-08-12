#!/bin/bash

# Normalization component - LUFS audio normalization

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh" 2>/dev/null || true
    source "$WORKCHAIN_ROOT/lib/common-utils.sh" 2>/dev/null || true
fi

if [[ -z "$LIB_DIR" ]]; then
    LIB_DIR="$WORKCHAIN_ROOT/lib"
fi

CONTEXT_FILE="$1"
STEP_CONFIG="$2"

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

log_step "Running: normalization"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
INPUT_EXT=$(ctx_get "$CONTEXT_FILE" input_ext)
GLOBALS=$(ctx_get_json "$CONTEXT_FILE" globals)

get_param() {
    local param_name="$1"
    local default="${2:-}"
    
    local config_str="$STEP_CONFIG"
    local value=$(echo "$config_str" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["'\'']\(.*\)["'\'']$/\1/')
    
    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

# Parameter resolution precedence: step params > chain globals (lufs_target alias) > default.
# (The engine's resolver already folds globals.lufs_target into target_lufs via STEP_CONFIG;
#  the direct-globals fallback below keeps this correct even when run outside the resolver.)
TARGET_LUFS=$(get_param "target_lufs" "")
TWO_PASS=$(get_param "two_pass" "true")
LRA=$(get_param "lra" "7")
TRUE_PEAK=$(get_param "true_peak" "-1.5")
OFFSET=$(get_param "offset" "0")

if [[ -z "$TARGET_LUFS" ]]; then
    GLOBALS_LUFS=$(get_global "$CONTEXT_FILE" lufs_target "")
    if [[ -n "$GLOBALS_LUFS" ]] && [[ "$GLOBALS_LUFS" != "None" ]]; then
        TARGET_LUFS="$GLOBALS_LUFS"
    fi
fi
[[ -z "$TARGET_LUFS" ]] && TARGET_LUFS="-11"

log_info "Normalization parameters:"
log_info "  Target LUFS: $TARGET_LUFS"
log_info "  Two-pass: $TWO_PASS"
log_info "  LRA: $LRA"
log_info "  True Peak: $TRUE_PEAK"
log_info "  Offset: $OFFSET LU"

if ! command_exists ffmpeg; then
    log_error "FFmpeg not found. Normalization requires FFmpeg but is not installed."
    log_error "Install with: brew install ffmpeg (macOS) or sudo apt install ffmpeg (Linux)"
    
    ctx_set_status "$CONTEXT_FILE" "normalization" "skipped" "ffmpeg_not_found" "FFmpeg not installed"
    return 1
fi

ensure_dir "$OUTPUT_DIR"
ensure_dir "$OUTPUT_DIR/logs"

ORIGINAL_FILE="$OUTPUT_DIR/${INPUT_NAME}_original.${INPUT_EXT}"
if [[ ! -f "$ORIGINAL_FILE" ]]; then
    log_info "Copying original to output directory..."
    cp "$INPUT_FILE" "$ORIGINAL_FILE" || log_warn "Could not copy original file"
fi

NORMALIZED_FILE="$OUTPUT_DIR/${INPUT_NAME}_normalized.$INPUT_EXT"
LOG_FILE="$OUTPUT_DIR/logs/normalization.log"

cat > "$LOG_FILE" << EOF
# Normalization Log - $(date)
Target LUFS: $TARGET_LUFS
Two-pass: $TWO_PASS
LRA: $LRA
True Peak: $TRUE_PEAK dB

EOF

log_info "Analyzing audio: $INPUT_FILE"

CHANNELS=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null)
SAMPLE_RATE=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null)
SAMPLE_FMT=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_fmt -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null)

CHANNELS="${CHANNELS:-2}"
SAMPLE_RATE="${SAMPLE_RATE:-44100}"

log_debug "Audio properties: $CHANNELS channels, $SAMPLE_RATE Hz, format: ${SAMPLE_FMT:-unknown}"

if [[ "$TWO_PASS" == "true" ]]; then
    log_info "Performing two-pass normalization..."
    
    LOUDNESS_INFO=$(ffmpeg -i "$INPUT_FILE" -af "loudnorm=I=$TARGET_LUFS:LRA=$LRA:TP=$TRUE_PEAK:print_format=json" -f null - 2>&1)
    
    INPUT_I=$(echo "$LOUDNESS_INFO" | grep "input_i" | head -1 | cut -d'"' -f4)
    INPUT_TP=$(echo "$LOUDNESS_INFO" | grep "input_tp" | head -1 | cut -d'"' -f4)
    INPUT_LRA=$(echo "$LOUDNESS_INFO" | grep "input_lra" | head -1 | cut -d'"' -f4)
    INPUT_THRESH=$(echo "$LOUDNESS_INFO" | grep "input_thresh" | head -1 | cut -d'"' -f4)
    
    if [[ -z "$INPUT_I" ]]; then
        log_warn "Could not parse loudness info, using single-pass mode"
        TWO_PASS="false"
    elif [[ "$INPUT_I" == "-inf" ]]; then
        log_warn "Input is silent (measured LUFS = -inf). Skipping normalization."
        cp "$INPUT_FILE" "$NORMALIZED_FILE" || log_warn "Could not copy original as normalized output"
        # Write loudness metadata JSON
        __WC_OUTDIR="$OUTPUT_DIR" python3 << PYEOF
import json, os
metadata = {
    'target_lufs': $TARGET_LUFS,
    'final_lufs': '-inf',
    'lra': $LRA,
    'true_peak': $TRUE_PEAK,
    'input_i': '-inf',
    'note': 'silent_input_skipped'
}
with open(os.environ['__WC_OUTDIR'] + '/logs/normalization.json', 'w') as f:
    json.dump(metadata, f, indent=2)
PYEOF
        register_output "$CONTEXT_FILE" "normalization" "primary_output" "$NORMALIZED_FILE" "file" \
            "{\"target_lufs\": $TARGET_LUFS, \"measured_lufs\": \"-inf\", \"note\": \"silent_input_skipped\"}" \
            "skipped"
        register_output "$CONTEXT_FILE" "normalization" "loudness_metadata" \
            "$OUTPUT_DIR/logs/normalization.json" "json" \
            "{\"input_i\": \"-inf\", \"final_lufs\": \"-inf\", \"target_lufs\": $TARGET_LUFS, \"note\": \"silent_input_skipped\"}" \
            "skipped"
        return 0
    else
        log_debug "Measured: I=$INPUT_I LUFS, TP=$INPUT_TP dB, LRA=$INPUT_LRA LU"
        
        FFMPEG_CMD="ffmpeg -i \"$INPUT_FILE\" -af \"loudnorm=I=$TARGET_LUFS:LRA=$LRA:TP=$TRUE_PEAK:measured_I=$INPUT_I:measured_TP=$INPUT_TP:measured_LRA=$INPUT_LRA:measured_thresh=$INPUT_THRESH:linear=true:offset=$OFFSET\" -ar $SAMPLE_RATE -ac $CHANNELS -y \"$NORMALIZED_FILE\""
    fi
fi

if [[ "$TWO_PASS" != "true" ]]; then
    log_info "Performing single-pass normalization..."
    FFMPEG_CMD="ffmpeg -i \"$INPUT_FILE\" -af \"loudnorm=I=$TARGET_LUFS:LRA=$LRA:TP=$TRUE_PEAK\" -ar $SAMPLE_RATE -ac $CHANNELS -y \"$NORMALIZED_FILE\""
fi

log_debug "FFmpeg command: $FFMPEG_CMD"

if eval "$FFMPEG_CMD" >> "$LOG_FILE" 2>&1; then
    log_info "Normalization completed: $NORMALIZED_FILE"
    
    FINAL_LUFS=$(ffmpeg -i "$NORMALIZED_FILE" -af "loudnorm=I=$TARGET_LUFS:print_format=json" -f null - 2>&1 | grep "input_i" | head -1 | cut -d'"' -f4)
    log_info "Final loudness: ${FINAL_LUFS:-unknown} LUFS"
    
    # Write loudness metadata JSON
    __WC_OUTDIR="$OUTPUT_DIR" python3 << PYEOF
import json, os
metadata = {
    'target_lufs': $TARGET_LUFS,
    'final_lufs': '${FINAL_LUFS:-unknown}',
    'lra': $LRA,
    'true_peak': $TRUE_PEAK,
    'input_i': '${INPUT_I:-unknown}',
    'input_tp': '${INPUT_TP:-unknown}',
    'input_lra': '${INPUT_LRA:-unknown}',
    'input_thresh': '${INPUT_THRESH:-unknown}',
    'sample_rate': $SAMPLE_RATE,
    'channels': $CHANNELS
}
with open(os.environ['__WC_OUTDIR'] + '/logs/normalization.json', 'w') as f:
    json.dump(metadata, f, indent=2)
PYEOF
    log_info "Loudness metadata saved to logs/normalization.json"

    # Register primary output
    register_output "$CONTEXT_FILE" "normalization" "primary_output" "$NORMALIZED_FILE" "file" \
        "{\"target_lufs\": $TARGET_LUFS, \"measured_lufs\": \"$FINAL_LUFS\", \"lra\": $LRA, \"true_peak\": $TRUE_PEAK}" \
        "completed"

    # Register loudness metadata output
    register_output "$CONTEXT_FILE" "normalization" "loudness_metadata" \
        "$OUTPUT_DIR/logs/normalization.json" "json" \
        "{\"input_i\": \"${INPUT_I:-unknown}\", \"final_lufs\": \"${FINAL_LUFS:-unknown}\", \"target_lufs\": $TARGET_LUFS}" \
        "completed"

    return 0
else
    log_error "Normalization failed. Check log: $LOG_FILE"
    return 1
fi
