#!/bin/bash

# Signal-chain validator — a thin delegate.
#
# This file used to be a second, independent, grep-based validator. It disagreed with
# the real one: on a chain using a folded block scalar the Python validator correctly
# refused the file while this script reported "Chain validation passed", because
# `grep -qE "^version:"` finds the key regardless of whether the parser can actually
# read the document. It failed OPEN — the worst direction for a gate.
#
# Two implementations of "is this chain valid?" is the same defect class as a component
# that exits 0 while producing silence: a check that can disagree with the truth is
# worse than no check, because it is trusted. So validation now happens in exactly one
# place, lib/workchain_yaml.py, and this script forwards to it.
#
# Keep it that way. If you find yourself adding a grep here, you are rebuilding the bug.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/constants.sh"
source "$LIB_DIR/common-utils.sh"

validate_chain() {
    local chain_file="$1"
    local root="${WORKCHAIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
    local out

    log_info "Validating chain: $chain_file"

    if [[ ! -f "$chain_file" ]]; then
        log_error "Chain file not found: $chain_file"
        return 1
    fi

    if ! out=$(python3 "$root/lib/workchain_yaml.py" validate "$root" "$chain_file" 2>&1); then
        log_error "Chain validation failed"
        while IFS= read -r line; do
            [[ -n "$line" ]] && log_error "  $line"
        done <<< "$out"
        return 1
    fi

    log_info "Chain validation passed"
    return 0
}

# Allow direct invocation: chain-validator.sh <chain.yaml>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ -z "$1" ]]; then
        echo "Usage: $0 <chain.yaml>"
        exit 2
    fi
    validate_chain "$1"
    exit $?
fi
