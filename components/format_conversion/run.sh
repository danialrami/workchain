#!/bin/bash

# Component: format_conversion
# Description: Audio format conversion using FFmpeg (powered by audioconv-cli logic)

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

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

# Check if context file exists
if [[ ! -f "$CONTEXT_FILE" ]]; then
    echo "Error: Context file not found: $CONTEXT_FILE"
    return 1
fi

log_step "Running: format_conversion"

# Get input/output paths from context using python3
get_context_value() {
    # Delegate to the shared, special-char-safe helper (lib/common-utils.sh).
    ctx_get "$CONTEXT_FILE" "$1"
}

INPUT_FILE=$(get_context_value "input_file")
OUTPUT_DIR=$(get_context_value "output_dir")
INPUT_NAME=$(get_context_value "input_name")
INPUT_EXT=$(get_context_value "input_ext")

# Validate inputs
if [[ -z "$INPUT_FILE" || -z "$OUTPUT_DIR" ]]; then
    log_error "Failed to read input_file or output_dir from context"
    return 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    log_error "Input file not found: $INPUT_FILE"
    return 1
fi

# Get parameters
get_param() {
    local param_name="$1"
    local default="${2:-}"
    
    local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["'\'']\(.*\)["'\'']$/\1/')
    
    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

TARGET_FORMAT=$(get_param "target_format" "")
PRESERVE_QUALITY=$(get_param "preserve_quality" "true")
BITRATE=$(get_param "bitrate" "320k")
# Explicit conform targets. Empty means "preserve whatever the source has", which is
# the historical behaviour; a value means the output MUST come out at that setting and
# the verify: contract re-probes the file to prove it did.
TARGET_SAMPLE_RATE=$(get_param "sample_rate" "")
TARGET_BIT_DEPTH=$(get_param "bit_depth" "")
TARGET_CHANNELS=$(get_param "channels" "")

if [[ -z "$TARGET_FORMAT" ]]; then
    log_error "target_format parameter is required (e.g., wav, mp3, flac)"
    return 1
fi

log_info "Format conversion parameters:"
log_info "  Target format: $TARGET_FORMAT"
log_info "  Preserve quality: $PRESERVE_QUALITY"
log_info "  Bitrate (lossy): $BITRATE"
log_info "  Sample rate: ${TARGET_SAMPLE_RATE:-preserve}"
log_info "  Bit depth: ${TARGET_BIT_DEPTH:-preserve}"
log_info "  Channels: ${TARGET_CHANNELS:-preserve}"

# Create output directory
ensure_dir "$OUTPUT_DIR"

# ────────────────────────────────────────────────────────────
# FFmpeg encoder helper functions (from audioconv-cli)
# ────────────────────────────────────────────────────────────

FFMPEG_ENCODERS_CACHE=""

_load_encoder_cache() {
    if [[ -z "$FFMPEG_ENCODERS_CACHE" ]]; then
        FFMPEG_ENCODERS_CACHE="$(ffmpeg -encoders 2>/dev/null || true)"
    fi
}

has_encoder() {
    local enc="$1"
    _load_encoder_cache
    echo "$FFMPEG_ENCODERS_CACHE" | grep -qE "[[:space:]]${enc}[[:space:]]"
}

pick_encoder() {
    local chosen=""
    for enc in "$@"; do
        if has_encoder "$enc"; then
            chosen="$enc"
            break
        fi
    done
    if [[ -z "$chosen" ]]; then
        return 1
    fi
    echo "$chosen"
}

pcm_codec_for_depth() {
    local depth="$1"
    local endian="${2:-le}"
    case "$depth" in
        8)  echo "pcm_u8" ;;
        16) echo "pcm_s16${endian}" ;;
        24) echo "pcm_s24${endian}" ;;
        32) echo "pcm_s32${endian}" ;;
        *)  echo "pcm_s16${endian}" ;;
    esac
}

# ────────────────────────────────────────────────────────────
# Probe input file
# ────────────────────────────────────────────────────────────

log_info "Probing input file: $(basename "$INPUT_FILE")"

PROBE_CODEC=""
PROBE_SAMPLE_RATE=""
PROBE_CHANNELS=""
PROBE_BIT_DEPTH=""
PROBE_SAMPLE_FMT=""

probe_out=$(ffprobe -v error \
    -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels,bits_per_raw_sample,sample_fmt \
    -of default=noprint_wrappers=1:nokey=0 \
    "$INPUT_FILE" 2>/dev/null)

if [[ -z "$probe_out" ]]; then
    log_error "ffprobe failed on: $INPUT_FILE"
    return 1
fi

