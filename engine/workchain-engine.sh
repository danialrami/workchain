#!/bin/bash

# LUFS Workchain Engine
# YAML-driven signal-chain execution engine

set -e

source "$(dirname "${BASH_SOURCE[0]}")/../lib/constants.sh"
source "$LIB_DIR/common-utils.sh"

CHAIN_FILE=""
INPUT_FILE=""
OUTPUT_DIR=""
DEBUG=0

usage() {
    cat << EOF
Usage: $0 [OPTIONS] -c <chain_file> <input_file>

Options:
    -c, --chain <file>      Signal-chain YAML file (required)
    -o, --output <dir>      Output directory (default: ./output)
    -d, --debug             Enable debug logging
    -h, --help              Show this help message

Examples:
    $0 -c chains/standard.yaml input.wav
    $0 -c chains/standard.yaml -o ./results input.wav
EOF
    exit 1
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -c|--chain)
                CHAIN_FILE="$2"
                shift 2
                ;;
            -o|--output)
                OUTPUT_DIR="$2"
                shift 2
                ;;
            -d|--debug)
                DEBUG=1
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                if [[ -z "$INPUT_FILE" ]]; then
                    INPUT_FILE="$1"
                else
                    log_error "Unknown argument: $1"
                    usage
                fi
                shift
                ;;
        esac
    done

    if [[ -z "$CHAIN_FILE" ]]; then
        log_error "Chain file is required"
        usage
    fi

    if [[ -z "$INPUT_FILE" ]]; then
        log_error "Input file is required"
        usage
    fi

    if [[ ! -f "$INPUT_FILE" ]]; then
        log_error "Input file not found: $INPUT_FILE"
        exit 1
    fi

    if ! is_audio_file "$INPUT_FILE"; then
        log_error "Input file is not a supported audio format"
        exit 1
    fi

    if [[ ! -f "$CHAIN_FILE" ]]; then
        if [[ -f "$CHAINS_DIR/$CHAIN_FILE" ]]; then
            CHAIN_FILE="$CHAINS_DIR/$CHAIN_FILE"
        else
            log_error "Chain file not found: $CHAIN_FILE"
            exit 1
        fi
    fi

    if [[ -z "$OUTPUT_DIR" ]]; then
        OUTPUT_DIR="$(pwd)/output_$(timestamp)"
    fi
}

validate_chain() {
    log_info "Validating signal-chain: $CHAIN_FILE"

    local out
    if ! out=$(python3 "$WORKCHAIN_ROOT/lib/workchain_yaml.py" validate "$WORKCHAIN_ROOT" "$CHAIN_FILE"); then
        log_error "Chain validation failed"
        echo "$out" | python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
    for e in d.get('errors', []):
        print('  - ' + e)
except Exception:
    pass" 2>/dev/null | while IFS= read -r line; do log_error "$line"; done
        exit 1
    fi

    log_info "Chain validation passed"
}

initialize_context() {
    local audio_name=$(basename "$INPUT_FILE" | sed 's/\.[^.]*$//')
    local audio_ext=$(get_audio_extension "$INPUT_FILE")

    ensure_dir "$OUTPUT_DIR"

    CONTEXT_FILE="$OUTPUT_DIR/context.json"

    cat > "$CONTEXT_FILE" << EOF
{
  "input_file": "$INPUT_FILE",
  "input_name": "$audio_name",
  "input_ext": "$audio_ext",
  "output_dir": "$OUTPUT_DIR",
  "chain_file": "$CHAIN_FILE",
  "chain_name": "$(basename "$CHAIN_FILE" .yaml)",
  "start_time": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "globals": {},
  "steps": {}
}
EOF

    log_debug "Context initialized at: $CONTEXT_FILE"
}

