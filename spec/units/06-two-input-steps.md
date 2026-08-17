# Unit 06 — two-input (`in2:`) steps (issue #10)

## Objective
Let a step declare a second audio input (`in2:`) that the engine stages and routes to the component, with verifier support and a working sample chain — the first prerequisite of chain topology beyond linear.

## Context
- Issue #10 (roadmap) — four checkboxes: schema, engine step-runner staging, verifier handling, docs + sample chain.
- **Unit 03 (wave 0, must be merged first) delivers per-step `id:` and the validated step schema in `lib/workchain_yaml.py` + `docs/format.md`.** This unit builds on it: another step key in `context.json`, another staged file per step, another positional to the component script.
- How a single input flows today: `engine/workchain-engine.sh` stages the input and invokes the step; `engine/step-runner.sh` (`get_context_value "steps.${step_name}.output"`, script invocation around line 121) and the run.sh contract (`$INPUT_FILE` / the standard env the bash components read; see `components/format_conversion/run.sh` for the canonical consumer shape).
- Verifier: `lib/workchain_verify.py` resolves the step's outputs from `ctx["steps"]`; a two-input post-condition needs both input-derived facts resolvable (e.g. a duration or format check against either input).
- The issue references `docs/product/workchain/08-chain-topology.md` — **that file does not exist in the tree.** This unit creates the topology doc (the natural home for the design) and can either create it at that path or at `docs/format.md`'s sibling; pick one and say so in the PR.
- No component in the registry consumes two inputs today — the sample chain needs a path to exist. Add a minimal two-input component (e.g. `mix`: ffmpeg `amix`/`amerge` of the two inputs with an `audio_valid` + duration post-condition) as part of this unit, or reuse nothing — but the sample must be real, not a stub.

## Acceptance criteria
- [ ] Schema: a step may declare `in2:` (path/glob or reference to another step's output — decide and document the accepted forms in `docs/format.md`; whatever form is chosen must parse under the **one** parser, `lib/workchain_yaml.py`, and validate under `validate --strict`).
- [ ] Engine: a step with `in2:` has its second input staged, and the component receives it and only it — `run.sh` sees the primary via the existing mechanism and the second via a documented, unambiguous channel (positional `$2`, or an env var, **one** choice, documented in `docs/format.md` and the component contract docs).
- [ ] Both inputs' provenance is recorded: the run JSON records each input's resolved path and (where practical) its hash — so a two-input post-condition can name which fact it measured.
- [ ] Verifier: at least one existing post-check class works against a two-input step's record (e.g. duration/format measured on either input), and the docs explain the model for two-input post-conditions.
- [ ] Sample chain: `chains/examples/two-input.yaml` (or `chains/tests/`) runs a two-input step end-to-end on two real inputs and verifies both sides of what it claims — no empty `verify:` block, README honest about which checks are independent re-measurements vs component-written facts.
- [ ] Duplicate/id interplay: two steps in one chain, or one step with an in2 referencing itself, cannot silently produce a bad record — the id model from unit 03 plus the new staging must fail closed.
- [ ] `docs/format.md` documents `in2:`; the topology doc is created; `./tools/release-check.sh` green; `workchain registry generate && registry check` clean (the new component dir changes the index).

## Interface contract
- The component contract for two-input steps: exactly one new, documented channel for the second input; existing single-input components are untouched and must still pass all existing chains (byte-identical behaviour for chains without `in2:`).
- `context.json` gains the recorded second-input provenance under the step's id; the shape is documented in `docs/format.md`.
- Downstream (`probe`, verifier) must tolerate `in2:` chains without special-casing that breaks single-input chains.

## Boundaries — do NOT touch
- `components/cdp_transform/**` (units 02/07/08) — unless the new demo component lives elsewhere (`components/mix/` is fine, new space).
- `cli/**` (units 04/05) — verify through the CLI, edit nothing there this unit.
- Do not implement graph topology beyond two inputs (multiple in2, outputs as inputs to later steps is unit 06+ scope, not this one) — keep it to the stated first-prerequisite scope.
- No new third-party dependencies for the demo component: ffmpeg (already required) is enough.

## Output
Two or three PRs, reviewable in this order: (1) schema + docs (`lib/workchain_yaml.py`, `docs/format.md`, topology doc), (2) engine staging + routing (`engine/workchain-engine.sh`, `engine/step-runner.sh`, verifier touch in `lib/workchain_verify.py` only for resolving two-input records), (3) demo component + sample chain (`components/mix/`, `chains/examples/two-input.yaml`, regenerated `components/index.json`). **Pre-dispatch note: if the agent estimates > 3 days, split before starting — (schema+docs) as one unit, (engine+verifier) as another, (demo+chain) as a third — do not discover the split mid-flight.**

## Verification
```bash
# two real inputs (generate with ffmpeg; do not commit noise):
ffmpeg -f lavfi -i sine=frequency=440:duration=2 inA.wav
ffmpeg -f lavfi -i sine=frequency=880:duration=2 inB.wav
python3 lib/workchain_yaml.py validate . chains/examples/two-input.yaml
./engine/workchain-engine.sh -c chains/examples/two-input.yaml inA.wav -o out \
    # with in2 declared per the docs you wrote (chain file or engine flag — single documented channel)
python3 -c "import json; d=json.load(open('out/context.json'))['steps']; print(sorted(d))"
node cli/bin/workchain.js validate all --strict
node cli/bin/workchain.js registry generate && node cli/bin/workchain.js registry check
./tools/release-check.sh
```
Leave one of the two inputs silent (or a mismatched duration) once, and show the verify block catching it — that is the "prove it can fail" evidence for the two-input contract.