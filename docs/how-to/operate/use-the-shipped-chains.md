---
title: Use the Shipped Chains
description: Walkthrough of the four delivered chains — deliverable-voice, deliverable-broadcast, deliverable-streaming, cdp-spectral-wash — their globals, steps, and the results to expect, plus the chains/tests/ family.
type: how-to
---

# Use the Shipped Chains

Four production chains ship under `chains/`, plus `simple-test.yaml` and a
`chains/tests/` family. All four follow one shape — **conform the format first, normalize
loudness second, audit the result third** — so loudness is measured on the audio that
actually ships, and a failing check halts the chain with the measured facts. Run
`workchain chains` for the descriptions, `workchain chain <name>` for each chain's
definition. See the chain YAMLs at [chains/](../../../chains/) for the authoritative source.

## Deliverable: Voice / Dialogue

`chains/deliverable-voice.yaml` — prep a finished recording to a dialogue/VO spec.

**Promises:** WAV, 48 kHz, 24-bit, true mono, −22 to −20 LUFS integrated, true peak
below −3 dBFS.

**Globals:** `lufs_target: -21` (with a ±1.0 LU tolerance this covers the −22…−20 window
exactly; it also feeds normalization through the legacy `lufs_target` alias).

**Steps:**

```yaml
- name: format_conversion    # wav / 48000 / 24-bit / 1 channel (true mono)
- name: normalization        # target_lufs -21, two_pass, LRA 7, true_peak -3.0
- name: audio_benchmark      # checks format, loudness, dc_offset, noise_floor, phase, dynamics; expected_spec 24/48000/1
```

**What to expect:** `take-07_converted_normalized.wav` in the output dir, measured
≈ −21 LUFS (within tolerance), and `audio_benchmark` output in
`logs/audio_benchmark.json` reporting all six checks. Use for podcast dialogue, VO reads,
audiobook audio.

## Deliverable: Broadcast (EBU R128)

`chains/deliverable-broadcast.yaml` — prep a finished mix for broadcast under EBU R128.

**Promises:** WAV, 48 kHz, 24-bit, stereo, −23 LUFS integrated, true peak below −1.0 dBTP.
The 48 kHz rate is not optional in this world, which is exactly why a format contract is
worth having.

**Globals:** `lufs_target: -23`.

**Steps:**

```yaml
- name: format_conversion    # wav / 48000 / 24-bit / 2 channels
- name: normalization        # target_lufs -23, two_pass, LRA 7, true_peak -1.0
- name: audio_benchmark      # same checks; expected_spec 24/48000/2
```

**What to expect:** a stereo 48/24 file sitting at −23 LUFS integrated, true peak under
−1 dBTP. Use for TV, radio, podcast platforms that ask for the R128 spec.

## Deliverable: Streaming

`chains/deliverable-streaming.yaml` — prep a finished master for streaming platforms.

**Promises:** WAV, 48 kHz, 24-bit, stereo, −14 LUFS integrated with a −1.0 dBTP ceiling.
Same shape as the voice profile with the platform numbers; the contract re-measures both
format and loudness.

**Globals:** `lufs_target: -14`.

**Steps:**

```yaml
- name: format_conversion    # wav / 48000 / 24-bit / 2 channels
- name: normalization        # target_lufs -14, two_pass, LRA 7, true_peak -1.0
- name: audio_benchmark      # checks format, loudness, dc_offset, phase, dynamics; expected_spec 24/48000/2
```

Note the benchmark omits `noise_floor` (compare the voice chain's list) — read the YAML,
not this page, for the authoritative check list. Use when a platform asks for a −14 LUFS master (the common streaming target).

## CDP: Spectral Wash

`chains/cdp-spectral-wash.yaml` — a creative chain: turn a short sound into a long
spectral wash, then bring it to a usable level.

**Promises:** a stretched, blurred version of the input at −18 LUFS, true peak −1.5 dBFS.

**Globals:** `lufs_target: -18`.

**Steps:**

```yaml
- name: cdp_transform       # effect stretch.time, values_json '{"factor": 4}', min_peak_dbfs -60
- name: normalization       # target_lufs -18, two_pass, true_peak -1.5
```

**What to expect:** a time-stretched, spectrally smeared version of the input at −18 LUFS.
With the default `factor: 4`, a measured run stretched 10 s of input to ≈40.08 s
(duration ratio ≈4.008). The order matters musically: stretch then blur smears an
already-long sound, where blur then stretch stretches the smear. Feed a short sample and get
a pad/ambience bed.

**Install note:** `cdp_transform` is tier `light` but needs the `cdp-wasm` Node package:
`npm install cdp-wasm` at the repo root (or set `cdp_wasm_dir` / `CDP_WASM_DIR`). Without
it the step fails with explicit install instructions.

**Determinism caveat (measured):** the component holds its own `render_is_deterministic`
invariant — it renders the same input twice and requires byte-identical output. On this
writer's 2-CPU sandbox, both `stretch.time` and `blur.blur` rendered *different* hashes on
the second pass, so the step failed verification and the chain halted:

```
✗ render_is_deterministic: determinism_ok: false == true  <- VIOLATED
```

The audio that rendered was real and correctly stretched (40.08 s, peak ≈ −12.8 dBFS);
what failed is byte-reproducibility on that machine. The component reports
`determinism_ok: false` and refuses to claim a verified run rather than silently shipping a
non-reproducible artifact. If you hit this, it is worth knowing before you rely on
byte-reproducible CDP renders from a given machine.

## simple-test

`chains/simple-test.yaml` — normalize to −14 then benchmark; used by the test suite as a
minimal two-component chain. Handy for smoke-testing a fresh engine.

## The chains/tests/ family

`chains/tests/` holds per-component contract tests (and a few deliberate failures). They
are valid chains you can run:

- `normalization_only` — normalization to −14 with the `lufs_target` global.
- `format_conversion_test`, `content_hash_test`, `audio_benchmark_test` — one component
  each, exercising a single contract.
- `cdp_transform_test`, `cdp_transform_envelope` — spectral effects under contract, the
  latter driving a param with a breakpoint envelope.
- `normalization_offtarget` — requests a target unreachable under the true-peak ceiling;
  the component exits 0 but misses, and **the verifier must catch it**. Run it to watch a
  verification FAILED block in action (exit 1) — see [Inspect a Run](./inspect-a-run.md).
- `stem_separation_test`, `stem_separation_demucs`, `stem_separation_and_normalize` — the
  heavy family; these need provisioning first (see
  [Provision Heavy Components](./provision-heavy-components.md)). `stem_separation_demucs`
  shows the preset knob (`demucs`, 4 stems); `stem_separation_and_normalize` shows context
  handoff: the vocals stem is mastered to target LUFS by normalization.

`workchain validate all --strict` validates every shipped and test chain.

## Which chain should I run?

| You have / you want | Chain |
|---------------------|-------|
| Dialogue / VO / audiobook, mono, −21 LUFS | `deliverable-voice` |
| Broadcast mix, stereo, −23 LUFS (R128) | `deliverable-broadcast` |
| Platform master, stereo, −14 LUFS | `deliverable-streaming` |
| A sample you want as a long ambient bed | `cdp-spectral-wash` (then normalize) |

## What next

- [Run Chains](./run-chains.md) — the run command and flags.
- [Inspect a Run](./inspect-a-run.md) — how to verify a run really delivered the spec.