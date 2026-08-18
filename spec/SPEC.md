# SPEC — clear the 8 open issues on lufs-audio/workchain

> These are operational plan documents (the fan-out briefs), not product docs, so they live in `spec/` outside the doc-gate's `docs/` tree. The unit contracts are the dispatch + review contract for this run.

State: `main` @ `90bfb75`, clean tree. All 8 issues open, none started. No `docs/units/` existed before this write.

## Problem

The repo carries eight open issues (as of 2026-08-17). They fall into three groups:

**Correctness / honesty defects (the ones that matter most for an engine whose thesis is "proven correct, not merely exited 0"):**

- #21 — `cdp_transform`'s `render_is_deterministic` proves determinism by hashing the *file container*, which embeds wall-clock fields (PEAK chunk timestamp, LIST/adtl DATE). Bit-identical audio fails the hash when two renders straddle a second boundary. The check passes on luck. A sample-hash fix is drafted in the issue.
- #22 — a chain with two steps of the same component runs both, validates clean, and **overwrites** the first step's verification record in `context.json` (keys `steps` by component name). Proof is silently deleted while the run reports success.
- #23 — `optionalDependencies: "cdp-wasm": "^0.5.3"` **cannot install 0.6.0**, the release containing the fix from our own upstream report. We ship against the bug we reported.
- #24 — `cdp_transform/step.yaml` documents `--list-effects`, which errors. Docs and code disagree; the flag is a good idea and the 232-effect catalog is otherwise unlistable without writing a script.

**Dependency hygiene:**

- #7 — 63 packages / 18 MB for 6 direct deps. `globby` (24 packages) has zero call sites; `conf` drags `ajv` (2.4 M) for an 84-line config module. Several independent, ordering-safe steps; the issue itself decomposes them.

**Roadmap (non-blocking):**

- #9 — add `audio_peak_above` POST_CHECK so peak/level claims are re-measured independently instead of trusting the component's own logged value (`json_fields_within` reads what the component wrote about itself).
- #10 — two-input (`in2:`) steps. The largest unit by far; prerequisite is per-step identity (#22) so context can hold two records.
- #11 — `stereoUnsafe` catalog flag; decide-and-document, upstream condition (cdp-wasm#4) is now closed/landed (0.6.0), so this is actionable.

## Goals / constraints

For every unit:

- **Per-issue PRs, one branch each, no cross-unit commits.** Every unit is independently reviewable and mergeable.
- **The AGENTS.md gates are non-negotiable.** No empty `verify:` blocks; stdout is final JSON; `return` not `exit` in run.sh; never hand-edit `components/index.json` (regenerate); never hand-write a hash to make a gate pass; all YAML through `lib/workchain_yaml.py` (one parser).
- **Prove the test can fail.** Every unit that adds or changes a contract must first observe the *broken* behaviour (red), then the fixed behaviour (green). A check nobody has seen fail is decoration.
- **Measured claims are provenance.** No measured number is invented, rounded, or re-derived. If a README value looks stale, report it; do not edit it to match.
- **No new dependencies unless the unit explicitly says so** (all eight can be done without adding any).

## Protected branch (do not touch)

`refs/heads/ciani/cdp-examples-for-oliver` is the caller's branch. It is **out of scope for the entire fan-out**: no builder, reviewer, or integrator may checkout, edit, push to it, or use it as a base. PRs only ever target `fixes`/`roadmap`; branches are `agent/NN-*` only.

## Surface / ownership table (the collision registry)

Parallel builders each work in an isolated VM, but their PRs merge into one repo — this table makes the shared-file risk deliberate (per `active-tasks.md`). PRs are opened against `fixes` or `roadmap` (see *Merge strategy* below).

