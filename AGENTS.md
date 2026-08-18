# Agent guidelines for Workchain

## What this is

A YAML-driven, agent-first audio processing engine. Self-contained **components**
(`step.yaml` + `run.sh` + `README.md`) compose into declarative **chains** (YAML). Three
interfaces share one parser so they can never silently diverge: the Bash engine
(`engine/workchain-engine.sh` + `engine/step-runner.sh`), the Node CLI (`cli/`, binary
`workchain`), and the Python MCP server (`mcp-server/server.py`, FastMCP).

**The filesystem under `components/` is the registry.** There is no database.

**Prime directive: proven correct, not merely exited 0.** A component that runs and produces the
wrong output is worse than one that fails, because it lies to whatever is operating it. Hold this
in mind for every change to a `run.sh` or a `step.yaml`.

## The component contract

Every `step.yaml` declares two contracts. Both are mandatory. Read
[`docs/format.md`](./docs/format.md) for the full specification and
`.agents/skills/authoring-a-component/SKILL.md` for the procedure.

**Verified IN — `requirements:`** — checked by `lib/workchain_preflight.py` *before* `run.sh`
runs. Classes: `commands`, `python`, `node`, `models`, `env`. A step whose dependencies are
missing fails *before* it executes, with a clear message, rather than half-running.

**Verified OUT — `verify:`** — checked by `lib/workchain_verify.py` after a clean exit:

- `outputs[].assert` — structural primitives: `exists`, `non_empty`, `audio_valid`, `json_valid`
- `outputs[].json_has` — required keys in a JSON output
- `post_conditions[]` — numeric and relational checks with sensible tolerances

**Always use `audio_valid` on an audio output.** `non_empty` only asks whether the file has
bytes, and a 44-byte WAV header with zero samples has bytes. `audio_valid` re-probes with ffprobe
and demands positive duration. Most silent-failure bugs live in exactly that gap.

**Know which checks are independent.** `audio_lufs_within`, `audio_duration_matches`,
`audio_format_matches`, `content_hash_matches`, `stems_recombine` and `acoustic_roundtrip`
re-measure or re-compute the artifact. `json_fields_within` reads a value the component wrote
about itself — legitimate, often the only option, but **weaker**, and a README resting on it must
say so rather than implying coverage we do not have.

Never ship a component with an empty `verify:` block to get it merged. If it genuinely cannot be
verified numerically yet, keep the structural asserts and document the gap honestly.

## Rules that will bite you

- **One parser.** All YAML parsing, parameter resolution and validation go through
  `lib/workchain_yaml.py`. Do not add a fourth parser. Three interfaces that disagree about what
  a chain means are three different products.
- **Parameter precedence** is step `params` > chain `globals` > component schema `default`. The
  engine resolves it and passes a resolved config to the component. Components must not
  re-implement or override it.
- **`return`, never `exit`** in a `run.sh` — the engine sources it.
- **stdout is the final JSON; all logging goes to stderr.** Never pollute stdout.
- **`params_schema` supports exactly four keys**: `type`, `default`, `description`, `range`.
  **There is no `required` key** — adding one is silently discarded by every layer. A param is
  mandatory by having no default plus an explicit guard in `run.sh`.
- **Generated scaffolds fail until implemented**, via `WORKCHAIN_NOT_IMPLEMENTED=1` in the file
  itself, not in a comment. Remove that line only when `run.sh` really produces its output — and
  fill in a real `verify:` block first.
- **`components/index.json` is generated** by `lib/workchain_registry.py`. Never hand-edit it and
  never hand-write a hash to make a gate pass. Regenerate with `workchain registry generate`; CI
  enforces freshness with `registry check`. Adding or editing any file in a component directory
  changes that component's definition hash and makes the index stale — that red build is
  expected, and fabricating a hash to go green is never acceptable.
- **Read JSON through the special-char-safe helpers** in `lib/common-utils.sh`. Paths contain
  apostrophes and spaces; never shell-interpolate them.
- Never overwrite `WORKCHAIN_ROOT`, `LIB_DIR`, `COMPONENTS_DIR`.
- Prefer dependencies that are genuinely everywhere. `python3` and `ffmpeg` are already required;
  reaching for `bc` bought a preflight failure on minimal containers for no benefit, and it was
  removed for exactly that reason.

## YAML: known parser limitations

