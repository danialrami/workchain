# Unit 03 — numeric video post-conditions

## Objective

Add and register `video_vmaf_within`, `video_bitrate_within`, and
`video_duration_matches` in `POST_CHECKS`, wired to Unit 02's helpers.

## Context

- Mirror `check_audio_lufs_within` / `check_audio_duration_matches` (measure → resolve
  target → compare within tolerance → `(ok, detail, measured)`).
- Reuse `resolve_target` and `_resolve_source` already in the file; do not reimplement.

## Acceptance criteria

- [ ] `video_vmaf_within(pc, …)`: params `output` (default `primary_output`),
      `target_param` (default `target_vmaf`), `tolerance` (default 1.0), `vmaf_model`;
      ok = `|measure_vmaf(source, output) − target| <= tolerance`; a `None` measure →
      `(False, "vmaf unavailable …", …)` (named, not zero).
- [ ] `video_bitrate_within(pc, …)`: `target_param` (default `target_bitrate_kbps`),
      `tolerance_pct` (default 15.0); ok = measured kbps within band.
- [ ] `video_duration_matches(pc, …)`: `outputs` (list|single), `tolerance_s` (default
      0.1); each output `measure_duration` within tolerance of the source (via
      `_resolve_source`).
- [ ] All three registered in `POST_CHECKS`; NaN/inf-safe comparisons (per the existing
      LUFS check).

## Interface contract

`POST_CHECKS` gains `"video_vmaf_within"`, `"video_bitrate_within"`,
`"video_duration_matches"`; each conforms to the `(pc, ctx, step_key, step_yaml,
output_paths) -> (ok, detail, measured)` signature.

## Boundaries — do NOT touch

- `STRUCTURAL` (Unit 01), measurement helpers beyond calling them (Unit 02),
  `manifest_segments_present`/`rendition_ladder_monotone` (Unit 04).

## Output

- Edit `lib/workchain_verify.py` (post-condition block) + tests: red→green per primitive,
  incl. a VMAF-unavailable honest failure and a duration-mismatch violation.

## Verification

- `python3 lib/workchain_verify.py … --json` on a violating contract exits 1 with the
  primitive named; a satisfying contract exits 0.
