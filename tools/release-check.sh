#!/bin/bash
#
# release-check.sh — prove this checkout works before anyone else sees it.
#
# Runs every light chain end to end against generated fixtures, confirms the verifier
# PASSED on each, and — the part that actually matters — confirms it FAILS on a chain
# designed to miss its target. A verification system nobody has watched fail is not
# evidence of anything.
#
#   ./tools/release-check.sh              # light path (no venv, no model weights)
#   ./tools/release-check.sh --heavy      # also exercise heavy components
#   ./tools/release-check.sh --keep       # keep the work dir for inspection
#
# Exit 0 only when every gate passed. Any failure is fatal and named.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

HEAVY=0
KEEP=0
for a in "$@"; do
    case "$a" in
        --heavy) HEAVY=1 ;;
        --keep)  KEEP=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option: $a"; exit 2 ;;
    esac
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/workchain-release.XXXXXX")"
cleanup() { [[ $KEEP -eq 1 ]] && echo "work dir kept: $WORK" || rm -rf "$WORK"; }
trap cleanup EXIT

PASS=0; FAIL=0; SKIP=0
declare -a FAILURES=()

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL=$((FAIL+1)); FAILURES+=("$*"); }
skip() { printf '  \033[33mskip\033[0m  %s\n' "$*"; SKIP=$((SKIP+1)); }

# ── 0. prerequisites ────────────────────────────────────────────────────────────
say "0. Prerequisites"
for cmd in python3 ffmpeg ffprobe node; do
    if command -v "$cmd" >/dev/null 2>&1; then ok "$cmd  ($($cmd --version 2>&1 | head -1 | cut -c1-40))"
    else bad "$cmd is not on PATH"; fi
done
[[ $FAIL -gt 0 ]] && { say "Cannot continue without the tools above."; exit 1; }

# The engine is invoked as ./engine/workchain-engine.sh, so a shell script committed 100644
# makes every behavioural gate below fail with exit 126 — and it fails that way ONLY on a
# clean checkout, because a working tree someone has already chmod'd looks fine forever.
# That is exactly how this shipped once. Check the committed mode, not just the local one.
say "0b. Executable bits"
# Detect executables by SHEBANG, not by filename. An earlier version globbed engine/*.sh,
# tools/*.sh and components/*/run.sh, so tools/hooks/pre-push — a git hook with no .sh
# extension — was invisible and shipped 100644. A hook without the exec bit silently never
# runs, which is the quietest possible failure.
#
# Written with a temp file rather than `mapfile < <(...)`: process substitution is not
# available in every shell this may run in, and when it failed here the check did nothing
# while the summary still reported all gates passed. A gate that can no-op silently is worse
# than no gate, so if enumeration yields nothing this FAILS.
SHEBANG_LIST="$WORK/shebanged.txt"
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    git ls-files > "$WORK/tracked.txt" 2>/dev/null || : > "$WORK/tracked.txt"
else
    find . -type f -not -path './.git/*' -not -path '*/node_modules/*' -not -path '*/.venv/*' \
        | sed 's|^\./||' > "$WORK/tracked.txt"
fi
: > "$SHEBANG_LIST"
while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    # A template or example carries a shebang for the file it will BECOME; it is not itself
    # runnable, so requiring the exec bit on it is a false positive.
    case "$f" in *.template|*.example|*.sample) continue ;; esac
    if [[ "$(head -c 2 "$f" 2>/dev/null)" == "#!" ]]; then printf '%s\n' "$f" >> "$SHEBANG_LIST"; fi
done < "$WORK/tracked.txt"

shebang_count=$(wc -l < "$SHEBANG_LIST" | tr -d ' ')
if [[ "${shebang_count:-0}" -lt 5 ]]; then
    bad "only ${shebang_count:-0} shebanged files found — this check is not working, treat as a failure"
else
    ok "$shebang_count files carry a shebang"
fi

if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    notexec=""
    while IFS= read -r f; do
        mode=$(git ls-files -s -- "$f" 2>/dev/null | awk '{print $1}')
        if [[ -n "$mode" && "$mode" != "100755" ]]; then notexec="$notexec $f"; fi
    done < "$SHEBANG_LIST"
    if [[ -z "$notexec" ]]; then
        ok "every shebanged file is committed executable (100755)"
    else
        bad "committed WITHOUT the executable bit — fix with: git update-index --chmod=+x$notexec"
    fi
else
    skip "committed file modes (not a git checkout)"
fi

missing=""
while IFS= read -r f; do
    [[ -f "$f" && ! -x "$f" ]] && missing="$missing $f"
done < "$SHEBANG_LIST"
if [[ -z "$missing" ]]; then ok "every shebanged file is executable on disk"
else bad "not executable in this working tree:$missing"; fi