The engine has a PyYAML fast-path and a dependency-free stdlib fallback. They do not understand
the same YAML, which used to make a chain mean different things on different machines.

**The governing rule is now: the format is what the weakest supported parser can read.**
`_reject_unsupported()` in `lib/workchain_yaml.py` runs on **both** paths and refuses anything
outside that subset, naming the construct and the line. So a chain that loads here loads
everywhere, and PyYAML being installed can no longer change a file's meaning.

Rejected explicitly, with a clear error:

- **Block scalars (`>` and `|`)** — use a single-line quoted string.
- **Anchors (`&name`) and aliases (`*name`)** — write the value out.
- **Merge keys (`<<:`)** — write the keys out.

Also fixed rather than documented-around: **inline comments are now stripped** on the fallback
path, per the YAML rule that `#` begins a comment only after whitespace and outside quotes — so
`name: a # b` is `a`, while `name: a#b` stays `a#b`, matching PyYAML.

Still a real limitation: **flow collections must open and close on the same line.** A `[`
continued onto later lines produces garbage structure on the stdlib path.

### Why this mattered

`engine/chain-validator.sh` used to be a second, independent, grep-based validator. On a chain
using a folded scalar the Python validator correctly refused the file while that script reported
**"Chain validation passed"** — it failed *open*, the worst direction for a gate. It is now a thin
delegate to `lib/workchain_yaml.py` and holds no validation logic of its own.

Two implementations of "is this chain valid?" is the same defect class as a component that exits 0
while producing silence: a check that can disagree with the truth is worse than no check, because
it is trusted. `tools/release-check.sh` now asserts the two validators agree, so this cannot
regress silently.

## Prove the test can fail

Before calling anything done, **break it on purpose and watch the contract go red.** A check
nobody has observed failing is decoration that manufactures confidence.
`chains/tests/normalization_offtarget.yaml` exists for this: it requests a target unreachable
under the true-peak ceiling, so the component exits 0 and misses, and the verifier must catch it.

Two failure modes we have shipped and you should expect to meet again:

- **Equality assertions fail open.** `None == None` is true, so an unguarded comparison reports
  PASS on a run where neither side executed. We logged
  `salvaged features == clean-control features  PASS — None vs None` on a run where the component
  never started, and CI went green. Prove both sides exist before comparing. Equality fails open;
  inequality fails closed — so the metamorphic relations we lean on hardest need the guard most.
- **An empty contract proves nothing.** A post-condition resolving to zero assertions must FAIL,
  not pass. `audio_format_matches` does this deliberately.

## Never invent a measurement

Some READMEs quote real measured values — an integrated LUFS reading, an RMS residual, a runtime.
Those are provenance claims about actual audio. Do not alter, round, extrapolate or add to them.
If a measured claim looks stale, report it; do not re-derive it. **A fabricated number in a
project about verification destroys the only thing the project is for.**

Related: when a README and its `step.yaml` disagree, that is a defect of unknown side — one
encodes an intention, the other encodes what shipped. Report it rather than editing either to
match, because editing the README to agree with the code can silently bless a bug.

## Commands

```bash
npm install                            # root manifest: the CLI's runtime deps (single source of truth)
cd cli && npm install && npm link      # cli manifest: vitest; then `workchain` is on PATH
workchain components                   # what's installed
workchain doctor                       # inbound preflight across the registry
workchain chains                       # available chains
workchain validate <chain|all> --strict
workchain run <chain> <input> -o ./out --json
workchain run <chain> <input> --dry-run
workchain run-component <name> <input> -o ./out
workchain generate component --name <name> --description "..."
workchain registry generate            # regenerate components/index.json
workchain registry check               # fail if it is stale
cd cli && npm test

# The engine directly, no npm needed:
./engine/workchain-engine.sh -c chains/<chain>.yaml <input> -o <output_dir>
```

Requires Node 18+, Python 3.10+, ffmpeg. Light components need nothing further. `stem_separation`
is the one heavy component and needs a venv plus model weights — see its README.

## Contributions

Pull requests are **not** currently accepted, on ownership grounds explained in
[`CONTRIBUTING.md`](./CONTRIBUTING.md). Bug reports are wanted, especially "it reported success
and the audio was wrong." Licensing, and what is deliberately not published here, is in
[`LICENSING.md`](./LICENSING.md).