while IFS='=' read -r key val; do
    case "$key" in
        codec_name)           PROBE_CODEC="$val"       ;;
        sample_rate)          PROBE_SAMPLE_RATE="$val" ;;
        channels)             PROBE_CHANNELS="$val"    ;;
        bits_per_raw_sample)  PROBE_BIT_DEPTH="$val"    ;;
        sample_fmt)           PROBE_SAMPLE_FMT="$val"  ;;
    esac
done <<< "$probe_out"

# Infer bit depth if not detected
if [[ -z "$PROBE_BIT_DEPTH" || "$PROBE_BIT_DEPTH" == "0" || "$PROBE_BIT_DEPTH" == "N/A" ]]; then
    case "$PROBE_SAMPLE_FMT" in
        s16*|u16*) PROBE_BIT_DEPTH=16 ;;
        s24*|u24*) PROBE_BIT_DEPTH=24 ;;
        s32*|u32*|flt) PROBE_BIT_DEPTH=32 ;;
        dbl) PROBE_BIT_DEPTH=64 ;;
        *) PROBE_BIT_DEPTH=16 ;;
    esac
fi

log_info "Probed: codec=${PROBE_CODEC} sr=${PROBE_SAMPLE_RATE}Hz ch=${PROBE_CHANNELS} depth=${PROBE_BIT_DEPTH}bit"

# ────────────────────────────────────────────────────────────
# Build FFmpeg output arguments
# ────────────────────────────────────────────────────────────

FFMPEG_ARGS=()

build_ffmpeg_args() {
    local target_fmt="$1"
    # An explicit target wins over the probed source value. Probe stays the fallback so
    # omitting these params preserves the old preserve-the-source behaviour exactly.
    local depth="${TARGET_BIT_DEPTH:-${PROBE_BIT_DEPTH:-16}}"
    local sr="${TARGET_SAMPLE_RATE:-${PROBE_SAMPLE_RATE:-44100}}"
    local ch="${TARGET_CHANNELS:-${PROBE_CHANNELS:-2}}"

    FFMPEG_ARGS=( -ar "$sr" -ac "$ch" )
    
    case "$target_fmt" in
        # Lossless PCM targets
        wav)
            FFMPEG_ARGS+=( -c:a "$(pcm_codec_for_depth "$depth" le)" )
            ;;
        aiff)
            FFMPEG_ARGS+=( -c:a "$(pcm_codec_for_depth "$depth" be)" )
            ;;
        au)
            local au_depth="$depth"
            (( au_depth > 32 )) && au_depth=32
            FFMPEG_ARGS+=( -c:a "$(pcm_codec_for_depth "$au_depth" be)" )
            ;;
        caf)
            FFMPEG_ARGS+=( -c:a "$(pcm_codec_for_depth "$depth" le)" )
            ;;
        
        # Native lossless encoders
        flac)
            FFMPEG_ARGS+=( -c:a flac )
            ;;
        alac)
            FFMPEG_ARGS+=( -c:a alac )
            ;;
        tta)
            FFMPEG_ARGS+=( -c:a tta )
            ;;
        wv)
            FFMPEG_ARGS+=( -c:a wavpack )
            ;;
        mka)
            FFMPEG_ARGS+=( -c:a flac )
            ;;
        
        # MP3 — libmp3lame preferred; libshine fallback
        mp3)
            local enc
            if enc="$(pick_encoder libmp3lame libshine)"; then
                log_info "MP3 encoder: ${enc}"
                FFMPEG_ARGS+=( -c:a "$enc" -b:a "$BITRATE" -q:a 0 )
            else
                log_error "No encoder available for MP3. Tried: libmp3lame, libshine"
                return 1
            fi
            ;;
        
        # AAC / M4A — libfdk_aac preferred; native aac fallback
        m4a|aac)
            if has_encoder libfdk_aac; then
                log_info "AAC encoder: libfdk_aac (highest quality)"
                FFMPEG_ARGS+=( -c:a libfdk_aac -b:a 256k )
            else
                log_info "AAC encoder: aac (native — libfdk_aac not available)"
                FFMPEG_ARGS+=( -c:a aac -b:a 256k )
            fi
            ;;
        
        # OGG Vorbis — libvorbis preferred; native vorbis fallback
        ogg)
            if has_encoder libvorbis; then
                log_info "OGG encoder: libvorbis"
                FFMPEG_ARGS+=( -c:a libvorbis -b:a "$BITRATE" )
            elif has_encoder vorbis; then
                log_warn "libvorbis not found — using native vorbis encoder"
                FFMPEG_ARGS+=( -c:a vorbis -strict experimental -b:a "$BITRATE" )
            else
                log_error "No encoder available for OGG. Tried: libvorbis, vorbis"
                return 1
            fi
            ;;
        
        # Opus — libopus preferred; native opus fallback
        opus)
            if has_encoder libopus; then
                log_info "Opus encoder: libopus"
                FFMPEG_ARGS+=( -c:a libopus -b:a 192k )
            elif has_encoder opus; then
                log_warn "libopus not found — using native opus encoder"
                FFMPEG_ARGS+=( -c:a opus -strict experimental -b:a 192k )
            else
                log_error "No encoder available for Opus. Tried: libopus, opus"
                return 1
            fi
            ;;
        
        # WMA — wmav2 preferred; wmav1 fallback
        wma)
            if has_encoder wmav2; then
                FFMPEG_ARGS+=( -c:a wmav2 -b:a "$BITRATE" )
            elif has_encoder wmav1; then
                log_warn "wmav2 not found — falling back to wmav1"
                FFMPEG_ARGS+=( -c:a wmav1 -b:a "$BITRATE" )
            else
                log_error "No encoder available for WMA. Tried: wmav2, wmav1"
                return 1
            fi
            ;;
        
        # AC-3 — ac3 always available
        ac3)
            FFMPEG_ARGS+=( -c:a ac3 -b:a 640k )
            ;;
        
        *)
            log_error "Unknown target format: ${target_fmt}"
            return 1
            ;;
    esac
    
    # If preserve_quality is false, we still keep sample rate and channels
    # but for lossless we might want to preserve bit depth via PCM codec
    if [[ "$PRESERVE_QUALITY" != "true" ]]; then
        # For lossy formats, bitrate is already set above
        # For lossless, we could reduce bit depth, but user said preserve quality
        log_info "Quality preservation: ${PRESERVE_QUALITY} (using specified settings)"
    fi
    
    log_debug "FFmpeg args for ${target_fmt}: ${FFMPEG_ARGS[*]}"
    return 0
}

