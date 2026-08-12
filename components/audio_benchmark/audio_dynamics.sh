#!/bin/bash
# Dynamic range and crest factor analysis
# Adapted from audio-benchmarks/audio_dynamics.sh for LUFS workchain

# Usage: run_dynamics_check <input_file>
# Outputs JSON result to stdout, logs to stderr
run_dynamics_check() {
    local FILE="$1"
    local STATUS="pass"
    
    echo "Analyzing dynamics..." >&2
    
    # Get integrated loudness and LRA via ebur128
    local EBUR_OUT=$(ffmpeg -i "$FILE" -filter_complex "ebur128=peak=true" -f null - 2>&1)
    local I_LUFS=$(echo "$EBUR_OUT" | grep "I:" | tail -1 | sed -E 's/.*I:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local LRA=$(echo "$EBUR_OUT" | grep "LRA:" | tail -1 | sed -E 's/.*LRA:[[:space:]]*([-]?[0-9.]+).*/\1/')
    
    # Get crest factor via astats
    local STATS_OUT=$(ffmpeg -i "$FILE" -af "astats=metadata=1" -f null - 2>&1)
    local RMS_VALUES=$(echo "$STATS_OUT" | grep "RMS level dB:" | sed -E 's/.*RMS level dB:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local PEAK_VALUES=$(echo "$STATS_OUT" | grep "Peak level dB:" | sed -E 's/.*Peak level dB:[[:space:]]*([-]?[0-9.]+).*/\1/')
    
    # Calculate average RMS and Peak
    local RMS_SUM=0
    local RMS_COUNT=0
    while read -r val; do
        if [[ -n "$val" ]]; then
            RMS_SUM=$(calc "$RMS_SUM + $val" 2>/dev/null || echo "$RMS_SUM")
            ((RMS_COUNT++))
        fi
    done <<< "$RMS_VALUES"

    local AVG_RMS=0
    if [[ $RMS_COUNT -gt 0 ]]; then
        AVG_RMS=$(python3 -c "print('%.2f' % ($RMS_SUM / $RMS_COUNT))" 2>/dev/null || echo "0")
    fi

    local PEAK_SUM=0
    local PEAK_COUNT=0
    while read -r val; do
        if [[ -n "$val" ]]; then
            PEAK_SUM=$(calc "$PEAK_SUM + $val" 2>/dev/null || echo "$PEAK_SUM")
            ((PEAK_COUNT++))
        fi
    done <<< "$PEAK_VALUES"

    local AVG_PEAK=0
    if [[ $PEAK_COUNT -gt 0 ]]; then
        AVG_PEAK=$(python3 -c "print('%.2f' % ($PEAK_SUM / $PEAK_COUNT))" 2>/dev/null || echo "0")
    fi

    # Calculate crest factor (Peak - RMS in dB)
    local CREST=$(python3 -c "print('%.2f' % ($AVG_PEAK - $AVG_RMS))" 2>/dev/null || echo "unknown")

    # Assess dynamics
    local ASSESSMENT="UNKNOWN"
    if [[ -n "$CREST" && "$CREST" != "unknown" ]]; then
        if (( $(calc_bool "$CREST > 18") )); then
            ASSESSMENT="HIGH (very dynamic)"
        elif (( $(calc_bool "$CREST > 12") )); then
            ASSESSMENT="MODERATE"
        else
            ASSESSMENT="COMPRESSED (low dynamic range)"
            STATUS="warn"
        fi
    fi
    
    # Log human-readable output to stderr
    echo "  Integrated LUFS: ${I_LUFS:-unknown}" >&2
    echo "  Loudness Range (LRA): ${LRA:-unknown} LU" >&2
    echo "  Avg RMS Level: ${AVG_RMS:-unknown} dB" >&2
    echo "  Avg Peak Level: ${AVG_PEAK:-unknown} dB" >&2
    echo "  Crest Factor: ${CREST:-unknown} dB" >&2
    echo "  Assessment: $ASSESSMENT" >&2
    
    if [[ "$STATUS" == "warn" ]]; then
        echo "  Audio appears heavily compressed" >&2
    fi
    
    # Output JSON to stdout (single line)
    local RESULT_JSON="{\"integrated_lufs\":$(json_num "$I_LUFS"),\"lra\":$(json_num "$LRA"),\"avg_rms_db\":$(json_num "$AVG_RMS"),\"avg_peak_db\":$(json_num "$AVG_PEAK"),\"crest_factor_db\":$(json_num "$CREST"),\"assessment\":\"$ASSESSMENT\"}"
    echo "$RESULT_JSON"
    
    return 0
}
