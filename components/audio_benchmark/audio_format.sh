#!/bin/bash
# Format compliance check
# Adapted from audio-benchmarks/audio_format.sh for LUFS workchain

# Usage: run_format_check <input_file> [expected_spec]
# Outputs JSON result to stdout, logs to stderr
run_format_check() {
    local FILE="$1"
    local EXPECTED_SPEC="${2:-}"
    local RESULT=""
    local STATUS="pass"
    local ISSUES=()
    
    echo "Checking audio format..." >&2
    
    # Get actual values
    local CODEC=$(stream_val "$FILE" "codec_name")
    local SAMPLE_RATE=$(stream_val "$FILE" "sample_rate")
    local CHANNELS=$(stream_val "$FILE" "channels")
    local BITS=$(stream_val "$FILE" "bits_per_raw_sample")
    local DURATION=$(format_val "$FILE" "duration")
    local FORMAT=$(format_val "$FILE" "format_name")
    local BITRATE=$(format_val "$FILE" "bit_rate")
    local FILE_SIZE=$(stat -f%z "$FILE" 2>/dev/null || stat -c%s "$FILE" 2>/dev/null)
    local SIZE_MB=$(calc "round($FILE_SIZE / 1048576, 2)" 2>/dev/null || echo "unknown")
    
    # Default bits if not detected
    if [[ -z "$BITS" || "$BITS" == "N/A" ]]; then
        local SAMPLE_FMT=$(stream_val "$FILE" "sample_fmt")
        case "$SAMPLE_FMT" in
            s16*|u16*) BITS=16 ;;
            s24*|u24*) BITS=24 ;;
            s32*|u32*|flt) BITS=32 ;;
            dbl) BITS=64 ;;
            *) BITS="unknown" ;;
        esac
    fi
    
    # (JSON is emitted at the end via python3 so missing/non-numeric fields can't corrupt it.)

    # Check against expected spec if provided
    local SPEC_STATUS="not_checked"
    if [[ -n "$EXPECTED_SPEC" ]]; then
        local EXP_BITS=$(echo "$EXPECTED_SPEC" | cut -d'/' -f1)
        local EXP_RATE=$(echo "$EXPECTED_SPEC" | cut -d'/' -f2)
        local EXP_CHAN=$(echo "$EXPECTED_SPEC" | cut -d'/' -f3)
        
        SPEC_STATUS="pass"
        if [[ "$EXP_BITS" != "$BITS" && "$BITS" != "unknown" ]]; then
            SPEC_STATUS="fail"
            STATUS="fail"
            ISSUES+=("Expected ${EXP_BITS}-bit, got ${BITS}-bit")
        fi
        if [[ "$EXP_RATE" != "$SAMPLE_RATE" ]]; then
            SPEC_STATUS="fail"
            STATUS="fail"
            ISSUES+=("Expected ${EXP_RATE} Hz, got ${SAMPLE_RATE} Hz")
        fi
        if [[ "$EXP_CHAN" != "$CHANNELS" ]]; then
            SPEC_STATUS="fail"
            STATUS="fail"
            ISSUES+=("Expected ${EXP_CHAN} channel(s), got ${CHANNELS} channel(s)")
        fi
    fi
    
    # Log human-readable output to stderr
    echo "  Codec: $CODEC" >&2
    echo "  Sample Rate: ${SAMPLE_RATE} Hz" >&2
    echo "  Channels: $CHANNELS" >&2
    echo "  Bit Depth: $BITS-bit" >&2
    echo "  Duration: $DURATION seconds" >&2
    echo "  Format: $FORMAT" >&2
    echo "  File Size: ${SIZE_MB} MB" >&2
    
    if [[ "$SPEC_STATUS" == "pass" ]]; then
        echo "  Spec check: PASS" >&2
    elif [[ "$SPEC_STATUS" == "fail" ]]; then
        echo "  Spec check: FAIL" >&2
        for issue in "${ISSUES[@]}"; do
            echo "    - $issue" >&2
        done
    fi
    
    # Output JSON to stdout — built by python3 so missing/non-numeric fields stay valid JSON
    # (numbers coerced where possible, otherwise null; strings always quoted). Review Bug 2.
    local ISSUES_STR=""
    if [[ ${#ISSUES[@]} -gt 0 ]]; then
        ISSUES_STR=$(printf '%s\n' "${ISSUES[@]}")
    fi
    CODEC="$CODEC" SAMPLE_RATE="$SAMPLE_RATE" CHANNELS="$CHANNELS" BITS="$BITS" \
    DURATION="$DURATION" FMT="$FORMAT" BITRATE="$BITRATE" FILE_SIZE="$FILE_SIZE" \
    SIZE_MB="$SIZE_MB" STATUS="$STATUS" SPEC_STATUS="$SPEC_STATUS" ISSUES_STR="$ISSUES_STR" \
    python3 -c '
import json, os
e = os.environ
def num(x):
    x = (x or "").strip()
    if not x or x in ("N/A", "unknown"):
        return None
    try:
        return int(x)
    except Exception:
        try:
            return float(x)
        except Exception:
            return None
actual = {
    "codec": e.get("CODEC") or None,
    "sample_rate": num(e.get("SAMPLE_RATE")),
    "channels": num(e.get("CHANNELS")),
    "bits_per_sample": (e.get("BITS") or "unknown"),
    "duration": num(e.get("DURATION")),
    "format": e.get("FMT") or None,
    "bitrate": num(e.get("BITRATE")),
    "file_size_bytes": num(e.get("FILE_SIZE")),
    "file_size_mb": num(e.get("SIZE_MB")),
}
issues = [i for i in (e.get("ISSUES_STR") or "").split("\n") if i.strip()]
print(json.dumps({"status": e.get("STATUS", "pass"), "actual": actual,
                  "spec_status": e.get("SPEC_STATUS", "not_checked"), "issues": issues}))
'

    if [[ "$STATUS" == "fail" ]]; then
        return 1
    fi
    return 0
}
