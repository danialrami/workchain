# CI Workflows

These files live in `ci/` rather than `.github/workflows/` because the authoring
agent does not have the GitHub App `workflow` scope needed to commit directly to
`.github/workflows/`. A human with push access must copy them across.

## Installing the workflows

```bash
mkdir -p .github/workflows
cp ci/verify.yml      .github/workflows/verify.yml
cp ci/shellcheck.yml  .github/workflows/shellcheck.yml
cp ci/publish.yml     .github/workflows/publish.yml
git add .github/workflows/
git commit -m "ci: install workflows from ci/"
git push
```

The two copies must stay byte-identical, or the workflow that runs is not the workflow that
was reviewed:

```bash
for f in ci/*.yml; do
  cmp -s "$f" ".github/workflows/$(basename "$f")" || echo "DRIFT: $f"
done
```

---

## What each workflow guards

### `verify.yml` — main correctness gate

Runs on every push to `main` and every pull request.

| Step | Gates? | What it checks |
|---|---|---|
| Install ffmpeg | yes (setup) | ffmpeg/ffprobe available for CLI and verifier |
| `npm ci` + `npm test` | yes | Frozen install from `cli/package-lock.json`, then Node CLI unit tests (vitest) |
| `tools/release-check.sh` | **yes, unconditionally** | Every light chain end to end, plus the negative test proving the verifier still fails closed |
| `tools/doc-check.sh` | **yes** | Documentation health: link resolution, llms.txt freshness, frontmatter completeness, license consistency |
| `registry check` | **yes** | `components/index.json` is not stale |
| `validate all --strict` | **yes** | All chains pass strict YAML + schema validation |
| `doctor` | **no** (informational) | Preflight across registry; stem_separation will fail on bare runner — see note |

**Why `doctor` does not gate:** `workchain doctor` runs preflight across every
component. The `stem_separation` component requires a Python venv and gigabytes of
model weights that cannot be provisioned on a free-tier GitHub-hosted runner. Making
`doctor` a gate would mean either permanently excluding that one component (fragile)
or spending free-tier minutes downloading models on every PR. Instead, `doctor` runs
with `continue-on-error: true` so its output is visible in CI logs. Real light-component
regressions are caught by `validate all --strict` and `registry check`.

**Why `release-check.sh` is called unconditionally.** It used to be wrapped in
`if [ -x tools/release-check.sh ]`, from when the script was still being written by a
concurrent task. That guard made the most important gate in the repository **fail open**: if
the file were missing, renamed, or had lost its executable bit — which happened four times,
because pushing over the GitHub REST API resets the mode to `100644` — CI skipped
verification entirely and reported green on an unverified tree. Confirmed by experiment:
`chmod -x tools/release-check.sh` made the old guard take the "skip" branch and the job pass,
while the current unconditional step exits `126`. Never reintroduce a conditional here.

**Local equivalent:**

```bash
sudo apt-get install -y ffmpeg
cd cli && npm ci && npm test
node cli/bin/workchain.js registry check
node cli/bin/workchain.js validate all --strict
node cli/bin/workchain.js doctor          # informational; stem_separation may fail
./tools/release-check.sh
```

---

### `publish.yml` — release to npm over OIDC

Runs on a `v*` tag push, or manual dispatch (which **defaults to a dry run**).

Publishes `@lufs-audio/workchain` to npmjs.com using **trusted publishing** — no npm token is
stored anywhere. npm attaches a provenance attestation automatically, linking the published
tarball to this repository, the commit and the workflow run.

Every gate runs *before* the publish, in this order, and all of them fail closed:

| Step | What it stops |
|---|---|
| npm CLI `>= 11.5.1` | An npm too old to attempt the OIDC exchange, which fails looking exactly like missing credentials |
| Tag matches `package.json` | `v0.1.1` shipping `0.1.0`'s bytes — the registry believes the manifest, not the tag |
| `npm ci` | Unfrozen dependency resolution in a release build |
| `tools/release-check.sh` | An unverified tree reaching the registry |
| `registry check` | A stale `components/index.json` |
| `validate all --strict` | A chain that does not parse |
| `npm pack --dry-run` | An unexamined tarball |