# ── 1. fixtures ─────────────────────────────────────────────────────────────────
# Generated, never committed: a binary fixture in git is a fixture nobody can regenerate.
say "1. Generating fixtures"
mk() {
    local name="$1"; shift
    if ffmpeg -nostdin -hide_banner -loglevel error -y "$@" "$WORK/$name" 2>/dev/null; then
        ok "$name"
    else
        bad "could not generate fixture $name"
    fi
}
# plain stereo tone, easy case
mk tone.wav -f lavfi -i "sine=frequency=220:duration=3:sample_rate=48000" -ac 2 -c:a pcm_s16le
# high crest factor: short bursts in silence. Integrated loudness sits far below peak, so a
# hot target is unreachable under a true-peak ceiling — this is what makes the negative test bite.
mk sparse.wav -f lavfi -i "sine=frequency=440:duration=6:sample_rate=48000" \
   -af "volume='if(lt(mod(t,2),0.06),0.9,0.0)':eval=frame" -ac 2 -c:a pcm_s16le
# 44.1k mono 16-bit, so format conformance has something real to change
mk odd-format.wav -f lavfi -i "sine=frequency=330:duration=2:sample_rate=44100" -ac 1 -c:a pcm_s16le
# Fixture for the heavy stem_separation chains. Source separation of a pure sine is
# pathological — a single steady tone is not something the models decompose, so the
# stems_recombine residual stays above threshold and the contract fails even though the
# component is fine. Feed the separators audio they can actually work on: a chord + noise bed
# (%chromatic instrumentals), plus — where a speech synthesizer is available — a spoken vocal
# line so the handoff chain (stem_separation -> normalization) gets a real, non-silent vocals
# stem instead of an honest-but-unverified skip.
mk inst.wav -f lavfi -i "aevalsrc=0.22*sin(2*PI*220*t)+0.16*sin(2*PI*277.18*t)+0.15*sin(2*PI*329.63*t)+0.11*sin(2*PI*440*t)+0.06*sin(2*PI*554.37*t)+0.05*sin(2*PI*659.25*t):d=4:s=44100" -f lavfi -i "anoisesrc=color=brown:amplitude=0.10:d=4:s=44100" -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:normalize=0,volume=0.8[a]" -map "[a]" -ac 2 -c:a pcm_s16le
TTS=""; command -v espeak-ng >/dev/null 2>&1 && TTS=espeak-ng; [ -z "$TTS" ] && command -v espeak >/dev/null 2>&1 && TTS=espeak
if [[ -n "$TTS" ]]; then
    "$TTS" -w "$WORK/vox.wav" -s 150 -p 50 "This is the work chain stem separation test" >/dev/null 2>&1
    if ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/inst.wav" -i "$WORK/vox.wav" \
        -filter_complex "[0:a]aresample=44100,apad[a0];[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];[a0][a1]amix=inputs=2:duration=longest:normalize=0,volume=0.9,atrim=0:6[a]" \
        -map "[a]" -ac 2 -c:a pcm_s16le "$WORK/mix.wav" 2>/dev/null; then
        ok "mix.wav (instrumental + TTS vocal)"
    else
        bad "mix.wav generation failed"
    fi
else
    cp "$WORK/inst.wav" "$WORK/mix.wav"
    ok "mix.wav (instrumental only — no TTS; stem_separation_and_normalize may skip)"
fi

