# Unit 04 — `run-component cdp_transform --list-effects` (issue #24)

## Objective
Implement the `--list-effects` option that `cdp_transform/step.yaml`'s `effect` parameter description already advertises, so a 232-effect / 109-group catalog is listable by an agent without writing a script against the installed package — with `--json` as the primary form, and with resolution following the exact same path a real run uses.

## Context
- Issue #24 — the documented flag currently errors: `error: unknown option '--list-effects'`.
- Command surface: `cli/commands/run-component.js` (agent-facing `run-component`; already distinguishes file vs batch input, honours global `--json`). Options are parsed by commander in `cli/bin/workchain.js` — follow the existing pattern for adding a flag (look at how sibling commands declare options).
- Resolution order that a run actually uses (must be mirrored exactly): `cdp_wasm_dir` param → `CDP_WASM_DIR` env → normal `node_modules` resolution. Read the real logic in `components/cdp_transform/run.sh` (~line 51, 79–80) and `transform.mjs` (lines 29–48, the `arg('lib', process.env.CDP_WASM_DIR || '')` path incl. `src/index.js` vs `index.js` candidates).
- Catalog data: `EFFECTS` from the resolved `cdp-wasm` package (per the issue: destructure `e.params` for per-effect `min`/`max`/`default`). Do **not** hardcode the 232/109 counts — derive them.
- The `doctor` and `components` commands are the established "what can I use here" pattern — the flag should feel like one of those.

## Acceptance criteria
- [ ] `node cli/bin/workchain.js run-component cdp_transform --list-effects` prints id, group, output count and each parameter's `min`/`max`/`default` for every effect, without requiring an input file (it must not demand the `<input>` positional — check the current commander setup for how to make it optional when the flag is present).
- [ ] `--list-effects --json` emits parseable JSON with the same content; shape is deterministic (stable key order, no timestamps)
- [ ] It honours the same resolution order: with `CDP_WASM_DIR` set to a directory, the listing comes from **that** catalog; with it unset, from normal resolution; `cdp_wasm_dir` param analog if run-component supports params. Prove with a run against the separately-installed copy used for the 0.6.0 checks (or after unit 01 lands, against the lockfile version).
- [ ] The printed effect count equals the catalog's actual `EFFECTS` count (derived, not asserted from the issue text), and the `step.yaml` description sentence remains true — do not weaken the docs.
- [ ] Fails honestly (clean CLI error, non-zero exit) when cdp-wasm cannot be resolved at all.
- [ ] `npm test` green (add a unit test for the formatter/listing helper); `workchain doctor` clean.

## Interface contract
- New CLI option: `--list-effects` (and `--json` via the existing global). **No change** to existing `run-component` behaviour or output shape for current invocations — the flag is additive.
- The listing must use the **same catalog resolution** as a run, so a listing and a run can never disagree about what effect ids exist. If that means a small shared helper, it lives in a **new** file `cli/lib/cdp-catalog.js` (this unit owns the file; unit 05's import-audit test must allow optionalDependencies imports — flag it in that PR if it trips).

## Boundaries — do NOT touch
- `components/cdp_transform/transform.mjs`, `step.yaml`, `README.md`, `components/index.json` — units 02/07 own the component dir this wave. Read the resolution logic; implement yours in `cli/`.
- `package.json` / `package-lock.json` / `cli/package.json` — unit 01 owns the dependency bump this wave; if the lockfile is stale in your working tree after 01 merges, rebase rather than edit it meaningfully here.
- `cli/lib/config.js`, `cli/lib/engine.js`, `cli/lib/formatter.js` beyond the minimal plumbing — unit 05 owns infra refactors.
- Any change to the catalog itself or to run behaviour.

## Output
One PR: `feat(cli): cdp_transform --list-effects [--json]`. Files: `cli/commands/run-component.js` (flag + branch), new `cli/lib/cdp-catalog.js` (resolution + formatting helpers), unit test under `cli/test/`, and (only if the docs sentence needs precision) a one-line `step.yaml` wording touch — otherwise no component edits at all.

## Verification
```bash
node cli/bin/workchain.js run-component cdp_transform --list-effects | head -30
node cli/bin/workchain.js run-component cdp_transform --list-effects --json | python3 -m json.tool | head -40
# resolution-order proof:
CDP_WASM_DIR=/tmp/cdp-wasm-0.6.0 node cli/bin/workchain.js run-component cdp_transform --list-effects --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["effects"]))'
# absent-library failure:
# (temporarily via a bogus CDP_WASM_DIR) expect a clean CLI error and non-zero exit
cd cli && npm test
```
Report the two derived counts (`EFFECTS` size and group count) from the real runs.