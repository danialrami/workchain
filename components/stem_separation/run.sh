#!/bin/bash
# Component: stem_separation
# Description: Source separation via python-audio-separator (UVR model zoo).
#
# One easy knob — `preset` — picks quality:
#   hybrid   (DEFAULT) two-stage RoFormer→Demucs: BS-RoFormer isolates RoFormer-grade
#            vocals, then Demucs splits the leftover instrumental into drums/bass/other.
#            Highest quality full 4-stem. (residual-vocals from stage 2 fold into `other`
#            so the stems still recombine exactly to the source.)
#   demucs   single fine-tuned Demucs v4 (htdemucs_ft) → vocals/drums/bass/other
#   demucs6  single htdemucs_6s → +guitar/piano (6 stems)
#   roformer single BS-RoFormer → vocals/instrumental (2-stem, best vocal isolation)
#   mdx      single MDX-Net Inst_HQ_3 → vocals/instrumental (2-stem, fast)
#   custom   single model of your choice (set `model`)
# Any preset's model(s) can be overridden: `model` (single), `vocal_model` +
# `instrumental_model` (hybrid). Set these in a chain step's `params:` or via
# `run-component --params-json '{"preset":"demucs"}'`.
#
# HEAVY component — shells out to the `audio-separator` CLI (PyTorch/ONNX Runtime + a UVR
# model) from its OWN venv, NOT the core uv env and NOT the light path. Honest failure if
# the tool/model is unavailable — never a faked success.
#   Binary:  $WORKCHAIN_AUDIO_SEPARATOR_BIN → <component>/.venv/bin/audio-separator → PATH
#   Models:  $WORKCHAIN_AUDIO_SEPARATOR_MODELS or <component>/models  (git-ignored)

set +e  # control flow explicitly; the parent engine runs under `set -e`.

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh" 2>/dev/null || true
    source "$WORKCHAIN_ROOT/lib/common-utils.sh" 2>/dev/null || true
fi
[[ -z "$LIB_DIR" ]] && LIB_DIR="$WORKCHAIN_ROOT/lib"

CONTEXT_FILE="$1"
STEP_CONFIG="$2"

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

log_step "Running: stem_separation"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)

if [[ -z "$INPUT_FILE" || ! -f "$INPUT_FILE" ]]; then
    log_error "Input file not found: $INPUT_FILE"
    ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "input_not_found" "$INPUT_FILE"
    return 1
fi

get_param() {
    local param_name="$1"
    local default="${2:-}"
    local value
    value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["'\'']\(.*\)["'\'']$/\1/')
    if [[ -n "$value" ]]; then echo "$value"; else echo "$default"; fi
}

PRESET="$(get_param "preset" "hybrid" | tr '[:upper:]' '[:lower:]')"
PRIMARY_STEM="$(get_param "primary_stem" "vocals" | tr '[:upper:]' '[:lower:]')"
OUTPUT_FORMAT="$(get_param "output_format" "wav" | tr '[:upper:]' '[:lower:]')"
EXT="$OUTPUT_FORMAT"

# ── Resolve preset → mode + default model(s) (explicit params override) ─────────
ROFORMER_DEFAULT="model_bs_roformer_ep_317_sdr_12.9755.ckpt"
MODE="single"; D_MODEL=""; D_VOCAL=""; D_INSTR=""
case "$PRESET" in
    hybrid)   MODE="hybrid"; D_VOCAL="$ROFORMER_DEFAULT"; D_INSTR="htdemucs_ft.yaml" ;;
    demucs)   MODE="single"; D_MODEL="htdemucs_ft.yaml" ;;
    demucs6)  MODE="single"; D_MODEL="htdemucs_6s.yaml" ;;
    roformer) MODE="single"; D_MODEL="$ROFORMER_DEFAULT" ;;
    mdx)      MODE="single"; D_MODEL="UVR-MDX-NET-Inst_HQ_3.onnx" ;;
    custom)   MODE="single"; D_MODEL="" ;;
    *)
        log_error "Unknown preset '$PRESET' (valid: hybrid, demucs, demucs6, roformer, mdx, custom)"
        ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "unknown_preset" "$PRESET"
        return 1 ;;
esac
MODEL="$(get_param "model" "$D_MODEL")"
VOCAL_MODEL="$(get_param "vocal_model" "$D_VOCAL")"
INSTRUMENTAL_MODEL="$(get_param "instrumental_model" "$D_INSTR")"

if [[ "$MODE" == "single" && -z "$MODEL" ]]; then
    log_error "preset '$PRESET' needs a 'model' param (no default)."
    ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "model_required" "preset=$PRESET"
    return 1