| Unit (issue) | Owns (must touch) | Reads (never writes) | PR base |
|---|---|---|---|
| 01 (#23) | `package.json` + `package-lock.json` (root) | cli manifests | `fixes` |
| 02 (#21) | `components/cdp_transform/{transform.mjs,step.yaml,README.md}`, `components/index.json` (regen) | engine, verify.py, cli | `fixes` |
| 03 (#22) | `engine/{workchain-engine,step-runner}.sh`, `lib/{workchain_yaml,workchain_preflight,workchain_verify}.py`, `docs/format.md`, test chains | components/, cli/commands | `fixes` |
| 04 (#24) | `cli/commands/run-component.js`, new `cli/lib/cdp-catalog.js`, cli/test | component dir, manifests | `fixes` |
| 05 (#7) | root + cli manifests, `package-lock.json`, `cli/lib/{config,engine,formatter,progress}.js`, cli/test | components/, cli/commands/run-component.js | `fixes` |
| 06 (#10) | `lib/workchain_yaml.py`, `engine/*.sh`, `docs/format.md`, topology doc, new `components/mix/`, sample chain | verify.py's POST_CHECKS | `roadmap` |
| 07 (#9) | `lib/workchain_verify.py` (POST_CHECKS), `components/{cdp_transform,normalization}/step.yaml` + READMEs, test chains, regen index | engine/, cli/ | `roadmap` |
| 08 (#11) | README/docs + optionally `cli/lib/cdp-catalog.js` listing | render logic, manifests | `roadmap` |

Discipline rule: the `components/cdp_transform` dir, the `engine/`+`lib/` verifier surface, and the manifests/lockfile are each owned by exactly one in-flight unit per wave (manifests: 01 then 05; 01 merges first).

## Approach — streams and waves

The eight issues share three file surfaces. The fan-out is organized so no two agents working in the same wave touch the same file. See the ownership matrix in each unit's *Boundaries* and the surface table above.

| Stream | Surface | Units (issue) |
|---|---|---|
| **D — dependencies** | root/`cli` manifests, lockfile, `cli/lib` infra | 01 (#23) → 05 (#7) |
| **C — cdp_transform contract** | `components/cdp_transform/*`, `cli/commands/run-component.js`, new `cli/lib/cdp-catalog.js` | 02 (#21) ‖ 04 (#24) → 07 (#9) → 08 (#11) |
| **E — engine & verifier** | `engine/*.sh`, `lib/workchain_preflight.py`, `lib/workchain_verify.py`, `lib/workchain_yaml.py`, `docs/format.md` | 03 (#22) → 06 (#10) |

## Dispatch waves

**Dispatch waves** (agents in the same wave run in parallel; a wave starts only when the wave before it has merged):

- Wave 0: units **01, 02, 03, 04** — four agents, zero shared files.
- Wave 1: units **05** (needs 01's lockfile), **06** (needs 03's id model), **07** (needs 02's step.yaml + 03's ctx model).
- Wave 2: unit **08** (roadmap; can be dropped).

If only three agents are available, the fallback is three long-lived agents (one per stream above), delivering their units as sequential PRs.

## Merge strategy (two final branches)

Per the caller's instruction, the review phase converges on **two integration branches**, and fixes always merge before roadmap:

1. **`fixes`** — off `main`. Fix PRs (units 01–05) target this branch. When all are APPROVE'd, an integration round merges them onto `fixes`, runs the full gate suite on it, and merges `fixes` → `main`.
2. **`roadmap`** — off `main`, fast-forwarded to include everything merged into `main` (i.e. the fixes) before roadmap PRs (units 06–08) target it. Same integration round, then `roadmap` → `main`.

Nothing merges to `main` except these two branch merges, each after its own green integration round. This keeps the released baseline (fixes) solid before any feature work lands on top.

## Overall done-criteria

- All eight issues closed by merged PRs (or, for 08, closed with a documented decision).
- `./tools/release-check.sh --cdp` green on `main` after each merge; `workchain registry generate && workchain registry check` clean wherever a component changed; `tools/doc-check.sh` clean.
- Every unit that touches a contract demonstrates both a red (broken) and green (fixed) run, with the red run's evidence in the PR description.
- No unit's PR changes CLI `--json` output shape, chain semantics for existing single-step chains, or the parameter-precedence rule.

## Non-goals

- Removing `commander`, vendoring `cdp-wasm`, bundling the CLI (from #7's own non-goals).
- Any change to the parse precedence `step params > chain globals > schema default`.
- Landing #10's full graph topology — only its first prerequisite (per-step identity) and the minimal two-input path.