#!/bin/bash
# Loudness analysis per EBU R128
# Adapted from audio-benchmarks/audio_loudness.sh for LUFS workchain

# Usage: run_loudness_check <input_file>
# Outputs JSON result to stdout, logs to stderr
run_loudness_check() {
    local FILE="$1"
    local STATUS="pass"
    
    echo "Analyzing loudness (EBU R128)..." >&2
    
    # Run ffmpeg ebur128 filter and volumedetect
    local EBUR_OUT=$(ffmpeg -i "$FILE" -filter_complex "ebur128=peak=true" -f null - 2>&1)
    local VOL_OUT=$(ffmpeg -i "$FILE" -af "volumedetect" -f null - 2>&1)
    
    # Extract EBU R128 values
    local I_LUFS=$(echo "$EBUR_OUT" | grep "I:" | tail -1 | sed -E 's/.*I:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local LRA=$(echo "$EBUR_OUT" | grep "LRA:" | tail -1 | sed -E 's/.*LRA:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local TP_L=$(echo "$EBUR_OUT" | grep "Peak:" | head -1 | sed -E 's/.*Peak:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local TP_R=$(echo "$EBUR_OUT" | grep "Peak:" | tail -1 | sed -E 's/.*Peak:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local TP_MAX=$(echo -e "$TP_L\n$TP_R" | sort -g | tail -1)
    
    # Extract volumedetect values
    local MEAN_VOL=$(echo "$VOL_OUT" | grep "mean_volume:" | sed -E 's/.*mean_volume:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local MAX_VOL=$(echo "$VOL_OUT" | grep "max_volume:" | sed -E 's/.*max_volume:[[:space:]]*([-]?[0-9.]+).*/\1/')
    
    # Assessment
    local LEVEL_ASSESS="UNKNOWN"
    if [[ -n "$I_LUFS" ]]; then
        if (( $(calc_bool "$I_LUFS > -8") )); then
            LEVEL_ASSESS="VERY LOUD"
        elif (( $(calc_bool "$I_LUFS > -18") )); then
            LEVEL_ASSESS="LOUD"
        elif (( $(calc_bool "$I_LUFS > -26") )); then
            LEVEL_ASSESS="OK"
        elif (( $(calc_bool "$I_LUFS > -40") )); then
            LEVEL_ASSESS="QUIET"
        else
            LEVEL_ASSESS="SILENT"
        fi
    fi

    local DYN_ASSESS="UNKNOWN"
    local CREST=$(calc "$MAX_VOL - $MEAN_VOL" 2>/dev/null || echo "unknown")
    if [[ -n "$CREST" && "$CREST" != "unknown" ]]; then
        if (( $(calc_bool "$CREST > 18") )); then
            DYN_ASSESS="WIDE"
        elif (( $(calc_bool "$CREST > 12") )); then
            DYN_ASSESS="MODERATE"
        else
            DYN_ASSESS="TIGHT"
        fi
    fi
    
    # Log human-readable output to stderr
    echo "  Integrated LUFS: ${I_LUFS:-unknown}" >&2
    echo "  Loudness Range (LRA): ${LRA:-unknown} LU" >&2
    echo "  True Peak (max): ${TP_MAX:-unknown} dB" >&2
    echo "  Mean Volume: ${MEAN_VOL:-unknown} dB" >&2
    echo "  Max Volume: ${MAX_VOL:-unknown} dB" >&2
    echo "  Level Assessment: $LEVEL_ASSESS" >&2
    echo "  Dynamic Assessment: $DYN_ASSESS" >&2
    
    # Output JSON to stdout (single line, no log messages)
    local RESULT_JSON="{\"integrated_lufs\":$(json_num "$I_LUFS"),\"lra\":$(json_num "$LRA"),\"true_peak_max\":$(json_num "$TP_MAX"),\"mean_volume\":$(json_num "$MEAN_VOL"),\"max_volume\":$(json_num "$MAX_VOL"),\"level_assessment\":\"$LEVEL_ASSESS\",\"dynamic_assessment\":\"$DYN_ASSESS\"}"
    echo "$RESULT_JSON"
    
    return 0
}
