#!/bin/bash

# Step runner - executes individual components
# Manages input/output context and parameter passing

source "$(dirname "${BASH_SOURCE[0]}")/../lib/constants.sh"
source "$LIB_DIR/common-utils.sh"

: "${CONTEXT_FILE:=}"
: "${CURRENT_STEP:=}"

init_step_runner() {
    CONTEXT_FILE="$1"
    log_debug "Step runner initialized with context: $CONTEXT_FILE"
}

get_context_value() {
    local key="$1"
    
    if [[ -z "$CONTEXT_FILE" ]] || [[ ! -f "$CONTEXT_FILE" ]]; then
        echo ""
        return 1
    fi
    
    # Delegate to the shared, special-char-safe helper (lib/common-utils.sh).
    ctx_get "$CONTEXT_FILE" "$key"
}

set_context_value() {
    local key="$1"
    local value="$2"
    
    if [[ -z "$CONTEXT_FILE" ]]; then
        log_error "Context file not initialized"
        return 1
    fi
    
    __WC_CF="$CONTEXT_FILE" __WC_KEY="$key" __WC_VALUE="$value" python3 << 'PYEOF'
import json, os, sys
cf = os.environ['__WC_CF']
try:
    with open(cf) as f:
        ctx = json.load(f)
    keys = os.environ['__WC_KEY'].split('.')
    current = ctx
    for k in keys[:-1]:
        current = current.setdefault(k, {})
    current[keys[-1]] = os.environ['__WC_VALUE']
    with open(cf, 'w') as f:
        json.dump(ctx, f, indent=2)
    print('OK')
except Exception as e:
    print('Error: %s' % e, file=sys.stderr)
    sys.exit(1)
PYEOF
}

run_step() {
    local step_name="$1"
    local step_config="$2"
    local context_file="$3"
    
    CURRENT_STEP="$step_name"
    
    log_step "Running step: $step_name"
    
    local step_dir="$COMPONENTS_DIR/$step_name"
    
    if [[ ! -d "$step_dir" ]]; then
        log_error "Step directory not found: $step_dir"
        return 1
    fi
    
    if [[ ! -f "$step_dir/run.sh" ]]; then
        log_error "Step run script not found: $step_dir/run.sh"
        return 1
    fi
    
    local step_enabled=$(echo "$step_config" | grep -E "^\s*enabled:" | sed 's/.*enabled: *//' | tr -d ' ')
    if [[ "$step_enabled" == "false" ]]; then
        log_info "Step $step_name is disabled, skipping"
        return 0
    fi
    
    source "$step_dir/run.sh" "$context_file" "$step_config"
    local result=$?
    
    if [[ $result -eq 0 ]]; then
        log_info "Step $step_name completed successfully"
    else
        log_error "Step $step_name failed with exit code: $result"
    fi
    
    return $result
}

get_step_param() {
    local step_config="$1"
    local param_name="$2"
    local default_value="${3:-}"
    
    local value=$(echo "$step_config" | grep -E "^\s*${param_name}:" | sed "s/.*${param_name}: *//" | head -1)
    
    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default_value"
    fi
}

get_input_file() {
    get_context_value "input_file"
}

get_output_dir() {
    get_context_value "output_dir"
}

get_previous_step_output() {
    # The `steps` map is keyed on each step's EFFECTIVE id (its `id:`, defaulting to
    # the component name), so the argument is that step's id — the same key the engine
    # wrote the record under. For chains without explicit ids, id == component name, so
    # existing callers are unchanged.
    local step_name="$1"
    get_context_value "steps.${step_name}.output"
}
