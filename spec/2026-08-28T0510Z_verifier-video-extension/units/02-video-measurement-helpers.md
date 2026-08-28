# Unit 02 — video measurement helpers

## Objective

Add the independent ffprobe/ffmpeg measurement helpers the numeric video post-conditions
call: `measure_video_bitrate`, `measure_vmaf`, `measure_video_stream`.

## Context

- Mirror `measure_duration` / `measure_stream` / `measure_integrated_lufs` subprocess
  patterns already in `lib/workchain_verify.py`.
- `measure_vmaf` requires ffmpeg's `libvmaf` filter at run time; no Python dependency is
  added — a missing `libvmaf` returns `None`, which the caller turns into a named failure.

## Acceptance criteria

- [ ] `measure_video_bitrate(path)` returns kbps via `ffprobe -show_entries format=bit_rate`
      (converting bits/s→kbps); falls back to `size*8/duration/1000` when `bit_rate` absent;
      returns `None` on any error.
- [ ] `measure_vmaf(source, output, model="version=vmaf_v0.6.1")` runs the libvmaf
      filter, parses the mean score from `log_fmt=json`, and returns `None` (never a
      fabricated value) if libvmaf is unavailable or the run fails.
- [ ] `measure_video_stream(path)` returns `(width, height, fps_num, fps_den, codec)` from
      `ffprobe -select_streams v:0`, each `None`-safe on absence.
- [ ] All three are stdlib+ffprobe/ffmpeg only; no new imports beyond what the file already uses.

## Interface contract

```
measure_video_bitrate(path) -> Optional[float]   # kbps
measure_vmaf(source, output, model=...) -> Optional[float]   # mean VMAF
measure_video_stream(path) -> (w, h, num, den, codec)  # each Optional
```

## Boundaries — do NOT touch

- `STRUCTURAL` (Unit 01), `POST_CHECKS` registration (Units 03–04).
- Helpers are pure functions; they do not write context or mutate state.

## Output

- Edit the measurement block of `lib/workchain_verify.py` + tests for each helper
  (fixture-driven, incl. the libvmaf-missing → `None` path).

## Verification

- `python3 -m pytest …` (or repo test runner) green; `measure_vmaf` on a system without
  libvmaf returns `None` rather than raising.
