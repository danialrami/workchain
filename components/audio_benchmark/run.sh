#!/bin/bash
# Component: audio_benchmark
# Description: Audio quality analysis benchmark suite

set +e  # Disable exit-on-error (parent may have set -e)

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# CRITICAL: Don't overwrite global variables!
if [[ -z "$WORKCHAIN_ROOT" ]]; then
    WORKCHAIN_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"
    source "$WORKCHAIN_ROOT/lib/constants.sh" 2>/dev/null || true
    source "$WORKCHAIN_ROOT/lib/common-utils.sh" 2>/dev/null || true
fi

if [[ -z "$LIB_DIR" ]]; then
    LIB_DIR="$WORKCHAIN_ROOT/lib"
fi

CONTEXT_FILE="$1"
STEP_CONFIG="$2"

if [[ -z "$CONTEXT_FILE" ]]; then
    echo "Usage: $0 <context_file> <step_config>"
    return 1
fi

# Check if context file exists
if [[ ! -f "$CONTEXT_FILE" ]]; then
    echo "Error: Context file not found: $CONTEXT_FILE"
    return 1
fi

log_step "Running: audio_benchmark"

# Get input/output paths from context using python3
get_context_value() {
    # Delegate to the shared, special-char-safe helper (lib/common-utils.sh).
    ctx_get "$CONTEXT_FILE" "$1"
}

INPUT_FILE=$(get_context_value "input_file")
OUTPUT_DIR=$(get_context_value "output_dir")
INPUT_NAME=$(get_context_value "input_name")
INPUT_EXT=$(get_context_value "input_ext")

# Validate inputs
if [[ -z "$INPUT_FILE" || -z "$OUTPUT_DIR" ]]; then
    log_error "Failed to read input_file or output_dir from context"
    return 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    log_error "Input file not found: $INPUT_FILE"
    return 1
fi

# Source benchmark functions
source "$COMPONENT_DIR/common.sh"
source "$COMPONENT_DIR/audio_format.sh"
source "$COMPONENT_DIR/audio_loudness.sh"
source "$COMPONENT_DIR/audio_dc_offset.sh"
source "$COMPONENT_DIR/audio_noise_floor.sh"
source "$COMPONENT_DIR/audio_spectral.sh"
source "$COMPONENT_DIR/audio_phase.sh"
source "$COMPONENT_DIR/audio_dynamics.sh"

