---
name: authoring-a-component
description: How to write a Workchain component that is verified rather than merely runnable. Use whenever creating a new component, editing an existing step.yaml or run.sh, or reviewing a component someone else wrote. Covers the two contracts, choosing post-conditions, metamorphic invariants for creative operations, and the failure modes that make a component lie.
---

# Authoring a component

A component is a folder: `step.yaml` + `run.sh` + `README.md`. The filesystem is the registry.

**Definition of done is not "it runs." It is "it proves what it produced."** A component that
exits 0 with the wrong output is worse than one that fails, because it lies to whatever is
operating it — and by the time anyone notices, the wrong audio is three steps downstream.

Scaffold with `workchain generate component --name <name> --description "..."`. The scaffold
**fails on purpose** via a `WORKCHAIN_NOT_IMPLEMENTED=1` line in `run.sh`. Remove that line only
when `run.sh` genuinely produces its primary output — and never before the `verify:` block is
real.

## The two contracts

**Verified IN — `requirements:`** — checked by `lib/workchain_preflight.py` *before* `run.sh`.
Classes: `commands`, `python`, `node`, `models`, `env`. Declare every external binary you shell
out to. A missing dependency must fail before the run, not halfway through it.

> Prefer dependencies that are actually everywhere. `python3` and `ffmpeg` are already required
> by the engine; reaching for something like `bc` for arithmetic buys a preflight failure on
> minimal containers for no benefit. Do the maths in `python3`.

**Verified OUT — `verify:`** — checked by `lib/workchain_verify.py` after a clean exit.

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
  post_conditions:
    - id: descriptive_id
      check: audio_lufs_within
      output: primary_output
      target_param: target_lufs
      tolerance: 1.0
      description: "What this guards against, in one sentence."
```

Every `required: true` output gets at least structural asserts. **For audio outputs always
include `audio_valid`** — `non_empty` only asks whether the file has bytes, and a 44-byte WAV
header with zero samples has bytes. `audio_valid` re-probes with ffprobe and demands positive
duration. That one word is the difference between a filesystem question and an audio question.

## Choosing post-conditions

Registered checks: `json_fields_within`, `audio_format_matches`, `audio_lufs_within`,
`audio_duration_matches`, `stems_recombine`, `acoustic_roundtrip`, `seed_record_verifies`,
`embedding_wellformed`. Read the docstrings in `lib/workchain_verify.py` before choosing — the
parameter names are per-check and are not guessable.

**If the component has a numeric target, assert it with a check that re-measures the output.**
Not one that reads a number the component wrote about itself. `normalization` shipped exactly
that bug: it measured its achieved loudness, logged it, and exited 0 whether or not it hit the
target. `audio_lufs_within` re-measures independently, which is why it caught it.

Know which checks are independent and which are self-reported:

| | |
| --- | --- |
| Re-measures the artifact | `audio_lufs_within`, `audio_duration_matches`, `audio_format_matches`, `stems_recombine`, `acoustic_roundtrip` |
| Reads what the component wrote | `json_fields_within` |

`json_fields_within` is legitimate and often the only option, but a contract resting on it is
**weaker** — and the README must say so out loud rather than implying coverage we do not have.
If the right check does not exist yet, adding one to `POST_CHECKS` is usually 30 lines and
benefits every future component. Prefer that over quietly settling for a weaker assertion.

## Creative operations, where there is no correct output

You cannot assert the right granular texture or the right artwork. Assert **relations** instead
— metamorphic testing:

- duration preserved, or related to the requested factor
- loudness preserved where the operation should not have changed it
- stems recombining to the source within a residual tolerance
- deterministic ids / byte-identical renders for the same input and parameters
- idempotence within tolerance

Run the cheap relations every execution; keep expensive ones (fixtures, full idempotence) for
test time.

**Two traps, both of which we have shipped:**

**Equality assertions fail open.** `None == None` is true, so an unguarded comparison reports
PASS on a run where neither side executed. We logged
`salvaged features == clean-control features  PASS — None vs None` on a run where the component
never started, and CI went green. Prove both sides exist before comparing, and fail explicitly
when either is missing. Note the asymmetry: equality fails open, inequality fails closed — so
the metamorphic relations we lean on hardest are exactly the ones needing the guard.

**An empty contract proves nothing.** A post-condition that resolves to zero assertions must
FAIL, not pass. `audio_format_matches` does this deliberately: if no format dimension resolves,
it fails rather than handing back a green format guarantee nobody requested.

## run.sh rules

- `return`, never `exit` — the engine sources the script.
- Read params with `get_param`; the engine has already resolved precedence
  (step `params` > chain `globals` > schema `default`). Never re-implement or override it.
- Never overwrite `WORKCHAIN_ROOT`, `LIB_DIR`, `COMPONENTS_DIR`.
- stdout is the final JSON; **all** logging goes to stderr (`log_*`).
- Register every output with `register_output`, and register `failed` /
  `not_implemented` plus `return 1` when you could not produce one. Never report `completed`
  for an output you did not write.
- Read JSON through the special-char-safe helpers in `lib/common-utils.sh`. Paths contain
  apostrophes and spaces; never shell-interpolate them.
- Guard mandatory params explicitly — the schema has no `required` key, so a missing mandatory
  param is caught by your guard or not at all.

## Params schema

A param entry supports exactly four keys: `type`, `default`, `description`, `range`. **There is
no `required` key** — anything else is silently discarded by every layer. A param is mandatory
by having no `default` plus a guard in `run.sh`; a param is *optional* by having no default and
a documented preserve-the-input fallback.

Bump `version` when you change a schema, and keep changes backwards-compatible.

## Prove the test can fail

Before calling a component done, **break it on purpose and watch the contract go red.** Change
a target, corrupt an output, skip a step. If you cannot make the check fail, it is not evidence
of anything — it is decoration that manufactures confidence.

`chains/tests/normalization_offtarget.yaml` exists for exactly this reason: it requests a target
unreachable under the true-peak ceiling, so the component exits 0 and misses, and the verifier
must catch it. Add the equivalent for your component.

## README

Follow `normalization` and `format_conversion`: What it does · Parameters (name | type | default
| range | meaning) · Inputs / Outputs · Verified IN · Verified OUT · Usage · Edge cases · Tier.

Document honestly. If the contract is structural-only because no numeric post-condition exists
yet, **say so** rather than implying coverage. Never write a measured claim you did not measure,
and never re-round or extrapolate one someone else measured — a fabricated number in a project
about verification is the fastest way to destroy the only thing we are selling.

## Related

- `lib/workchain_verify.py` — the enforcer, and the docstring for every check
- `components/normalization/step.yaml` — the reference contract
- `docs/format.md` — the chain and `step.yaml` specification