fi

log_info "stem_separation parameters:"
log_info "  preset:        $PRESET (mode=$MODE)"
if [[ "$MODE" == "hybrid" ]]; then
    log_info "  vocal_model:   $VOCAL_MODEL"
    log_info "  instr_model:   $INSTRUMENTAL_MODEL"
else
    log_info "  model:         $MODEL"
fi
log_info "  primary_stem:  $PRIMARY_STEM"
log_info "  output_format: $OUTPUT_FORMAT"

# ── Resolve the audio-separator binary (honest failure if unavailable) ──────────
SEP=""
if [[ -n "$WORKCHAIN_AUDIO_SEPARATOR_BIN" && -x "$WORKCHAIN_AUDIO_SEPARATOR_BIN" ]]; then
    SEP="$WORKCHAIN_AUDIO_SEPARATOR_BIN"
elif [[ -x "$COMPONENT_DIR/.venv/bin/audio-separator" ]]; then
    SEP="$COMPONENT_DIR/.venv/bin/audio-separator"
elif command_exists audio-separator; then
    SEP="$(command -v audio-separator)"
fi
if [[ -z "$SEP" ]]; then
    log_error "audio-separator not found. This heavy component needs python-audio-separator in its own venv."
    log_error "  Install:  python3 -m venv \"$COMPONENT_DIR/.venv\" && \"$COMPONENT_DIR/.venv/bin/pip\" install \"audio-separator[cpu]\""
    log_error "  (macOS gets MPS/CoreML via [cpu]; Linux+NVIDIA uses [gpu]. Use Python 3.10 — Demucs diffq has no cp311 wheel.)"
    log_error "  Or point WORKCHAIN_AUDIO_SEPARATOR_BIN at an existing audio-separator executable."
    ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "audio_separator_not_found" \
        "python-audio-separator is not installed for this component"
    return 1
fi
log_info "  binary:        $SEP"

MODELS_DIR="${WORKCHAIN_AUDIO_SEPARATOR_MODELS:-$COMPONENT_DIR/models}"
ensure_dir "$OUTPUT_DIR"; ensure_dir "$OUTPUT_DIR/logs"; ensure_dir "$MODELS_DIR"
LOG_FILE="$OUTPUT_DIR/logs/stem_separation.log"
: > "$LOG_FILE"

# run_model <input> <model> <outdir> → stdout: "stem<TAB>path" per produced file; rc from separator.
run_model() {
    local in="$1" mdl="$2" od="$3"
    rm -rf "$od"; ensure_dir "$od"
    echo "### audio-separator: model=$mdl input=$(basename "$in")" >> "$LOG_FILE"
    "$SEP" "$in" --model_filename "$mdl" --output_dir "$od" --output_format "$OUTPUT_FORMAT" \
        --model_file_dir "$MODELS_DIR" --log_level info >> "$LOG_FILE" 2>&1
    local rc=$?
    [[ $rc -ne 0 ]] && return $rc
    python3 - "$od" "$EXT" <<'PYEOF'
import os, re, sys
d, ext = sys.argv[1], sys.argv[2].lower()
for fn in sorted(os.listdir(d)):
    if not fn.lower().endswith("." + ext):
        continue
    groups = re.findall(r'\(([^)]+)\)', fn)
    stem = (groups[-1] if groups else os.path.splitext(fn)[0]).strip().lower()
    stem = re.sub(r'[^a-z0-9]+', '_', stem).strip('_') or "stem"
    print("%s\t%s" % (stem, os.path.join(d, fn)))
PYEOF
}

# manifest_get <manifest> <stem> → path of that stem, or empty
manifest_get() { echo "$1" | awk -F'\t' -v s="$2" '$1==s{print $2; exit}'; }

declare -a STEM_NAMES=()
declare -a STEM_PATHS=()

