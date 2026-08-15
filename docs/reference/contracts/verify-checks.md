---
title: "verify: check catalog"
description: "Complete quick-lookup catalog of the verify contract vocabulary — structural asserts and every post-condition implemented in lib/workchain_verify.py, with params, fail-open/fail-closed semantics, real component examples, and use-when guidance."
type: reference
---

# Verify checks: the complete catalog

This page is the lookup table you open when deciding **which checks your component's
`verify:` block needs**. It is a companion to [`docs/format.md`](../../format.md), which is
the canonical spec for the contract's shape and syntax — this page does not restate the
full format. Link, don't duplicate: the yaml field tables and grammar below are the
decision-relevant facts, and each entry points at its canonical `format.md` section.

Everything here is derived from one ground truth: `lib/workchain_verify.py`. The catalog
was diffed against `grep 'def check_' lib/workchain_verify.py` (9 post-conditions,
below) and the structural assert table against the `STRUCTURAL` dict in the same file.
If the two ever disagree, the source file wins and this page is stale — report it, don't
"fix" the source to match.

## The two contract levels

A `verify:` block has two parts, both mandatory to never have:

- **`verify.outputs[]`** — per-output *structural* asserts: `exists`, `non_empty`,
  `audio_valid`, `json_valid`, and the `json_has` key list. Cheap, every run, no tools
  beyond stdlib + ffprobe. These prove the file is *there and shaped right* — they
  cannot prove it is *correct*.
- **`verify.post_conditions[]`** — component-level *numeric or relational* checks
  (`audio_lufs_within`, `audio_duration_matches`, `stems_recombine`, …). These re-measure
  the artifact or compute a relation over it. This is where "exited 0" becomes "proven
  correct", and it is the half most components get wrong by omission.

The verifier runs `lib/workchain_verify.py` immediately after `run.sh` exits 0. A
component with no `verify:` key is reported tier `unverified` and passes
non-blockingly; a declared contract that fails halts the chain. See
[`docs/format.md#verify`](../../format.md) for the full spec.

## Hard rules (read before writing any contract)

These are the project rules that shape every choice below.

1. **`audio_valid` on every audio output, always.** `non_empty` only asks whether the file
   has bytes — a 44-byte WAV header with zero samples *has* bytes. `audio_valid`
   re-probes with ffprobe and demands an audio stream with positive duration. Most
   silent-failure bugs live in exactly that gap (see `cdp_transform`, which exists
   because `stretch.time` at factor 0.02 renders zero samples and exits 0).
2. **Equality fails open; inequality fails closed.** `None == None` is true, so an
   unguarded equality comparison reports PASS on a run where neither side executed. A
   check that reads a value the component wrote about itself must prove both sides
   exist. This is why `json_fields_within` fails on a *missing* field, and why
   `cdp_transform`'s determinism field is written only when both renders completed — a
   missing field FAILS rather than passing on `None == None`.
3. **A post-condition that resolves to zero assertions must FAIL, not pass.**
   `json_fields_within` with an empty `require` fails; `audio_format_matches` with no
   dimension named fails; `stems_recombine` with no usable stems fails. An empty
   contract proves nothing, and proving nothing is not verification.
4. **`stems_recombine` and `audio_format_matches` deliberately fail on empty
   contracts** rather than passing vacuously — see their entries below.
5. **Trust the artifact, not the report.** Checks that re-measure (`audio_lufs_within`,
   `audio_duration_matches`, `audio_format_matches`, `content_hash_matches`,
   `stems_recombine`, `acoustic_roundtrip`, `seed_record_verifies`,
   `embedding_wellformed`) are strictly stronger than checks that read recorded values
   (`json_fields_within`, `json_has`). Where only the weaker class is available, say so
   in the component README rather than implying coverage you do not have.

## Structural asserts (`verify.outputs[].assert`)