# ────────────────────────────────────────────────────────────
# Output extension resolver
# ────────────────────────────────────────────────────────────

output_extension() {
    local fmt="$1"
    case "$fmt" in
        alac) echo "m4a" ;;
        aiff) echo "aiff" ;;
        *)    echo "$fmt" ;;
    esac
}

# ────────────────────────────────────────────────────────────
# Perform conversion
# ────────────────────────────────────────────────────────────

OUTPUT_EXT=$(output_extension "$TARGET_FORMAT")
OUTPUT_FILE="$OUTPUT_DIR/${INPUT_NAME}_converted.${OUTPUT_EXT}"

log_info "Converting to ${TARGET_FORMAT}..."
log_info "Output file: $(basename "$OUTPUT_FILE")"

if ! build_ffmpeg_args "$TARGET_FORMAT"; then
    log_error "Failed to build FFmpeg arguments for ${TARGET_FORMAT}"
    return 1
fi

# Check dependencies
if ! command_exists ffmpeg; then
    log_error "Command 'ffmpeg' not found"
    return 1
fi

if ! command_exists ffprobe; then
    log_error "Command 'ffprobe' not found"
    return 1
fi

# Execute FFmpeg conversion
log_info "Running FFmpeg conversion..."

# Ensure logs directory exists
ensure_dir "$OUTPUT_DIR/logs"
LOG_FILE="$OUTPUT_DIR/logs/format_conversion.log"

log_debug "FFmpeg args: ${FFMPEG_ARGS[*]}"

# Run ffmpeg with arguments array
if ffmpeg -i "$INPUT_FILE" "${FFMPEG_ARGS[@]}" "$OUTPUT_FILE" >> "$LOG_FILE" 2>&1; then
    log_info "Conversion completed: $(basename "$OUTPUT_FILE")"
    
    # Verify output file exists
    if [[ -f "$OUTPUT_FILE" ]]; then
        log_info "Output size: $(stat -f%z "$OUTPUT_FILE" 2>/dev/null || stat -c%s "$OUTPUT_FILE" 2>/dev/null) bytes"
    else
        log_error "Output file not created: $OUTPUT_FILE"
        return 1
    fi
else
    log_error "FFmpeg conversion failed. Check log: $OUTPUT_DIR/logs/format_conversion.log"
    return 1
fi

# Register output
register_output "$CONTEXT_FILE" "format_conversion" "primary_output" "$OUTPUT_FILE" "file" \
    "{\"target_format\": \"$TARGET_FORMAT\", \"preserve_quality\": $PRESERVE_QUALITY, \"bitrate\": \"$BITRATE\"}" \
    "completed"

log_info "Format conversion completed: $TARGET_FORMAT"
return 0
