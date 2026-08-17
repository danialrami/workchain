# Unit 03 — per-step identity: two steps of one component must each keep a verification record (issue #22)

## Objective
Give a step an optional `id:` (defaulting to its component name), key `context.json`'s `steps` map on that id, and fail validation when two steps in one chain resolve to the same id — so a duplicate-component chain is either faithfully recorded or refused, never silently overwritten.

## Context
- Issue #22 — contains the repro (two `cdp_transform` steps validate, both run, one record survives), the three options, and the recommendation (option 2, per-step identity, with option 1 as interim guard — this unit implements option 2 including the unique-id validation, which is the fail-closed form).
- Keying today: `engine/workchain-engine.sh` `record_step_params()` (`ctx.setdefault("steps", {}).setdefault(step, {})["params"] = params`) and `engine/step-runner.sh` (`get_context_value "steps.${step_name}.output"`); `__WC_STEP` env carries the name. The name **is** the component name.
- Readers of `ctx["steps"]`: `lib/workchain_preflight.py` (lines ~114, 357–362) and `lib/workchain_verify.py` (lines ~155, 290, 313, 439). All keyed on the component name — that becomes "the step's effective id".
- All chain/step validation lives in **one parser**: `lib/workchain_yaml.py` (delegated to by `engine/chain-validator.sh`; the CLI validates the same way). The schema change and the duplicate-id rejection both go there — no fourth parser, no grep validator.
- Step schema is documented in `docs/format.md` — the `id:` field must be documented there.
- Requirement: **single-step chains and chains with one instance per component must behave byte-identically** to today (id defaults to name ⇒ existing chains unchanged).

## Acceptance criteria
- [ ] A step may declare `id:` (string). Resolution: `id` if present and non-empty, else the step's `name` (component name). `name` **remains** the component to execute and to resolve files for (`resolveComponentDir`); `id` is purely the record key — documented in `docs/format.md`.
- [ ] Validation (`workchain validate --strict` and the engine's own path) **fails** with a precise message when two steps in one chain resolve to the same id. Show the red run: the issue's `probe-two-cdp.yaml` must now FAIL validation (or, with explicit distinct `id:`s, validate and record both).
- [ ] The issue's repro chain, rewritten with explicit `id: trace` / `id: blur`, runs both steps and **both records survive**: `list(json.load(open('out/context.json'))['steps'].keys())` is `['trace', 'blur']` with each holding its own `params`, `outputs`, and verification result.
- [ ] Single-step and single-instance chains behave byte-identically to before (id absent or equal to name ⇒ key stays the component name).
- [ ] The verifier's per-step lookups resolve the **current step's** record via the same key the engine wrote (no component-name fallback that re-introduces the overwrite — see the verification below for the case that must stay broken).
- [ ] All preflight/verify component tests and `npm test` green; `./tools/release-check.sh` (without `--cdp`) green.

## Interface contract
- `context.json` shape: `steps` is keyed by **step id** (defaults to component name). For existing chains nothing observable changes.
- `__WC_STEP` (set by the engine when invoking the record/verify helpers) carries the **effective id**, not the raw name, when they differ.
- Step schema in `lib/workchain_yaml.py` and `docs/format.md`: optional `id`, `type: string`, no `required` key (per AGENTS.md, nothing else either).
- Downstream readers must not assume `steps` map order; nothing else changes.

## Boundaries — do NOT touch
- `components/cdp_transform/*` — units 02 and 07 own them; you may read them (they exercise the id model) but not edit.
- `cli/commands/**` and `cli/lib/cdp-catalog.js` — units 04 owns command surface; `cli/lib/config.js`/`engine.js`/`formatter.js` — unit 05 owns infra. If you need the CLI for verification, use `node cli/bin/workchain.js`, don't edit it.
- The `in2:` feature (unit 06) builds on top of this unit's `id` model — do **not** implement any second-input plumbing here.
- Client code that reads context must not be refactored beyond the keying change.

## Output
One PR: `feat(engine): per-step id, context keyed on it, duplicate-id validation`. Files: `lib/workchain_yaml.py`, `engine/workchain-engine.sh`, `engine/step-runner.sh`, `lib/workchain_preflight.py`, `lib/workchain_verify.py`, `docs/format.md`, plus a test chain under `chains/tests/` (e.g. `two_same_component.yaml` with distinct ids) and a failing-validation fixture. PR description shows the three runs: duplicate-id refused, distinct-ids both recorded, single-instance byte-identical.

## Verification
```bash
# 1) refused: the unmodified repro from issue #22 must FAIL validation
python3 lib/workchain_yaml.py validate . probe-two-cdp.yaml     # expect invalid, precise duplicate message
# 2) both recorded: with distinct id: fields
./engine/workchain-engine.sh -c chains/tests/two_same_component.yaml bell.wav -o out
python3 -c "import json; d=json.load(open('out/context.json'))['steps']; print(list(d.keys())); [print(k, sorted(d[k])) for k in d]"
# 3) regression: existing single-instance chains, before/after diff of context.json keys
node cli/bin/workchain.js validate all --strict
node cli/bin/workchain.js registry check
npm test
./tools/release-check.sh
```
Note: `bell.wav` — use the repo's usual fixture input; if the repro needs a real WAV, create one with ffmpeg (`ffmpeg -f lavfi -i sine=frequency=440:duration=2 bell.wav`) — do not commit fixture noise to the repo unless a fixture already exists.