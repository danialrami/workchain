# Unit 08 — `stereoUnsafe` catalog flag: decide, then document (issue #11)

## Objective
Resolve issue #11 — which is a decision-and-documentation task, not a feature push — now that its upstream condition is met (cdp-wasm-suite/cdp-wasm#4 closed, the guard shipped in 0.6.0, and unit 01 bumps us onto it).

## Context
- Issue #11 (roadmap, explicitly "not blocking release") — three checkboxes: confirm current cdp-wasm behavior/catalog fields; decide whether to report `stereoUnsafe` per-effect now or wait; document the decision.
- After unit 01: resolved cdp-wasm is ≥ 0.6.0, which contains the guard from cdp-wasm#4.
- After units 02/04/07: `transform.mjs` records per-effect facts and the catalog is listable via `--list-effects` (unit 04) — the natural homes for a flag, if one is added.
- `components/cdp_transform/step.yaml` has a `channels: split|mix` param already describing the mono-compat concern this flag would address (README section on mono-compatibility, mentioned in the step.yaml param description).
- The question standing in the issue: does our catalog view surface which effects can produce stereo output that a mono assumption would mishandle, and do we report the signal upstream to cdp-wasm?

## Acceptance criteria
- [ ] The investigation checkbox is answered in the PR: cdp-wasm ≥ 0.6.0's catalog fields relevant to stereo/mono are inspected and quoted **from the installed package** (point to the file/field, do not paraphrase from memory).
- [ ] A decision is made and recorded: surface `stereoUnsafe` in our catalog view now (small: extend the `--list-effects` output unit 04 built, plus a `stereo_unsafe` note in the step.yaml `channels` description), or defer with a concrete trigger. Either is acceptable **if the chosen option is argued from the inspected evidence** — do not default to "do it all" or "skip" to satisfy the checkbox count.
- [ ] If the flag is added: `--list-effects [--json]` includes it per effect, `channels` doc mentions it, and the README's mono-compatibility section names which effects are flagged (from real inspection, not invented).
- [ ] The decision about upstream reporting is documented: whether to open/propose against cdp-wasm (friendly first contact — the repo's own upstream relationship already exists via cdp-wasm#4), or file an internal note with a trigger. If an upstream proposal is made, use the submitting-an-issue standard (research before filing).
- [ ] No behavioural change to rendering; no new dependencies; registry/docs gates stay clean.

## Interface contract
- If the flag ships: name is **`stereoUnsafe`** (case per the issue), boolean, per-effect in the resolved JDEC catalog and in `--list-effects` output. The same resolution order a run uses (unit 04's helper) must be the one inspected for real flags.
- If deferred: the doc (topology doc from unit 06 or the component README) states the trigger that would un-defer it.

## Boundaries — do NOT touch
- Verifier/engine (units 03/06/07), manifests (units 01/05), transform.mjs render logic (unit 02 — the catalog *view* in `--list-effects` is unit 04's file; touch that only if the flag ships, and only its listing side).
- Do not change what `cdp_transform` renders, its params, or its post-conditions.
- No new runtime dependencies — none are needed for a flag.

## Output
One PR, likely mostly prose: `docs(cdp_transform): stereoUnsafe decision + (flag | defer note)`. Expected: updated `README.md`, possibly `cli/lib/cdp-catalog.js` + `cli/test` if the flag ships, and the topology/nearby doc recording the decision. The acceptance bar is the *recorded, evidence-based decision*, not the size of the diff.

## Verification
```bash
# (flag ships) both forms show the field, derived from the installed catalog:
node cli/bin/workchain.js run-component cdp_transform --list-effects | head -20
node cli/bin/workchain.js run-component cdp_transform --list-effects --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print([e for e in d["effects"] if e.get("stereoUnsafe")][:5])'
# (either way)
node cli/bin/workchain.js registry check
./tools/release-check.sh --cdp
tools/doc-check.sh
```
The "prove it can fail" bar here is softer (this is a decision unit) but **the sourced evidence is not**: every claim about cdp-wasm's catalog must trace to the installed package's fields, quoted in the PR.