# ── 2. static validation ────────────────────────────────────────────────────────
say "2. Chain validation (every chain, strict)"
shopt -s nullglob
for c in chains/*.yaml chains/tests/*.yaml; do
    if out=$(python3 lib/workchain_yaml.py validate . "$c" 2>&1) \
       && printf '%s' "$out" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("valid") else 1)' 2>/dev/null; then
        ok "$c"
    else
        bad "$c does not validate"
    fi
done

# ── 3. the two parsers must agree ───────────────────────────────────────────────
say "3. Parser agreement (the format must not depend on what is installed)"
cat > "$WORK/folded.yaml" <<'YAML'
name: "folded"
description: >
  spans
  lines
version: "1.0"
steps:
  - name: normalization
    params: {}
YAML
py_rc=0; python3 lib/workchain_yaml.py validate . "$WORK/folded.yaml" >/dev/null 2>&1 || py_rc=1
sh_rc=0; ./engine/chain-validator.sh "$WORK/folded.yaml" >/dev/null 2>&1 || sh_rc=1
if [[ $py_rc -eq 1 && $sh_rc -eq 1 ]]; then
    ok "both validators reject an unsupported block scalar"
else
    bad "validators disagree on a block scalar (python rc=$py_rc, bash rc=$sh_rc) — one is failing OPEN"
fi

# ── 4. light chains, end to end ─────────────────────────────────────────────────
# A chain "passes" only when the engine exits 0 AND every step's verification record
# says verified. Exit 0 alone is exactly the claim this project does not accept.
verified_all() {
    CTX="$1" python3 - <<'PY'
import json, os, sys
ctx = json.load(open(os.environ["CTX"]))
steps = ctx.get("steps", {})
if not steps:
    print("no steps recorded"); sys.exit(1)
bad = []
for name, s in steps.items():
    v = s.get("verification") or {}
    if s.get("status") != "completed":
        bad.append("%s status=%s" % (name, s.get("status")))
    elif v.get("verified") is not True:
        bad.append("%s verified=%r" % (name, v.get("verified")))
if bad:
    print("; ".join(bad)); sys.exit(1)
print("%d step(s) verified" % len(steps))
PY
}

run_chain() {
    local chain="$1" fixture="$2" expect="${3:-pass}" label
    label="$(basename "$chain" .yaml)"
    local out="$WORK/out-$label"
    local log="$WORK/log-$label.txt"
    local rc=0
    timeout 900 ./engine/workchain-engine.sh -c "$chain" "$WORK/$fixture" -o "$out" >"$log" 2>&1 || rc=$?

    if [[ "$expect" == "fail" ]]; then
        if [[ $rc -ne 0 ]] && grep -q "verification FAILED" "$log"; then
            ok "$label — correctly FAILED its contract (this is the important one)"
        else
            bad "$label was supposed to fail its contract but exited $rc"
        fi
        return
    fi

    if [[ $rc -ne 0 ]]; then
        bad "$label — engine exited $rc ($(grep -m1 'ERROR' "$log" | cut -c1-100))"
        return
    fi
    local detail
    if detail=$(verified_all "$out/context.json"); then
        ok "$label — $detail"
    else
        bad "$label — exited 0 but verification was not clean: $detail"
    fi
}

say "4. Light chains, end to end"
run_chain chains/deliverable-voice.yaml       tone.wav
run_chain chains/deliverable-streaming.yaml   tone.wav
run_chain chains/deliverable-broadcast.yaml   tone.wav
run_chain chains/simple-test.yaml             tone.wav
run_chain chains/tests/normalization_only.yaml     tone.wav
run_chain chains/tests/format_conversion_test.yaml odd-format.wav
run_chain chains/tests/audio_benchmark_test.yaml   tone.wav
run_chain chains/tests/content_hash_test.yaml      tone.wav

# ── 5. the negative test ────────────────────────────────────────────────────────
say "5. Negative test — the verifier must fail closed"
run_chain chains/tests/normalization_offtarget.yaml sparse.wav fail

# ── 6. heavy path ───────────────────────────────────────────────────────────────
say "6. Heavy components"
if [[ $HEAVY -eq 1 ]]; then
    for c in chains/tests/stem_separation*.yaml; do run_chain "$c" mix.wav; done
else
    skip "heavy chains (pass --heavy; needs a venv and model weights — see components/stem_separation/README.md)"
fi

# ── 7. registry + unit tests ────────────────────────────────────────────────────
say "7. Registry and unit tests"
# Ask the Python registry module directly. Going through the Node CLI made this a FALSE
# NEGATIVE on a cold clone: with cli/node_modules absent the CLI cannot load commander, so
# the check exited non-zero and this harness reported the index STALE when it was current.
# A verification harness that cries wolf is worse than one that stays quiet — people learn
# to ignore it. The Python path needs nothing installed.
if python3 lib/workchain_registry.py check . >/dev/null 2>&1; then
    ok "components/index.json is current"
else
    bad "components/index.json is STALE — run: node cli/bin/workchain.js registry generate"
fi

# Cross-check that the two entry points agree. Compare EXIT CODES: when the index is
# genuinely stale both should report stale, and treating "node exited non-zero" as
# disagreement produced a false DISAGREES alarm the first time this ran. The Node command
# delegates to lib/workchain_registry.py, so any difference here is a wiring fault.
if [[ -d cli/node_modules ]]; then
    python3 lib/workchain_registry.py check . >/dev/null 2>&1; py_reg=$?
    node cli/bin/workchain.js registry check >/dev/null 2>&1; node_reg=$?
    if [[ $py_reg -eq $node_reg ]]; then
        ok "Node CLI and Python registry check agree (both rc=$py_reg)"
    else
        bad "registry check DISAGREES: python rc=$py_reg vs node rc=$node_reg — one is failing OPEN"
    fi
else
    skip "Node/Python registry cross-check (run: cd cli && npm install)"
fi

if [[ -d cli/node_modules ]]; then
    if (cd cli && npm test >"$WORK/npm-test.txt" 2>&1); then ok "cli npm test"
    else bad "cli npm test failed (see $WORK/npm-test.txt)"; fi
else
    skip "cli npm test (run: cd cli && npm install)"
fi

# ── 8. documentation sanity ─────────────────────────────────────────────────────
# Cheap greps for the drift that embarrasses us publicly.
say "8. Documentation sanity"
# This script and PORTING.md legitimately name the strings they screen for.
# Private component and repo names are screened by their full, distinctive forms.
# A bare `embed` alternative was tried and removed: as a standalone token it matches
# ordinary English -- "embed the engine", "to embed, run" -- so it cried wolf, and the
# only way to keep it quiet was excluding LICENSING.md wholesale, which left a
# public-facing file unscreened for hostnames and local paths as well. The word
# "embed" on its own reveals nothing private; `embed_clap` does, and is matched.
leaks=$(grep -rIl -E '\b(siku|klaxon|carnyx|tambora|kora|regalle|pandeiro|samvadini|sound-archive|agent-knowledge|archive-index|archive_index|archive-ingest|embed_clap)\b|100\.[0-9]+\.[0-9]+\.[0-9]+|exe\.xyz|lufshq\.com|/Users/|/home/[a-z]|yourusername|localhost:[0-9]{4}/[a-z]|danialrami/' \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv . 2>/dev/null \
    | grep -vE '^\./(docs/PORTING\.md|tools/release-check\.sh|ci/README\.md)$' || true)
if [[ -z "$leaks" ]]; then ok "no internal hostnames, tailnet addresses, private repo or personal config references"
else bad "internal references present in: $(echo "$leaks" | tr '\n' ' ')"; fi

for comp in components/*/; do
    name="$(basename "$comp")"
    [[ "$name" == "_template" ]] && continue
    if [[ -f "$comp/step.yaml" && -f "$comp/run.sh" && -f "$comp/README.md" ]]; then ok "$name has step.yaml + run.sh + README.md"
    else bad "$name is missing one of step.yaml / run.sh / README.md"; fi
    if grep -q "^verify:" "$comp/step.yaml" 2>/dev/null; then ok "$name declares a verify: contract"
    else bad "$name has NO verify: block"; fi
