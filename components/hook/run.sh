# hook — loudest-window 3s clip + waveform PNG (archive-ingest stage 3)
#
# This component was already honest — it checked that its outputs were non-empty and failed
# when they weren't, which is the only reason a whole library's worth of null probe/features
# records never reached the archive index. It keeps that check, and now shares the decode path
# so a WAV whose chunk table ffmpeg refuses gets salvaged instead of halting the chain.
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi
CONTEXT_FILE="$1"; STEP_CONFIG="$2"
[[ -z "$CONTEXT_FILE" ]] && { echo "usage: $0 <context> <config>"; return 1; }
log_step "Running: hook"
INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
HOOK="$OUTPUT_DIR/archive/${INPUT_NAME}.hook.wav"
WAVE="$OUTPUT_DIR/archive/${INPUT_NAME}.waveform.png"
PREP="$OUTPUT_DIR/hook.prep.json"
ensure_dir "$(dirname "$HOOK")"
HOOK_SECONDS=$(echo "$STEP_CONFIG" | grep -E "^\s+hook_seconds:" | sed 's/.*hook_seconds: *//' | head -1 | tr -d ' ')
[[ -z "$HOOK_SECONDS" ]] && HOOK_SECONDS=3

# Resolve a decodable path and the loudest-window start in ONE python pass, and hand both
# back through a JSON file read with ctx_get — never by interpolating a path into the shell.
# The sample library is full of apostrophes, commas and brackets.
IN="$INPUT_FILE" PREP="$PREP" LEN="$HOOK_SECONDS" WORKDIR="$OUTPUT_DIR" \
WCLIB="$WORKCHAIN_ROOT/lib" python3 <<'PY'
import os, sys, json
sys.path.insert(0, os.environ["WCLIB"])
import workchain_decode as D
import numpy as np

src = os.environ["IN"]; prep = os.environ["PREP"]
win_s = float(os.environ["LEN"]); SR = 22050
workdir = os.environ.get("WORKDIR") or None

try:
    read_path, prov = D.decodable_path(src, workdir=workdir)
    raw, _ = D.decode_mono_f32(read_path, sr=SR, allow_salvage=False)
except D.DecodeError as e:
    sys.stderr.write("hook: %s\n" % e)
    raise SystemExit(1)

x = np.frombuffer(raw, dtype=np.float32)
w = int(SR * win_s)
start = 0.0
if x.size >= w and w > 0:
    energy = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    step = max(1, SR // 10)
    starts = np.arange(0, x.size - w, step)
    if starts.size:
        sums = energy[starts + w] - energy[starts]
        start = float(starts[int(np.argmax(sums))]) / SR

rec = {"start_s": round(start, 2), "read_path": read_path, "decoder": prov["decoder"],
       "decoded_duration_s": round(x.size / float(SR), 4)}
if "salvage" in prov:
    rec["salvage"] = prov["salvage"]
tmp = prep + ".tmp.%d" % os.getpid()
with open(tmp, "w") as f:
    json.dump(rec, f, indent=2, allow_nan=False)
os.replace(tmp, prep)
PY
if [[ $? -ne 0 || ! -s "$PREP" ]]; then
    log_error "hook failed (input is not decodable, even after salvage)"
    register_output "$CONTEXT_FILE" "hook" "hook_clip" "$HOOK" "file" '{"error":"hook_undecodable"}' "failed"
    return 1
fi
START=$(ctx_get "$PREP" start_s)
READ_PATH=$(ctx_get "$PREP" read_path)
DECODER=$(ctx_get "$PREP" decoder)
[[ -z "$START" ]] && START=0.0
[[ -z "$READ_PATH" ]] && READ_PATH="$INPUT_FILE"

ffmpeg -nostdin -hide_banner -v error -y -ss "$START" -t "$HOOK_SECONDS" -i "$READ_PATH" \
    -ac 1 -ar 44100 "$HOOK" </dev/null
ffmpeg -nostdin -hide_banner -v error -y -i "$READ_PATH" \
    -filter_complex "aformat=channel_layouts=mono,showwavespic=s=640x120:colors=#78BEBA" \
    -frames:v 1 "$WAVE" </dev/null

if [[ ! -s "$HOOK" || ! -s "$WAVE" ]]; then
    log_error "hook failed (clip or waveform missing; decoder=$DECODER read_path=$READ_PATH)"
    register_output "$CONTEXT_FILE" "hook" "hook_clip" "$HOOK" "file" '{"error":"hook_failed"}' "failed"
    return 1
fi
register_output "$CONTEXT_FILE" "hook" "hook_clip" "$HOOK" "file" \
    "{\"loudest_start_s\": $START, \"decoder\": \"$DECODER\", \"source_input\": \"$INPUT_FILE\"}" "completed"
register_output "$CONTEXT_FILE" "hook" "waveform" "$WAVE" "file" "{\"w\":640,\"h\":120}" "completed"
log_info "hook completed (loudest window @ ${START}s, decoder=$DECODER)"
return 0
