#!/bin/bash
# Phase correlation check
# Adapted from audio-benchmarks/audio_phase.sh for LUFS workchain

# Usage: run_phase_check <input_file>
# Outputs JSON result to stdout, logs to stderr
run_phase_check() {
    local FILE="$1"
    local STATUS="pass"
    
    echo "Checking phase correlation..." >&2
    
    # Get channel count
    local CHANNELS=$(stream_val "$FILE" "channels")
    
    if [[ "$CHANNELS" == "1" ]]; then
        echo "  Mono file - phase not applicable" >&2
        local RESULT_JSON="{\"channels\":1,\"phase_correlation\":null,\"assessment\":\"CLEAN (mono)\"}"
        echo "$RESULT_JSON"
        return 0
    fi
    
    # Run aphasemeter for phase correlation
    local PHASE_OUT=$(ffmpeg -i "$FILE" -af "aphasemeter=ratio=1" -f null - 2>&1)
    
    # Extract phase correlation values (should be between -1 and +1)
    local PHASE_VALS=$(echo "$PHASE_OUT" | grep -oE "t:[0-9.]+" | sed 's/t://' | head -100)
    
    local MIN_PHASE=1
    local MAX_PHASE=-1
    local SUM_PHASE=0
    local COUNT=0
    
    while read -r val; do
        if [[ -n "$val" ]]; then
            # Update min/max
            if (( $(calc_bool "$val < $MIN_PHASE") )); then
                MIN_PHASE=$val
            fi
            if (( $(calc_bool "$val > $MAX_PHASE") )); then
                MAX_PHASE=$val
            fi
            SUM_PHASE=$(calc "$SUM_PHASE + $val" 2>/dev/null || echo "$SUM_PHASE")
            ((COUNT++))
        fi
    done <<< "$PHASE_VALS"

    local AVG_PHASE=0
    if [[ $COUNT -gt 0 ]]; then
        AVG_PHASE=$(python3 -c "print('%.3f' % ($SUM_PHASE / $COUNT))" 2>/dev/null || echo "0")
    fi

    # Assess phase issues
    local ASSESSMENT="GOOD"
    local BAD_FRAMES=0

    if (( $(calc_bool "$MIN_PHASE < -0.5") )); then
        ASSESSMENT="ISSUES (poor correlation)"
        STATUS="warn"
        echo "  Phase correlation issues detected (min: $MIN_PHASE)" >&2
        echo "  Possible phase cancellation in stereo field" >&2
    else
        echo "  Phase correlation: GOOD (avg: ${AVG_PHASE})" >&2
    fi
    
    # Log human-readable output to stderr
    echo "  Channels: $CHANNELS" >&2
    echo "  Min Phase Correlation: ${MIN_PHASE}" >&2
    echo "  Max Phase Correlation: ${MAX_PHASE}" >&2
    echo "  Avg Phase Correlation: ${AVG_PHASE}" >&2
    echo "  Assessment: $ASSESSMENT" >&2
    
    # Output JSON to stdout (single line)
    local RESULT_JSON="{\"channels\":$(json_num "$CHANNELS"),\"min_phase\":$(json_num "$MIN_PHASE"),\"max_phase\":$(json_num "$MAX_PHASE"),\"avg_phase\":$(json_num "$AVG_PHASE"),\"assessment\":\"$ASSESSMENT\"}"
    echo "$RESULT_JSON"
    
    return 0
}
