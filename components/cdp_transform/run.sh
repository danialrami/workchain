#!/bin/bash

# cdp_transform — Composers Desktop Project transformations via cdp-wasm.
#
# The heavy lifting (catalog validation, render, measurement) lives in transform.mjs,
# which is plain Node + the cdp-wasm npm package: no uv venv, no native build, no
# Python. This script wires the engine's context/params to that worker and registers
# the outputs honestly.

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

log_step "Running: cdp_transform"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)

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

EFFECT=$(get_param "effect" "blur.blur")
VALUES_JSON=$(get_param "values_json" "{}")
VALUES_BRK_JSON=$(get_param "values_brk_json" "{}")
CHANNELS=$(get_param "channels" "split")
MIN_PEAK_DBFS=$(get_param "min_peak_dbfs" "-60")
ALLOW_UNLOCKED=$(get_param "allow_unlocked_range" "false")
CDP_WASM_DIR=$(get_param "cdp_wasm_dir" "${CDP_WASM_DIR:-}")

OUTPUT_FILE="$OUTPUT_DIR/output/${INPUT_NAME}_cdp_transform.wav"
RECORD_FILE="$OUTPUT_DIR/logs/cdp_transform.json"

ensure_dir "$(dirname "$OUTPUT_FILE")"
ensure_dir "$(dirname "$RECORD_FILE")"

log_debug "Effect: $EFFECT"
log_debug "Values: $VALUES_JSON"
log_debug "Channels: $CHANNELS  min_peak_dbfs: $MIN_PEAK_DBFS  unlocked: $ALLOW_UNLOCKED"
log_info "Input: $INPUT_FILE"
log_info "Output: $OUTPUT_FILE"

WORKER_ARGS=(
    "$COMPONENT_DIR/transform.mjs"
    --input "$INPUT_FILE"
    --output "$OUTPUT_FILE"
    --record "$RECORD_FILE"
    --effect "$EFFECT"
    --values "$VALUES_JSON"
    --brk "$VALUES_BRK_JSON"
    --channels "$CHANNELS"
    --min-peak "$MIN_PEAK_DBFS"
)
if [[ "$ALLOW_UNLOCKED" == "true" ]]; then
    WORKER_ARGS+=(--unlocked)
fi
if [[ -n "$CDP_WASM_DIR" ]]; then
    WORKER_ARGS+=(--lib "$CDP_WASM_DIR")
fi

# stdout of the worker is its final JSON line; keep it off the engine's stdout.
if ! node "${WORKER_ARGS[@]}" >/dev/null; then
    log_error "cdp_transform: $EFFECT was refused or failed (see the message above)."
    log_error "Record (if written): $RECORD_FILE"
    register_output "$CONTEXT_FILE" "cdp_transform" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"effect\": \"$EFFECT\", \"error\": \"refused_or_failed\"}" \
        "failed"
    return 1
fi

# Honest output check — never report success without the declared outputs.
if [[ ! -f "$OUTPUT_FILE" ]]; then
    log_error "cdp_transform did not produce its primary output: $OUTPUT_FILE"
    register_output "$CONTEXT_FILE" "cdp_transform" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\": \"missing_primary_output\"}" \
        "failed"
    return 1
fi
if [[ ! -f "$RECORD_FILE" ]]; then
    log_error "cdp_transform did not produce its transform record: $RECORD_FILE"
    register_output "$CONTEXT_FILE" "cdp_transform" "transform_record" "$RECORD_FILE" "json" \
        "{\"error\": \"missing_transform_record\"}" \
        "failed"
    return 1
fi

register_output "$CONTEXT_FILE" "cdp_transform" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"effect\": \"$EFFECT\", \"channels_mode\": \"$CHANNELS\"}" \
    "completed"

register_output "$CONTEXT_FILE" "cdp_transform" "transform_record" "$RECORD_FILE" "json" \
    "{\"effect\": \"$EFFECT\"}" \
    "completed"

log_info "cdp_transform completed: $EFFECT"
return 0
