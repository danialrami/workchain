# archive_index — upsert one file into the shared archive index (archive-ingest stage 5, terminal)
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi
CONTEXT_FILE="$1"; STEP_CONFIG="$2"
[[ -z "$CONTEXT_FILE" ]] && { echo "usage: $0 <context> <config>"; return 1; }
log_step "Running: archive_index"
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
OUT="$OUTPUT_DIR/archive/${INPUT_NAME}.index.json"
ensure_dir "$(dirname "$OUT")"

# Per-file scope precedence: ARCHIVE_SCOPE env (set by the batch driver) > param > global > default.
SCOPE="${ARCHIVE_SCOPE:-}"
if [[ -z "$SCOPE" ]]; then
    SCOPE=$(echo "$STEP_CONFIG" | grep -E "^\s+scope:" | sed 's/.*scope: *//' | head -1 | tr -d ' "')
fi
[[ -z "$SCOPE" ]] && SCOPE=$(get_global "$CONTEXT_FILE" scope "archive")
ARCHIVE_DB="${ARCHIVE_DB:-$(get_global "$CONTEXT_FILE" archive_db "$OUTPUT_DIR/archive.db")}"

PROBE=$(ctx_get "$CONTEXT_FILE" steps.probe.outputs.probe.path)
FEATS=$(ctx_get "$CONTEXT_FILE" steps.features.outputs.features.path)
# The embedder step is `embed` (melstats) or `embed_clap` (LAION-CLAP) depending on the chain.
EMB=$(ctx_get "$CONTEXT_FILE" steps.embed_clap.outputs.embedding.path)
[[ -z "$EMB" ]] && EMB=$(ctx_get "$CONTEXT_FILE" steps.embed.outputs.embedding.path)
HOOK=$(ctx_get "$CONTEXT_FILE" steps.hook.outputs.hook_clip.path)
WAVE=$(ctx_get "$CONTEXT_FILE" steps.hook.outputs.waveform.path)

OUT="$OUT" DB="$ARCHIVE_DB" SCOPE="$SCOPE" PROBE="$PROBE" FEATS="$FEATS" EMB="$EMB" HOOK="$HOOK" WAVE="$WAVE" python3 <<'PY'
import os, json, sqlite3, datetime
out=os.environ["OUT"]; db=os.environ["DB"]; scope=os.environ["SCOPE"]
def load(p):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return {}
pr=load(os.environ["PROBE"]); ft=load(os.environ["FEATS"]); em=load(os.environ["EMB"])
sha=pr.get("content_sha256")
if not sha:
    with open(out,"w") as f: json.dump({"indexed":False,"error":"no content hash","db_path":db,"scope":scope,"content_sha256":None},f,indent=2)
    raise SystemExit(1)
# Honest failure: never index a null vector. If the embed step's output wasn't found (e.g. a chain
# whose embedder step name we didn't resolve), fail loudly instead of writing a broken row.
vec=em.get("vector")
if not (isinstance(vec, list) and len(vec) > 0):
    with open(out,"w") as f: json.dump({"indexed":False,"error":"no embedding vector from embed/embed_clap","db_path":db,"scope":scope,"content_sha256":sha},f,indent=2)
    raise SystemExit(1)
os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
con=sqlite3.connect(db); cur=con.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS assets(
  content_sha256 TEXT PRIMARY KEY, catalog_number TEXT, path TEXT, filename TEXT, scope TEXT,
  duration_s REAL, samplerate INTEGER, channels INTEGER, peak_dbfs REAL, mean_dbfs REAL,
  spectral_centroid_hz REAL, rms_dbfs REAL, brightness REAL, bpm REAL, key TEXT,
  embed_model TEXT, dim INTEGER, vector TEXT, hook_path TEXT, waveform_path TEXT,
  feature_source TEXT, indexed_at TEXT)""")
# NOTE: prod uses a sqlite-vec vec0 virtual table for the vector; here vector is JSON text
# and KNN is brute-force in the query CLI. Same schema, same rows — only the ANN mechanism differs.
row=(sha, pr.get("catalog_number"), pr.get("path"), pr.get("filename"), scope,
     pr.get("duration_s"), pr.get("samplerate"), pr.get("channels"), pr.get("peak_dbfs"), pr.get("mean_dbfs"),
     ft.get("spectral_centroid_hz"), ft.get("rms_dbfs"), ft.get("brightness"), ft.get("bpm"), ft.get("key"),
     em.get("model"), em.get("dim"), json.dumps(em.get("vector")), os.environ["HOOK"], os.environ["WAVE"],
     ft.get("feature_source"), datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
cur.execute("""INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(content_sha256) DO UPDATE SET
    catalog_number=excluded.catalog_number, path=excluded.path, filename=excluded.filename, scope=excluded.scope,
    duration_s=excluded.duration_s, samplerate=excluded.samplerate, channels=excluded.channels,
    peak_dbfs=excluded.peak_dbfs, mean_dbfs=excluded.mean_dbfs, spectral_centroid_hz=excluded.spectral_centroid_hz,
    rms_dbfs=excluded.rms_dbfs, brightness=excluded.brightness, bpm=excluded.bpm, key=excluded.key,
    embed_model=excluded.embed_model, dim=excluded.dim, vector=excluded.vector,
    hook_path=excluded.hook_path, waveform_path=excluded.waveform_path,
    feature_source=excluded.feature_source, indexed_at=excluded.indexed_at""", row)
con.commit()
n=cur.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
con.close()
rec={"indexed":True,"content_sha256":sha,"catalog_number":pr.get("catalog_number"),
     "scope":scope,"db_path":db,"rows_in_index":n,"embed_model":em.get("model"),"dim":em.get("dim")}
with open(out,"w") as f: json.dump(rec,f,indent=2)
print("indexed:", pr.get("catalog_number"), "scope=%s"%scope, "rows=%d"%n)
PY
rc=$?
if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
    log_error "archive_index failed"
    register_output "$CONTEXT_FILE" "archive_index" "index_record" "$OUT" "json" '{"error":"index_failed"}' "failed"
    return 1
fi
register_output "$CONTEXT_FILE" "archive_index" "index_record" "$OUT" "json" "{\"db\":\"$ARCHIVE_DB\"}" "completed"
log_info "archive_index completed"
return 0
