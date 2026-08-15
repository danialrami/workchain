---
title: "format_conversion: structural-only, and honest about it"
description: "The smallest verify contract in the system proves the output is decodable audio — and says out loud that it does not yet prove the format matches what was asked for."
type: case-study
---

# format_conversion: structural-only, and honest about it

`format_conversion` probes the input (codec, sample rate, channels, bit depth) with `ffprobe`, then builds an FFmpeg command tailored to the requested `target_format`. Lossless targets preserve the source's sample rate and channel count and pick the matching PCM or native lossless codec; lossy targets pick the best available encoder — "e.g. `libmp3lame` before falling back to `libshine`, `libfdk_aac` before native `aac`" — and apply the requested bitrate.

## The problem

Format conversion's lying failure mode is the silent downgrade: a target whose encoder is missing, quietly converted into something else with a clean exit. This component fails loudly instead: "If a target format has no usable encoder installed, the step fails loudly rather than silently downgrading." The fallback logic "is lifted from `audioconv-cli`, so the fallback behavior is proven outside the workchain too."

## The decision

Light tier: `requirements.commands: [ffmpeg, ffprobe]`, preflighted before the run — "missing either one blocks the step outright." The verify block is deliberately minimal: structural only — `primary_output` must be `exists, non_empty, audio_valid`. "No `post_conditions` are declared, so this is structural-only: the contract doesn't (yet) assert that the output's codec/sample-rate/channel-count actually match what you asked for." The README names the fix: "a future `audio_format_matches` post-condition could close it." A related declared defect in the same family (`alac` → `.m4a`, unexpressible in the current `path_template`) is tracked as "one family, one fix, tracked together".

## The war story

The story is the gap named rather than hidden: the contract is structural-only and says so, twice — in the step.yaml comment and the README. A check that asserts existence and decodability but not format is honest about what it proves, and the missing `audio_format_matches` is a named, recognized fix rather than a surprise when it lands.

## Measured verification

None exist in the README, and this study adds none. The absence is the point: `format_conversion` is the system's structural-only contract, and both the step.yaml comment and the README say so openly.

## What it teaches

**A structural contract is real coverage, and no more.** exists + non-empty + `audio_valid` proves the file is decodable audio with positive duration; it does not prove it is the format you asked for. Coverage you do not have should be named, not implied — that is what lets a future `audio_format_matches` land as a recognized fix rather than a surprise. "Proven correct, not merely exited 0" still applies: even the weakest contract re-measures the artifact instead of trusting the exit code.

- [component README](../../components/format_conversion/README.md)
- [step.yaml](../../components/format_conversion/step.yaml)
- [verification philosophy](../explanation/verification.md)
- [architecture](../explanation/architecture.md)