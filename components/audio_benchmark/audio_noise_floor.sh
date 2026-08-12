#!/bin/bash
# Noise floor and silence detection
# Adapted from audio-benchmarks/audio_noise_floor.sh for LUFS workchain

# Usage: run_noise_floor_check <input_file>
# Outputs JSON result to stdout, logs to stderr
run_noise_floor_check() {
    local FILE="$1"
    local STATUS="pass"
    
    echo "Analyzing noise floor and silence..." >&2
    
    # Run ffmpeg with astats and silencedetect
    local STATS_OUT=$(ffmpeg -i "$FILE" -af "astats=metadata=1" -f null - 2>&1)
    local SILENCE_OUT=$(ffmpeg -i "$FILE" -af "silencedetect=n=-40dB:d=0.3" -f null - 2>&1)
    
    # Extract RMS values - get all RMS level lines from astats
    local RMS_VALUES=$(echo "$STATS_OUT" | grep "RMS level" | sed -E 's/.*RMS level dB:[[:space:]]*([-]?[0-9.]+).*/\1/' | grep -v '^$')
    
    # Calculate min, max, avg using python for robustness
    local RMS_MIN=$(echo "$RMS_VALUES" | sort -g | head -1)
    local RMS_MAX=$(echo "$RMS_VALUES" | sort -g | tail -1)
    
    # Calculate average RMS using python
    local RMS_AVG=0
    if [[ -n "$RMS_VALUES" ]]; then
        RMS_AVG=$(echo "$RMS_VALUES" | python3 -c "
import sys
values = []
for line in sys.stdin:
    line = line.strip()
    if line:
        try:
            values.append(float(line))
        except:
            pass
if values:
    print(round(sum(values)/len(values), 6))
else:
    print(0)
" 2>/dev/null)
    fi
    
    # Extract silence info
    local SILENCE_STARTS=$(echo "$SILENCE_OUT" | grep "silence_start" | sed -E 's/.*silence_start:[[:space:]]*([-]?[0-9.]+).*/\1/')
    local SILENCE_DURATIONS=$(echo "$SILENCE_OUT" | grep "silence_duration" | sed -E 's/.*silence_duration:[[:space:]]*([-]?[0-9.]+).*/\1/')
    
    local SILENCE_COUNT=$(echo "$SILENCE_STARTS" | grep -c '.' 2>/dev/null; true)
    local TOTAL_SILENCE=0
    while read -r dur; do
        if [[ -n "$dur" ]]; then
            TOTAL_SILENCE=$(calc "$TOTAL_SILENCE + $dur" 2>/dev/null || echo "$TOTAL_SILENCE")
        fi
    done <<< "$SILENCE_DURATIONS"

    # Assess
    local ASSESSMENT="GOOD"
    if [[ -n "$RMS_MIN" && "$RMS_MIN" != "unknown" ]]; then
        if (( $(calc_bool "$RMS_MIN > -30") )); then
            ASSESSMENT="POOR (high noise floor)"
            STATUS="warn"
        elif (( $(calc_bool "$RMS_MIN > -50") )); then
            ASSESSMENT="FAIR"
        else
            ASSESSMENT="GOOD (low noise floor)"
        fi
    fi
    
    # Log human-readable output to stderr
    echo "  RMS Min (noise floor): ${RMS_MIN:-unknown} dB" >&2
    echo "  RMS Max: ${RMS_MAX:-unknown} dB" >&2
    echo "  RMS Average: ${RMS_AVG:-unknown} dB" >&2
    echo "  Silence segments: ${SILENCE_COUNT:-0}" >&2
    echo "  Total silence: ${TOTAL_SILENCE:-0} seconds" >&2
    echo "  Noise Floor Assessment: $ASSESSMENT" >&2
    
    if [[ $SILENCE_COUNT -gt 0 ]]; then
        echo "  Silence detected in file (may indicate pauses or quiet sections)" >&2
    fi
    
    # Output JSON to stdout using python for proper formatting
    python3 << EOF
import json
result = {
    "noise_floor_db": ${RMS_MIN:-null},
    "rms_max_db": ${RMS_MAX:-null},
    "rms_avg_db": ${RMS_AVG:-null},
    "silence_count": $SILENCE_COUNT,
    "total_silence_sec": $TOTAL_SILENCE,
    "assessment": "$ASSESSMENT"
}
print(json.dumps(result))
EOF
    
    return 0
}
