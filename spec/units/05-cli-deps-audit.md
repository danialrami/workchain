# Unit 05 — CLI dependency audit: 63 → ≤21 packages (issue #7)

## Objective
Take the published CLI from 63 packages / 18 MB for 6 direct deps down to **≤ 21 packages (steps 1–2), ideally ≤ 5 (step 3)**, with byte-identical behaviour and a contract test that would have caught `globby`'s drift the day its last call site was deleted.

## Context
- Issue #7 is the authoritative audit: measured baseline table (globby 24 pkgs / zero call sites, conf 18 pkgs incl. ajv 2.4 M, execa 16 pkgs, commander/chalk/split2 single-site), the five-step fix, the acceptance criteria, and the non-goals. **Read the full issue before starting.**
- The manifests: root `package.json` and `cli/package.json` both carry the identical six-entry `dependencies` block (verified identical today — F5). `cdp-wasm` is optional in the root only; `cli/package.json` has no optionalDependencies.
- Do the five steps **in the issue's order** and stop whenever the number is good enough (steps 1–2 are the required core; 3 is a decision, 4 is cosmetic, 5 is the enforcement).
- Unit 01 (wave 0, must be merged first) bumped `cdp-wasm` in the root manifest and lockfile — rebase onto it; keep that bump.
- Unit 04 (wave 0) adds `cli/lib/cdp-catalog.js` importing nothing extra beyond `node:path`/`node:fs` (it mirrors resolution in pure Node, no new deps) — the step-5 import-audit must permit imports of `cdp-wasm` from **optional** dependencies too.
- AGENTS.md: no CLI output-shape changes — agents parse `--json`; that contract does not move.

## Acceptance criteria (from the issue, made checkable)
- [ ] Step 1 lands: `globby` gone from both manifests; `npm ls --all --parseable | wc -l` drops **63 → 39** (measure at the current merged state first; report the before/after).
- [ ] Step 2 lands: `conf` replaced by `cli/lib/config.js` internals (XDG/`APPDATA` path rules, `JSON.parse` with tolerant read, temp-write + `renameSync` atomic replace) with the **same exported API** so no command changes; `39 → 21` and `ajv` gone.
- [ ] Byte-identical behaviour: `components`, `chains`, `validate all --json`, `doctor`, `config get/set`, and one real `run` (e.g. format_conversion or normalization) produce byte-identical stdout/JSON (modulo nothing — compare against a baseline captured pre-change).
- [ ] Step 3 (only if pursuing ≤5): `execa` replaced **in one PR with all six call sites converted together** to a `node:child_process` promise helper (`cli/lib/engine.js` + others); partial conversion is explicitly forbidden (two spawn conventions is worse than the dep). If not pursuing, say so and keep `execa`.
- [ ] Step 5 lands: `dependencies` declared in exactly one place (drop the block from `cli/package.json`, or generate it with a check that the two agree), and a contract test fails when any `import`/`require` in `cli/` resolves to a package not declared (allowing `cdp-wasm` via optionalDependencies). **Show this test failing first** (introduce a stray import on a branch, watch it go red, then restore).
- [ ] `npm test` green; `workchain registry check` clean (no component touched — confirm only); `./tools/release-check.sh` green.

## Interface contract
- Public surface unchanged: the 12 commander commands, all `--json` shapes, `config get/set` semantics, help text. Only internals and node_modules change.
- `cli/lib/config.js`: keep exports identical so CLI commands don't change — the unit is internal.
- `cdp-wasm` stays `optionalDependencies`; the CDP component keeps working when installed and fails honestly when not.

## Boundaries — do NOT touch
- `components/**` (units 02/07 wave work) — call, don't edit.
- `cli/commands/run-component.js` and `cli/lib/cdp-catalog.js` (unit 04) — keep them compiling and the import-audit tolerant of them; do not refactor them.
- `commander` (non-goal), `cdp-wasm` (non-goal), bundling/minifying (non-goal).
- Do not renumber the issue's five steps or merge two steps into one commit unless the issue already says so.

## Output
One PR per step at minimum (steps 1–2 may be one PR if reviewable together; step 3 and step 5 separate). PRs: `chore(cli): drop globby (~24 packages)`, `chore(cli): replace conf with native config module`, optional `chore(cli): replace execa with child_process wrapper`, `test(cli): import-audit contract test + single manifest`. Each PR reports the measured before/after `wc -l` and the byte-identical check.

## Verification
```bash
npm ls --all --parseable | wc -l                      # before/after per step: 63 → 39 → 21 (→ 5)
du -sh node_modules
node cli/bin/workchain.js components --json > /tmp/after.json   # diff vs pre-change baseline
node cli/bin/workchain.js validate all --json | tail -5
node cli/bin/workchain.js config set demo_key demo_value && node cli/bin/workchain.js config get demo_key
# atomic-replace proof: kill -9 during a config write, then re-read — file must be intact (old or new, never torn)
npm test
./tools/release-check.sh
```
The "prove it can fail" requirement applies to the step-5 contract test specifically (see criterion).