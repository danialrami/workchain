#!/bin/bash
# DC offset measurement
# Adapted from audio-benchmarks/audio_dc_offset.sh for LUFS workchain

# Usage: run_dc_offset_check <input_file>
# Outputs JSON result to stdout, logs to stderr
run_dc_offset_check() {
    local FILE="$1"
    local STATUS="pass"
    local MAX_OFFSET=0
    
    echo "Measuring DC offset..." >&2
    
    # Run ffmpeg with astats to get DC offset per frame
    local DC_OUT=$(ffmpeg -i "$FILE" -af "astats=measure_perchannel=0:metadata=1" -f null - 2>&1)
    
    # Extract DC offset values
    local DC_VALUES=$(echo "$DC_OUT" | grep "DC offset" | sed -E 's/.*DC offset:[[:space:]]*([-]?[0-9.]+).*/\1/')
    
    # Find max absolute DC offset
    if [[ -n "$DC_VALUES" ]]; then
        MAX_OFFSET=$(echo "$DC_VALUES" | sort -g | tail -1)
    fi
    
    # Assess
    local ASSESSMENT="CLEAN"
    if (( $(calc_bool "$MAX_OFFSET > 0.001") )); then
        ASSESSMENT="HAS DC OFFSET"
        STATUS="warn"
        echo "  DC offset detected: ${MAX_OFFSET}. Consider highpass filter." >&2
    else
        echo "  DC offset: ${MAX_OFFSET} (clean)" >&2
    fi
    
    # Log human-readable output to stderr
    echo "  Max DC Offset: ${MAX_OFFSET}" >&2
    echo "  Assessment: $ASSESSMENT" >&2
    
    # Output JSON to stdout (single line, no log messages)
    local RESULT_JSON="{\"max_dc_offset\":$(json_num "$MAX_OFFSET"),\"assessment\":\"$ASSESSMENT\"}"
    echo "$RESULT_JSON"
    
    if [[ "$STATUS" == "warn" ]]; then
        return 0  # Warning, not failure
    fi
    return 0
}
