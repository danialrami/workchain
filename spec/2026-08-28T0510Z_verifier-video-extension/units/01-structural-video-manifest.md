# Unit 01 — structural video/manifest asserts

## Objective

Add `video_valid` and `manifest_valid` primitives to `STRUCTURAL` in
`lib/workchain_verify.py`, so a contract can assert a video stream decodes-positive and a
manifest is a recognizable HLS/DASH document.

## Context

- `lib/workchain_verify.py` @ fork `fb82746`; `STRUCTURAL` is `{ exists, non_empty,
  audio_valid, json_valid }` (line ~118). `audio_valid` is the reference shape to mirror.
- See `spec/2026-08-28T0510Z_verifier-video-extension/SPEC.md` for the full phase context
  and the exact primitive contract.
- Consumers (not touched here): `lufs-audio/smart-abr-ladder`, `lufs-audio/llhls-certify`,
  `lufs-audio/serverless-transcode`.

## Acceptance criteria

- [ ] `_assert_video_valid(path)` shells `ffprobe -select_streams v:0 -show_entries
      stream=codec_type:format=duration -of json`; ok = a `codec_type=="video"` stream exists
      and `duration > 0`.
- [ ] `_assert_manifest_valid(path)` text-reads the file; ok = contains a line starting
      `#EXTM3U` (HLS) OR a `<MPD` element (DASH); returns detected kind in `detail`.
- [ ] Both registered in `STRUCTURAL`; both return `(False, "missing: <path>")` on a
      missing file.
- [ ] Honest failures: a non-video file fails `video_valid`; a non-manifest text file fails
      `manifest_valid` — neither fabricates a pass.

## Interface contract

`STRUCTURAL` gains `"video_valid": _assert_video_valid` and
`"manifest_valid": _assert_manifest_valid`. Signature `(path, **_) -> (ok: bool, detail: str)`
unchanged from the existing primitives.

## Boundaries — do NOT touch

- `audio_valid`, `json_valid`, and all existing structural asserts (additive only).
- `POST_CHECKS` and the measurement helpers (Units 02–04).
- `engine/`, `cli/`, `mcp-server/`, `components/`.

## Output

- Edit `lib/workchain_verify.py` (structural block only) + a test fixture (a tiny generated
  mp4/ts via ffmpeg, plus a not-video file) + a test that fails-then-passes.

## Verification

- `python3 lib/workchain_verify.py … --json` on a contract declaring both primitives:
  exit 0 on a valid fixture, exit 1 on an invalid one.
