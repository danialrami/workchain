# CI Workflows

These files live in `ci/` rather than `.github/workflows/` because the authoring
agent does not have the GitHub App `workflow` scope needed to commit directly to
`.github/workflows/`. A human with push access must copy them across.

## Installing the workflows

```bash
mkdir -p .github/workflows
cp ci/verify.yml      .github/workflows/verify.yml
cp ci/shellcheck.yml  .github/workflows/shellcheck.yml
git add .github/workflows/
git commit -m "ci: install workflows from ci/"
git push
```

---

## What each workflow guards

### `verify.yml` — main correctness gate

Runs on every push to `main` and every pull request.

| Step | Gates? | What it checks |
|---|---|---|
| Install ffmpeg | yes (setup) | ffmpeg/ffprobe available for CLI and verifier |
| `npm install` + `npm test` | yes | Node CLI unit tests (vitest) |
| `tools/release-check.sh` | yes (if script exists) | Release-readiness checks written by orchestrator |
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

**Local equivalent:**

```bash
sudo apt-get install -y ffmpeg
cd cli && npm install && npm test
node cli/bin/lufs-workchain.js registry check
node cli/bin/lufs-workchain.js validate all --strict
node cli/bin/lufs-workchain.js doctor          # informational; stem_separation may fail
bash tools/release-check.sh                    # if the file exists
```

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

**SC2296 is NOT excluded.** There is a genuine error in `engine/yaml-parser.sh`
line 86 where `${空格}` (Chinese characters, not a valid Bash variable) is used in
a regex. This causes the pattern to silently expand to `${}`  and match too broadly.
The shellcheck workflow will fail on this file until the bug is fixed. Do not suppress
SC2296 to get a green run.

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
