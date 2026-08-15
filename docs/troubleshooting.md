---
title: "Troubleshooting"
description: "Symptom → cause → fix for the failure modes you will actually meet: reading verification failures, silent-input skips, preflight stops, missing or unknown presets, model provisioning, YAML parser gotchas, and exit codes. All quoted error text is real output from the repo or observed runs."
type: troubleshooting
---

# Troubleshooting

How to read a failed run, and what to do about each failure class. Format of every entry:
**symptom** (real output where available) → **cause** → **fix**. Error text quoted here is
either copied verbatim from the repo's own docs or observed directly; provenance per entry.

## How to read a failure

A step can fail in two places, and the wording tells you which:

- **`dependency preflight FAILED`** — checked *before* `run.sh` runs. Something the step
  declared it needs (command, venv, model, env var) is missing on this machine.
- **`verification FAILED`** — checked *after* `run.sh` exited 0. The output exists but does
  not meet the declared contract. The per-check detail lines are the measured facts that
  stopped the run — read them first.

Either way the chain halts and the run records a non-zero outcome. The full recorded state —
preflight report, resolved params, registered outputs, verification report — lands in
`context.json` in the output directory.

## Verification failures

### `verification FAILED (N of M checks)` after the component reported success

<!-- quoted verbatim from README.md; grep provenance: "verification FAILED" -->
```
✗ normalization — verification FAILED (1 of 8 checks)
    integrated_loudness_on_target: measured -10.56 LUFS vs target -5.0 (±1.0) → off by 5.56 LU
Chain halted: step 'normalization' failed
```

**Cause.** `run.sh` exited 0 — the component even logged "Normalization completed" — but the
verifier re-measured the output and it missed the declared contract. In this case the target
is unreachable under the true-peak ceiling for a signal with that crest factor. The component
does not get to grade its own homework.

**Fix.** Read the detail lines: they state measured vs expected (`measured -10.56 LUFS vs
target -5.0 (±1.0) → off by 5.56 LU`). Either the parameters ask for something the input
cannot reach (lower the target or relax the peak ceiling), or the component has a real bug.
`chains/tests/normalization_offtarget.yaml` exists to exercise exactly this gate.
→ [`docs/explanation/verification.md`](explanation/verification.md)

### A chain using the CLI says `Chain halted: step 'X' failed verification`

Same failure, different reporter. The CLI surfaces the same measured facts and stops the run.
Read the failure detail lines above the halt message, or `context.json` →
`steps.<name>.verification.failures` for the full check-by-check report.
→ [`docs/explanation/verification.md`](explanation/verification.md)

## Silent input

### The run "succeeded" but the normalization step was skipped

