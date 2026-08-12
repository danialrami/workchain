# Release procedure

How to prove this repository is fit to be seen.

Written to be followed by a human **or** an agent. Every step has a command, an expected result,
and a stop condition. If a step's expected result does not appear, **stop and report** — do not
improvise around a failing gate, because the point of the gate is that nobody has to trust
anyone's judgement about whether it matters.

## Verify a checkout

```bash
cd cli && npm install && npm link && cd ..    # once per clone
./tools/release-check.sh                      # light path
./tools/release-check.sh --heavy              # + stem_separation
./tools/release-check.sh --keep               # keep the work dir to inspect outputs
```

Exit 0 means every gate passed. What it actually checks, and why each one exists:

| Gate | Guards against |
| --- | --- |
| 0. Prerequisites | Missing `python3` / `ffmpeg` / `ffprobe` / `node` |
| 0b. Executable bits | A shebanged file committed `100644`. Detected by shebang, not filename — an earlier version globbed `*.sh` and never saw `tools/hooks/pre-push` |
| 1. Fixtures | Generated at run time, never committed. A committed binary fixture is one nobody can regenerate |
| 2. Chain validation | Every chain parses and validates strictly |
| 3. Parser agreement | The Python and Bash validators must agree. One used to report "validation passed" on a file the other refused — it failed **open** |
| 4. Light chains end to end | A chain passes only when the engine exits 0 **and** every step's verification record says `verified`. Exit 0 alone is the claim this project does not accept |
| 5. Negative test | The verifier must **fail** on a chain asking for an unreachable target. A verification system nobody has watched fail is not evidence of anything |
| 6. Heavy path | `stem_separation`, behind `--heavy` |
| 7. Registry + unit tests | `components/index.json` freshness (via the Python module, so it works on a cold clone) and `npm test` |
| 8. Documentation sanity | Internal hostnames, local paths, private repo references, stale CLI names, and every component having a `README.md` and a `verify:` block |

## After changing a component

Editing **any** file in a component directory — including its `README.md` — changes that
component's `definition_hash`, which makes the generated index stale.

```bash
workchain registry generate      # regenerate the index (never hand-edit it)
workchain registry check         # must be clean
```

Never hand-edit `components/index.json`, and never write a hash by hand to make a gate pass.

## After adding a chain or component

- `./tools/release-check.sh` — the new chain is picked up by the validation sweep automatically.
- Add an end-to-end line to section 4 of the harness if the chain should be exercised on every
  run, and choose a **representative** fixture. A pure sine is pathological for source
  separation: the recombine residual sits above threshold even when the component is correct.
  The fixture has to resemble real material, or the invariant produces a false failure.
- Break the component on purpose and confirm its contract goes red. If you cannot make a check
  fail, it is not evidence — it is decoration.

## Known gotchas

- **`git update-index --chmod=+x` needs a path.** Bare, it silently does nothing.
- **Pushing files through the GitHub API can reset the executable bit to `100644`.** Anything
  pushed by an agent over the REST API should have its mode re-checked; that is how
  `tools/release-check.sh` lost its bit. Gate `0b` exists to catch this.
- **A modern `python3` is too new for `stem_separation`.** Demucs' `diffq` has no wheel past
  3.10. Use `uv python install 3.10`.
- **`bc` is deliberately not a dependency.** It is absent from minimal containers; arithmetic
  goes through `python3`, which the engine already requires.
- **No block scalars (`>` / `|`), anchors, aliases or merge keys in any YAML here.** The
  dependency-free parser cannot read them, so they are rejected on both paths — the format is
  what the weakest supported parser can read. See `docs/format.md`.
- **Templates carry a shebang but must not be executable.** `*.template`, `*.example` and
  `*.sample` are excluded from gate `0b`.
