# probe — content hash + deterministic facts for one audio file (archive-ingest stage 1)
#
# HONESTY NOTE (2026-08): this component used to do
#     d = json.loads(r.stdout or "{}")
# which turned a hard ffprobe failure into a sidecar full of nulls, printed "probe ok", and
# exited 0. On WAVs whose chunk table ffmpeg refuses ("too short LIST tag") that produced a
# record with duration 0.0 and null samplerate/channels/codec that still satisfied the
# contract, because the contract only asserted key PRESENCE. It now measures from a file
# ffmpeg accepts — the original, or a stdlib-salvaged copy — and FAILS if it cannot.
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi
CONTEXT_FILE="$1"
[[ -z "$CONTEXT_FILE" ]] && { echo "usage: $0 <context> <config>"; return 1; }
log_step "Running: probe"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
OUT="$OUTPUT_DIR/archive/${INPUT_NAME}.probe.json"
ensure_dir "$(dirname "$OUT")"

IN="$INPUT_FILE" OUT="$OUT" WORKDIR="$OUTPUT_DIR" WCLIB="$WORKCHAIN_ROOT/lib" python3 <<'PY'
import os, sys, json, hashlib, re
sys.path.insert(0, os.environ["WCLIB"])
import workchain_decode as D

src, out = os.environ["IN"], os.environ["OUT"]
workdir = os.environ.get("WORKDIR") or None

# The content hash is of the ORIGINAL bytes, always. A salvaged copy is a decode aid, never
# the identity of the asset — catalog numbers must not change because ffmpeg got stricter.
h = hashlib.sha256()
with open(src, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
sha = h.hexdigest()

try:
    read_path, prov = D.decodable_path(src, workdir=workdir)
    d = D.ffprobe_json(read_path)
except D.DecodeError as e:
    sys.stderr.write("probe: %s\n" % e)
    raise SystemExit(1)

st = (d.get("streams") or [{}])[0]
fmt = d.get("format") or {}

# D.run() always decodes stderr with errors="replace" — WAV INFO tags carrying latin-1 bytes
# used to raise UnicodeDecodeError here and take the whole batch run down with them.
vd = D.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", read_path,
            "-af", "volumedetect", "-f", "null", "-"]).stderr

SILENT_DBFS = -144.0   # below the 24-bit floor: digital silence, stated as a number rather
                       # than -inf, which is not valid JSON and poisons downstream consumers

def grab(key):
    m = re.search(key + r":\s*(-?[0-9.]+|-?inf)", vd)
    if not m:
        return None
    raw = m.group(1)
    return SILENT_DBFS if "inf" in raw else float(raw)

def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

peak, mean = grab("max_volume"), grab("mean_volume")
rec = {
  "content_sha256": sha,
  "catalog_number": "lufs-" + sha[:8],
  "path": os.path.abspath(src),
  "filename": os.path.basename(src),
  "duration_s": round(float(fmt.get("duration") or 0.0), 4),
  "samplerate": as_int(st.get("sample_rate")),
  "channels": as_int(st.get("channels")),
  "bits_per_raw_sample": as_int(st.get("bits_per_raw_sample")),
  "codec": st.get("codec_name"),
  "container": fmt.get("format_name"),
  "peak_dbfs": peak,
  "mean_dbfs": mean,
  "silent": bool(peak is not None and peak <= SILENT_DBFS),
  "decoder": prov["decoder"],
}
if "salvage" in prov:
    rec["salvage"] = prov["salvage"]

# The contract enforces this too (step.yaml post_conditions), but a component that already
# knows its own answer is wrong must not hand it downstream and hope the gate catches it.
missing = [k for k in ("duration_s", "samplerate", "channels", "codec") if not rec.get(k)]
if missing:
    sys.stderr.write("probe: ffprobe returned no %s for %s (decoder=%s) — refusing to write "
                     "a null record\n" % (", ".join(missing), src, rec["decoder"]))
    raise SystemExit(1)

tmp = out + ".tmp.%d" % os.getpid()
with open(tmp, "w") as f:
    json.dump(rec, f, indent=2, allow_nan=False)   # never emit Infinity/NaN into the index
os.replace(tmp, out)
print("probe ok:", rec["catalog_number"], rec["duration_s"], "s", "via", rec["decoder"])
PY
rc=$?
if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
    log_error "probe failed to produce $OUT"
    register_output "$CONTEXT_FILE" "probe" "probe" "$OUT" "json" '{"error":"probe_failed"}' "failed"
    return 1
fi
DECODER=$(ctx_get "$OUT" decoder)
register_output "$CONTEXT_FILE" "probe" "probe" "$OUT" "json" \
    "{\"source_input\": \"$INPUT_FILE\", \"decoder\": \"$DECODER\"}" "completed"
log_info "probe completed (decoder=$DECODER)"
return 0
