# embed_clap — LAION-CLAP embedding, one contract, two backends (heavy local / thin remote)
#
#   local  : $COMPONENT_DIR/.venv + clap_embed.py — loads the ~2GB checkpoint per file.
#   remote : clap_remote.py — decodes to 48k mono f32 and POSTs to a resident-model
#            serve-embed endpoint. stdlib + ffmpeg only; no venv, no torch, no checkpoint.
#   auto   : remote, falling back to local LOUDLY if the endpoint is unusable.
#
# Whichever serves, the record stamps `served_by` — a silent degradation is the one
# outcome this component will not produce.
COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi
CONTEXT_FILE="$1"; STEP_CONFIG="$2"
[[ -z "$CONTEXT_FILE" ]] && { echo "usage: $0 <context> <config>"; return 1; }
log_step "Running: embed_clap"
INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
INPUT_NAME=$(ctx_get "$CONTEXT_FILE" input_name)
OUT="$OUTPUT_DIR/archive/${INPUT_NAME}.embedding.json"
ensure_dir "$(dirname "$OUT")"

# step_param <key> <default> — same single-line YAML shape the other components parse.
step_param() {
    local key="$1" def="$2" val
    val=$(echo "$STEP_CONFIG" | grep -E "^[[:space:]]+${key}:" | sed "s/.*${key}: *//" | head -1 \
          | tr -d ' "')
    [[ -z "$val" ]] && val="$def"
    echo "$val"
}

MODEL=$(step_param model "laion-clap-630k")
BACKEND=$(step_param backend "local")
ENDPOINT=$(step_param endpoint "")
TIMEOUT_S=$(step_param timeout_s "120")
RETRIES=$(step_param retries "2")
[[ -z "$ENDPOINT" ]] && ENDPOINT="${EMBED_CLAP_ENDPOINT:-}"

run_local() {
    local venv_py="$COMPONENT_DIR/.venv/bin/python"
    if [[ ! -x "$venv_py" ]]; then
        log_error "embed_clap local backend not provisioned — run: (cd $COMPONENT_DIR && bash provision.sh)"
        return 1
    fi
    "$venv_py" "$COMPONENT_DIR/clap_embed.py" "$INPUT_FILE" "$OUT" "$MODEL"
}

run_remote() {
    if [[ -z "$ENDPOINT" ]]; then
        log_error "embed_clap backend '$BACKEND' needs an endpoint — set the step's \`endpoint\` param or \$EMBED_CLAP_ENDPOINT (e.g. http://127.0.0.1:8770)"
        return 1
    fi
    # Deliberately python3, not the venv: the remote path must work on a host that has no
    # torch and no checkpoint. That is the entire benefit.
    python3 "$COMPONENT_DIR/clap_remote.py" "$INPUT_FILE" "$OUT" "$MODEL" "$ENDPOINT" "$TIMEOUT_S" "$RETRIES"
}

rc=1
case "$BACKEND" in
    local)
        run_local; rc=$?
        ;;
    remote)
        run_remote; rc=$?
        ;;
    auto)
        run_remote
        rc=$?
        if [[ $rc -ne 0 ]]; then
            # LOUD, never silent. A quiet fallback to the slow path is how a week of
            # 2GB-per-file reloads goes unnoticed. If you want this to be fatal instead,
            # use backend: remote.
            log_warn "embed_clap: remote backend FAILED at '${ENDPOINT:-<unset>}' — falling back to the LOCAL checkpoint (slow path, ~2GB load for this file). Fix the endpoint or set backend: remote to make this fatal."
            run_local; rc=$?
        fi
        ;;
    *)
        log_error "embed_clap: unknown backend '$BACKEND' (expected local|remote|auto)"
        rc=2
        ;;
esac

if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
    log_error "embed_clap failed to produce $OUT (backend=$BACKEND)"
    register_output "$CONTEXT_FILE" "embed_clap" "embedding" "$OUT" "json" \
        "{\"error\":\"clap_failed\",\"backend\":\"$BACKEND\"}" "failed"
    return 1
fi

# ctx_get is the special-char-safe JSON reader (env-var injection into a quoted heredoc);
# it works on ANY json file, not just the context. Never shell-interpolate these paths —
# the sample library is full of apostrophes and spaces.
SERVED_BY=$(ctx_get "$OUT" served_by)
[[ -z "$SERVED_BY" ]] && SERVED_BY="$BACKEND"
register_output "$CONTEXT_FILE" "embed_clap" "embedding" "$OUT" "json" \
    "{\"model\":\"$MODEL\",\"backend\":\"$BACKEND\",\"served_by\":\"$SERVED_BY\",\"source_input\": \"$INPUT_FILE\"}" \
    "completed"
log_info "embed_clap completed (served_by=$SERVED_BY)"
return 0
