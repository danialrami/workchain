# Unit 07 — independent peak re-measurement: `audio_peak_above` POST_CHECK (issue #9)

## Objective
Add `audio_peak_above` to the verifier's POST_CHECKS so true-peak/level claims are **re-measured independently** (ffmpeg) rather than trusted from the component's own logged value, and wire it into the `cdp_transform` contract — replacing the admitted gap in its README.

## Context
- Issue #9 (roadmap, now unblocked) — checklist: design the post-check, implement in `lib/workchain_verify.py`, wire into relevant step.yaml verify contracts, update release-check coverage.
- The gap is already honestly documented: `components/cdp_transform/README.md` lines ~86–93 state explicitly that the peak floor is enforced only via `json_fields_within` on the component's own record and that "There is no `audio_peak_above` post-condition in `lib/workchain_verify.py`". This unit closes that: the README sentence must be updated as part of wiring, not left stale.
- The `json_fields_within` honest-docs pattern: `AGENTS.md` ranks checks — `json_fields_within` reads values the component wrote about itself (legitimate, weaker). `audio_lufs_within` is the model independent check (re-measures via `ebur128`). See `lib/workchain_verify.py` `check_audio_lufs_within` (~line 197) and `check_json_fields_within` (~line 799), and the POST_CHECKS dict (~line 1031).
- `cdp_transform/step.yaml` post-conditions: `output_is_live_audio` uses `measured_peak_dbfs > -60` from the component's own record (unit 02 owns that file in wave 0 — **must be merged first**).
- `normalization` also makes a true-peak claim (`true_peak` param, `loudness_metadata` output) — candidate for the same check.
- Re-measurement tool: ffmpeg (`astats` or `volumedetect`; `audio_lufs_within` already proves the ffmpeg-probe pattern).
- Design freedom is intentionally left to this unit (the issue's first checkbox): decide what the check asserts (e.g. `measured_peak_dbfs > threshold` on a named output, tolerance in dB), and document the choice in the README with the same precision `audio_lufs_within` gets.

## Acceptance criteria
- [ ] `audio_peak_above` is registered in POST_CHECKS and implemented as an independent re-measurement (probe with ffmpeg, not the component's record), asserting a peak **above** a threshold (and, if designed so, a `below` counterpart only if the design justifies it — keep the scope to the issue's name).
- [ ] An empty post-condition resolves to **FAIL** (per AGENTS.md: zero assertions must not pass) — the check fails when the measured value is missing or unmeasurable.
- [ ] Wired into `cdp_transform/step.yaml` (the `-60` floor becomes an `audio_peak_above` post-condition in addition to the component-side floor) and the README's gap sentence is replaced with the truthful description of the new independent check.
- [ ] `normalization` gets the same check where its `true_peak` claim can be re-measured, or an honest note in its README if not (mirroring the `json_fields_within`-weaker declaration rule).
- [ ] **Prove it can fail:** a render whose true peak is below the threshold (filter rejecting the passband, per the existing `chains/tests/normalization_offtarget.yaml` pattern or a cdp_transform variant) makes the chain FAIL via `audio_peak_above` — show the red run; and a healthy render passes.
- [ ] Release-check coverage: a chain exercising `audio_peak_above` is part of `./tools/release-check.sh`'s suite (see how `normalization_offtarget.yaml` / chains/tests are wired).
- [ ] `workchain registry generate && registry check` clean (step.yaml touched); `tools/doc-check.sh` clean; `npm test` green.

## Interface contract
- New POST_CHECK name: **`audio_peak_above`**; parameters follow the existing post-condition schema (see `docs/format.md` and how `audio_lufs_within` is declared in `normalization/step.yaml` lines ~86–87). Public names/units (dBFS) documented in `docs/format.md`.
- Does not change the ctx/steps keying model from unit 03 — resolves the step's record by the effective id like every other check.
- Does not change `cdp_transform`'s param semantics: `min_peak_dbfs` stays a **component** floor; the post-condition is the verifier's independent re-measurement of it. The README must keep saying they are deliberately independent (loosening the parameter cannot loosen the contract).

## Boundaries — do NOT touch
- `transform.mjs` render/record internals (unit 02) — this unit measures the output file, it does not change what the component records.
- `engine/**` and preflight (unit 03 owns through wave 0; afterwards read-only for this unit).
- `cli/**` (units 04/05).
- `cdp-wasm` version/policy (unit 01).
- Do not rename or reshape existing POST_CHECKS names.

## Output
One PR: `feat(verify): audio_peak_above independent peak re-measurement`. Files: `lib/workchain_verify.py`, `docs/format.md` (if the check's params need documenting there), `components/cdp_transform/step.yaml` + `README.md`, `components/normalization/step.yaml` + `README.md` (or honest note), a failing fixture chain under `chains/tests/`, `tools/release-check.sh` wiring if needed, regenerated `components/index.json`. PR description shows design decision + the red/green run pair.

## Verification
```bash
# red: filter a source so the output peak is below the floor, run the fixture chain — must FAIL via audio_peak_above
./engine/workchain-engine.sh -c chains/tests/<peak-floor-fail>.yaml <input> -o /tmp/u07a
# green: same chain with a healthy input — passes
python3 -c "import json; print(json.load(open('/tmp/u07a/context.json'))['steps'])"
node cli/bin/workchain.js registry generate && node cli/bin/workchain.js registry check
./tools/release-check.sh --cdp
tools/doc-check.sh
```
Quote the measured peak from the failing run in the PR (a real number, from your run).