
# acoustic_encode — encode a short text pointer into an over-the-air audio-QR
# waveform via the @lufs/audioqr CLI (ggwave). Proves the result decodes back to
# the source text at run time; refuses to report success it did not earn.

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

log_step "Running: acoustic_encode"

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

TEXT=$(get_param "text" "")
PROTOCOL=$(get_param "protocol" "audible-fast")
VOLUME=$(get_param "volume" "15")
SAMPLE_RATE=$(get_param "sample_rate" "48000")

# Honest failure: no payload, nothing to encode.
if [[ -z "$TEXT" ]]; then
    log_error "acoustic_encode requires a non-empty 'text' param (the pointer to encode)."
    ctx_set_status "$CONTEXT_FILE" "acoustic_encode" "failed" "missing_text" "no text param supplied"
    return 1
fi

# Resolve the audioqr binary: explicit override → PATH. audioqr is a Node CLI
# (@lufs/audioqr); only acoustic chains need it, so we resolve it like a heavy tool
# rather than assuming it is always present.
AUDIOQR_BIN="${WORKCHAIN_AUDIOQR_BIN:-}"
if [[ -z "$AUDIOQR_BIN" ]]; then
    if command_exists audioqr; then
        AUDIOQR_BIN="audioqr"
    fi
fi
if [[ -z "$AUDIOQR_BIN" ]]; then
    log_error "audioqr CLI not found. Install @lufs/audioqr or set WORKCHAIN_AUDIOQR_BIN."
    ctx_set_status "$CONTEXT_FILE" "acoustic_encode" "skipped" "audioqr_not_found" "@lufs/audioqr not installed"
    return 1
fi

log_info "acoustic_encode parameters:"
log_info "  Payload bytes: ${#TEXT}"
log_info "  Protocol: $PROTOCOL"
log_info "  Volume: $VOLUME"
log_info "  Sample rate: $SAMPLE_RATE"

ensure_dir "$OUTPUT_DIR/output"
ensure_dir "$OUTPUT_DIR/logs"

OUTPUT_FILE="$OUTPUT_DIR/output/${INPUT_NAME}_beacon.wav"
META_FILE="$OUTPUT_DIR/logs/acoustic_encode.json"

# 1) Encode (JSON out captured for metadata — never shell-interpolate the payload).
ENC_JSON=$("$AUDIOQR_BIN" encode "$TEXT" -o "$OUTPUT_FILE" \
    --protocol "$PROTOCOL" --volume "$VOLUME" --sample-rate "$SAMPLE_RATE" --json 2>/dev/null)
if [[ $? -ne 0 || ! -f "$OUTPUT_FILE" ]]; then
    log_error "audioqr encode failed to produce $OUTPUT_FILE"
    register_output "$CONTEXT_FILE" "acoustic_encode" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\": \"encode_failed\"}" "failed"
    return 1
fi

# 2) Round-trip proof: decode the produced waveform and require it to equal the
#    source text. This is the anti-"exit-0-but-wrong" gate — a beacon that does not
#    decode is a FAILURE, not a silent success.
DEC_JSON=$("$AUDIOQR_BIN" decode "$OUTPUT_FILE" --json 2>/dev/null)

__WC_TEXT="$TEXT" __WC_DEC="$DEC_JSON" __WC_ENC="$ENC_JSON" \
__WC_OUT="$META_FILE" __WC_PROTO="$PROTOCOL" python3 << 'PYEOF'
import json, os
text = os.environ["__WC_TEXT"]
try:
    dec = json.loads(os.environ.get("__WC_DEC") or "{}")
except Exception:
    dec = {}
try:
    enc = json.loads(os.environ.get("__WC_ENC") or "{}")
except Exception:
    enc = {}
decoded_list = dec.get("decoded") or []
ok = text in decoded_list
meta = {
    "source_text": text,
    "decoded_text": decoded_list[0] if decoded_list else "",
    "decoded_all": decoded_list,
    "roundtrip_ok": ok,
    "protocol": os.environ.get("__WC_PROTO"),
    "sample_rate": enc.get("sampleRate"),
    "duration_s": enc.get("durationSec"),
    "bytes": enc.get("bytes"),
}
with open(os.environ["__WC_OUT"], "w") as f:
    json.dump(meta, f, indent=2)
raise SystemExit(0 if ok else 1)
PYEOF
ROUNDTRIP=$?

if [[ $ROUNDTRIP -ne 0 ]]; then
    log_error "acoustic_encode round-trip FAILED: produced audio did not decode back to the source text."
    register_output "$CONTEXT_FILE" "acoustic_encode" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"roundtrip_ok\": false, \"protocol\": \"$PROTOCOL\"}" "failed"
    register_output "$CONTEXT_FILE" "acoustic_encode" "metadata" "$META_FILE" "json" \
        "{\"roundtrip_ok\": false}" "failed"
    return 1
fi

log_info "Round-trip verified: beacon decodes back to source text."
register_output "$CONTEXT_FILE" "acoustic_encode" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"roundtrip_ok\": true, \"protocol\": \"$PROTOCOL\", \"sample_rate\": $SAMPLE_RATE}" \
    "completed"
register_output "$CONTEXT_FILE" "acoustic_encode" "metadata" "$META_FILE" "json" \
    "{\"roundtrip_ok\": true, \"protocol\": \"$PROTOCOL\"}" \
    "completed"

log_info "acoustic_encode completed"
return 0
