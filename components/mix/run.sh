#!/bin/bash

# Component: mix — two-input audio mix (ffmpeg amix)
#
# The demo consumer of the two-input (`in2:`) channel (issue #10). It reads the PRIMARY
# input through the existing mechanism (context.json `input_file`) and the SECOND input
# through the single documented in2: channel — the WORKCHAIN_INPUT_2 env var, exported by
# the engine after staging. A mix run without the second input env var is an authoring
# error, refused loudly rather than silently producing a single-input mix.

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# CRITICAL: Don't overwrite global variables!
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

if [[ -z "$CONTEXT_FILE" || ! -f "$CONTEXT_FILE" ]]; then
    log_error "Context file not found: $CONTEXT_FILE"
    return 1
fi

log_step "Running: mix"

INPUT_FILE=$(ctx_get "$CONTEXT_FILE" "input_file")
OUTPUT_DIR=$(ctx_get "$CONTEXT_FILE" "output_dir")
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" "input_name")

if [[ -z "$INPUT_FILE" || -z "$OUTPUT_DIR" ]]; then
    log_error "Failed to read input_file or output_dir from context"
    return 1
fi
if [[ ! -f "$INPUT_FILE" ]]; then
    log_error "Primary input file not found: $INPUT_FILE"
    return 1
fi

# ── The second-input channel (issue #10) ───────────────────────────────────────
# The engine resolves the step's `in2:` (a path/glob relative to CWD), verifies it is a
# real audio file, records its provenance in context.json, and exports the resolved path
# as WORKCHAIN_INPUT_2 before sourcing this script. That env var is the ONE documented
# channel — see docs/format.md "Second input (in2:)". Refuse a run without it.
IN2_FILE="${WORKCHAIN_INPUT_2:-}"
if [[ -z "$IN2_FILE" ]]; then
    log_error "WORKCHAIN_INPUT_2 is not set — this step declared in2: but the engine did not stage a second input. Run it via a chain whose step declares in2:."
    return 1
fi
if [[ ! -f "$IN2_FILE" ]]; then
    log_error "Second input file not found: $IN2_FILE"
    return 1
fi

# Read params (engine has resolved precedence: step params > globals > schema default).
get_param() {
    local param_name="$1"
    local default="${2:-}"
    local value
    value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["'\'']\(.*\)["'\'']$/\1/')
    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

DURATION_MODE=$(get_param "duration_mode" "longest")
NORMALIZE=$(get_param "normalize" "true")

case "$DURATION_MODE" in
    longest|first) ;;
    *)
        log_error "duration_mode must be 'longest' or 'first', got '$DURATION_MODE'"
        return 1
        ;;
esac

log_info "Mix parameters: duration_mode=$DURATION_MODE normalize=$NORMALIZE"
log_info "  in_a (primary): $(basename "$INPUT_FILE")"
log_info "  in_b (second):  $(basename "$IN2_FILE")"

# ── Measure both inputs ─────────────────────────────────────────────────────────
# Component-measured facts, written to the sidecar. The verify contract is explicit that
# the duration check re-measures independently while these sidecar fields are what the
# component wrote about itself (weaker). A silent input reports mean_volume_db null.
measure_input() {   # $1=path → prints "DURATION|SHA256|MEAN_DB"
    local p="$1" d sha vol
    d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$p" 2>/dev/null | head -1)
    sha=$(python3 - "$p" << 'PYEOF'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PYEOF
)
    vol=$(ffmpeg -nostdin -hide_banner -i "$p" -af volumedetect -f null - 2>&1 \
        | grep -oE 'mean_volume: -?[0-9.]+' | head -1 | grep -oE '\-?[0-9.]+' || echo "null")
    echo "${d}|${sha}|${vol}"
}

IN_A=$(measure_input "$INPUT_FILE") || { log_error "Failed to measure primary input ($INPUT_FILE)"; return 1; }
IN_B=$(measure_input "$IN2_FILE")   || { log_error "Failed to measure second input ($IN2_FILE)"; return 1; }
IN_A_DUR="${IN_A%%|*}";            IN_A_SHA="$(echo "$IN_A" | cut -d'|' -f2)";            IN_A_VOL="$(echo "$IN_A" | cut -d'|' -f3)"
IN_B_DUR="${IN_B%%|*}";            IN_B_SHA="$(echo "$IN_B" | cut -d'|' -f2)";            IN_B_VOL="$(echo "$IN_B" | cut -d'|' -f3)"
log_debug "in_a: dur=${IN_A_DUR} vol=${IN_A_VOL} sha=${IN_A_SHA:0:12}…"
log_debug "in_b: dur=${IN_B_DUR} vol=${IN_B_VOL} sha=${IN_B_SHA:0:12}…"