Implemented in the `STRUCTURAL` dict of `lib/workchain_verify.py`; `json_has` is the
per-output key list handled in the same loop.

| Assert | What it checks | Fails on | Use when |
|---|---|---|---|
| `exists` | Path is non-null and `os.path.exists(path)` is true | missing/empty path | every output. The floor of all contracts |
| `non_empty` | File is non-zero bytes; directory has ≥ 1 entry | zero-byte file, empty dir | the file must carry data. Weakest of the trio — see rule 1 |
| `audio_valid` | `ffprobe` reports an audio stream *and* positive duration | undecodable, no audio stream, zero/absent duration | **every audio output** (rule 1) |
| `json_valid` | File parses with `json.load` | malformed JSON | every JSON output |
| `json_has` | The listed keys exist on the JSON root object | any listed key absent | whenever the JSON's *shape* matters. Does **not** check values — a null or wrong value passes (fail-open by design); that's what `json_fields_within` is for |

> `json_has` is the classic fail-open gap: key presence is not correctness.
> `probe` and `features` shipped for months writing null/zero sidecars that passed
> their contracts, because nothing looked at the values. Copy that lesson: `json_has` is
> never the end of a contract for a JSON whose values matter.

Real example — the standard trio on every audio component:

```yaml
# components/normalization/step.yaml (verbatim)
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
    - name: loudness_metadata
      assert: [exists, non_empty, json_valid]
      json_has: [target_lufs, final_lufs]
```

## Post-conditions (`verify.post_conditions[]`)

All 9 registered checks, matching `grep 'def check_' lib/workchain_verify.py` exactly.
Params are taken from the function docstrings; the canonical syntax spec for each is
linked in its heading (`docs/format.md` sections).

### audio_lufs_within

[`docs/format.md#audio_lufs_within`](../../format.md) · *numeric, re-measured*

Independently measures the output's integrated loudness with `ffmpeg loudnorm` and
fails if it is more than `tolerance` LU from the target the step was asked to hit.

