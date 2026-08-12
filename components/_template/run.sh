#!/bin/bash

# Component run script - template
# This script is executed by the workchain engine for each step
# Python dependencies managed via `uv sync` at project root
# Execute scripts with: uv run --project "$WORKCHAIN_ROOT" python3 script.py

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

log_step "Running: template component"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
INPUT_EXT=$(ctx_get "$CONTEXT_FILE" input_ext)

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

EXAMPLE_PARAM=$(get_param "example_param" "100")
EXAMPLE_FLAG=$(get_param "example_flag" "true")
EXAMPLE_STRING=$(get_param "example_string" "default_value")

log_debug "Example param: $EXAMPLE_PARAM"
log_debug "Example flag: $EXAMPLE_FLAG"
log_debug "Example string: $EXAMPLE_STRING"

OUTPUT_FILE="$OUTPUT_DIR/output/${INPUT_NAME}_template.$INPUT_EXT"

ensure_dir "$(dirname "$OUTPUT_FILE")"

log_info "Template component processing..."
log_info "Input: $INPUT_FILE"
log_info "Output: $OUTPUT_FILE"

# If your component needs Python dependencies, use:
#   uv run --project "$WORKCHAIN_ROOT" python3 your_script.py
#
# For shell commands and stdlib-only Python (json, os), plain python3 is fine.

# ─────────────────────────────────────────────────────────────────────────────
#  IMPLEMENT ME
#  This scaffold FAILS ON PURPOSE so an agent never mistakes an unimplemented
#  component (whether generated OR copied from _template) for a working one.
#  Replace the body below with real processing that writes "$OUTPUT_FILE",
#  then DELETE the `WORKCHAIN_NOT_IMPLEMENTED=1` line.
# ─────────────────────────────────────────────────────────────────────────────
WORKCHAIN_NOT_IMPLEMENTED=1

if [[ "${WORKCHAIN_NOT_IMPLEMENTED:-0}" == "1" ]]; then
    log_error "template is an unimplemented scaffold."
    log_error "Add processing in run.sh, then remove the 'WORKCHAIN_NOT_IMPLEMENTED=1' line."
    register_output "$CONTEXT_FILE" "template" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"note\": \"scaffold_not_implemented\"}" \
        "not_implemented"
    return 1
fi

# TODO: produce "$OUTPUT_FILE" here (e.g. ffmpeg -nostdin -i "$INPUT_FILE" "$OUTPUT_FILE").

# Honest output check — never report success without the declared primary output.
if [[ ! -f "$OUTPUT_FILE" ]]; then
    log_error "template did not produce its primary output: $OUTPUT_FILE"
    register_output "$CONTEXT_FILE" "template" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\": \"missing_primary_output\"}" \
        "failed"
    return 1
fi

register_output "$CONTEXT_FILE" "template" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"example_param\": $EXAMPLE_PARAM, \"example_flag\": $EXAMPLE_FLAG}" \
    "completed"

log_info "Template component completed"
return 0