if [[ "$MODE" == "hybrid" ]]; then
    log_info "Stage 1/2: RoFormer vocal isolation ($VOCAL_MODEL)..."
    if ! S1=$(run_model "$INPUT_FILE" "$VOCAL_MODEL" "$OUTPUT_DIR/.stem_s1"); then
        log_error "Stage 1 (RoFormer) failed. Log tail:"; tail -n 15 "$LOG_FILE" | while IFS= read -r l; do log_error "  $l"; done
        ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "stage1_error" "$VOCAL_MODEL"; return 1
    fi
    VOX_SRC=$(manifest_get "$S1" vocals)
    INSTR_SRC=$(manifest_get "$S1" instrumental)
    if [[ -z "$VOX_SRC" || -z "$INSTR_SRC" ]]; then
        log_error "Stage 1 did not yield vocals+instrumental (got: $(echo "$S1" | cut -f1 | tr '\n' ' '))"
        ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "stage1_unexpected" "$VOCAL_MODEL"; return 1
    fi

    log_info "Stage 2/2: Demucs splits the instrumental ($INSTRUMENTAL_MODEL)..."
    # Feed the instrumental under a clean, paren-free name so stage-2 output filenames
    # (and the stem tag we parse) don't inherit stage-1's "(Instrumental)" tag.
    INSTR_CLEAN="$OUTPUT_DIR/.s1_instrumental.$EXT"
    cp -f "$INSTR_SRC" "$INSTR_CLEAN"
    if ! S2=$(run_model "$INSTR_CLEAN" "$INSTRUMENTAL_MODEL" "$OUTPUT_DIR/.stem_s2"); then
        log_error "Stage 2 (Demucs) failed. Log tail:"; tail -n 15 "$LOG_FILE" | while IFS= read -r l; do log_error "  $l"; done
        ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "stage2_error" "$INSTRUMENTAL_MODEL"; return 1
    fi
    D_DRUMS=$(manifest_get "$S2" drums)
    D_BASS=$(manifest_get "$S2" bass)
    D_OTHER=$(manifest_get "$S2" other)
    D_VOX=$(manifest_get "$S2" vocals)   # residual vocal bleed from the instrumental
    if [[ -z "$D_DRUMS" || -z "$D_BASS" || -z "$D_OTHER" ]]; then
        log_error "Stage 2 did not yield drums+bass+other (got: $(echo "$S2" | cut -f1 | tr '\n' ' '))"
        ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "stage2_unexpected" "$INSTRUMENTAL_MODEL"; return 1
    fi

    VOCALS_OUT="$OUTPUT_DIR/${INPUT_NAME}_vocals.$EXT"
    DRUMS_OUT="$OUTPUT_DIR/${INPUT_NAME}_drums.$EXT"
    BASS_OUT="$OUTPUT_DIR/${INPUT_NAME}_bass.$EXT"
    OTHER_OUT="$OUTPUT_DIR/${INPUT_NAME}_other.$EXT"
    mv -f "$VOX_SRC" "$VOCALS_OUT"
    mv -f "$D_DRUMS" "$DRUMS_OUT"
    mv -f "$D_BASS" "$BASS_OUT"
    # Fold stage-2 residual vocals into `other` so nothing is discarded and the four
    # stems recombine exactly to the source (vocals + drums + bass + other == mix).
    if [[ -n "$D_VOX" && -f "$D_VOX" ]]; then
        # amix's normalize option needs ffmpeg >= 4.4; the fleet image is 4.2.x, so we
        # pre-scale ×2 and let amix's default 1/N normalisation make the same mix.
        ffmpeg -nostdin -hide_banner -y -i "$D_OTHER" -i "$D_VOX" \
            -filter_complex "[0:a]volume=2.0[a0];[1:a]volume=2.0[a1];[a0][a1]amix=inputs=2[o]" -map "[o]" "$OTHER_OUT" >> "$LOG_FILE" 2>&1
        [[ ! -f "$OTHER_OUT" ]] && mv -f "$D_OTHER" "$OTHER_OUT"
    else
        mv -f "$D_OTHER" "$OTHER_OUT"
    fi
    rm -rf "$OUTPUT_DIR/.stem_s1" "$OUTPUT_DIR/.stem_s2" "$INSTR_CLEAN"
    STEM_NAMES=(vocals drums bass other)
    STEM_PATHS=("$VOCALS_OUT" "$DRUMS_OUT" "$BASS_OUT" "$OTHER_OUT")
else
    log_info "Separating with '$MODEL' (heavy; minutes on CPU for Demucs)..."
    if ! SM=$(run_model "$INPUT_FILE" "$MODEL" "$OUTPUT_DIR/.stem_tmp"); then
        log_error "audio-separator failed. Log tail:"; tail -n 15 "$LOG_FILE" | while IFS= read -r l; do log_error "  $l"; done
        ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "separator_error" "$MODEL"; return 1
    fi
    while IFS=$'\t' read -r stem src; do
        [[ -z "$stem" || -z "$src" ]] && continue
        dest="$OUTPUT_DIR/${INPUT_NAME}_${stem}.$EXT"
        mv -f "$src" "$dest"
        STEM_NAMES+=("$stem"); STEM_PATHS+=("$dest")
    done <<< "$SM"
    rm -rf "$OUTPUT_DIR/.stem_tmp"
fi

