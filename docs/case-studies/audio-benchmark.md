---
title: "audio_benchmark: measures, does not gatekeep"
description: "Seven independent checks file a report; a failed check marks the run completed_with_errors rather than lying about a clean success. Verify validates the report's shape, not its content."
type: case-study
---

# audio_benchmark: report, not gate

`audio_benchmark` is the diagnostic pass. It sources seven independent check scripts — format, loudness, DC offset, noise floor, spectral, phase, dynamics — runs whichever subset you ask for, and combines the results into a single JSON report via a small python3 helper.

## The problem

A diagnostic that gated on its own results would fail your chain because loudness came in hot — punishing the very thing you wanted measured. And a diagnostic whose check script silently errored would produce a partial report that looks complete. The README's one-line principle: "it measures, it doesn't gatekeep."

## The decision

Report not gate. If a check's output fails to parse, "the run still completes but is honestly marked `completed_with_errors` rather than papering over it as clean." Parameters: `checks` (defaults to all seven, or `"all"`), `expected_spec` (e.g. `"24/48000/2"`). Light tier: `requirements.commands: [ffmpeg, ffprobe, python3]`. Verify is structural only — both `benchmark_report` and `primary_output` must be `exists, non_empty, json_valid` and carry `checks` and `benchmark_count`. "That's deliberate: this component reports, it doesn't judge." The README also records a portability fix: "All arithmetic uses stdlib python3 (replacing `bc`, which is absent from minimal containers)."

## The war story

The honesty is in the failure path: `completed_with_errors` keeps the run alive while telling the truth. "exit 0 alone proves nothing here; verify is what proves the report is real."

## Measured verification

The README records no numeric measurements, and this study adds none.

## What it teaches

**Verification's job depends on the component's role.** For a gate, fail on miss. For a report, verify means "a well-formed report," not "the audio sounds good." A measure that does not judge still has to be honest about its own failure — `completed_with_errors` says "the check script itself had a problem," rather than hiding it.

- [component README](../../components/audio_benchmark/README.md)
- [step.yaml](../../components/audio_benchmark/step.yaml)
- [verification philosophy](../explanation/verification.md)
- [architecture](../explanation/architecture.md)