done

# Every markdown file, not just the two at the top. This gate previously looked only at
# README.md and docs/*.md, so four component READMEs kept telling users to run
# `lufs-workchain run-component ...` — a command that does not exist — and it reported green.
# A check with the wrong scope is indistinguishable from no check.
# Declared licence must match the LICENSE file. agent.json shipped "MIT" while LICENSE was
# Apache-2.0 — a machine-readable discovery file is exactly where a wrong licence does damage,
# because tooling believes it.
if [[ -f LICENSE && -f agent.json ]]; then
    lic_file=$(head -20 LICENSE | grep -oE 'Apache License|MIT License|GNU (Lesser )?General Public License' | head -1)
    lic_decl=$(python3 -c "import json;print(json.load(open('agent.json')).get('license',''))" 2>/dev/null)
    case "$lic_file:$lic_decl" in
        "Apache License:Apache-2.0"|"MIT License:MIT") ok "agent.json licence ($lic_decl) matches LICENSE ($lic_file)" ;;
        *) bad "agent.json declares '$lic_decl' but LICENSE is '$lic_file'" ;;
    esac
fi

# Internal branch names have no business in a public tree.
branchleak=$(grep -rIl -E '\b(ciani|kardashev|amacher|oliveros|chachi|deedee)/[a-z0-9-]+' \
    --exclude-dir=.git --exclude-dir=node_modules --exclude='release-check.sh' . 2>/dev/null || true)
if [[ -z "$branchleak" ]]; then ok "no internal branch names referenced"
else bad "internal branch names referenced in: $(echo "$branchleak" | tr '\n' ' ')"; fi

stale_cli=$(grep -rIl -E '\blufs-workchain (run-component|registry|doctor|run|validate|chains|components|generate)\b' \
    --include='*.md' --exclude-dir=.git --exclude-dir=node_modules . 2>/dev/null || true)
if [[ -z "$stale_cli" ]]; then
    ok "every doc uses the current CLI name"
else
    bad "docs still invoke the old CLI name (binary is 'workchain'): $(echo "$stale_cli" | tr '\n' ' ')"
fi

# ── summary ─────────────────────────────────────────────────────────────────────
say "Summary"
printf '  %d passed, %d failed, %d skipped\n' "$PASS" "$FAIL" "$SKIP"
if [[ $FAIL -gt 0 ]]; then
    printf '\n\033[31mNot ready.\033[0m Failures:\n'
    for f in "${FAILURES[@]}"; do printf '  - %s\n' "$f"; done
    exit 1
fi
printf '\n\033[32mAll gates passed.\033[0m\n'
exit 0
