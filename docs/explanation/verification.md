---
title: "Verification: proven correct, not exited 0"
description: "The prime directive and its consequences — verified IN vs verified OUT, why audio_valid beats non_empty, why the verifier re-measures instead of trusting the run's own logs, fail-open vs fail-closed, metamorphic invariants for creative operations, and the honest limits of what can be proven."
type: explanation
---

# Verification: proven correct, not exited 0

The prime directive is one sentence: **proven correct, not merely exited 0.** This page is
the argument for that sentence and the machinery that carries it.

## Why a green exit code is not success

Audio DSP almost never crashes. It produces *something*: silence, a 6 dB level error, a 30 ms
truncation, a decorrelated stereo image. Every one of those is a valid audio file that passes
every check a normal pipeline makes.

That was survivable while a human sat in the loop, because the ear is a post-condition — it
fires automatically and cannot be fooled by a byte count. Automation deletes that sensor and,
by default, replaces it with nothing. An agent cannot listen; it reads an exit code, and an
exit code cannot tell the difference between a stretched sound and an empty file.

So a component that runs but produces the wrong output is worse than one that fails, because
it lies to whatever is operating it. A tool that fails is a nuisance. **A tool that lies is a
liability** — it spends trust it did not earn, and the bill arrives later, for someone who has
stopped checking.

Workchain's answer is that every component declares a contract, and a single verifier enforces
it after every run. Two contracts, on two sides of the run.

## Verified IN — checked before the run

`requirements:` in `step.yaml` declares what the component needs: `commands` (ffmpeg,
ffprobe, …), `python` (venv + packages), `node`, `models`, `env`. `lib/workchain_preflight.py`
checks them *before* `run.sh` executes, so a missing dependency fails the step immediately with
a clear message instead of letting it half-run and die somewhere in the middle. `when:` guards
make requirement groups conditional on the resolved params and fail closed: if the guard's
param cannot be resolved, the group is treated as required.

`workchain doctor` runs this preflight across the whole registry — the install health check for
a machine.

## Verified OUT — checked after the run, against the artifacts

`verify:` in `step.yaml` declares what the run must have produced:

- **Structural asserts** — `exists`, `non_empty`, `audio_valid`, `json_valid` — against the
  declared outputs.
- **`json_has`** — required keys in a JSON output.
- **Post-conditions** — numeric and relational checks on the artifacts: loudness on target,
  format matches the request, duration preserved, stems recombine, hash matches, and more
  (the authoritative list is `POST_CHECKS` in `lib/workchain_verify.py`).

A component with no `verify:` contract is honestly labeled **unverified** rather than silently
trusted. There is no default that sneaks a run through.

## Why `audio_valid` and not `non_empty` alone

`non_empty` asks a filesystem question: does the file have bytes? A 44-byte WAV header with
zero samples in it has bytes — and passes. `audio_valid` asks an audio question: it re-probes
the file with `ffprobe` and requires at least one audio stream with a positive duration. It
does not pass for a header with no samples. **Most silent-failure bugs live in exactly that
gap**, which is why the rule for any audio output is: always use `audio_valid`.

## The component does not get to grade its own homework

The verifier re-measures. `audio_lufs_within` runs `ffmpeg loudnorm` on the output file on
disk and compares the measured value to the target that the resolved parameters called for.
`audio_format_matches` re-probes with `ffprobe`. `content_hash_matches` recomputes a hash.
`stems_recombine` mixes the stems it finds on disk back together and measures the residual —
it never asks the component how the separation went. The component's own logged value is not
evidence.

Why so distrustful? Because the log is written by the same code that produced the output, and
we have shipped the bug that makes this necessary: normalization used to measure loudness and
*never compare it* — the measurement sat in the output JSON, looking like verification, while
an off-target file sailed through. The post-condition `integrated_loudness_on_target` exists
specifically to close that "measured it and never compared it" hole. Logging is not
verification; verification is a separate pass over separate evidence.

Here is the real shape of a failed verification, quoted from `README.md` (produced by running
a chain whose requested target is unreachable under the true-peak ceiling):

```
✗ normalization — verification FAILED (1 of 8 checks)
    integrated_loudness_on_target: measured -10.56 LUFS vs target -5.0 (±1.0) → off by 5.56 LU
Chain halted: step 'normalization' failed
```

The component exited 0 and reported "Normalization completed". The verifier disagreed. That
disagreement — and only that disagreement — is what stops the chain.

## Fail-open vs fail-closed: which side each check is on

Every check must be designed knowing which failure mode it permits:

- **Equality fails open.** `None == None` is `true`. We shipped exactly this: an equality
  assertion between two absent values passed, and CI reported green on a run where the
  component never started. The guard that prevents it: prove both sides exist before
  comparing. Inequality fails closed — which is why the metamorphic relations we lean on
  hardest need the existence guard most.
- **An empty contract fails, it never passes vacuously.** `audio_format_matches` refuses to
  report PASS when no format dimension resolved ("empty contract proves nothing"), and
  `json_fields_within` with an empty `require` list fails rather than passing. The same rule
  applies at the component level: verify blocks are never shipped empty.
- **Unknown constructs fail.** An unknown assert primitive, unknown post-condition check, or
  unparsable constraint is a failure, never a skip. The verifier would rather refuse a run
  than bless a check it does not understand.

## Creative operations: no right answer, so assert the invariants

For a transform where "correct output" is a matter of taste, you cannot assert the output —
so assert the *relations* that must hold:

- duration preserved, or related to the requested factor (`audio_duration_matches`);
- loudness preserved where the operation should not have changed it;
- separated stems recombine to the source within a residual tolerance
  (`stems_recombine` — silence + silence = silence, so this catches a silent-input
  failure mode of a different kind than duration does);
- the same input and parameters render byte-identically (`content_hash_matches`).

Tolerances are declared in the contract and enforced by the verifier — the loudness check
above carries `±1.0 LU`, the residual check a floor in dB below the source level. They are
checked, not asserted: a tolerance written into `step.yaml` is a promise the verifier can
enforce, not a log line the component can write.

## The honest limits

None of this proves the output *sounds good*. There is no "is this audible?" check, and there
cannot be a numeric one — verification proves conformance to the contract the component
declared, not aesthetics. That is why the tiers are honest about what was actually proven:

- **unverified** — ran, but no contract proved its output;
- **verified** — passed its declared contract automatically;
- **certified** — an ed25519 signature over the component's definition hash; roadmap, not yet
  implemented.

And because a gate nobody has watched fail is decoration that manufactures confidence, the
test chains include [`chains/tests/normalization_offtarget.yaml`](../../chains/tests/normalization_offtarget.yaml):
it requests a target unreachable under the true-peak ceiling, the component exits 0 and
misses, and the verifier must catch it. On signals whose crest factor makes the target
unreachable, that chain goes red — on a plain sine it does not, which is exactly the point:
whether the gate is exercised depends on the signal, and the gate is what has to be right.

- The full contract specification: [`docs/format.md`](../format.md)
- The prime directive in full, with the shipped failure stories: [`AGENTS.md`](../../AGENTS.md)
- What this verification does *for agents*: [`docs/explanation/agent-first.md`](./agent-first.md)
- How to read a failed run: [`docs/troubleshooting.md`](../troubleshooting.md)