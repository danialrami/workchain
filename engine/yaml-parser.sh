#!/bin/bash

# YAML Parser for signal-chain files
# Provides functions to read and parse YAML files

source "$(dirname "${BASH_SOURCE[0]}")/../lib/constants.sh"
source "$LIB_DIR/common-utils.sh"

yaml_get_value() {
    local yaml_file="$1"
    local key="$2"
    
    if [[ ! -f "$yaml_file" ]]; then
        echo ""
        return 1
    fi
    
    local value=$(grep -E "^${key}:" "$yaml_file" | head -1 | sed 's/^[^:]*: *//' | sed 's/^["'\'']\(.*\)["'\'']$/\1/')
    echo "$value"
}

yaml_has_key() {
    local yaml_file="$1"
    local key="$2"
    
    grep -qE "^${key}:" "$yaml_file"
}

yaml_get_array() {
    local yaml_file="$1"
    local key="$2"
    local in_array=0
    local indent=""
    
    while IFS= read -r line; do
        if [[ "$line" =~ ^${key}:[[:space:]]*$ ]]; then
            in_array=1
            # Legacy dead-code extraction of a key-line prefix; not a clean ${//} replacement.
            # shellcheck disable=SC2001
            indent=$(echo "$line" | sed 's/\(.*\)[^:].*/\1/')
            continue
        fi
        
        if [[ $in_array -eq 1 ]]; then
            if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+(.+) ]]; then
                # Strips a surrounding single/double quote pair; not a clean ${//} replacement.
                # shellcheck disable=SC2001
                echo "${BASH_REMATCH[1]}" | sed 's/^["'\'']\(.*\)["'\'']$/\1/'
            elif [[ "$line" =~ ^[[:space:]]* ]]; then
                continue
            else
                break
            fi
        fi
    done < "$yaml_file"
}

yaml_get_list_items() {
    local yaml_file="$1"
    local key="$2"
    local in_list=0
    
    while IFS= read -r line; do
        if [[ "$line" =~ ^${key}:[[:space:]]*$ ]]; then
            in_list=1
            continue
        fi
        
        if [[ $in_list -eq 1 ]]; then
            if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+(.+) ]]; then
                echo "${BASH_REMATCH[1]}"
            elif [[ -z "$line" ]]; then
                break
            elif [[ "$line" =~ ^[[:space:]] ]]; then
                continue
            else
                break
            fi
        fi
    done < "$yaml_file"
}

yaml_get_step() {
    local yaml_file="$1"
    local step_name="$2"
    local in_step=0
    local step_indent=0
    
    while IFS= read -r line; do
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*name:[[:space:]]*(.+)$ ]]; then
            if [[ "${BASH_REMATCH[1]}" == "$step_name" ]]; then
                in_step=1
                step_indent="${line%%[! ]*}"
                continue
            fi
        elif [[ $in_step -eq 1 ]]; then
            if [[ "$line" =~ ^[[:space:]]*[^[:space:]] ]]; then
                local line_indent="${line%%[! ]*}"
                if [[ ${#line_indent} -le ${#step_indent} ]]; then
                    break
                fi
            fi
            echo "$line"
        fi
    done < "$yaml_file"
}

yaml_validate_chain() {
    local chain_file="$1"
    local errors=0
    
    if [[ ! -f "$chain_file" ]]; then
        log_error "Chain file not found: $chain_file"
        return 1
    fi
    
    if ! yaml_has_key "$chain_file" "name"; then
        log_error "Chain missing required 'name' field"
        errors=$((errors + 1))
    fi
    
    if ! yaml_has_key "$chain_file" "version"; then
        log_error "Chain missing required 'version' field"
        errors=$((errors + 1))
    fi
    
    if ! yaml_has_key "$chain_file" "steps"; then
        log_error "Chain missing required 'steps' field"
        errors=$((errors + 1))
    fi
    
    if [[ $errors -gt 0 ]]; then
        return 1
    fi
    
    return 0
}

yaml_expand_variables() {
    local yaml_content="$1"
    local globals_json="$2"
    
    echo "$yaml_content"
}