# ── Mix ─────────────────────────────────────────────────────────────────────────
OUTPUT_FILE="$OUTPUT_DIR/${INPUT_NAME}_mixed.wav"
ensure_dir "$OUTPUT_DIR"
ensure_dir "$OUTPUT_DIR/logs"
LOG_FILE="$OUTPUT_DIR/logs/mix.log"

# Force a common sample rate / layout (like the verifier's own stem mixer does) so amix
# never hits a format mismatch that only surfaces on certain pairs of inputs.
if ! ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "$INPUT_FILE" -i "$IN2_FILE" \
    -filter_complex "[0:a]aresample=44100,aformat=channel_layouts=stereo[a0];[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];[a0][a1]amix=inputs=2:duration=${DURATION_MODE}:normalize=${NORMALIZE}[mix]" \
    -map "[mix]" -c:a pcm_s16le "$OUTPUT_FILE" >> "$LOG_FILE" 2>&1; then
    log_error "ffmpeg mix failed — see $LOG_FILE"
    return 1
fi
if [[ ! -f "$OUTPUT_FILE" ]]; then
    log_error "Mix output not created: $OUTPUT_FILE"
    return 1
fi
log_info "Mix completed: $(basename "$OUTPUT_FILE") ($(stat -f%z "$OUTPUT_FILE" 2>/dev/null || stat -c%s "$OUTPUT_FILE" 2>/dev/null) bytes)"

# ── Sidecar (component-measured facts about BOTH inputs) ────────────────────────
# Written via python/JSON so paths with apostrophes/spaces/ampersands survive intact.
META_FILE="$OUTPUT_DIR/logs/mix_metadata.json"
__WC_IA="$INPUT_FILE" __WC_IB="$IN2_FILE" __WC_OA="$OUTPUT_FILE" \
__WC_IA_DUR="$IN_A_DUR" __WC_IB_DUR="$IN_B_DUR" \
__WC_IA_SHA="$IN_A_SHA" __WC_IB_SHA="$IN_B_SHA" \
__WC_IA_VOL="$IN_A_VOL" __WC_IB_VOL="$IN_B_VOL" \
__WC_DM="$DURATION_MODE" __WC_NZ="$NORMALIZE" __WC_META="$META_FILE" python3 << 'PYEOF'
import json, os
def num(v):
    try:
        return float(v)
    except Exception:
        return None
meta = {
    "in_a": {"path": os.environ["__WC_IA"], "duration_s": num(os.environ.get("__WC_IA_DUR")),
             "sha256": os.environ.get("__WC_IA_SHA") or "", "mean_volume_db": num(os.environ.get("__WC_IA_VOL"))},
    "in_b": {"path": os.environ["__WC_IB"], "duration_s": num(os.environ.get("__WC_IB_DUR")),
             "sha256": os.environ.get("__WC_IB_SHA") or "", "mean_volume_db": num(os.environ.get("__WC_IB_VOL"))},
    "output": {"path": os.environ["__WC_OA"], "duration_mode": os.environ.get("__WC_DM"),
               "normalize": os.environ.get("__WC_NZ") == "true"},
}
with open(os.environ["__WC_META"], "w") as f:
    json.dump(meta, f, indent=2)
PYEOF

register_output "$CONTEXT_FILE" "mix" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"duration_mode\": \"$DURATION_MODE\", \"normalize\": $NORMALIZE}" "completed"
register_output "$CONTEXT_FILE" "mix" "mix_metadata" "$META_FILE" "json" \
    "{\"in_a_sha256\": \"$IN_A_SHA\", \"in_b_sha256\": \"$IN_B_SHA\"}" "completed"

log_info "Mix done: $(basename "$INPUT_FILE") ⊕ $(basename "$IN2_FILE") → $(basename "$OUTPUT_FILE")"
return 0