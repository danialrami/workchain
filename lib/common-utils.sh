#!/bin/bash

# Common utilities for audio workchain v2

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Run log ───────────────────────────────────────────────────────────────────
# When $WORKCHAIN_RUNLOG names a file, every log_* line is ALSO appended to it —
# uncoloured, with a full ISO-8601 local timestamp — so a run log can answer "what was
# done to which file, when" long after the terminal is gone. Retention is handled by
# lib/workchain_runlog.py (newest 25 by default); this side only appends.
#
# Appending is a bare `printf >>`: NO subprocess per line. An ingest of 259k files emits
# millions of log lines, and a python (or even an extra `date`) call per line would cost
# more than the work being logged. Each log_* takes ONE `date` reading and slices both the
# short console stamp and the full log stamp out of it, so the fork count per log line is
# exactly what it was before run logs existed.
_wc_runlog() {   # $1=level  $2=iso timestamp  $3=message
    [[ -n "${WORKCHAIN_RUNLOG:-}" ]] || return 0
    printf '%s %-5s %s\n' "$2" "$1" "$3" >> "$WORKCHAIN_RUNLOG" 2>/dev/null || true
}

# Append a line to the run log WITHOUT printing it to the console. For detail that is
# worth keeping but would drown a terminal at library scale.
runlog() {   # $1=level  $2=message
    [[ -n "${WORKCHAIN_RUNLOG:-}" ]] || return 0
    printf '%s %-5s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "${1:-LOG}" "$2" \
        >> "$WORKCHAIN_RUNLOG" 2>/dev/null || true
}

