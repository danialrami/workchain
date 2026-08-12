#!/bin/bash
# Common library for audio-benchmark component
# Adapted from audio-benchmarks repo for LUFS workchain

# Floating-point arithmetic via python3 (bc is not present on minimal systems).
calc() { python3 -c "import sys; print(eval(sys.argv[1]))" "$1"; }
# Returns 1 when expression is true, 0 when false — matches bc -l convention.
calc_bool() { python3 -c "import sys; print(1 if eval(sys.argv[1]) else 0)" "$1"; }

# Portable helpers for extracting values from ffprobe output

# Extract value from ffprobe stream output by key
# Usage: stream_val <file> <key>
stream_val() {
    local file="$1" key="$2"
    ffprobe -v quiet -show_streams "$file" 2>/dev/null | sed -nE "s/^${key}=(.*)/\1/p" | head -1
}

# Extract value from ffprobe format output by key
format_val() {
    local file="$1" key="$2"
    ffprobe -v quiet -show_format "$file" 2>/dev/null | sed -nE "s/^${key}=(.*)/\1/p" | head -1
}

# Coerce a value to a valid JSON number, or `null` when it isn't one.
# This is the honesty guard for JSON built by shell string-interpolation: ffmpeg/astats
# parsing can yield an empty string, a bareword ("unknown"), or inf/nan on degenerate or
# unusual signals — any of which would otherwise emit invalid JSON (review Bug 2). A check
# that can't compute a number reports `null`, never a token that breaks the parser.
# Usage: json_num "$VALUE"
json_num() {
    local v="$1"
    if [[ "$v" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then
        printf '%s' "$v"
    else
        printf 'null'
    fi
}
