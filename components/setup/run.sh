
# Setup component - Prerequisite checker only
# Venv and deps are managed by `uv sync` at the project level

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh"
    source "$WORKCHAIN_ROOT/lib/common-utils.sh"
fi

CONTEXT_FILE="$1"
STEP_CONFIG="$2"

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

log_step "Running: setup"

get_param() {
    local param_name="$1"
    local default="${2:-}"

    local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["\'']\(.*\)["\'']$/\1/')

    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

CHECK_ONLY=$(get_param "check_only" "false")
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)
SETUP_JSON="$OUTPUT_DIR/logs/setup.json"
ensure_dir "$(dirname "$SETUP_JSON")"

write_environment_record() {
    local status="$1"
    STATUS="$status" FAILURES="$FAILURES" CHECK_ONLY="$CHECK_ONLY" OUT="$SETUP_JSON" python3 <<'PY'
import json, os
record = {
    "status": os.environ["STATUS"],
    "failures": int(os.environ["FAILURES"]),
    "check_only": os.environ["CHECK_ONLY"] == "true",
}
with open(os.environ["OUT"], "w") as f:
    json.dump(record, f, indent=2)
PY
}

FAILURES=0

if ! command_exists python3; then
    log_error "Python 3 is not installed. Please install Python 3."
    FAILURES=$((FAILURES + 1))
else
    log_info "  Python 3 found: $(python3 --version 2>&1)"
fi

if ! command_exists uv; then
    log_error "uv is not installed. Run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    FAILURES=$((FAILURES + 1))
else
    log_info "  uv found: $(uv --version 2>&1)"
    if [[ "$CHECK_ONLY" != "true" ]] && [[ -f "$WORKCHAIN_ROOT/pyproject.toml" ]]; then
        log_info "  Running uv sync to ensure dependencies are installed..."
        if (cd "$WORKCHAIN_ROOT" && uv sync 2>&1); then
            log_info "  Dependencies installed successfully"
        else
            log_error "uv sync failed. Run 'uv lock' to update lockfile"
            FAILURES=$((FAILURES + 1))
        fi
    fi
fi

if ! command_exists ffmpeg; then
    log_warn "FFmpeg not found. Audio normalization will fail without FFmpeg."
    log_warn "Install with: brew install ffmpeg (macOS) or sudo apt install ffmpeg (Linux)"
    FAILURES=$((FAILURES + 1))
else
    log_info "  FFmpeg found: $(ffmpeg -version 2>&1 | head -1)"
fi

if ! command_exists npm; then
    log_warn "npm not found. Artwork generation may fail without jdenticon."
    log_warn "Install with: brew install node (macOS)"
else
    log_info "  npm found: $(npm --version)"
fi

if ! command_exists node && command_exists npm; then
    log_info "Installing Node.js dependencies..."
    if [[ -f "$WORKCHAIN_ROOT/package.json" ]]; then
        (cd "$WORKCHAIN_ROOT" && npm install 2>&1 | tail -3)
        log_info "  Node dependencies installed"
    fi
fi

if [[ $FAILURES -gt 0 ]]; then
    log_error "Setup completed with $FAILURES error(s)"
    write_environment_record "failed"
    register_output "$CONTEXT_FILE" "setup" "environment" "$SETUP_JSON" "json" \
        "{\"status\":\"failed\",\"failures\":$FAILURES}" \
        "failed"
    return 1
fi

log_info "All prerequisites met"
write_environment_record "ready"
register_output "$CONTEXT_FILE" "setup" "environment" "$SETUP_JSON" "json" \
    "{\"status\":\"ready\",\"failures\":$FAILURES}" \
    "completed"

return 0