load_globals() {
    python3 "$WORKCHAIN_ROOT/lib/workchain_yaml.py" parse "$CHAIN_FILE" 2>/dev/null |     CTX="$CONTEXT_FILE" python3 -c "
import json, os, sys
try:
    chain = json.load(sys.stdin) or {}
except Exception:
    chain = {}
g = chain.get('globals') or {}
ctx_file = os.environ['CTX']
ctx = json.load(open(ctx_file))
ctx['globals'] = g
json.dump(ctx, open(ctx_file, 'w'), indent=2)
" 2>/dev/null || true
}

run_steps() {
    local plan_file
    plan_file=$(mktemp "${TMPDIR:-/tmp}/wc-plan.XXXXXX")
    python3 "$WORKCHAIN_ROOT/lib/workchain_yaml.py" engine-plan "$WORKCHAIN_ROOT" "$CHAIN_FILE" > "$plan_file"
    if [[ ! -s "$plan_file" ]]; then
        log_warn "Chain has no steps to run"
        rm -f "$plan_file"
        return 0
    fi

    local tag name b64 b64params step_config step_params
    while IFS=$'	' read -r tag name b64 b64params <&3; do
        [[ -z "$tag" ]] && continue
        if [[ "$tag" == "SKIP" ]]; then
            log_info "Skipping disabled step: $name"
            continue
        fi
        step_config=$(printf '%s' "$b64" | base64 -d)
        # Resolved params as JSON (serialized by the single Python resolver). Empty for
        # older plans — process_step treats an empty blob as "no params to record".
        step_params=$(printf '%s' "$b64params" | base64 -d 2>/dev/null)
        if ! process_step "$name" "$step_config" "$step_params" </dev/null; then
            log_error "Chain halted: step '$name' failed"
            mark_chain_failed "$name"
            rm -f "$plan_file"
            exit 1
        fi
    done 3< "$plan_file"
    rm -f "$plan_file"
}

