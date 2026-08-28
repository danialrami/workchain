# Spec — add video/manifest/VMAF assertion primitives to the workchain verifier

State: fork `danialrami/workchain` @ `fb82746` (this is the workchain fork Daniel
maintains; migrate to `lufs-audio/workchain` upstream when ready). The verifier is
`lib/workchain_verify.py` (60 KB).

## Problem

The verifier's reachable condition primitives are audio-only. Grep of
`lib/workchain_verify.py` confirms:

- `STRUCTURAL = { exists, non_empty, audio_valid, json_valid }` — `audio_valid` shells to
  `ffprobe -select_streams a:0` and asserts an audio stream exists with positive duration;
  there is **no `video_valid`** (and no manifest check of any kind).
- `POST_CHECKS = { json_fields_within, audio_format_matches, content_hash_matches,
  audio_lufs_within, audio_peak_above, audio_duration_matches, stems_recombine,
  acoustic_roundtrip, seed_record_verifies, embedding_wellformed }` — every numeric/
  relational check is audio- (or provenance-) specific; there is **no VMAF**, bitrate,
  manifest-integrity, or rendition-consistency post-condition.

The consequence is load-bearing: three new LUFS projects — `smart-abr-ladder` (per-shot
ABR encoding), `llhls-certify` (HLS/LL-HLS/DASH manifest certification), and
`serverless-transcode` (verifiable transcode) — each declare, in their own `verify:` stage,
post-conditions the verifier literally cannot express. A contract that names an unknown
primitive records a `false` "unknown post-condition check" failure today (see the
`POST_CHECKS.get(kind) is None` branch), so those components cannot reach a verified tier
until this extension lands. This is the *one* shared dependency on all three video paths.

The extension is deliberately small and additive: it generalizes the verifier's existing
shape (structural assert + numeric/relational post-condition, measured independently via
ffmpeg/ffprobe) from "audio files" to "audio **or video** files and manifests." It does
not introduce new architecture, new dependencies, or a second verifier.

## Goals / constraints

- Add `STRUCTURAL` primitive `video_valid` — a decode/stream check mirroring `audio_valid`,
  but for a video stream (asserts a video stream exists, has positive duration, and has a
  decodable codec per ffprobe).
- Add `STRUCTURAL` primitive `manifest_valid` — a manifest**s** structure check: the file
  parses and carries the minimal HLS/DASH markers (see *Primitives* for the exact, honest
  scope — this is structural validation, not full conformance).