Then it asks the registry whether that exact version already exists and **skips the publish
with a notice** rather than failing. This makes a re-run idempotent, and makes it safe to push
`v0.1.0` after publishing `0.1.0` by hand.

**The first release cannot use this workflow.** A Trusted Publisher is configured in the
*package's own* settings on npmjs.com, so the package must exist before those settings do.
`0.1.0` is published manually per [`docs/PUBLISHING.md`](../docs/PUBLISHING.md); this workflow
takes over from `0.1.1`.

**Things that break OIDC in misleading ways**, all documented in the workflow header: a
missing `id-token: write`; a self-hosted runner; npm below 11.5.1; a `NODE_AUTH_TOKEN` that is
present but **empty**; the trusted-publisher workflow field entered as a path rather than a
bare filename; and a `repository.url` mismatch, which fails provenance signing with a `422`.

**Actions here are pinned by commit SHA, not tag** — unlike the rest of `ci/`. This workflow
holds `id-token: write`, so a mutable tag on a third-party action would be a route to an OIDC
token that can publish under our name.

---

### `shellcheck.yml` — shell script linting

Runs on push to `main` and pull requests, but only when `.sh` files change (path filter).

Lints: `engine/*.sh`, `lib/*.sh`, `components/*/run.sh`,
and the `audio_benchmark` helper scripts.

**Active exclusions** (with rationale):

| Code | Reason excluded |
|---|---|
| SC2034 | Variables in `constants.sh`, `common-utils.sh`, and component scripts are consumed by the sourcing engine, not in the file that defines them. Correct by design. |
| SC2155 | `local var=$(cmd)` pattern throughout the codebase. The return-value-masking risk is understood; fixing all sites is a separate task. |
| SC1091 / SC1090 | Scripts source siblings via runtime variables (`$WORKCHAIN_ROOT`, `$LIB_DIR`, `$COMPONENT_DIR`). shellcheck cannot resolve dynamic paths. Correct by design. |
| SC2094 | False positive from engine using a dedicated fd (`done 3< "$plan_file"`) for step iteration. |

**SC2296 is NOT excluded**, and it earned its keep. It caught a genuine bug in
`engine/yaml-parser.sh`: a regex written as `name:${空格}(.+)$`, where those two characters are
not a valid Bash identifier, so the expansion produced nothing and the pattern matched far too
broadly. It is now `name:[[:space:]]*(.+)$` and the workflow passes. Keep SC2296 enabled — and
if it fires again, fix the script rather than suppressing the rule.

**Local equivalent:**

```bash
sudo apt-get install -y shellcheck
shellcheck -x \
  -e SC2034 -e SC2155 -e SC1091 -e SC1090 -e SC2094 \
  engine/*.sh lib/*.sh components/*/run.sh \
  components/audio_benchmark/common.sh \
  components/audio_benchmark/audio_*.sh
```

---

## Important constraints honoured by these workflows

- **GitHub-hosted runners only** (`ubuntu-latest`). Self-hosted runners are
  forbidden for a public repository — fork PRs would execute arbitrary code on
  our hardware.
- **No `continue-on-error` on correctness gates.** Only `doctor` (informational)
  carries `continue-on-error: true`, and that is documented explicitly.
- **No `|| true` on verification steps.** Every gate fails closed.
- **`components/index.json` is never regenerated in CI** — only its freshness is
  checked. Regeneration is the author's responsibility before opening a PR
  (`workchain registry generate`).
- **`stem_separation` is never exercised in CI.** Its venv and model weights are
  not provisioned. Any step that would trigger it is excluded or skipped.
- **No block scalars or YAML anchors** are used in these workflow files, consistent
  with the parser limitations documented in `docs/format.md` (though GitHub Actions
  uses a full YAML parser, the habit is worth keeping).
