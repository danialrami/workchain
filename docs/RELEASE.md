# Release procedure

How to prove this repository is fit to be seen, and how to finish the carve-out that produced it.

Written to be followed by a human **or** an agent. Every step has a command, an expected result,
and a stop condition. If a step's expected result does not appear, **stop and report** — do not
improvise around a failing gate, because the point of the gate is that nobody has to trust
anyone's judgement about whether it matters.

---

# Part 1 — Finish the carve-out (one-time; delete this Part when done)

`main` is currently a single orphan commit ("Initial public release") created from the private
repo's carve-out branch. Three things are still wrong with it. All three must be fixed **in that
one commit**, not in a follow-up commit, because two of them are about what history contains.

**Current defects on `main`:**

| # | Defect | Why it matters |
| --- | --- | --- |
| 1 | `docs/DIAGNOSTICS-ciani-port-engine.md` is committed | A branch-specific build journal. It is process, not product, and it names an unreleased track and a local path. Preserved in the knowledge base instead |
| 2 | `tools/release-check.sh` is committed `100644` | The release gate itself is not executable from a clean clone |
| 3 | `tools/hooks/pre-push` is committed `100644` | A git hook without the exec bit **silently never runs** |

Defects 2 and 3 were caught by the harness's own `0b. Executable bits` gate. Note that
`git update-index --chmod=+x` **requires a path argument** — run bare, it is a silent no-op,
which is how defect 2 survived the first attempt.

## 1.1 Get the current main and the latest gate

```bash
cd /path/to/workchain
git fetch origin
git checkout -B main origin/main      # local branch named main, tracking origin/main
git pull --ff-only
```

**Expected:** you are on `main`, and `docs/RELEASE.md` exists (this file).
**Stop if:** the branch is still called `public-main` — the `-B main` above is what renames it.

## 1.2 Remove the diagnostics record

```bash
git rm docs/DIAGNOSTICS-ciani-port-engine.md
ls docs/
```

**Expected:** `docs/` contains `format.md` and `RELEASE.md` only.

## 1.3 Restore the executable bits

```bash
git update-index --chmod=+x tools/release-check.sh
git update-index --chmod=+x tools/hooks/pre-push
git ls-files -s tools/ | awk '{print $1, $4}'
```

**Expected:** every entry under `tools/` reads `100755`.
**Stop if:** any reads `100644`. Re-run with the exact path; a bare `--chmod=+x` does nothing.

## 1.4 Prove it, before you rewrite anything

```bash
cd cli && npm install && npm link && cd ..
./tools/release-check.sh
```

**Expected:** `All gates passed.` — currently 48 passed, 0 failed, 2 skipped. The two skips are
the heavy chains and, if you have not installed the CLI, `npm test`.
**Stop if:** anything failed. Fix it here; a rewritten history that fails its own gate is worse
than the current state, because you cannot go back.

Optional but worth doing once, and the only way `stem_separation` is actually proven:

```bash
./tools/release-check.sh --heavy
```

Needs a Python 3.10 venv (see `components/stem_separation/README.md`; a modern system `python3`
is too new for Demucs' `diffq`, so use `uv python install 3.10`).

## 1.5 Collapse to one clean commit

The diagnostics file is in the current root commit, so removing it from *history* means
replacing that commit rather than adding to it.

```bash
git checkout --orphan release-tmp
git add -A
git commit -m "Initial public release

Workchain: a YAML-driven, agent-first audio processing engine where a step must
prove its output rather than merely exit 0. Apache-2.0."

git log --oneline                      # must be exactly ONE line
git ls-tree -r HEAD --name-only | grep -c DIAGNOSTICS    # must print 0
git ls-files -s tools/ | awk '{print $1}' | sort -u      # must print only 100755
./tools/release-check.sh               # must still pass, from this commit
```

**Stop if** any of those four checks disagrees with its expected result.

## 1.6 Make it `main` and publish

```bash
git branch -M release-tmp main         # rename this branch to main, replacing the old one
git push --force-with-lease origin main:main
git branch -vv                         # main should track origin/main
```

`--force-with-lease` rather than `--force`: it refuses if the remote moved under you.

**Then, in the GitHub UI:** confirm `main` shows one commit and `docs/` has no diagnostics file.

## 1.7 Let CI run, and only then flip the lid

The workflows in `.github/workflows/` have **never executed**. Push triggers them.

```bash
gh run list --limit 5                  # or watch the Actions tab
gh run watch
```

**Expected:** `verify` green. `shellcheck` may go red on its first real run; the known findings
were fixed, but the workflow itself is unproven.
**Do not make the repository public until CI has been green once.** A public repo with a red
badge on day one is the first thing a visitor sees.

## 1.8 Delete Part 1

Once CI is green and visibility is flipped, delete Part 1 of this file and commit. Part 2 is the
part that stays.

---

# Part 2 — The standing release gate

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
workchain registry generate      # or: node cli/bin/lufs-workchain.js registry generate
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