- Add `POST_CHECKS` primitives, each independently measured via ffmpeg/ffprobe (never
  trusting the component's own sidecar):
  - `video_vmaf_within` — measured VMAF vs. a target, within tolerance (mirrors
    `audio_lufs_within`'s measure/compare shape).
  - `video_bitrate_within` — measured bitrate vs. target bitrate within a tolerance band.
  - `video_duration_matches` — output duration vs. source within frame tolerance (the video
    analogue of `audio_duration_matches`).
  - `manifest_segments_present` — every segment URI an HLS/DASH manifest references exists
    and is non-empty (the integrity check `llhls-certify`/`serverless-transcode` need).
  - `rendition_ladder_monotone` — across a set of renditions, quality is non-decreasing and
    bitrate is non-decreasing with resolution (no redundant/dominated rung).
- Reuse the existing helpers (`resolve_target`, `_resolve_source`, `measure_duration`,
  `_record`, `_persist`, the `STEP`/`POST_CHECKS` dispatch) — the new primitives slot into
  the exact dispatch the verifier already uses, so nothing in `engine/` or `cli/` changes.
- **No new dependencies.** Everything is ffmpeg/ffprobe + stdlib, exactly like the existing
  file. `video_vmaf_within` requires ffmpeg's `libvmaf` filter at *run* time but adds no
  Python package; a missing `libvmaf` is an honest named failure ("vmaf unavailable"), not
  a fallback value.
- Keep the file stdlib+ffmpeg on the light path: the video primitives follow the same
  subprocess-based pattern as `audio_valid` and `measure_integrated_lufs`.

## Primitives (the contract)

### STRUCTURAL: `video_valid`

Signature/behavior mirrors `_assert_audio_valid`:

```
video_valid  → ffprobe -select_streams v:0 -show_entries stream=codec_type:format=duration
```

- ok = a `v:0` stream exists with `codec_type == "video"` AND `duration > 0`.
- detail = `"video_stream=%s duration=%.3fs"` or the ffprobe error.
- No decode-to-frame; this is stream-presence + positive-duration, exactly as `audio_valid`
  does for audio (the deep decode check is `video_duration_matches`/`video_vmaf_within`).

### STRUCTURAL: `manifest_valid`

Honest scope: this is **structural** validation, not full conformance. It proves the file
is a parseable HLS or DASH manifest with the required root markers — the full conformance
rules (sequence monotonicity, part alignment, rendition switching) live in the
`llhls-certify` *component*, which declares *this* primitive as its floor and adds its own
`post_conditions` on top. Mirroring `_assert_json_valid`'s shape, but for playlist text:

```
manifest_valid → text-parse + root-marker check:
  - HLS: file contains a line beginning "#EXTM3U"
  - DASH: file contains a "<MPD" element
```

- ok = one of the two markers present (and the file is non-empty by `non_empty`'s nature).
- detail = detected kind + whether the marker was found.
- Deliberately does **not** attempt a full RFC 8216 / ISO 23009 grammar here — that would
  re-bless a half-implemented conformance checker inside the verifier itself, which is the
  exact "component measures its own output" trap this file exists to refuse. The verifier
  proves *shape*; the sibling component proves *conformance*.

### POST_CHECKS: `video_vmaf_within`

Mirrors `check_audio_lufs_within` (measure → resolve target → compare within tolerance):

```
params: output (default "primary_output"), target_param (default "target_vmaf"),
        tolerance (default 1.0), vmaf_model (default "version=vmaf_v0.6.1")
```

- measure: `ffmpeg -i <source> -i <output> -lavfi libvmaf=<model>:log_fmt=json -f null -`
  (or `-filter_complex` for the reference/output pair), parse the mean VMAF score.
- resolve target via `resolve_target` (component's declared target, e.g. the ladder's
  per-rendition `vmaf_target`).
- ok = `|measured − target| <= tolerance` (NaN-safe; missing libvmaf → named failure).
- detail = measured vs. target vs. tolerance, mirroring the LUFS check's wording.

### POST_CHECKS: `video_bitrate_within`

```
params: output (default "primary_output"), target_param (default "target_bitrate_kbps"),
        tolerance_pct (default 15.0)
```

- measure bitrate via `ffprobe -show_entries format=bit_rate` (bits/sec → kbps), or
  `format=duration,size` fallback when `bit_rate` is absent (size*8/duration/1000).
- ok = measured within `target *_param* ± tolerance_pct%`.
- detail = measured vs. target vs. band.

### POST_CHECKS: `video_duration_matches`

```
params: outputs (list|single|"auto"), source (resolution via `_resolve_source`),
        tolerance_s (default 0.1)
```

- Video analogue of `audio_duration_matches`: each listed output's `measure_duration`
  within `tolerance_s` of the source duration. Reuses `_resolve_stem_list`'s list/auto
  semantics if present in the fork (else an explicit `outputs` list).

### POST_CHECKS: `manifest_segments_present`

```
params: manifest (output name), base_dir (optional), segment_globs (optional)
```

- Reads the manifest, extracts segment URIs (`.ts`/`.m4s`/`.mp4`/`.aac` URI lines /
  `<SegmentTemplate>`/`<BaseURL>` for DASH), resolves them against `base_dir`, and asserts
  each exists and is non-empty.
- ok = all referenced segments present and non-empty; detail lists the first missing/bad
  URI.
- This is the integrity floor `llhls-certify` and `serverless-transcode` both need.

### POST_CHECKS: `rendition_ladder_monotone`

```
params: renditions (list of output names, ordered ascending by resolution),
        quality_param (default "vmaf"), strict (default true)
```

- For each adjacent pair, assert (a) measured VMAF is non-decreasing and (b) bitrate is
  non-decreasing. A rung whose higher-resolution neighbor does not strictly improve quality
  at higher bitrate is a dominated/redundant rung → violation.
- measured map keyed by rendition; detail names the offending rung pair.

## Units (fan-out briefs — one PR each)

- **01 — structural video/manifest asserts** (`video_valid`, `manifest_valid`): add the two
  `_assert_*` functions, register in `STRUCTURAL`, add fixtures/tests. Owns only the
  `lib/workchain_verify.py` structural block.
- **02 — video measurement helpers** (`measure_video_bitrate`, `measure_vmaf`,
  `measure_video_stream`): the ffprobe/ffmpeg subprocess helpers the post-conditions call.
  Owns the measurement block only.
- **03 — numeric video post-conditions** (`video_vmaf_within`, `video_bitrate_within`,
  `video_duration_matches`): register in `POST_CHECKS`, wire to Unit 02 helpers, tests
  (incl. the libvmaf-unavailable honest-failure path).
- **04 — manifest + ladder post-conditions** (`manifest_segments_present`,
  `rendition_ladder_monotone`): register in `POST_CHECKS`, tests with checked-in fixture
  playlists (text) + a small ladder fixture.

## Boundaries — do NOT touch

- `engine/`, `cli/`, `mcp-server/`, `components/` — this extension is verifier-only; the
  three consumer projects wire their *own* `verify:` declarations against these primitives
  later.
- The existing audio primitives and their semantics — additive only; no renames, no
  behavior changes.
- `spec/` fan-out briefs from the prior run (they are dispatch docs, read-only here).
- Do NOT add a Python dependency (stay stdlib+ffmpeg). Do NOT implement a full HLS/DASH
  grammar inside the verifier (that is `llhls-certify`'s job).

## Done criteria

- [ ] `grep -n "video_valid\|manifest_valid\|video_vmaf_within\|video_bitrate_within\|video_duration_matches\|manifest_segments_present\|rendition_ladder_monotone" lib/workchain_verify.py` shows all seven registered in `STRUCTURAL`/`POST_CHECKS`.
- [ ] Each new primitive has a test that *fails on the broken case then passes on the fixed
      case* (red→green), per the repo's "prove the test can fail" rule.
- [ ] `video_valid`/`manifest_valid` return honest named failures on a missing/bad file
      (never a fabricated pass).
- [ ] `video_vmaf_within` fails by name when `libvmaf` is unavailable (no fallback value).
- [ ] No new third-party dependency; `python3 -m pytest` (or the repo's test runner) green.
- [ ] Exit-code semantics unchanged (0 verified / 1 contract / 2 usage).

## Verification

- `python3 lib/workchain_verify.py <root> <component> <context> --json` against a fixture
  component declaring each new primitive, once with a satisfying contract (exit 0) and once
  with a violating contract (exit 1), proving the enforcer rejects an "exit 0 but wrong"
  video output.

## Ecosystem references (where the consumers live)

- `lufs-audio/smart-abr-ladder`, `lufs-audio/llhls-certify`,
  `lufs-audio/serverless-transcode` — the three projects whose `verify` stages name these
  primitives. Their in-repo specs already reference this extension as the shared dependency.
- The centralized motivation for the *whole* five-project push (and the orchestration
  plan) lives in the KB suite, not in any codebase.
