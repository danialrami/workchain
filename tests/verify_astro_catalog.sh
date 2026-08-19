# verify_astro_catalog.sh
# Rigorously check (and optionally re-run) astro-catalog outputs.
# Verifies each audio file's context.json has status=="completed" AND that every
# step in the chain also completed. Also flags tracks that completed but have no
# HTML report (the report is only produced when the chain runs with --report).
#
# Usage:
#   bash tests/verify_astro_catalog.sh [CATALOG_BASE] [--rerun]
#     (no flag)  report completed / incomplete / missing / completed-without-report
#     --rerun    re-run every unfinished file, WITH --report so it keeps its report
#
# Env:
#   SKIP_DIRS      space-separated album folder names to skip (default: "_utilities")
#   WORKCHAIN_CMD  CLI to invoke (default: lufs-workchain)
#   CHAIN          chain name (default: astro-catalog)

set -u
CATALOG_BASE="${1:-/Volumes/project/continuo/catalogs}"
RERUN=0; [[ "${2:-}" == "--rerun" ]] && RERUN=1
SKIP_DIRS="${SKIP_DIRS:-_utilities}"
WORKCHAIN_CMD="${WORKCHAIN_CMD:-lufs-workchain}"
CHAIN="${CHAIN:-astro-catalog}"

ok=0; bad=0; missing=0; noreport=0
declare -a FAILED

# Stage the file list on disk and read from it (portable: no /dev/fd process
# substitution, which some shells/containers don't expose).
LIST="$(mktemp)"; trap 'rm -f "$LIST"' EXIT
find "$CATALOG_BASE" -type f \
    \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.aiff' -o -iname '*.aif' \
       -o -iname '*.m4a' -o -iname '*.flac' -o -iname '*.ogg' \) -print0 > "$LIST"

while IFS= read -r -d '' f; do
    dir=$(dirname "$f"); base=$(basename "$dir")
    # skip configured dirs, dot-dirs, and files already inside an output dir
    skip=0; for s in $SKIP_DIRS; do [[ "$base" == "$s" ]] && skip=1; done
    [[ "$skip" == 1 ]] && continue
    [[ "$base" == .* ]] && continue
    [[ "$dir" == *_astro-catalog ]] && continue

    name="${f##*/}"; name="${name%.*}"
    out="$dir/${name}_astro-catalog"; ctx="$out/context.json"

    if [[ ! -f "$ctx" ]]; then
        echo "  MISSING (never produced): $f"
        missing=$((missing+1)); FAILED+=("$f"); continue
    fi

    # rigorous: chain completed AND no step left non-completed
    status=$(python3 - "$ctx" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("unreadable"); sys.exit()
bad = [k for k, v in (d.get("steps") or {}).items()
       if isinstance(v, dict) and v.get("status") not in ("completed",)]
ch = d.get("status")
print("ok" if ch == "completed" and not bad
      else "incomplete:" + (",".join(bad) or ch or "?"))
PY
    )

    if [[ "$status" == "ok" ]]; then
        ok=$((ok+1))
        # soft check: a completed track with no report (run was missing --report)
        if ! ls "$out"/*_report.html >/dev/null 2>&1; then
            echo "  NO REPORT (completed): $name  — re-run with --report to add it"
            noreport=$((noreport+1))
        fi
    else
        echo "  INCOMPLETE [$status]: $f"
        bad=$((bad+1)); FAILED+=("$f")
    fi
done < "$LIST"

echo ""
echo "completed: $ok | incomplete: $bad | missing: $missing | completed-without-report: $noreport"

if [[ $RERUN -eq 1 && ${#FAILED[@]} -gt 0 ]]; then
    echo ""
    echo "Re-running ${#FAILED[@]} unfinished file(s) (with --report)..."
    for f in "${FAILED[@]}"; do
        dir=$(dirname "$f"); name="${f##*/}"; name="${name%.*}"
        out="$dir/${name}_astro-catalog"
        echo "  -> $name"
        "$WORKCHAIN_CMD" run "$CHAIN" "$f" -o "$out" --report --json \
            >"$out.rerun.log" 2>&1 \
            && echo "     done" \
            || echo "     STILL FAILING (see $out.rerun.log)"
    done
fi