**Symptom.** A silent input went through normalization; the step is recorded as `skipped`
with a `silent_input_skipped` note in the metadata, and the chain continues.
(`components/normalization/README.md` — "copies the input through unchanged, and registers
the step as `skipped` with a `silent_input_skipped` note" when measured LUFS is `-inf`.)

**Cause.** The input truly is silence (measured integrated loudness `-inf`). There is nothing
to normalize; copying through unchanged is the honest behavior.

**Fix.** Usually none — it is expected behavior, not an error. If the chain must fail on
silent input, add a check of the metadata note. If the input is *not* supposed to be silent,
the recording chain upstream is the thing to investigate.
→ [`components/normalization/README.md`](../components/normalization/README.md)

## Preflight failures

### `dependency preflight FAILED` — the step never ran

**Symptom.** Observed on a stock golden VM with no Python venv provisioned, running the
`stem_separation` test chain:

```
✗ stem_separation — dependency preflight FAILED (1 of 3 checks)
    python:venv: venv python not found at /path/to/components/stem_separation/.venv — provision: python3 -m venv .venv && .venv/bin/pip install 'audio-separator[cpu]' (use Python 3.10 — Demucs diffq has no cp311 wheel)
  - *Fix:* run `components/stem_separation/provision.sh` or follow the instructions in [`provision-heavy-components`](how-to/operate/provision-heavy-components.md)
Step failed dependency preflight: stem_separation
Chain halted: step 'stem_separation' failed
```

**Cause.** The step declared a requirement (in this case a Python venv) that is not present
on this machine. Preflight runs before `run.sh` — the step deliberately never started.

**Fix.** The failing line names the check and the missing thing. For commands: install them.
For venv/model requirements, the `provision:` hint is printed in the message — follow it.
Then re-run, or run `workchain doctor` to check the whole registry at once. Missing
requirements are recorded in `context.json` with `reason: missing_dependency`.
→ [`docs/explanation/verification.md`](explanation/verification.md#verified-in--checked-before-the-run)

## Preset and model provisioning (stem_separation)

### `audio_separator_not_found`

**Cause.** The `audio-separator` binary is not on `PATH`, not at
`$WORKCHAIN_AUDIO_SEPARATOR_BIN`, and not in `components/stem_separation/.venv/bin/`. The
step fails honestly with status `failed` and reason `audio_separator_not_found` — never a
faked success — and prints install instructions.

**Fix.** Create the venv per the component README and install `audio-separator[cpu]` into it
(`python3 -m venv .venv && .venv/bin/pip install 'audio-separator[cpu]'`).
→ [`components/stem_separation/README.md`](../components/stem_separation/README.md)

### `model_required`

**Cause.** `preset: custom` requires an explicit `model:` parameter; omitting it fails with
`model_required`.

**Fix.** Pass a valid `model` value when using `preset: custom`.
→ [`components/stem_separation/README.md`](../components/stem_separation/README.md)

### `unknown_preset`

**Cause.** The preset is none of `hybrid`, `demucs`, `demucs6`, `roformer`, `mdx`, `custom`.

**Fix.** Use one of the declared values.
→ [`components/stem_separation/README.md`](../components/stem_separation/README.md)

### `too_few_stems`

**Cause.** The separator returned fewer than 2 output files.

**Fix.** Investigate the separator run and the input; the required minimum is two stems.
→ [`components/stem_separation/README.md`](../components/stem_separation/README.md)

## YAML parser gotchas

The engine runs without PyYAML on bare systems, using a subset parser; constructs outside the
subset are rejected at validation (the `_reject_unsupported` rule) or — for the legacy Bash
validator — must be avoided. Everything below matches `docs/format.md` "Known Limitations and
Parser Gotchas". Rule of thumb: if a chain parses differently on two machines, it is a
different chain.

### `Missing required field: version` / `steps` — but the fields are there

**Symptom.** A chain with a multi-line `description: >` (or `|`) fails validation with
`Missing required field: version`, even though both fields are present.

**Cause.** A block scalar. The stdlib fallback parser consumes the bare `>` as the
description value and misparses the continuation lines, producing a broken structure and a
misleading error. The Bash validator makes it worse: its `grep`-based field check reports
"Chain validation passed" for the same file — a false positive (fails open in the worst
direction).

**Fix.** Use single-line quoted strings for every description:

```yaml
description: "A long description spanning multiple lines."
```

### Parameter values come out wrong — e.g. `target_lufs: *tgt` stays literal

**Symptom.** Repro'd in `docs/format.md`:

```json
{"globals": {"target_lufs": "&tgt -21"}, "steps": [{"params": {"target_lufs": "*tgt"}}]}
```

**Cause.** YAML anchors (`&name`) and aliases (`*name`) are not supported by the fallback
parser. `&anchor` is kept verbatim in the scalar; `*alias` is treated as a literal string,
not dereferenced — so the wrong value runs, silently.

**Fix.** No anchors or aliases. Repeat values explicitly.

### A value contains `# inline comment` text

**Symptom.** `name: my-chain  # inline comment` parses as the string
`"my-chain  # inline comment"`.

**Cause.** The fallback parser and the Bash parser both include the inline comment in the
value (full-line comments are correctly stripped on both).

**Fix.** Put comments on their own lines.

### A flow list spanning multiple lines produces garbage structure

**Symptom.** A `params:` block like:

```yaml
params:
  checks: [
    "format",
    "loudness"
  ]
```

**Cause.** Flow collections (`[...]` / `{...}`) are only supported on a single line.

**Fix.** Open and close on the same line:

```yaml
params:
  checks: ["format", "loudness"]
```

## Exit codes

| Code | Meaning | Typical cause to fix |
|---|---|---|
| `0` | success | — |
| `1` | execution error | A step failed preflight or verification; see the entries above. |
| `2` | input error | The input file is missing, unreadable, or unacceptable. |
| `3` | config error | CLI configuration is broken (see `workchain config`). |

These values are declared in [`agent.json`](../agent.json) and `llms.txt`; they are part of
the interface contract, so an agent can branch on them without parsing prose.

**If the exit code is `0` and the audio is still wrong** — that is not a config problem, it
is a missing or weak contract. The project treats that exact report as its most wanted bug
class; open an issue with the chain, the input, and measured vs expected values.
→ [`CONTRIBUTING.md`](../CONTRIBUTING.md)

---

## Provenance of quoted output

- `verification FAILED` block, `Chain halted: step 'normalization' failed`, `measured -10.56
  LUFS vs target -5.0 (±1.0) → off by 5.56 LU` — verbatim from [`README.md`](../README.md)
  (grep `verification FAILED`).
- `silent_input_skipped` — verbatim naming from `components/normalization/README.md`.
- Preflight failure block — observed on a stock golden VM running
  `chains/tests/stem_separation_demucs.yaml` with no venv provisioned; the line format comes
  from `lib/workchain_preflight.py` and `engine/workchain-engine.sh`.
- `audio_separator_not_found`, `model_required`, `unknown_preset`, `too_few_stems` — verbatim
  failure reasons from `components/stem_separation/README.md` and `run.sh`.
- YAML gotchas — symptom, repro, and fixes match `docs/format.md` "Known Limitations and
  Parser Gotchas" (the anchors repro JSON is quoted from that file).
- Exit codes — from `agent.json` `io.exit_codes`.