---
title: How to write a verify block
description: Choose structural asserts and post-conditions that actually prove what the component did — independent re-measurement, metamorphic invariants, and the failure modes that make assertions lie.
type: how-to
---

# How to write a verify block

`verify:` is the **outbound contract** — what the component *guarantees* about what it
produced. It is enforced by `lib/workchain_verify.py` **after** `run.sh` exits 0, *before* the
step's output becomes the next step's input. A component with no `verify` key reports as
`unverified` and passes non-blockingly — which is another way of saying it contributes no
proof. This page is about turning "ran (exit 0)" into "proven correct."

The check vocabulary lives in two places: the canonical reference is
[`docs/format.md`](../../format.md) (the `verify` section, with every registered check and its
keys); the contracts reference at [`docs/reference/contracts/`](../../reference/contracts/) is
its companion catalog. Read the docstrings in `lib/workchain_verify.py` before choosing —
parameter names are per-check and are not guessable.

## Two layers: structural asserts and post-conditions

Every `verify:` block has an `outputs` section and a `post_conditions` section:

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
  post_conditions:
    - id: integrated_loudness_on_target
      check: audio_lufs_within
      output: primary_output
      target_param: target_lufs
      tolerance: 1.0
      description: "One sentence about what this guards against."
```

### Structural asserts — the filesystem layer

| Assert | What it checks | Trap |
|---|---|---|
| `exists` | Path is non-null and exists. | A registered output whose path was never written. |
| `non_empty` | File is non-zero bytes; directory has at least one entry. | **A 44-byte WAV header with zero samples has bytes.** |
| `audio_valid` | `ffprobe` reports an audio stream with **positive duration**. | Requires ffprobe on PATH; this is the audio question `non_empty` cannot ask. |
| `json_valid` | File parses as JSON. | Valid JSON, wrong content — see `json_has` and `json_fields_within`. |

`json_has` takes a list of key names and fails if any key is absent from a JSON output. It does
not check values.

**Every `required: true` output gets at least structural asserts, and audio outputs always get
`audio_valid`.** `non_empty` only asks whether the file has bytes; `audio_valid` re-probes with
ffprobe and demands positive duration. Most silent-failure bugs live in exactly that gap.

### Post-conditions — the measurement layer

Post-conditions are component-level numeric or relational checks. The registered checks
(`lib/workchain_verify.py` `POST_CHECKS`) are:

- `audio_lufs_within` — re-measures integrated LUFS of the output, fails if more than
  `tolerance` LU from the target param.
- `audio_format_matches` — re-probes sample rate / channels / bit depth against the params the
  step was asked to meet.
- `audio_duration_matches` — metamorphic: outputs preserve the source duration within
  `tolerance_s`.
- `stems_recombine` — metamorphic: the stems sum back to the source within a residual
  threshold.
- `acoustic_roundtrip` — decodes an encoded output and requires the recovered text to match the
  source text.
- `seed_record_verifies` — runs the seed-verifier against the produced record at a minimum
  tier.
- `embedding_wellformed` — an embedding sidecar is a real vector: finite, non-zero, L2-normed
  (recomputed, not trusted from the record).
- `json_fields_within` — declarative value constraints (`FIELD OP VALUE`) over a JSON output;
  nested keys via dotted paths, operators `> >= < <= == != is one_of`.

## Choose a check that re-measures — not one that reads the component's own claim

If the component has a numeric target, assert it with a check that **re-measures the
artifact**:

| | |
|---|---|
| Re-measures the artifact | `audio_lufs_within`, `audio_duration_matches`, `audio_format_matches`, `stems_recombine`, `acoustic_roundtrip` |
| Reads what the component wrote | `json_fields_within` |

`normalization` shipped exactly the bug this table exists to explain: it measured its achieved
loudness, logged it, and exited 0 whether or not it hit the target. `audio_lufs_within` is what
closes the gap — it independently re-measures and fails the step that missed.

`json_fields_within` is legitimate and often the only option (nothing else reads "the artifact
is a plausible embedding"), but a contract resting on it is **weaker**, and the README must say
so out loud rather than implying coverage the repo does not have. If the right check does not
exist yet, adding one to `POST_CHECKS` is usually ~30 lines and benefits every future
component. Prefer that over quietly settling for a weaker assertion.

## Creative operations: assert relations, not outcomes

For separation, denoise, restoration, artwork — anything with no single correct output — you
cannot assert the right result. Assert **metamorphic invariants** instead:

- duration preserved, or related to the requested factor (`audio_duration_matches`)
- loudness preserved where the operation should not have changed it
- stems recombining to the source within a residual tolerance (`stems_recombine`)
- deterministic ids / byte-identical renders for the same input and parameters
- idempotence within tolerance

`components/stem_separation/` is the reference: separation quality cannot be asserted, but
"the stems must sum back to the source within a residual tolerance" can — so its contract runs
`stems_recombine` with `stems: auto` (every registered stem, so one contract covers the 2/4/6-
stem presets). Run the cheap relations on every execution; keep expensive ones (fixtures, full
idempotence) for test time.

## Failure modes — how an assertion lies

Two traps, both of which this project has shipped into production:

**Equality assertions fail open.** `None == None` is true, so an unguarded comparison reports
PASS on a run where neither side executed. The repo has logged exactly that:
`salvaged features == clean-control features  PASS — None vs None` on a run where the component
never started, and CI went green. The asymmetry is the poison: **equality fails open,
inequality fails closed** — so the metamorphic relations you lean on hardest are exactly the
ones needing the guard. Prove both sides exist before comparing, and fail explicitly when
either is missing.

**An empty contract proves nothing.** A post-condition that resolves to zero assertions must
FAIL, not pass. `audio_format_matches` does this deliberately: if no format dimension resolves
(no param asks the step to change anything), it fails rather than handing back a green format
guarantee nobody requested. `json_fields_within` likewise fails on an empty `require` list and
on an unparsable constraint — fail-closed, never a skip.

**Complexity check:** if you cannot make the check fail by breaking the component, it is not
evidence — it is decoration. This is why `chains/tests/normalization_offtarget.yaml` exists: it
requests a target unreachable under the true-peak ceiling, the component exits 0 and misses,
and the verifier must catch it. Add the equivalent for your component. (The authoring
walkthrough in [`author-a-component.md`](author-a-component.md) shows two live breaks on one
component: a header-only "audio" file that fails `audio_valid` with 44 bytes, and a
copy-through that fails `audio_lufs_within` at −21.75 vs −16.0 LUFS.)

## The two contracts are a pair

`verify:` is only half of the component contract — its mirror is `requirements:`, the inbound
contract checked *before* `run.sh` runs, so a missing dependency fails honestly rather than
half-running (see [`author-a-component.md`](author-a-component.md)). A component is proven
correct only when both hold: the environment was real before it ran, and the artifact is real
after it finished.