STEM_COUNT=${#STEM_NAMES[@]}
if [[ "$STEM_COUNT" -lt 2 ]]; then
    log_error "Expected ≥2 stems; got $STEM_COUNT (${STEM_NAMES[*]})"
    ctx_set_status "$CONTEXT_FILE" "stem_separation" "failed" "too_few_stems" "$STEM_COUNT"
    return 1
fi

# Choose the primary stem (what the chain advances on); fall back to the first.
PRIMARY_OUT=""
for i in "${!STEM_NAMES[@]}"; do
    if [[ "${STEM_NAMES[$i]}" == "$PRIMARY_STEM" ]]; then PRIMARY_OUT="${STEM_PATHS[$i]}"; break; fi
done
if [[ -z "$PRIMARY_OUT" ]]; then
    log_warn "primary_stem '$PRIMARY_STEM' not produced (${STEM_NAMES[*]}); using '${STEM_NAMES[0]}'"
    PRIMARY_STEM="${STEM_NAMES[0]}"; PRIMARY_OUT="${STEM_PATHS[0]}"
fi

log_info "Produced $STEM_COUNT stems: ${STEM_NAMES[*]}"
log_info "  primary: $PRIMARY_OUT ($PRIMARY_STEM)"

SRC_SR=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null)
SRC_CH=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null)

META_JSON="$OUTPUT_DIR/logs/stem_separation.json"
STEMS_CSV=$(IFS=,; echo "${STEM_NAMES[*]}")
__WC_META="$META_JSON" __WC_PRESET="$PRESET" __WC_MODE="$MODE" __WC_MODEL="$MODEL" \
__WC_VOCAL="$VOCAL_MODEL" __WC_INSTR="$INSTRUMENTAL_MODEL" __WC_PRIM="$PRIMARY_STEM" __WC_FMT="$OUTPUT_FORMAT" \
__WC_SRC="$INPUT_FILE" __WC_BIN="$SEP" __WC_STEMS="$STEMS_CSV" \
__WC_SR="${SRC_SR:-unknown}" __WC_CHN="${SRC_CH:-unknown}" python3 << 'PYEOF'
import json, os
stems = [s for s in os.environ["__WC_STEMS"].split(",") if s]
mode = os.environ["__WC_MODE"]
meta = {
    "preset": os.environ["__WC_PRESET"],
    "mode": mode,
    "stems": stems,
    "stem_count": len(stems),
    "primary_stem": os.environ["__WC_PRIM"],
    "output_format": os.environ["__WC_FMT"],
    "source_input": os.environ["__WC_SRC"],
    "backend": "python-audio-separator",
    "backend_bin": os.environ["__WC_BIN"],
    "source_sample_rate": os.environ["__WC_SR"],
    "source_channels": os.environ["__WC_CHN"],
}
if mode == "hybrid":
    meta["stages"] = [
        {"stage": 1, "role": "vocal_isolation", "model": os.environ["__WC_VOCAL"]},
        {"stage": 2, "role": "instrumental_split", "model": os.environ["__WC_INSTR"],
         "note": "residual vocals folded into 'other' for exact recombination"},
    ]
    meta["model"] = "%s + %s" % (os.environ["__WC_VOCAL"], os.environ["__WC_INSTR"])
else:
    meta["model"] = os.environ["__WC_MODEL"]
with open(os.environ["__WC_META"], "w") as f:
    json.dump(meta, f, indent=2)
PYEOF

# Register primary_output FIRST (sets backward-compat `output`; engine advances to it),
# then each stem, then the JSON sidecar. source_input in metadata lets the verifier
# resolve the recombination/duration reference robustly.
register_output "$CONTEXT_FILE" "stem_separation" "primary_output" "$PRIMARY_OUT" "file" \
    "{\"preset\": \"$PRESET\", \"primary_stem\": \"$PRIMARY_STEM\", \"stem_count\": $STEM_COUNT, \"source_input\": \"$INPUT_FILE\"}" \
    "completed"
for i in "${!STEM_NAMES[@]}"; do
    register_output "$CONTEXT_FILE" "stem_separation" "${STEM_NAMES[$i]}" "${STEM_PATHS[$i]}" "file" \
        "{\"stem\": \"${STEM_NAMES[$i]}\", \"source_input\": \"$INPUT_FILE\"}" \
        "completed"
done
register_output "$CONTEXT_FILE" "stem_separation" "separation_metadata" "$META_JSON" "json" \
    "{\"preset\": \"$PRESET\", \"stem_count\": $STEM_COUNT}" \
    "completed"

log_info "stem_separation completed (preset=$PRESET, $STEM_COUNT stems)"
return 0
