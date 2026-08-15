---
title: "stem separation: asserting relations, because there is no right answer"
description: "How a two-stage separator with no single correct output is verified — stems recombine to the source within a residual tolerance, and every stem preserves duration."
type: case-study
---

# stem separation: assert relations, not outputs

`stem_separation` is the reference example of two advanced contracts at once: a `requirements.python` preflight class, and **metamorphic verification** — a `verify:` block asserting *relations* between output and source rather than properties of the output alone. It is powered by `python-audio-separator` (MDX-Net / RoFormer / Demucs over ONNX Runtime + PyTorch), and it is the one heavy component in the system.

## The problem

There is no single correct answer to "what should the drums sound like?" — "Separation quality cannot be asserted". But a silent, duplicated, truncated, or source-mismatched stem *can* be detected, because whatever the separation is, it must decompose the input. "Separation is a canonical 'exit 0 but wrong' operator", and a component that produces silence and advances the chain is exactly what the contract exists to catch.

## The decision

Metamorphic, stem-count-agnostic verification. Two post-conditions:

- `stems_preserve_duration` — `audio_duration_matches`, `outputs: auto`, `tolerance_s: 0.2`: "Every produced stem must preserve the source duration (±0.2s). Guards silent/truncated/padded outputs a green exit would hide."
- `stems_recombine_to_source` — `stems_recombine`, `stems: auto`, `max_residual_db: -9.0`: "The stems must decompose the input: summing all stems must leave a residual at least 9 dB below the source. In hybrid mode the stage-2 residual vocals are folded into 'other' so this holds exactly. Catches a silent/duplicated/garbage/mismatched stem even though separation has no single right answer."

`stems: auto` covers every registered stem file, so one contract spans the hybrid 4-stem, demucs6 6-stem, and 2-stem presets. Below them, structural asserts: `primary_output` `exists, non_empty, audio_valid`; `separation_metadata` valid JSON carrying `preset`, `stems`, `source_input`. The invariant also holds by construction in hybrid mode: "The hybrid's stage-2 residual vocal bleed is **folded into `other`** (nothing discarded), so the four stems still recombine exactly to the source: `vocals + drums + bass + other == mix`." Inbound, the component is honest about its gravity: if `audio-separator` is missing it "fails honestly (`status: failed`, `reason: audio_separator_not_found`) — never a faked success".

## The war story

This component's war story is the bug class it is built against, plus two traps the README documents from experience:

**Silence defeats recombination; duration catches it.** "The separator will run; the output stems may be near-silent. The `stems_recombine_to_source` contract will still pass (silence + silence = silence), but `stems_preserve_duration` will still catch a truncated output." No single relation covers everything — which is exactly why there are two, and why the caveat is written down.

**A preflight that passes and a build that fails.** "Demucs `diffq` has no cp311 wheel (and the requirement's `python_version` floor is `>=3.10`, so a newer interpreter would *pass preflight* and then fail to build — pin the venv to 3.10)." A green check that lies about readiness is the same defect class as exit 0 with silence.

## Measured verification

The README's measured section is on a 12-second excerpt, CPU. Provenance — quoted byte-identically from `components/stem_separation/README.md`; this study did **not** re-run separation (heavy tier: venv, model weights, slow on CPU — "BS-RoFormer takes minutes for tens of seconds of audio"):

- **hybrid** → `vocals, drums, bass, other`; `verified`; recombination residual ≈ **−27.6 dB**; durations preserved.
- **handoff** — hybrid → `normalization`: the vocals stem mastered to **−13.9 LUFS** (target −14), both contracts pass, chain `completed`.
- **preset switch** — `demucs` preset → single htdemucs_ft, `primary_stem: drums` honored, `verified` (−24.1 dB). Proves the knob.

Provenance note, in the README's own words: "The measured values (residual dB, LUFS, duration) are provenance claims about real audio; they have not been altered."

## What it teaches

**For creative operations, assert relations, not outputs.** When there is no single correct answer, there is still an invariant — here, decomposition: the stems must sum back to the source. One relation cannot catch everything (silence passes recombination by definition), so pair relations that fail independently — recombination and duration. And make the contract count-agnostic (`stems: auto`) so one verified contract scales across every preset the knob can produce.

- [component README](../../components/stem_separation/README.md)
- [step.yaml](../../components/stem_separation/step.yaml)
- [the handoff target, verified upstream](./normalization.md)
- [verification philosophy](../explanation/verification.md)
- [architecture](../explanation/architecture.md)