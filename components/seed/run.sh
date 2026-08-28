
# seed component - Mint a verifiable, provenanced seed from a noise-floor recording
#
# Deliberately UNLIKE catalog: catalog hunts the context for the most-processed
# audio available (protection -> normalization -> raw). This component does the
# opposite and takes the RAWEST audio it can justify, because every processing step
# destroys the thing we are harvesting. Normalizing a noise floor applies gain to
# the LSBs; a lossy transcode replaces them with codec noise. Either would leave a
# step that still "succeeds" while seeding from something that is no longer thermal
# noise -- the exact failure class this project exists to refuse.
#
# So: seed belongs FIRST in a chain, and if it detects that a prior step has already
# advanced input_file, it fails honestly rather than quietly seeding from a
# derivative.

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

log_step "Running: seed"

INPUT_FILE=$(ctx_get_abs "$CONTEXT_FILE" input_file)
OUTPUT_DIR=$(ctx_get_abs "$CONTEXT_FILE" output_dir)

get_param() {
    local param_name="$1"
    local default="${2:-}"

    local value=$(echo "$STEP_CONFIG" | grep -E "^\s+${param_name}:" | sed "s/.*${param_name}: *//" | head -1 | sed 's/^["\x27]\(.*\)["\x27]$/\1/')

    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

LSB_BITS=$(get_param "lsb_bits" "8")
FLOOR_MAX_DBFS=$(get_param "floor_max_dbfs" "-30")
FLOOR_MIN_DBFS=$(get_param "floor_min_dbfs" "-110")
MIN_DURATION_S=$(get_param "min_duration_s" "5")
MIN_ENTROPY_BITS=$(get_param "min_entropy_bits" "256")
USE_JITTER=$(get_param "jitter" "true")
SIGN_KEY=$(get_param "sign" "")
NOTE=$(get_param "note" "")

SEED_DIR="$OUTPUT_DIR/seed"
ensure_dir "$OUTPUT_DIR"
ensure_dir "$SEED_DIR"

RECORD_FILE="$SEED_DIR/seed_record.json"
SUMMARY_FILE="$SEED_DIR/seed_info.txt"

# ── Refuse to seed from a processed derivative ────────────────────────────────
# If any earlier step registered a file output, the engine has advanced input_file
# to it and we are no longer looking at the original capture.
PRIOR_STEP=$(__WC_CF="$CONTEXT_FILE" python3 << 'PYEOF' 2>/dev/null
import json, os
with open(os.environ['__WC_CF']) as f:
    ctx = json.load(f)
for name, data in (ctx.get('steps') or {}).items():
    if name == 'seed':
        continue
    if isinstance(data, dict) and data.get('output'):
        print(name)
        break
PYEOF
)

if [[ -n "$PRIOR_STEP" ]]; then
    log_error "seed must run FIRST in a chain, but step '$PRIOR_STEP' has already produced audio."
    log_error "input_file now points at a processed derivative: $INPUT_FILE"
    log_error "Processing destroys the thermal noise in the LSBs, so a seed minted here"
    log_error "would claim a provenance it does not have. Move 'seed' to the top of the chain."
    register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"not_first_step\", \"prior_step\": \"$PRIOR_STEP\"}" \
        "failed"
    return 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    log_error "No input recording found for seed minting: $INPUT_FILE"
    register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"missing_input\"}" "failed"
    return 1
fi

log_info "Minting seed from noise floor: $(basename "$INPUT_FILE")"
log_debug "lsb_bits=$LSB_BITS floor window=[$FLOOR_MIN_DBFS, $FLOOR_MAX_DBFS] dBFS"

# ── Build the lufs-seed invocation ────────────────────────────────────────────
# Arrays, not a string, so paths containing apostrophes/spaces survive.
MINT_CMD=(lufs-seed mint
    --audio "$INPUT_FILE"
    --out "$RECORD_FILE"
    --lsb-bits "$LSB_BITS"
    --floor-max-dbfs "$FLOOR_MAX_DBFS"
    --floor-min-dbfs "$FLOOR_MIN_DBFS"
    --min-duration "$MIN_DURATION_S"
    --min-entropy-bits "$MIN_ENTROPY_BITS"
    --json)

if [[ "$USE_JITTER" == "true" ]]; then
    MINT_CMD+=(--jitter)
fi

if [[ -n "$SIGN_KEY" ]]; then
    if [[ ! -f "$SIGN_KEY" ]]; then
        log_error "Signing key not found: $SIGN_KEY"
        log_error "Either provide a valid key or drop the 'sign' param to mint unsigned."
        register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
            "{\"error\": \"signing_key_missing\"}" "failed"
        return 1
    fi
    MINT_CMD+=(--sign "$SIGN_KEY")
fi

if [[ -n "$NOTE" ]]; then
    MINT_CMD+=(--note "$NOTE")
fi

MINT_OUT=$("${MINT_CMD[@]}" 2>&1)
MINT_RC=$?

if [[ $MINT_RC -ne 0 ]]; then
    # Surface the tool's own reason. lufs-seed uses distinct exit codes:
    # 3 source unavailable, 4 health check failed, 5 entropy budget not met,
    # 7 signing error. All of these are honest refusals, not crashes.
    case $MINT_RC in
        3) log_error "seed: required entropy source unavailable" ;;
        4) log_error "seed: the recording failed its health gate" ;;
        5) log_error "seed: assessed min-entropy below the required budget" ;;
        7) log_error "seed: signing failed" ;;
        *) log_error "seed: lufs-seed mint failed (exit $MINT_RC)" ;;
    esac
    echo "$MINT_OUT" | while IFS= read -r line; do log_error "  $line"; done
    register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"mint_failed\", \"exit_code\": $MINT_RC}" \
        "failed"
    return 1
