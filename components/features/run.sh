# features — cheap deterministic DSP features (archive-ingest stage 2)
#
# HONESTY NOTE (2026-08): this component used to treat an EMPTY decode and a genuinely tiny
# file as the same case. When ffmpeg refused a WAV, `raw` came back b"", x.size was 0, and it
# wrote the "insufficient_audio" record (centroid 0.0, rms -120.0, brightness 0.0) and exited
# 0 — a measurement of nothing, indistinguishable from a measurement of near-silence. A failed
# decode is now a FAILURE. The short-file branch can only be reached when the decode SUCCEEDED,
# and it records decoded_duration_s as the evidence.
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi
CONTEXT_FILE="$1"
[[ -z "$CONTEXT_FILE" ]] && { echo "usage: $0 <context> <config>"; return 1; }
log_step "Running: features"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
OUT="$OUTPUT_DIR/archive/${INPUT_NAME}.features.json"
ensure_dir "$(dirname "$OUT")"

IN="$INPUT_FILE" OUT="$OUT" WORKDIR="$OUTPUT_DIR" WCLIB="$WORKCHAIN_ROOT/lib" python3 <<'PY'
import os, sys, json
sys.path.insert(0, os.environ["WCLIB"])
import workchain_decode as D
import numpy as np

src, out = os.environ["IN"], os.environ["OUT"]
SR = 22050
MIN_SAMPLES = 256          # ~12ms. Was SR//10 (100ms), which threw away real one-shots.
SILENT_DBFS = -144.0       # matches probe's floor

try:
    raw, prov = D.decode_mono_f32(src, sr=SR, workdir=os.environ.get("WORKDIR") or None)
except D.DecodeError as e:
    sys.stderr.write("features: %s\n" % e)
    raise SystemExit(1)

x = np.frombuffer(raw, dtype=np.float32)
decoded_s = round(x.size / float(SR), 4)

rec = {"feature_source": "native-melstats-v0",
       "decoder": prov["decoder"],
       "decoded_duration_s": decoded_s,
       "bpm": None, "key": None}
if "salvage" in prov:
    rec["salvage"] = prov["salvage"]

if x.size < MIN_SAMPLES:
    # Reachable ONLY on a successful decode of a genuinely tiny file. decoded_duration_s is
    # the proof; the old code could land here because ffmpeg had failed.
    rec.update({"spectral_centroid_hz": 0.0, "spectral_rolloff85_hz": 0.0,
                "rms_dbfs": SILENT_DBFS, "zero_crossing_rate": 0.0, "brightness": 0.0,
                "note": "decoded %.4fs (<%d samples) — too short for a spectral estimate"
                        % (decoded_s, MIN_SAMPLES)})
else:
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)
    rms_db = max(SILENT_DBFS, 20 * np.log10(rms))
    win = np.hanning(min(len(x), 1 << 15))
    seg = x[:len(win)] * win
    mag = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / SR)
    total = float(mag.sum())
    centroid = float((freqs * mag).sum() / (total + 1e-12))
    zcr = float(np.mean(np.abs(np.diff(np.sign(x))) > 0))
    rolloff_idx = int(np.searchsorted(np.cumsum(mag), 0.85 * total))
    rolloff = float(freqs[min(rolloff_idx, len(freqs) - 1)])
    rec.update({"spectral_centroid_hz": round(centroid, 2),
                "spectral_rolloff85_hz": round(rolloff, 2),
                "rms_dbfs": round(float(rms_db), 2),
                "zero_crossing_rate": round(zcr, 5),
                "brightness": round(min(centroid / (SR / 2), 1.0), 4),
                "note": "bpm/key deferred (v0) — librosa/essentia or sononym warm-start"})

for k, v in rec.items():
    if isinstance(v, float) and not np.isfinite(v):
        sys.stderr.write("features: computed a non-finite %s for %s — refusing to write it\n"
                         % (k, src))
        raise SystemExit(1)

tmp = out + ".tmp.%d" % os.getpid()
with open(tmp, "w") as f:
    json.dump(rec, f, indent=2, allow_nan=False)
os.replace(tmp, out)
print("features ok: centroid=%.0fHz rms=%.1fdB (%.3fs via %s)"
      % (rec["spectral_centroid_hz"], rec["rms_dbfs"], decoded_s, rec["decoder"]))
PY
rc=$?
if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
    log_error "features failed to produce $OUT"
    register_output "$CONTEXT_FILE" "features" "features" "$OUT" "json" '{"error":"features_failed"}' "failed"
    return 1
fi
DECODER=$(ctx_get "$OUT" decoder)
register_output "$CONTEXT_FILE" "features" "features" "$OUT" "json" \
    "{\"source_input\": \"$INPUT_FILE\", \"decoder\": \"$DECODER\"}" "completed"
log_info "features completed (decoder=$DECODER)"
return 0
