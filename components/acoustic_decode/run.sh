
# acoustic_decode — recover a text payload from an audio recording carrying an
# over-the-air audio-QR waveform, via the @lufs/audioqr CLI (ggwave). Fails
# honestly when nothing decodes (its whole job is to recover a payload).

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

log_step "Running: acoustic_decode"

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

EXPECTED=$(get_param "expected" "")

if [[ ! -f "$INPUT_FILE" ]]; then
    log_error "acoustic_decode: input audio not found: $INPUT_FILE"
    ctx_set_status "$CONTEXT_FILE" "acoustic_decode" "failed" "missing_input" "no input audio"
    return 1
fi

AUDIOQR_BIN="${WORKCHAIN_AUDIOQR_BIN:-}"
if [[ -z "$AUDIOQR_BIN" ]]; then
    if command_exists audioqr; then
        AUDIOQR_BIN="audioqr"
    fi
fi
if [[ -z "$AUDIOQR_BIN" ]]; then
    log_error "audioqr CLI not found. Install @lufs/audioqr or set WORKCHAIN_AUDIOQR_BIN."
    ctx_set_status "$CONTEXT_FILE" "acoustic_decode" "skipped" "audioqr_not_found" "@lufs/audioqr not installed"
    return 1
fi

ensure_dir "$OUTPUT_DIR/output"
OUTPUT_FILE="$OUTPUT_DIR/output/${INPUT_NAME}_decoded.json"

log_info "acoustic_decode: decoding $INPUT_FILE"
DEC_JSON=$("$AUDIOQR_BIN" decode "$INPUT_FILE" --json 2>/dev/null)

# Parse, apply optional expected-assertion, and write the sidecar (env-safe: the
# payload text is never shell-interpolated).
__WC_DEC="$DEC_JSON" __WC_EXP="$EXPECTED" __WC_OUT="$OUTPUT_FILE" python3 << 'PYEOF'
import json, os
try:
    dec = json.loads(os.environ.get("__WC_DEC") or "{}")
except Exception:
    dec = {}
decoded_list = dec.get("decoded") or []
expected = os.environ.get("__WC_EXP") or ""
result = {
    "decoded": decoded_list,
    "count": len(decoded_list),
    "expected": expected or None,
    "match": (expected in decoded_list) if expected else None,
}
with open(os.environ["__WC_OUT"], "w") as f:
    json.dump(result, f, indent=2)

# Exit status encodes the honest outcome:
#   2 → nothing decoded (the component failed at its one job)
#   3 → an expected payload was required but not recovered
#   0 → recovered (and matched expected, if supplied)
if not decoded_list:
    raise SystemExit(2)
if expected and expected not in decoded_list:
    raise SystemExit(3)
raise SystemExit(0)
PYEOF
RESULT=$?

if [[ $RESULT -eq 2 ]]; then
    log_error "acoustic_decode recovered no payload from $INPUT_FILE"
    register_output "$CONTEXT_FILE" "acoustic_decode" "primary_output" "$OUTPUT_FILE" "json" \
        "{\"count\": 0}" "failed"
    return 1
elif [[ $RESULT -eq 3 ]]; then
    log_error "acoustic_decode: expected payload not found among decoded results."
    register_output "$CONTEXT_FILE" "acoustic_decode" "primary_output" "$OUTPUT_FILE" "json" \
        "{\"match\": false}" "failed"
    return 1
fi

log_info "acoustic_decode recovered payload(s)."
register_output "$CONTEXT_FILE" "acoustic_decode" "primary_output" "$OUTPUT_FILE" "json" \
    "{\"decoded_from\": \"$INPUT_NAME\"}" "completed"

log_info "acoustic_decode completed"
return 0
