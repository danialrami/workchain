# embed — melstats-v0 vector behind the CLAP contract (archive-ingest stage 4)
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi
CONTEXT_FILE="$1"; STEP_CONFIG="$2"
[[ -z "$CONTEXT_FILE" ]] && { echo "usage: $0 <context> <config>"; return 1; }
log_step "Running: embed"
INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
OUT="$OUTPUT_DIR/archive/${INPUT_NAME}.embedding.json"
ensure_dir "$(dirname "$OUT")"
MODEL=$(echo "$STEP_CONFIG" | grep -E "^\s+model:" | sed 's/.*model: *//' | head -1 | tr -d ' "')
[[ -z "$MODEL" ]] && MODEL="melstats-v0"

IN="$INPUT_FILE" OUT="$OUT" MODEL="$MODEL" python3 <<'PY'
import os, json, subprocess, numpy as np
src, out, model = os.environ["IN"], os.environ["OUT"], os.environ["MODEL"]
SR=22050; NBANDS=32
raw=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-v","error","-i",src,
    "-ac","1","-ar",str(SR),"-f","f32le","-"],capture_output=True).stdout
x=np.frombuffer(raw,dtype=np.float32)
def logmel_stats(x):
    if x.size < 2048: x=np.pad(x,(0,2048))
    n=1024; hop=512
    frames=[x[i:i+n]*np.hanning(n) for i in range(0,len(x)-n,hop)]
    if not frames: frames=[np.zeros(n)]
    S=np.abs(np.fft.rfft(np.stack(frames),axis=1))  # frames x freq
    freqs=np.fft.rfftfreq(n,1.0/SR)
    # mel-ish band edges
    mel=lambda f:2595*np.log10(1+f/700)
    edges=np.linspace(mel(20),mel(SR/2),NBANDS+1)
    hz=700*(10**(edges/2595)-1)
    bands=[]
    for i in range(NBANDS):
        m=(freqs>=hz[i])&(freqs<hz[i+1])
        bands.append(S[:,m].mean(axis=1) if m.any() else np.zeros(S.shape[0]))
    B=np.log1p(np.stack(bands,axis=1))  # frames x NBANDS
    return np.concatenate([B.mean(axis=0), B.std(axis=0)])  # 2*NBANDS
v=logmel_stats(x).astype(np.float64)
nrm=np.linalg.norm(v)+1e-12
v=v/nrm
rec={"model":model,"dim":int(v.size),"l2norm":round(float(np.linalg.norm(v)),6),
     "vector":[round(float(z),6) for z in v],
     "note":"melstats-v0 placeholder for LAION-CLAP/MuQ-MuLan; identical vector contract"}
with open(out,"w") as f: json.dump(rec,f)
print("embed ok: %s dim=%d |v|=%.4f"%(model,rec["dim"],rec["l2norm"]))
PY
rc=$?
if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
    log_error "embed failed to produce $OUT"
    register_output "$CONTEXT_FILE" "embed" "embedding" "$OUT" "json" '{"error":"embed_failed"}' "failed"
    return 1
fi
register_output "$CONTEXT_FILE" "embed" "embedding" "$OUT" "json" "{\"model\":\"$MODEL\",\"source_input\": \"$INPUT_FILE\"}" "completed"
log_info "embed completed"
return 0
