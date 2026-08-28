# Unit 04 — manifest + ladder post-conditions

## Objective

Add and register `manifest_segments_present` and `rendition_ladder_monotone` in
`POST_CHECKS`.

## Context

- The integrity and consistency checks `llhls-certify` and `serverless-transcode` need.
- `manifest_segments_present` is the *floor* (do referenced segments exist/non-empty);
  full conformance lives in the `llhls-certify` component, not the verifier (see SPEC.md).

## Acceptance criteria

- [ ] `manifest_segments_present(pc, …)`: params `manifest` (output name), `base_dir`
      (optional), `segment_exts` (default `.ts .m4s .mp4 .aac`); extracts segment URIs from
      the manifest (`#EXTINF` URI lines for HLS; `<SegmentTemplate>`/`<BaseURL>` for DASH),
      resolves against `base_dir`, asserts each exists & non-empty; detail names the first
      failing URI.
- [ ] `rendition_ladder_monotone(pc, …)`: params `renditions` (ordered list),
      `quality_param` (default `vmaf`); for each adjacent pair asserts measured VMAF
      non-decreasing AND bitrate non-decreasing; a dominated rung (higher res, lower-or-equal
      quality at higher bitrate) → `(False, …, <rung pair>)`.
- [ ] Both registered in `POST_CHECKS`; honest named failures.

## Interface contract

`POST_CHECKS` gains `"manifest_segments_present"`, `"rendition_ladder_monotone"`.

## Boundaries — do NOT touch

- Units 01–03, `engine/`, `cli/`, `mcp-server/`, `components/`.
- Do not implement a full HLS/DASH grammar here — structural/floor only.

## Output

- Edit `lib/workchain_verify.py` + tests: text-fixture playlists (valid + one with a
  missing segment) and a small ladder fixture (monotone + one redundant rung).

## Verification

- `python3 lib/workchain_verify.py … --json`: missing-segment manifest → exit 1 naming the
  segment; redundant-rung ladder → exit 1 naming the pair; clean fixtures → exit 0.