fi

if [[ ! -f "$RECORD_FILE" ]]; then
    log_error "seed: lufs-seed exited 0 but produced no record at $RECORD_FILE"
    register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"missing_record\"}" "failed"
    return 1
fi

# ── Pull identity out of the record for the context ───────────────────────────
SEED_META=$(__WC_REC="$RECORD_FILE" __WC_SRC="$INPUT_FILE" python3 << 'PYEOF' 2>/dev/null
import json, os
with open(os.environ['__WC_REC']) as f:
    rec = json.load(f)
p = rec.get('payload', {})
audio = next((s for s in p.get('sources', [])
              if s.get('source_id') == 'audio-noise-floor'), {})
detail = audio.get('detail', {})
print(json.dumps({
    'seed_id': p.get('seed_id', ''),
    'tier': p.get('tier', ''),
    'entropy_bits': (p.get('entropy') or {}).get('assessed_bits', ''),
    'catalog_number': detail.get('catalog_number', ''),
    'content_sha256': detail.get('content_sha256', ''),
    'lsb_bits': detail.get('lsb_bits', ''),
    'sources': ','.join(s.get('source_id', '') for s in p.get('sources', [])),
    # source_input is the key lib/workchain_verify.py's _resolve_source looks for.
    # Recording it means the contract can re-check the ACTUAL recording we minted
    # from, even if the chain advances input_file afterwards.
    'source_input': os.environ['__WC_SRC'],
}))
PYEOF
)

if [[ -z "$SEED_META" ]]; then
    log_error "seed: could not parse the record lufs-seed produced"
    register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
        "{\"error\": \"unparseable_record\"}" "failed"
    return 1
fi

SEED_ID=$(echo "$SEED_META" | python3 -c "import json,sys; print(json.load(sys.stdin)['seed_id'])" 2>/dev/null)
SEED_TIER=$(echo "$SEED_META" | python3 -c "import json,sys; print(json.load(sys.stdin)['tier'])" 2>/dev/null)

# ── Human-readable summary ────────────────────────────────────────────────────
__WC_REC="$RECORD_FILE" __WC_SRC="$INPUT_FILE" python3 << 'PYEOF' > "$SUMMARY_FILE"
import json, os
with open(os.environ['__WC_REC']) as f:
    rec = json.load(f)
p = rec.get('payload', {})
print("SEED RECORD")
print("===========")
print("Seed ID:        %s" % p.get('seed_id', ''))
print("Tier:           %s" % p.get('tier', ''))
print("Minted:         %s" % p.get('minted_at', ''))
print("Host:           %s" % p.get('host', ''))
print("Seed:           %s" % p.get('seed_hex', ''))
ent = p.get('entropy', {})
print("Entropy:        %s bits assessed (required %s) — physical sources only"
      % (ent.get('assessed_bits', '?'), ent.get('required_bits', '?')))
if p.get('note'):
    print("Note:           %s" % p['note'])
print()
print("Sources:")
for s in p.get('sources', []):
    kind = 'physical' if s.get('physical') else 'non-physical'
    print("  - %-20s %-14s %s bits" % (s.get('source_id'), '(%s)' % kind,
                                       s.get('entropy_bits')))
    d = s.get('detail', {})
    if s.get('source_id') == 'audio-noise-floor':
        print("      recording   %s" % d.get('path'))
        print("      catalog     %s" % d.get('catalog_number'))
        print("      peak/rms    %s / %s dBFS" % (d.get('peak_dbfs'), d.get('rms_dbfs')))
        print("      lsb_bits    %s" % d.get('lsb_bits'))
for a in p.get('absent_sources', []):
    print("  - %-20s ABSENT (%s)" % (a.get('source_id'), a.get('reason')))
if 'signature' in rec:
    print()
    print("Signed by:      %s" % rec['signature'].get('public_key'))
else:
    print()
    print("Unsigned — tier below `certified`.")
print()
print("Derive from this seed:")
print("  lufs-seed derive <label> --record seed/seed_record.json --floats 4")
PYEOF

log_info "Seed minted: $SEED_ID (tier: $SEED_TIER)"

register_output "$CONTEXT_FILE" "seed" "summary" "$SUMMARY_FILE" "file" \
    "{}" ""

register_output "$CONTEXT_FILE" "seed" "primary_output" "$RECORD_FILE" "json" \
    "$SEED_META" \
    "completed"

return 0
