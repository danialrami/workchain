---
title: "normalization: the gate that closes 'measured but never compared'"
description: "Why loudness normalization got a contract that re-measures the output instead of trusting the component's own log — and how a hardcoded 0.6 offset shipped for every user until the verifier's ±1.0 LU gate caught it."
type: case-study
---

# normalization: a green exit is not a target hit

Loudness normalization is the last step before a master ships, and the canonical worked example of the component contract — "small, deterministic, and fully contracted" (`components/normalization/README.md`). The component measures integrated loudness, normalizes to a target LUFS with FFmpeg's `loudnorm` (two-pass by default, so the exact gain is computed rather than estimated), and writes the normalized audio plus a JSON sidecar of the measurements.

## The problem

The failure mode is quiet in every sense: `loudnorm` can run, write a perfectly valid WAV, log a `final_lufs` value — and still miss the requested target. The gate's own description names the bug: "the component recorded `final_lufs` and exited 0 regardless". Streaming platforms "sit around −14 LUFS; the schema default is −11", so a chain that advances an off-target master ships a different product than asked — while every log line reads as success.

## The decision

Two contracts, both mandatory. **Verified IN**: `requirements.commands: [ffmpeg, ffprobe]`, checked by `lib/workchain_preflight.py` *before* `run.sh` runs. **Verified OUT**: structural asserts — `primary_output` must be `exists, non_empty, audio_valid`; `loudness_metadata` valid JSON carrying `target_lufs` and `final_lufs` — plus one post-condition, `integrated_loudness_on_target` (`audio_lufs_within`, `target_param: target_lufs`, `tolerance: 1.0`). "`lib/workchain_verify.py` **independently re-measures** the output's integrated LUFS and fails the step if it's more than ±1.0 LU off the requested `target_lufs`." The target is resolved from the params the step actually ran with (params > chain globals > schema default), so a `--params-json '{"target_lufs":-16}'` run is checked against −16. **The component's own logged value is not evidence.**

## The war story

The README records two shipped bugs and one test built to catch the next one.

**Measured but never compared.** The component recorded `final_lufs` and exited 0 regardless — the log could not distinguish a miss from a hit. `integrated_loudness_on_target` is the enforcement that gap needed: an independent party re-measures the artifact.

**The hardcoded 0.6.** "Historical note: this was previously hardcoded to `0.6`, which silently pushed every normalize +0.6 LU hot and made the combined `stem_separation → normalization` chain overshoot target — the verifier's ±1.0 LU gate caught it. It is now `0` by default and configurable." The `offset` knob — meant as an intentional post-correction nudge for the rare deliberate bias — was shipping as a universal bias. Every chain normalized hot and green until an independent gate, tighter than the bias and out of the component's control, caught it.

**The negative test.** `chains/tests/normalization_offtarget.yaml` "asks for a target unreachable under the TP ceiling; the component exits 0 but misses. The verifier must catch it" (`target_lufs: -5` under `true_peak: -1.5`). A check nobody has watched fail is decoration that manufactures confidence.

## Measured verification

Provenance — every value below is quoted byte-identically from the named source; no fresh measurement was taken for this study.

- gate tolerance **±1.0 LU** — `components/normalization/README.md` ("more than ±1.0 LU off the requested target") and `step.yaml` (`tolerance: 1.0`)
- shipped bias **+0.6 LU** hot on every normalization — `components/normalization/README.md`, historical note
- target conventions: "Streaming platforms sit around −14 LUFS; the schema default is −11." — `components/normalization/README.md`
- the measured handoff (vocals stem mastered to **−13.9 LUFS**, target −14) lives in the `stem_separation` README — see [stem-separation.md](./stem-separation.md)

## What it teaches

**A green exit is not evidence.** Any component can log a number that looks like success; the system stays trustworthy because an independent party re-measures the artifact and compares it to what was asked for. When a parameter lets you bias a measurement, default it to zero — and keep the gate tight enough to catch the bias that ships anyway.

- [component README](../../components/normalization/README.md)
- [step.yaml](../../components/normalization/step.yaml)
- [the negative test chain](../../chains/tests/normalization_offtarget.yaml)
- [verification philosophy](../explanation/verification.md)
- [architecture](../explanation/architecture.md)