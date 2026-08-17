# Unit 01 — cdp-wasm dependency bump (issue #23)

## Objective
Ship `optionalDependencies.cdp-wasm` as `^0.6.0` (the release containing the `stretch.time` zero-frame guard from our own upstream report, cdp-wasm-suite/cdp-wasm#4), verify the three CDP chains against it, and record the range policy decision.

## Context
- Issue #23 (full reasoning and the verified 0.6.0 result: `60 passed, 0 failed, 1 skipped`).
- `package.json` at repo root: `optionalDependencies: { "cdp-wasm": "^0.5.3" }`. `^0.5.3` resolves `<0.6.0`, so the current declaration is the version with the bug we reported.
- `cli/package.json` has **no** optionalDependencies block — the bump touches only the root manifest plus `package-lock.json`. Do not add a block to `cli/package.json`.
- CDP tests: `./tools/release-check.sh --cdp` (exercises `chains/tests/cdp_transform*.yaml` + `chains/cdp-*.yaml`; needs cdp-wasm installed or `CDP_WASM_DIR` set).
- Policy question from the issue: caret-on-minor vs `>=0.6.0` given the catalog grows by minor version and parameters are validated against the *present* catalog at run time.

## Acceptance criteria
- [ ] Root `package.json` declares `"cdp-wasm": "^0.6.0"` (or the chosen policy range), and `package-lock.json` reflects it (`npm install`, committed).
- [ ] `./tools/release-check.sh --cdp` passes against the bumped version using the **normal resolution path** (installed from the lockfile, not `CDP_WASM_DIR` pointing at a separately-installed copy).
- [ ] A `components/cdp_transform` run still works with `allow_unlocked_range: true` (the bypass the guard backstops) — no regression in the out-of-range validation layer.
- [ ] The policy decision is written down in the unit's PR description: `^0.6.0` vs `>=0.6.0`, with a one-paragraph rationale. If `>=0.6.0` is chosen, say why broader is safe for an optional peer-ish dependency.
- [ ] `workchain registry check` clean (nothing in a component changed, but confirm), `npm test` green.

## Interface contract
- The **name** `cdp-wasm` and the **optionality** are unchanged — only the range moves. Optional means the CDP component must still fail honestly (preflight `models`/`python`-class error, not a crash) when the package is absent.
- Unit 04 (`--list-effects`) reads the catalog from whatever version resolves; 04 should land after this PR so the shipped range is what gets listed.

## Boundaries — do NOT touch
- `cli/package.json`, `cli/package-lock.json` — owned by unit 05; it will restructure manifests after this lands (this unit's bare lockfile change to the root is the only lockfile touch this wave).
- `components/cdp_transform/*` — owned by units 02/07 running in parallel. You may **run** them for verification, not edit them.
- The `render_is_deterministic` check (unit 02's surface) must not be "fixed" here even though 0.6.0 changes render behaviour — that is a separate unit.

## Output
One PR: `chore(deps): cdp-wasm ^0.5.3 -> <chosen range>` touching `package.json` + `package-lock.json` only, PR description containing the policy rationale.

## Verification
```bash
cd cli && npm install          # refresh root lockfile if needed (root gets regenerated from package.json)
cd .. && npm install           # regenerates package-lock.json against new range
rm -rf node_modules && npm ci  # prove lockfile installs clean
node cli/bin/workchain.js registry check
npm test
./tools/release-check.sh --cdp   # the 60/0/1 result from the issue must reproduce
node cli/bin/workchain.js doctor  # preflight stays clean
```
Show the `--cdp` tally in the PR.