mark_chain_failed() {
    local failed_step="$1"
    __WC_CF="$CONTEXT_FILE" __WC_STEP="$failed_step" python3 << 'PYEOF' 2>/dev/null || true
import json, os, datetime
cf = os.environ['__WC_CF']
ctx = json.load(open(cf))
ctx['status'] = 'failed'
ctx['failed_step'] = os.environ['__WC_STEP']
ctx['end_time'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
json.dump(ctx, open(cf, 'w'), indent=2)
PYEOF
}

preflight_requirements() {
    local comp="$1"
    local missing
    missing=$(python3 "$WORKCHAIN_ROOT/lib/workchain_yaml.py" component-schema "$WORKCHAIN_ROOT" "$comp" 2>/dev/null | python3 -c "
import json, sys, shutil
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
cmds = (d.get('requirements') or {}).get('commands') or []
print(' '.join(c for c in cmds if shutil.which(c) is None))
" 2>/dev/null)

    if [[ -n "$missing" ]]; then
        log_error "Component '$comp' is missing required command(s): $missing"
        log_error "  Install the missing tool(s), then re-run — or disable this step in the chain."
        ctx_set_status "$CONTEXT_FILE" "$comp" "failed" "missing_dependency" "missing required command(s): $missing"
        return 1
    fi
    return 0
}

# Verifier hook: turn "ran (exit 0)" into "proven correct" (verifier P0).
# Runs the single enforcer (lib/workchain_verify.py) against the component's declared
# step.yaml `verify:` contract, using the just-written context.json. A component with
# no contract is reported "unverified" and passes (non-blocking); a declared contract
# that fails halts the chain. Independent of the heavy uv venv — stdlib + ffmpeg only.
verify_step() {
    local step_name="$1"
    local verifier="$WORKCHAIN_ROOT/lib/workchain_verify.py"
    [[ -f "$verifier" ]] || return 0  # back-compat: no verifier present → no-op

    local report rc
    report=$(python3 "$verifier" "$WORKCHAIN_ROOT" "$step_name" "$CONTEXT_FILE" 2>&1)
    rc=$?
    if [[ $rc -eq 0 ]]; then
        [[ -n "$report" ]] && echo "$report" | while IFS= read -r line; do log_debug "$line"; done
        return 0
    fi
    echo "$report" | while IFS= read -r line; do log_error "$line"; done
    return 1
}

# Preflight hook: turn "hope the deps are there" into "proven present" (the verified-IN half).
# Runs the single inbound enforcer (lib/workchain_preflight.py) against the component's declared
# step.yaml `requirements:` (commands / python / node / models / env) BEFORE run.sh, persisting a
# preflight report into context.json. Cheap by default (model sha256 only with --deep). If the lib
# isn't present (older checkout), fall back to the legacy commands-only preflight — back-compat.
preflight_step() {
    local step_name="$1"
    local preflight="$WORKCHAIN_ROOT/lib/workchain_preflight.py"
    if [[ ! -f "$preflight" ]]; then
        preflight_requirements "$step_name"; return $?
    fi
    local report rc
    report=$(python3 "$preflight" "$WORKCHAIN_ROOT" "$step_name" "$CONTEXT_FILE" 2>&1)
    rc=$?
    if [[ $rc -eq 0 ]]; then
        [[ -n "$report" ]] && echo "$report" | while IFS= read -r line; do log_debug "$line"; done
        return 0
    fi
    echo "$report" | while IFS= read -r line; do log_error "$line"; done
    return 1
}

# Persist a step's resolved params (JSON, from the single Python resolver) into
# context.json under steps.<name>.params, so the verifier can resolve numeric targets
# from what the step ACTUALLY ran with — not a schema default or a globals alias. The
# JSON is loaded, never regex-parsed (single source of truth stays in workchain_yaml.py).
# Runs before run.sh; register_output preserves existing step keys, so params survive.
record_step_params() {
    local step_name="$1"
    local params_json="$2"
    [[ -z "$params_json" ]] && return 0
    __WC_CF="$CONTEXT_FILE" __WC_STEP="$step_name" __WC_PJSON="$params_json" python3 << 'PYEOF' 2>/dev/null || true
import json, os
cf = os.environ["__WC_CF"]; step = os.environ["__WC_STEP"]
try:
    params = json.loads(os.environ.get("__WC_PJSON") or "{}")
except Exception:
    params = {}
if not isinstance(params, dict):
    params = {}
with open(cf) as f:
    ctx = json.load(f)
ctx.setdefault("steps", {}).setdefault(step, {})["params"] = params
with open(cf, "w") as f:
    json.dump(ctx, f, indent=2)
PYEOF
}

process_step() {
    local step_name="$1"
    local step_config="$2"
    local step_params="${3:-}"

    local step_enabled=$(echo "$step_config" | grep -E "^\s*enabled:" | sed 's/.*enabled: *//' | tr -d ' 
')
    if [[ "$step_enabled" == "false" ]]; then
        log_info "Skipping disabled step: $step_name"
        return 0
    fi

    # Name the file in every step line. Grepping a run log for a filename should show
    # that file's whole journey through the chain — which is the entire point of asking
    # "what got done to what, when".
    #
    # ${VAR##*/} and $SECONDS are bash builtins: no `basename` fork, no `date` fork. At
    # 259k files x 5 steps, anything that forks per step is not free.
    local __step_t0=$SECONDS
    local __in_name="${INPUT_FILE##*/}"
    log_step "Executing step: $step_name  ←  $__in_name"
    runlog "FILE " "step=$step_name file=$INPUT_FILE"

    if [[ ! -d "$COMPONENTS_DIR/$step_name" ]]; then
        log_error "Component not found: $step_name"
        return 1
    fi

    # Record resolved params FIRST. Preflight's `when:` requirement guards resolve from
    # steps.<name>.params, so the params must already be in context.json when preflight
    # reads it. Ordered the other way, every guard hit its fail-closed path and a
    # component's light code path was still forced to satisfy its heavy dependencies —
    # e.g. a component whose remote backend demands a heavy venv it never actually loads.
    # The verifier reads the same key post-run, so one write serves both bookends.
    record_step_params "$step_name" "$step_params"

    if ! preflight_step "$step_name"; then
        log_error "Step failed dependency preflight: $step_name"
        return 1
    fi

    source "$ENGINE_DIR/step-runner.sh"
    init_step_runner "$CONTEXT_FILE"

    if [[ ! -f "$COMPONENTS_DIR/$step_name/run.sh" ]]; then
        log_error "Component run script not found: $step_name/run.sh"
        return 1
    fi

    if ! source "$COMPONENTS_DIR/$step_name/run.sh" "$CONTEXT_FILE" "$step_config"; then
        log_error "Step failed: $step_name"
        return 1
    fi

    # Turn "ran" into "proven": enforce the component's declared contract before its
    # output is allowed to become the next step's input. Honest failure beats a
    # silently-wrong output flowing downstream.
    if ! verify_step "$step_name"; then
        log_error "Step failed verification: $step_name"
        return 1
    fi

    # Update input_file to point to this step's primary output
    update_input_file "$step_name"

    log_info "Step completed: $step_name  ($((SECONDS - __step_t0))s)  ←  $__in_name"
}

update_input_file() {
    local step_name="$1"

    local primary_output
    primary_output=$(__WC_CF="$CONTEXT_FILE" __WC_STEP="$step_name" python3 << 'PYEOF' 2>/dev/null
import json, os
with open(os.environ['__WC_CF']) as f:
    ctx = json.load(f)
step_data = ctx.get('steps', {}).get(os.environ['__WC_STEP'], {})
primary = (step_data.get('outputs', {}) or {}).get('primary_output', {})
print(primary.get('path', '') if isinstance(primary, dict) else '')
PYEOF
)

    if [[ -n "$primary_output" && -f "$primary_output" ]]; then
        __WC_CF="$CONTEXT_FILE" __WC_PO="$primary_output" python3 << 'PYEOF' 2>/dev/null
import json, os
cf = os.environ['__WC_CF']; po = os.environ['__WC_PO']
with open(cf) as f:
    ctx = json.load(f)
ctx['input_file'] = po
b = os.path.basename(po)
ctx['input_name'] = os.path.splitext(b)[0]
ctx['input_ext'] = os.path.splitext(b)[1].lstrip('.')
with open(cf, 'w') as f:
    json.dump(ctx, f, indent=2)
PYEOF
        log_debug "Updated input_file to: $primary_output"
    fi
}

finalize() {
    local end_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    __WC_CF="$CONTEXT_FILE" __WC_END="$end_time" python3 << 'PYEOF' 2>/dev/null
import json, os
cf = os.environ['__WC_CF']
with open(cf) as f:
    ctx = json.load(f)
ctx['end_time'] = os.environ['__WC_END']
ctx['status'] = 'completed'
with open(cf, 'w') as f:
    json.dump(ctx, f, indent=2)
PYEOF

    log_info "Workchain completed successfully"
    log_info "Output directory: $OUTPUT_DIR"
    log_info "Context saved to: $CONTEXT_FILE"
}

main() {
    parse_arguments "$@"

    # Open (or INHERIT) a run log. When a batch driver has already exported
    # $WORKCHAIN_RUNLOG, runlog_open adopts it, so a 259k-file ingest produces one log for
    # the batch rather than 259k logs that instantly evict each other under retention.
    runlog_open "${CHAIN_FILE##*/}" "chain=$CHAIN_FILE" "input=$INPUT_FILE" "output=$OUTPUT_DIR"

    log_info "=== LUFS Workchain Engine ==="
    log_info "Chain: $CHAIN_FILE"
    log_info "Input: $INPUT_FILE"
    log_info "Output: $OUTPUT_DIR"
    [[ -n "${WORKCHAIN_RUNLOG:-}" ]] && log_info "Run log: $WORKCHAIN_RUNLOG"

    validate_chain
    initialize_context
    load_globals
    run_steps
    finalize
}

main "$@"