| Param | Default | Meaning |
|---|---|---|
| `output` | `"primary_output"` | output name to measure |
| `target_param` | `"target_lufs"` | component param carrying the target LUFS; resolved via the full chain (recorded output metadata > step params > globals > `normalization`'s `lufs_target` globals alias > schema default) |
| `tolerance` | `1.0` | max allowed `|measured − target|` in LU |

- **Fails closed**: missing output, unresolvable target, unmeasurable audio, or NaN all
  FAIL. An infinite delta (silence) fails.
- **Why it exists**: this is the gate that closes the *measured but never compared*
  bug. `normalization` used to record `final_lufs` and exit 0 regardless; the verifier
  now re-measures and fails the step if the file missed target.

Real example:

```yaml
# components/normalization/step.yaml (verbatim)
  post_conditions:
    - id: integrated_loudness_on_target
      check: audio_lufs_within
      output: primary_output
      target_param: target_lufs
      tolerance: 1.0
```

### audio_duration_matches

[`docs/format.md#audio_duration_matches`](../../format.md) · *metamorphic, re-measured*

Metamorphic invariant: each listed audio output preserves the source duration within a
tolerance. The canonical check for creative operators (separation, denoise,
restoration) with no single right answer.

| Param | Default | Meaning |
|---|---|---|
| `outputs` | `"auto"` | output name(s) to check; `"auto"` = every file-type output except `primary_output`, so the same contract holds for any stem count |
| `exclude` | `["primary_output"]` | outputs excluded from `auto` resolution |
| `tolerance_s` (alias `tolerance`) | `0.1` | max allowed duration difference in seconds |

- **Fails closed**: if the source duration cannot be measured, FAIL. Any output whose
  duration cannot be measured or is out of tolerance counts as a mismatch → FAIL.
- **Use when**: any operator that must not change length — separation, denoise,
  restoration, protection. Guards silent/truncated/padded outputs a green exit hides.

Real example:

```yaml
# components/stem_separation/step.yaml (verbatim)
  post_conditions:
    - id: stems_preserve_duration
      check: audio_duration_matches
      outputs: auto
      tolerance_s: 0.2
```

### stems_recombine

[`docs/format.md#stems_recombine`](../../format.md) · *metamorphic, re-computed*

Metamorphic relation for source separation: the stems must **decompose** the input. The
verifier sums the stems, subtracts the sum from the source, and requires the residual to
sit at least `max_residual_db` below the source level. Catches a silent, duplicated,
garbage, or mismatched stem without demanding a perceptually "correct" split (there is
no single right answer).

| Param | Default | Meaning |
|---|---|---|
| `stems` | `"auto"` | stem output names to sum; same resolution rules as `outputs` above (list / single / `auto`) |
| `exclude` | `["primary_output"]` | excluded from `auto` resolution |
| `max_residual_db` | `-10.0` | residual must be at most this many dB above the source level (i.e. at least `|max_residual_db|` dB below it) |

- **Fails closed**: fewer than 2 usable stems → FAIL; missing source or any stem → FAIL;
  unmeasurable source level → FAIL. An empty contract (auto resolving to no stems) fails.
- **Deliberate fail-open, documented**: a *silent source* passes trivially
  ("source is silent; recombination trivially satisfied") — there is nothing to
  decompose, and failing a silent input is not useful. Say so in the README if you rely
  on it.
- **Use when**: any separation/stemming component, regardless of stem count (2/4/6) —
  `auto` keeps the same contract correct for all presets.

Real example:

```yaml
# components/stem_separation/step.yaml (verbatim)
    - id: stems_recombine_to_source
      check: stems_recombine
      stems: auto
      max_residual_db: -9.0
```

### acoustic_roundtrip

[`docs/format.md#acoustic_roundtrip`](../../format.md) · *relational, re-decoded*

Metamorphic/relational: `decode(output)` must contain the source text the step was asked
to encode. The verifier **independently** re-decodes the produced waveform with the
`@lufs-audio/audioqr` decoder (resolved from `WORKCHAIN_AUDIOQR_BIN` or `audioqr` on
PATH) — it does not trust the component's own sidecar. This is the anti-"exit-0-but-
wrong" gate for acoustic encoding, and the deliberate opposite of measuring an output
without comparing it to the target.

| Param | Default | Meaning |
|---|---|---|
| `output` | `"primary_output"` | output name containing the encoded audio |
| `target_param` | `"text"` | component param carrying the source text to recover |

- **Fails closed**: missing output, unresolvable source text, absent decoder, or a
  decode that does not contain the target → all FAIL.
- **Reach**: `format.md` documents it; no component in the current public registry
  declares it (the acoustic-encode component was not open-sourced). Implemented and
  ready in the verifier for any component whose `step.yaml` adds it — no example to copy
  from a shipped `step.yaml` exists yet, so do not invent one.

### seed_record_verifies

[`docs/format.md#seed_record_verifies`](../../format.md) · *relational, re-verified*

Independently re-runs `lufs-seed verify` against the produced seed record **and** the
source recording (when available), re-walking the whole chain: recording bytes → LSB
stream → audio digest → seed → ed25519 signature — then requires the record to reach the
declared tier. A seed record is a claim about where bytes came from; a component
asserting its own provenance is exactly the failure this check exists to end.

| Param | Default | Meaning |
|---|---|---|
| `output` | `"primary_output"` | output name (the seed record) to verify |
| `require_tier` | `"verified"` | minimum tier required: `"unverified"` < `"verified"` < `"certified"` |

- **Fails closed**: missing record, absent `lufs-seed` binary, failed verification, or a
  verified-but-below-required-tier record → FAIL. Tiers are ordered numerically, so a
  `verified` record under a `certified` contract fails.
- **Reach**: same honest note as `acoustic_roundtrip` — implemented in the verifier,
  declared by no currently-shipped component, so no verbatim example exists.

### embedding_wellformed

[`docs/format.md#embedding_wellformed`](../../format.md) · *value check, re-computed*

The embedding sidecar contains a **real, usable vector**, not merely the right keys.
Structural asserts can prove `vector` and `l2norm` are present; this proves the vector is
usable: declared length, finite values, not all zeros, and unit-norm when *recomputed*
from the vector itself. The producer's stored `l2norm` is treated as a claim, not
evidence — on a remote backend the producer is a network service you did not run.

| Param | Default | Meaning |
|---|---|---|
| `output` | `"embedding"` | output name to inspect |
| `expect_dim` | — | required dimensionality; a different dim is a *different embedding space* and fails unless the contract changed deliberately |
| `l2_tolerance` | `0.001` | max `|recomputed_norm − 1.0|` |
| `require_served_by` | — | if set, the record's `served_by` must equal it — assert the backend you asked for rather than hoping |

- **Fails closed**: missing vector, non-positive/mismatched dim, NaN/Inf values, all
  zeros, recomputed norm outside tolerance, or a `served_by` that does not match → FAIL.
- **Why it is strict**: a bad vector is worse than a missing one — it flows silently
  into an index and quietly rots retrieval.
- **Reach**: same honest note as the two above — no currently-shipped component declares
  it. Copy the *shape* from the verifier docstring, never from memory of a component.

### json_fields_within

[`docs/format.md#json_fields_within`](../../format.md) · *declarative value contract*

The reusable value contract. It reads a JSON output and evaluates a list of constraint
expressions — `FIELD OP VALUE` — against its fields. This closes the most common and
boring failure: a component writing the right keys with wrong values and exiting 0.

| Param | Default | Meaning |
|---|---|---|
| `output` | — *(required)* | output name to inspect |
| `require` | — *(required)* | list of constraint strings; a single string is also accepted |

Constraint grammar (fail-closed — an unparsable constraint is a FAILURE, never a skip):

```
FIELD <op> NUMBER        ops: > >= < <= == !=   (== and != also compare strings)
FIELD is <kind>          kinds: number string bool array object non_empty not_null
FIELD one_of A|B|C       membership (pipe-separated so commas stay legal in values)
FIELD.SUB ...            dotted paths reach into nested objects
```

- **Fails closed**: empty `require` → FAIL ("an empty contract proves nothing"); missing
  field → FAIL; null compared numerically → FAIL; unparsable constraint → FAIL.
- **Weaker class — read values the component wrote about itself.** It is legitimate and
  often the only option, but the README must say so rather than implying re-measured
  coverage. `cdp_transform` says exactly this in its own contract comments.
- **Use when**: fields the component measured (duration, peak, out-of-range counts,
  booleans) need bounds.

Real examples:

```yaml
# components/cdp_transform/step.yaml (verbatim)
    - id: params_within_declared_range
      check: json_fields_within
      output: transform_record
      require:
        - "params_out_of_range == 0"
        - "params_unknown == 0"
```

```yaml
# components/cdp_transform/step.yaml (verbatim)
    - id: output_is_live_audio
      check: json_fields_within
      output: transform_record
      require:
        - "measured_duration_s > 0"
        - "measured_peak_dbfs > -60"
```

```yaml
# components/content_hash/step.yaml (verbatim, the "structural sanity" companion)
    - id: identifier_is_well_formed
      check: json_fields_within
      output: primary_output
      require:
        - "bytes_hashed > 0"
        - "short_id is non_empty"
        - "digest is non_empty"
```

### audio_format_matches

[`docs/format.md#audio_format_matches`](../../format.md) · *numeric, re-probed*

Independently re-probes an audio output with ffprobe and confirms its sample rate,
channel count, and/or bit depth match what the step was **asked** to produce. This
exists because "converted successfully" is not the same claim as "is now 48 kHz /
24-bit / mono" — a parameter that never reaches ffmpeg silently preserves the source
format while every structural assert passes.

| Param | Default | Meaning |
|---|---|---|
| `output` | `"primary_output"` | output name to probe |
| `sample_rate_param` | — | component param carrying the target sample rate |
| `channels_param` | — | component param carrying the target channel count |
| `bit_depth_param` | — | component param carrying the target bit depth |

- **Fails closed, deliberately, on an empty contract**: with **no dimension param
  named at all**, the check FAILS ("an empty contract proves nothing") rather than
  passing vacuously — a chain cannot accidentally claim a format guarantee it never
  requested.
- **Documented pass**: dimension names declared but all resolving empty → PASS with the
  explicit note "format preserved from the source, so there is no format claim to
  verify". The step was asked to *preserve* every dimension, so there is no claim to
  check. These two situations were conflated once — a bug caught by
  `tools/release-check.sh` — and are deliberately kept apart.
- A dimension whose param resolves to nothing is **not asserted** (preserve semantics).
- **Use when**: any format conversion/conform step with target params.

Real example:

```yaml
# components/format_conversion/step.yaml (verbatim)
  post_conditions:
    - id: output_conforms_to_requested_format
      check: audio_format_matches
      output: primary_output
      sample_rate_param: sample_rate
      bit_depth_param: bit_depth
      channels_param: channels
```

### content_hash_matches

[`docs/format.md#content_hash_matches`](../../format.md) · *numeric, re-computed*

Re-computes the content hash of the **source** and confirms it equals the digest the
component recorded. Provenance is the one claim in this system that can be checked
perfectly — a hash is reproducible by anyone holding the bytes — so the verifier does not
take the component's word for it.

| Param | Default | Meaning |
|---|---|---|
| `output` | `"primary_output"` | name of the JSON output holding the digest |
| `digest_field` | `"digest"` | key in that JSON holding the hex digest |
| `algorithm_field` | `"algorithm"` | key holding the algorithm name |

- **Fails closed**: no usable digest, unresolvable source, zero-byte source ("a digest
  of nothing is not provenance"), unsupported algorithm, mismatch → FAIL.
- **Use when**: any content-addressed provenance component. This is the strongest
  contract in the catalog — the one perfectly checkable claim — so it deserves the
  strongest gate.

Real example:

```yaml
# components/content_hash/step.yaml (verbatim)
  post_conditions:
    - id: digest_reproduces_from_source
      check: content_hash_matches
      output: primary_output
      digest_field: digest
      algorithm_field: algorithm
```

## Fail-open / fail-closed summary

| Check | Fails closed? | Deliberate pass / fail-open branch |
|---|---|---|
| `exists`, `non_empty`, `audio_valid`, `json_valid`, `json_has` | yes | `json_has` is value-blind (keys only) — a wrong value passes |
| `audio_lufs_within` | yes | — |
| `audio_duration_matches` | yes | — |
| `stems_recombine` | yes | silent source passes trivially (documented) |
| `acoustic_roundtrip` | yes | — |
| `seed_record_verifies` | yes | — |
| `embedding_wellformed` | yes | — |
| `json_fields_within` | yes (unparsable constraint = failure) | — |
| `audio_format_matches` | yes: no dimension named → FAIL | names declared but all unset → pass ("nothing proven", documented) |
| `content_hash_matches` | yes | — |

The general rule: **nothing in this file passes vacuously.** Where a pass is possible
without proving anything, the check either fails (empty contract) or says out loud that
nothing was proven. If you find a branch that does neither, that is a defect — report it.

## Source of truth

- Post-condition list: `grep 'def check_' lib/workchain_verify.py` — 9 functions.
- Registered names: the `POST_CHECKS` dict at the bottom of the same file.
- Structural asserts: the `STRUCTURAL` dict (4 primitives) plus the `json_has`
  per-output loop.
- Canonical syntax: `docs/format.md` (`verify` section), linked per check above.