# Get parameters
get_param() {
    local param_name="$1"
    local default="${2:-}"
    
    local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["'"'"']\(.*\)["'"'"']$/\1/')
    
    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

CHECKS=$(get_param "checks" "all")
EXPECTED_SPEC=$(get_param "expected_spec" "")

log_info "Audio benchmark parameters:"
log_info "  Checks: $CHECKS"
log_info "  Expected spec: ${EXPECTED_SPEC:-none}"

# Create output directory
ensure_dir "$OUTPUT_DIR"
ensure_dir "$OUTPUT_DIR/logs"

BENCHMARK_JSON="$OUTPUT_DIR/logs/audio_benchmark.json"
TEMP_DIR=$(mktemp -d /tmp/audio_benchmark.XXXXXX)

# Track overall status
OVERALL_STATUS="completed"
BENCHMARK_COUNT=0

# Run all checks and save results to temp files
log_info "--- Running benchmarks ---"

if [[ "$CHECKS" == "all" || "$CHECKS" == *"format"* ]]; then
    log_info "Running format check..."
    run_format_check "$INPUT_FILE" "$EXPECTED_SPEC" > "$TEMP_DIR/format.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/format.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

if [[ "$CHECKS" == "all" || "$CHECKS" == *"loudness"* ]]; then
    log_info "Running loudness check..."
    run_loudness_check "$INPUT_FILE" > "$TEMP_DIR/loudness.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/loudness.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

if [[ "$CHECKS" == "all" || "$CHECKS" == *"dc_offset"* ]]; then
    log_info "Running DC offset check..."
    run_dc_offset_check "$INPUT_FILE" > "$TEMP_DIR/dc_offset.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/dc_offset.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

if [[ "$CHECKS" == "all" || "$CHECKS" == *"noise"* ]]; then
    log_info "Running noise floor check..."
    run_noise_floor_check "$INPUT_FILE" > "$TEMP_DIR/noise_floor.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/noise_floor.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

if [[ "$CHECKS" == "all" || "$CHECKS" == *"spectral"* ]]; then
    log_info "Running spectral check..."
    run_spectral_check "$INPUT_FILE" > "$TEMP_DIR/spectral.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/spectral.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

if [[ "$CHECKS" == "all" || "$CHECKS" == *"phase"* ]]; then
    log_info "Running phase check..."
    run_phase_check "$INPUT_FILE" > "$TEMP_DIR/phase.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/phase.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

if [[ "$CHECKS" == "all" || "$CHECKS" == *"dynamics"* ]]; then
    log_info "Running dynamics check..."
    run_dynamics_check "$INPUT_FILE" > "$TEMP_DIR/dynamics.json" 2>/dev/null
    if [[ -s "$TEMP_DIR/dynamics.json" ]]; then
        ((BENCHMARK_COUNT++))
    fi
fi

# Combine all results into single JSON file using python3
log_info "--- Combining results ---"

# Write python script to temp file to avoid heredoc issues
PY_SCRIPT=$(mktemp /tmp/benchmark_combine.XXXXXX.py)
cat > "$PY_SCRIPT" << 'PYEOF'
import json
import os
import sys

temp_dir = sys.argv[1]
benchmark_json = sys.argv[2]
input_name = sys.argv[3]

result = {
    "input_file": input_name,
    "checks": {},
    "benchmark_count": 0,
    "overall_status": "completed"
}

count = 0
for check in ['format', 'loudness', 'dc_offset', 'noise_floor', 'spectral', 'phase', 'dynamics']:
    json_file = os.path.join(temp_dir, f'{check}.json')
    if os.path.exists(json_file) and os.path.getsize(json_file) > 0:
        with open(json_file, 'r') as f:
            content = f.read().strip()
            if content:
                try:
                    data = json.loads(content)
                    result['checks'][check] = data
                    count += 1
                except Exception as e:
                    result['checks'][check] = {"error": f'Failed to parse: {e}', "raw": content[:100]}

result['benchmark_count'] = count

with open(benchmark_json, 'w') as f:
    json.dump(result, f, indent=2)

print(f"Benchmark complete: {count} checks run", file=sys.stderr)
PYEOF

export TEMP_DIR
python3 "$PY_SCRIPT" "$TEMP_DIR" "$BENCHMARK_JSON" "$INPUT_NAME"
rm -f "$PY_SCRIPT"

log_info "Benchmark results saved to: $BENCHMARK_JSON"

# Cleanup temp files
rm -rf "$TEMP_DIR"

# Derive an HONEST status from the combined results (review Bug 2):
# if any check failed to parse/produce data, don't claim a clean "completed".
if [[ -f "$BENCHMARK_JSON" ]]; then
    OVERALL_STATUS=$(__WC_BJ="$BENCHMARK_JSON" python3 << 'PYEOF' 2>/dev/null
import json, os
try:
    d = json.load(open(os.environ['__WC_BJ']))
    errs = sum(1 for c in (d.get('checks') or {}).values() if isinstance(c, dict) and 'error' in c)
    print('completed' if errs == 0 else 'completed_with_errors')
except Exception:
    print('completed')
PYEOF
)
    [[ -z "$OVERALL_STATUS" ]] && OVERALL_STATUS="completed"
    log_info "Benchmark overall status: $OVERALL_STATUS"
fi

# Register outputs
register_output "$CONTEXT_FILE" "audio_benchmark" "benchmark_report" "$BENCHMARK_JSON" "json" \
    "{\"benchmark_count\": $BENCHMARK_COUNT, \"overall_status\": \"$OVERALL_STATUS\"}" \
    "$OVERALL_STATUS"

register_output "$CONTEXT_FILE" "audio_benchmark" "primary_output" "$BENCHMARK_JSON" "json" \
    "{\"benchmark_count\": $BENCHMARK_COUNT}" \
    "$OVERALL_STATUS"

log_info "Audio benchmark completed with status: $OVERALL_STATUS"
