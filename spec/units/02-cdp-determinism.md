# Unit 02 — cdp_transform determinism: hash the samples, not the container (issue #21)

## Objective
Make `render_is_deterministic` prove bit-identical **audio** (decoded samples) rather than a byte-identical file, while keeping the container comparison as a recorded, non-gating fact.

## Context
- Issue #21 — contains the evidence (two renders 2.5 s apart: sample hash identical, file differs at the PEAK-chunk timestamp offset 50 and LIST/adtl DATE offset 128) and a locally-verified, **not committed** patch design.
- `components/cdp_transform/transform.mjs` — measures the render and writes the record (`record.render_*` hashes); already has `decodeWav` in scope.
- `components/cdp_transform/step.yaml` — the `render_is_deterministic` post-condition and its description ("byte-identical audio").
- `components/cdp_transform/README.md` — measured values and the determinism story (lines ~40–95); update **only** what the code change makes stale, never invent new measurements.
- AGENTS.md rule: changing any file under `components/` makes `components/index.json` stale → regenerate, never hand-edit.
- Feature of this component to re-check: `blur.chorus` advertises per-partial randomisation yet was bit-exact — the RNG is deterministically seeded; do not "fix" that.

## Acceptance criteria
- [ ] `determinism_ok` compares a SHA-256 over the **decoded samples** (`sampleDigest()` per the issue's draft, using `decodeWav`).
- [ ] A new recorded, **non-gating** fact (per the draft: `container_bytes_stable`) keeps the old file-byte comparison without failing the step.
- [ ] Both fields appear in the render record, and the step.yaml post-condition + README describe the distinction accurately (sample hash gates; container hash is recorded context).
- [ ] **Prove the flake is gone:** force a render slow enough to cross a second boundary (issue's method: 6 s source stretched eightfold → 48 s of output), render twice, assert `determinism_ok: true` and `container_bytes_stable: false` in one run. The old check would have gone red on bit-identical audio.
- [ ] Prove it still catches real non-determinism: the check must fail when the samples genuinely differ (e.g., a deliberately non-seeded renderer or an edited sample) — show the red run.
- [ ] `workchain registry generate && workchain registry check` clean; `./tools/release-check.sh --cdp` green; docs gate `tools/doc-check.sh` clean.

## Interface contract
- Render record keys shipped in the step's JSON are **public** to downstream readers (probe's content hash, README tables). New/changed keys: `render_samples_sha256` (or the draft's exact name) and `container_bytes_stable`. Keep `render_*` naming consistent with what `step.yaml` and `README.md` already document.
- This changes **no** CLI surface and **no** chain semantics. Only the meaning of the determinism gate within `cdp_transform` moves.

## Boundaries — do NOT touch
- `cli/**` — units 04 and 05 own the CLI surface. Verify with commands, do not edit.
- `lib/workchain_verify.py` and `engine/**` — unit 03 owns the ctx/`steps` model and unit 07 adds the peak check; do not add post-condition machinery here. This unit only reshapes **this component's** record + yaml + README.
- The `stereoUnsafe` / catalog question (unit 08) — out of scope; no catalog changes.
- Do **not** edit measured values in README that are untouched by this change (provenance rule). If one looks stale, report it in the PR, do not re-derive it.

## Output
One PR: `fix(cdp_transform): determinism proof is sample-based, container bytes recorded non-gating`. Files: `components/cdp_transform/transform.mjs`, `components/cdp_transform/step.yaml`, `components/cdp_transform/README.md`, regenerated `components/index.json`. PR description shows the forced-boundary red/green pair per the criteria above.

## Verification
```bash
node cli/bin/workchain.js registry check        # before, expect stale (red is expected, do not fake it green)
node cli/bin/workchain.js registry generate
./engine/workchain-engine.sh -c chains/cdp-stretch.yaml bell.wav -o /tmp/u02a   # adjust chain name to the stretch chain
# inspect out/context.json for determinism_ok / container_bytes_stable on a render forced across a second boundary
./tools/release-check.sh --cdp
tools/doc-check.sh
```
Observed values quoted in the PR must be from the actual runs above — the issue's numbers are its own evidence, not yours.