# Start a run log and export it. $1 = label, remaining args = key=value metadata.
#
# INHERITANCE IS THE POINT: if $WORKCHAIN_RUNLOG is already set we adopt it and return.
# all 259k engine invocations append to that single file. Without this, each invocation
# would open its own log, retention would evict everything within seconds, and the feature
# would be worse than useless — it would actively destroy the evidence.
runlog_open() {
    [[ "${WORKCHAIN_RUNLOG_DISABLE:-0}" == "1" ]] && return 0
    [[ -n "${WORKCHAIN_RUNLOG:-}" ]] && return 0      # inherit the parent run's log
    local script="${WORKCHAIN_ROOT:-.}/lib/workchain_runlog.py"
    [[ -f "$script" ]] || return 0                     # older checkout: no-op, back-compat
    local label="${1:-run}"; shift || true
    local meta_json="{}" k v
    if [[ $# -gt 0 ]]; then
        meta_json=$(__WC_META_ARGS="$*" python3 -c '
import json, os, shlex
out = {}
for tok in shlex.split(os.environ.get("__WC_META_ARGS", "")):
    if "=" in tok:
        k, v = tok.split("=", 1); out[k] = v
print(json.dumps(out))' 2>/dev/null || echo "{}")
    fi
    local path
    path=$(python3 "$script" open --label "$label" --meta "$meta_json" 2>/dev/null)
    if [[ -n "$path" ]]; then
        export WORKCHAIN_RUNLOG="$path"
    fi
}

log_info() {
    local __b; __b=$(date '+%Y-%m-%dT%H:%M:%S%z|%H:%M:%S')
    _wc_runlog "INFO" "${__b%|*}" "$1"
    echo -e "${GREEN}[${__b#*|}]${NC} $1"
}

log_warn() {
    local __b; __b=$(date '+%Y-%m-%dT%H:%M:%S%z|%H:%M:%S')
    _wc_runlog "WARN" "${__b%|*}" "$1"
    echo -e "${YELLOW}[${__b#*|}] WARNING:${NC} $1"
}

log_error() {
    local __b; __b=$(date '+%Y-%m-%dT%H:%M:%S%z|%H:%M:%S')
    _wc_runlog "ERROR" "${__b%|*}" "$1"
    echo -e "${RED}[${__b#*|}] ERROR:${NC} $1" >&2
}

# NB: debug detail goes to the run log ALWAYS, console only when DEBUG=1. That asymmetry is
# deliberate — it is how the run log gets genuinely verbose (full verifier reports, per-step
# contract results) without turning the terminal into a firehose.
log_debug() {
    local __b; __b=$(date '+%Y-%m-%dT%H:%M:%S%z|%H:%M:%S')
    _wc_runlog "DEBUG" "${__b%|*}" "$1"
    if [[ "$DEBUG" == "1" ]]; then
        echo -e "${BLUE}[${__b#*|}] DEBUG:${NC} $1"
    fi
}

log_step() {
    local __b; __b=$(date '+%Y-%m-%dT%H:%M:%S%z|%H:%M:%S')
    _wc_runlog "STEP" "${__b%|*}" "$1"
    echo -e "${CYAN}[${__b#*|}] STEP:${NC} $1"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

error_exit() {
    log_error "$1"
    exit 1
}

ensure_dir() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir" || error_exit "Failed to create directory: $dir"
    fi
}

is_audio_file() {
    local file="$1"
    local ext="${file##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    for valid_ext in "${SUPPORTED_AUDIO_EXTENSIONS[@]}"; do
        if [[ "$ext" == "$valid_ext" ]]; then
            return 0
        fi
    done
    return 1
}

get_audio_extension() {
    local file="$1"
    echo "${file##*.}" | tr '[:upper:]' '[:lower:]'
}

get_filename() {
    local file="$1"
    echo "${file%.*}"
}

get_basename() {
    local file="$1"
    basename "$file"
}

get_dirname() {
    local file="$1"
    dirname "$file"
}

timestamp() {
    date +"%Y%m%d_%H%M%S"
}

# ─────────────────────────────────────────────────────────────────────────────
# Safe context.json access helpers.
#
# Every value (paths, keys) is passed to Python via ENVIRONMENT VARIABLES inside a
# QUOTED heredoc (<< 'PYEOF'), never shell-interpolated into the Python source. This
# makes them robust to apostrophes, spaces, quotes, and backslashes in file paths —
# e.g. output dirs derived from track names like "Here's The Song" or "Don't Stop".
# (Shell-interpolated `python3 -c "...open('$CONTEXT_FILE')..."` breaks on a single
#  quote in the path; these helpers are the fix. See docs/nyquist-exploration/.)
# ─────────────────────────────────────────────────────────────────────────────

# ctx_get <context_file> <dotted.key> → scalar value (json for list/dict), empty if missing.
ctx_get() {
    local cf="$1" key="$2"
    [[ -f "$cf" ]] || { echo ""; return 1; }
    __WC_CF="$cf" __WC_KEY="$key" python3 << 'PYEOF' 2>/dev/null
import json, os, sys
try:
    with open(os.environ['__WC_CF']) as f:
        ctx = json.load(f)
    v = ctx
    for k in os.environ['__WC_KEY'].split('.'):
        if isinstance(v, dict) and k in v:
            v = v[k]
        else:
            print(''); sys.exit(0)
    print(json.dumps(v) if isinstance(v, (dict, list)) else v)
except Exception:
    print('')
PYEOF
}

# ctx_get_abs <context_file> <dotted.key> → os.path.abspath(value), empty if missing.
ctx_get_abs() {
    local cf="$1" key="$2"
    [[ -f "$cf" ]] || { echo ""; return 1; }
    __WC_CF="$cf" __WC_KEY="$key" python3 << 'PYEOF' 2>/dev/null
import json, os
try:
    with open(os.environ['__WC_CF']) as f:
        ctx = json.load(f)
    v = ctx
    for k in os.environ['__WC_KEY'].split('.'):
        v = v[k] if isinstance(v, dict) and k in v else ''
    print(os.path.abspath(v) if v else '')
except Exception:
    print('')
PYEOF
}

# ctx_get_json <context_file> <dotted.key> → json.dumps(value or {}).
ctx_get_json() {
    local cf="$1" key="$2"
    [[ -f "$cf" ]] || { echo "{}"; return 1; }
    __WC_CF="$cf" __WC_KEY="$key" python3 << 'PYEOF' 2>/dev/null
import json, os
try:
    with open(os.environ['__WC_CF']) as f:
        ctx = json.load(f)
    v = ctx
    for k in os.environ['__WC_KEY'].split('.'):
        v = v.get(k, {}) if isinstance(v, dict) else {}
    print(json.dumps(v))
except Exception:
    print('{}')
PYEOF
}

# get_global <context_file> <key> <default> → globals.<key> or default.
get_global() {
    local v
    v=$(ctx_get "$1" "globals.$2")
    if [[ -n "$v" && "$v" != "null" ]]; then echo "$v"; else echo "$3"; fi
}

# ctx_set_status <context_file> <component> <status> [reason] [error]
ctx_set_status() {
    local cf="$1" comp="$2" status="$3" reason="${4:-}" error="${5:-}"
    __WC_CF="$cf" __WC_COMP="$comp" __WC_ST="$status" __WC_RE="$reason" __WC_ER="$error" python3 << 'PYEOF' 2>/dev/null
import json, os
cf = os.environ['__WC_CF']
try:
    with open(cf) as f: ctx = json.load(f)
except Exception:
    ctx = {}
ctx.setdefault('steps', {})
entry = {'status': os.environ['__WC_ST']}
if os.environ.get('__WC_RE'): entry['reason'] = os.environ['__WC_RE']
if os.environ.get('__WC_ER'): entry['error'] = os.environ['__WC_ER']
ctx['steps'][os.environ['__WC_COMP']] = entry
with open(cf, 'w') as f: json.dump(ctx, f, indent=2)
PYEOF
}


# Register an output for a component
# Usage: register_output <context_file> <component_name> <output_name> <output_path> [type] [metadata_json] [status]
#
# Registers an output in the standardized outputs schema (see step.yaml outputs schema)
# Also sets backward-compatible fields (output, output_dir) in context
#
# Args:
#   context_file: Path to context.json
#   component_name: Name of the component (e.g., 'normalization')
#   output_name: Unique identifier for this output (e.g., 'primary_output', 'metadata')
#   output_path: Path to the output file/directory (can be empty for non-file types)
#   type: Output type - file, directory, json, number, string, boolean (default: file)
#   metadata_json: Optional JSON string with additional metadata (default: {})
#   status: Optional status to set for the component (e.g., 'completed', 'skipped')
#
# The function reads the component's step.yaml to extract:
#   - description: Human-readable description of the output
#   - path_template: Relative path template (e.g., "artwork/{input_name}_artwork.png")
#
# Example:
#   register_output "$CONTEXT_FILE" "normalization" "primary_output" "$NORMALIZED_FILE" "file" \
#     "{\"target_lufs\": $TARGET_LUFS, \"measured_lufs\": \"$FINAL_LUFS\"}" "completed"
register_output() {
    local context_file="$1"
    local component_name="$2"
    local output_name="$3"
    local output_path="$4"
    local output_type="${5:-file}"
    # NOTE: do NOT write this as ${6:-{}} — bash ends the parameter expansion at the
    # FIRST '}', so a supplied JSON object comes back with a stray '}' appended
    # ('{"a":1}' -> '{"a":1}}'). json.loads then throws, the bare `except` below
    # swallows it, and the metadata vanishes silently. That meant EVERY component
    # passing metadata (catalog's catalog_number/hash included) was registering none
    # of it. Assign, then default.
    local metadata_json="$6"
    [[ -z "$metadata_json" ]] && metadata_json='{}'
    local status="${7:-}"

    if [[ -z "$context_file" ]] || [[ -z "$component_name" ]] || [[ -z "$output_name" ]]; then
        log_error "register_output: Missing required arguments"
        return 1
    fi

    # Pass all values via env vars into a QUOTED heredoc — robust to apostrophes / quotes /
    # backslashes / spaces in output paths and metadata (review: special-char path bug).
    export WORKCHAIN_ROOT
    __WC_CF="$context_file" __WC_COMP="$component_name" __WC_NAME="$output_name" \
    __WC_PATH="$output_path" __WC_TYPE="$output_type" __WC_META="$metadata_json" __WC_STATUS="$status" \
    python3 << 'PYEOF'
import json
import os
import re
import sys

ctx_file = os.environ['__WC_CF']
comp = os.environ['__WC_COMP']
name = os.environ['__WC_NAME']
path = os.environ['__WC_PATH']
otype = os.environ['__WC_TYPE']
metadata_str = os.environ.get('__WC_META') or '{}'
status = os.environ['__WC_STATUS'] if os.environ.get('__WC_STATUS') else None

# Parse metadata if provided.
# Malformed metadata is reported LOUDLY rather than swallowed. A bare `except:
# metadata = {}` here is how the ${6:-{}} expansion bug above stayed invisible:
# every component's metadata was being discarded while every step still exited 0.
# Registration still proceeds (the output path is the important part) but the
# operator — human or agent — is told the metadata was lost.
try:
    metadata = json.loads(metadata_str) if metadata_str and metadata_str != '{}' else {}
except Exception as e:
    sys.stderr.write(
        "register_output: WARNING — metadata for %s.%s is not valid JSON and was "
        "DISCARDED (%s): %r\n" % (comp, name, e, metadata_str))
    metadata = {}

# Try to read step.yaml to get description and path_template
description = ""
path_template = ""

# Use WORKCHAIN_ROOT environment variable to find step.yaml
workchain_root = os.environ.get('WORKCHAIN_ROOT', '')
if workchain_root:
    step_yaml_path = os.path.join(workchain_root, 'components', comp, 'step.yaml')
else:
    # Fallback to old behavior (relative to context file)
    step_yaml_path = os.path.join(os.path.dirname(ctx_file), '..', 'components', comp, 'step.yaml')

if os.path.exists(step_yaml_path):
    try:
        # Simple YAML parsing for outputs schema (avoid PyYAML dependency)
        with open(step_yaml_path, 'r') as sf:
            content = sf.read()

        # Find the outputs section
        in_outputs = False
        in_items = False
        in_target_item = False

        for line in content.split('\n'):
            stripped = line.strip()

            # Skip comments and empty lines
            if not stripped or stripped.startswith('#'):
                continue

            # Check for outputs: section
            if stripped.startswith('outputs:'):
                in_outputs = True
                continue

            if in_outputs:
                # Check for schema_version or description at outputs level
                if stripped.startswith('items:'):
                    in_items = True
                    continue

                if in_items:
                    # Check if this is a list item (starts with '-')
                    if stripped.startswith('-') or (line and line[0] == ' ' and '-' in line):
                        # New item - check if it's our target
                        name_match = re.search(r'name:\s*(\S+)', line)
                        if name_match:
                            item_name = name_match.group(1)
                            if item_name == name:
                                in_target_item = True
                                current_indent = len(line) - len(line.lstrip())
                            else:
                                in_target_item = False

                    if in_target_item:
                        # Extract description
                        desc_match = re.search(r'description:\s*(.+)', line)
                        if desc_match and (not description):
                            description = desc_match.group(1).strip().strip('"').strip("'")

                        # Extract path_template
                        template_match = re.search(r'path_template:\s*(.+)', line)
                        if template_match:
                            path_template = template_match.group(1).strip().strip('"').strip("'")

                        # If we hit a line with less indent that's not a comment, we're done
                        if line.strip() and line[0] != ' ' and not line.strip().startswith('#'):
                            break
    except Exception as e:
        print(f"Warning: Could not parse step.yaml: {e}")

try:
    with open(ctx_file, 'r') as f:
        ctx = json.load(f)
except Exception as e:
    print(f"Error reading context: {e}")
    exit(1)

# Ensure steps dict exists
if 'steps' not in ctx:
    ctx['steps'] = {}

# Ensure component entry exists
if comp not in ctx['steps']:
    ctx['steps'][comp] = {}

# Ensure outputs dict exists
if 'outputs' not in ctx['steps'][comp]:
    ctx['steps'][comp]['outputs'] = {}

# Register this output
output_entry = {
    'path': path,
    'type': otype,
    'exists': os.path.exists(path) if path else False
}

# Add description if found
if description:
    output_entry['description'] = description

# Add path_template if found
if path_template:
    output_entry['path_template'] = path_template

# Merge metadata if provided
if metadata and isinstance(metadata, dict):
    output_entry.update(metadata)

ctx['steps'][comp]['outputs'][name] = output_entry

# For backward compatibility, set 'output' field if not set and type is file/directory
if otype in ['file', 'directory'] and 'output' not in ctx['steps'][comp]:
    ctx['steps'][comp]['output'] = path

# Set output_dir based on output type
if otype == 'file' and path:
    output_dir = os.path.dirname(path)
    if 'output_dir' not in ctx['steps'][comp]:
        ctx['steps'][comp]['output_dir'] = output_dir
elif otype == 'directory' and path:
    if 'output_dir' not in ctx['steps'][comp]:
        ctx['steps'][comp]['output_dir'] = path

# Update status if provided
if status:
    ctx['steps'][comp]['status'] = status

with open(ctx_file, 'w') as f:
    json.dump(ctx, f, indent=2)

print(f"Registered output: {comp}.{name} -> {path} (type: {otype})", file=sys.stderr)
PYEOF
}

