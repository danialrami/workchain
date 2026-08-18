# cdp_transform

## What it does

Runs one Composers Desktop Project sound transformation on the input audio, via
[`cdp-wasm`](https://github.com/cdp-wasm-suite/cdp-wasm) — Oliver Larkin's WebAssembly port
of CDP — under a fail-closed parameter and output contract.

CDP is the original composable command-line audio-transformation suite (Trevor Wishart,
Richard Dobson, Martin Atkins, Composers Desktop Project Ltd, 1983–2023). `cdp-wasm` bundles
215 of its programs as WebAssembly and wraps 232 of them in a curated typed catalog: spectral
(PVOC) blurring and morphing, granular reordering, waveset distortion, time-stretching,
pitch-shifting, formant work, spatialisation. This component makes that catalog available as a
Workchain step.

**Why a wrapper is the useful thing to build.** `cdp-wasm` deliberately treats its declared
parameter ranges as advisory — `src/effects.js:147–158` says so, so a consuming UI can offer
to unlock the full span — and its only output check is `bytes.length === 0`. A 44-byte-header
WAV containing zero samples passes that. So `stretch.time` at `factor: 0.02` (declared minimum
0.25) renders silence, and the library's own agent-facing chain runner reports
`step 1 stretch.time: ok (0.00s, 1ch)` and exits 0. This component supplies the enforcement
the catalog leaves to the caller. The behaviour was confirmed against the published `cdp-wasm@0.5.3`: `stretch.time` at `factor: 0.02` returns a 2130-byte WAV containing zero sample frames, and every layer reports success.

No native build, no Python, no `uv` venv — plain Node plus one npm package.

## Parameters

| Name | Type | Default | Range | Meaning |
| --- | --- | --- | --- | --- |
| `effect` | string | `blur.blur` | — | cdp-wasm catalog effect id (`blur.blur`, `stretch.time`, `grain.reorder`, …). 232 available; `transform.mjs --list-effects` prints them as JSON with per-parameter ranges and a `supported` flag |
| `values_json` | string | `{}` | — | JSON object of effect parameters, e.g. `{"factor": 4}`. Anything omitted uses the cdp-wasm catalog default. Every supplied value is checked against that effect's declared min/max **before** any audio is processed |
| `values_brk_json` | string | `{}` | — | JSON object mapping a parameter to a breakpoint envelope so it varies over time: `{"windows": "0 1\n2 80"}` sweeps blur from 1 to 80 windows across two seconds. Each line is `time value`; times must not decrease and at least two points are required |
| `channels` | string | `split` | `split` \| `mix` | How multichannel sources reach mono-only effects. `split` processes each channel independently and recombines, preserving channel count; `mix` folds to mono first. See Edge cases — `split` is not free, and the `stereoUnsafe` flag for effects that own their output width |
| `min_peak_dbfs` | number | `-60` | −120 to 0 | Liveness floor. The render's true peak must exceed this or the step fails. Catches the well-formed-but-inaudible result |
| `allow_unlocked_range` | boolean | `false` | — | Fall back to the engine's hard limit (`hardMin`/`hardMax`) for parameters that record one. Many do not, and those stay bound by the curated range even when unlocked. Never disables the output contract |
| `cdp_wasm_dir` | string | `""` | — | Path to an installed `cdp-wasm` package (the directory with `package.json` and `wasm/`). Empty resolves `cdp-wasm` from `node_modules`. Also read from `CDP_WASM_DIR` |

## Inputs / Outputs

Input: `wav`, `mp3`, `aiff`, `aif`, `flac`, `m4a`, `ogg`.

| Output | Type | Required | Path | Notes |
| --- | --- | --- | --- | --- |
| `primary_output` | file | yes | `output/{input_name}_cdp_transform.wav` | Transformed audio, 32-bit float WAV, `audio/wav` |
| `transform_record` | json | yes | `logs/cdp_transform.json` | Effect id, resolved parameters, violations, and the independently measured properties of the render |

The record carries `measured_duration_s`, `measured_peak_dbfs`, `measured_rms_dbfs`,
`measured_sample_rate`, `measured_channels`, `input_duration_s`, `duration_ratio`,
`render_sha256` (+ `render_sha256_repeat`, file bytes), `render_samples_sha256`
(+ `render_samples_sha256_repeat`, SHA-256 over the decoded samples), `determinism_ok`
(gated on the sample digests), `container_bytes_stable` (recorded file-bytes comparison,
non-gating), and — for stereo output — `stereo_correlation` and `mono_sum_change_db`.

## Verified IN (inbound contract)

```yaml
requirements:
  commands:
    - node
    - ffmpeg
    - ffprobe
```

The `cdp-wasm` package itself is not expressible in the `commands` class, so `transform.mjs`
resolves it explicitly and fails with install instructions if it is absent. Install with
`npm install cdp-wasm` (Node 18+), or point `cdp_wasm_dir` at an existing copy.

## Verified OUT (outbound contract)

Structural asserts: `primary_output` must satisfy `exists`, `non_empty`, `audio_valid`;
`transform_record` must satisfy `exists`, `non_empty`, `json_valid` and carry `effect`,
`params_out_of_range`, `params_unknown`, `measured_duration_s`, `measured_peak_dbfs`,
`determinism_ok`, `render_samples_sha256`, `container_bytes_stable`.

`audio_valid` is the load-bearing one. It re-measures duration from the file with ffprobe and
requires it to be greater than zero, which is exactly what kills the zero-length class —
`non_empty` alone passes the bad file at 2130 bytes, the same way `requireOutput` does upstream.

Four post-conditions:

| id | Guards against |
| --- | --- |
| `params_within_declared_range` | A parameter outside the catalog's declared range, or naming a parameter that does not exist. Refused before processing |
| `output_peak_above_floor` | A render whose peak is at or below −60 dBFS — the well-formed-but-inaudible class. **audio_peak_above** re-measures the FILE with ffmpeg astats, independently of the component's record |
| `envelopes_were_applied` | A breakpoint envelope the step asked for that was not applied |
| `render_is_deterministic` | `determinism_ok == true`. Same input and parameters render the same decoded samples; the container is deliberately not part of the claim |

**Honest scoping — read this before trusting the contract further than it goes.**
`audio_valid` re-measures duration from the file with ffprobe, and `output_peak_above_floor`
re-measures the peak from the file with ffmpeg `astats` — both are independent re-measurements
of the written output; neither reads the value the component wrote about itself. What remains
asserted through `json_fields_within` (self-reported) is the determinism relation and the
parameter/envelope accounting: those compare fields the component computed, which is the right
tier for claims only the component's own pipeline can produce, and it is weaker than an
independent re-measurement. The `-60` floor is a deliberate literal in the contract rather than
a reference to `min_peak_dbfs`, so loosening the parameter cannot silently loosen the contract.
The fixture `chains/tests/cdp_peak_floor_fail.yaml` proves that independence: it loosens
`min_peak_dbfs` to `-90` so a `-65.1 dBFS` render exits the component cleanly and is still
failed by the verifier's re-measured floor.

**Why the samples and not the file?** Two renders of identical audio can still differ as
files: CDP's soundfile layer stamps wall-clock fields into the WAV container (the `PEAK` chunk
timestamp and the `LIST`/`adtl` `DATE` string), so a render that straddles a second boundary
differs from its sibling in exactly those bytes while the decoded samples are identical.
`determinism_ok` therefore compares SHA-256 digests over the **decoded samples**
(`render_samples_sha256` vs `render_samples_sha256_repeat`), and the old file-bytes
comparison is kept as a recorded, non-gating fact (`container_bytes_stable`) so the record
still says whether the container matched without letting a wall-clock field fail the step.

Determinism is asserted only for effects the catalog does **not** mark `parityExempt` or
`paritySkip` (seeded RNG, randomised event placement). For those, the component sets
`determinism_ok` true, records both sample digests, and states in `determinism_note` that
equality was not claimed — rather than manufacturing a passing comparison. The field is
emitted only when both renders actually completed, so a run where either side failed reports a
missing field and **fails**; it cannot pass on `None == None`.

## Usage

```bash
# Single component, straight through the CLI
node cli/bin/workchain.js run-component cdp_transform input.wav -o ./out \
  --param effect=stretch.time --param 'values_json={"factor":4}'

# In a chain
#   - component: cdp_transform
#     params:
#       effect: blur.blur
#       values_json: '{"windows": 40}'
#       min_peak_dbfs: -50

# Browse the catalog as JSON via the CLI (232 effects, ranges, per-effect flags incl. stereoUnsafe)
node cli/bin/workchain.js run-component cdp_transform --list-effects --json | python3 -m json.tool | less
```

## Edge cases

- **Only single-input, single-output effects run.** Multi-output (`partition.*`, `cantor.*`,
  `isolate.*`, `housekeep.split`), variadic (`rejoin.rejoin`), mixfile-chain (`multimix.*`,
  `panorama.spatial`) and two-input (`morph.*`, `formants.vocode`, `submix.merge`) effects are
  **refused with an explanatory error**. `applyEffect` returns `{outputs, names}` for
  multi-output effects, and writing that object to disk yields a file that still passes an
  exists check — refusing is the honest behaviour. Two-input and multi-output support needs a
  second input channel in the chain contract; that is deliberate future work, not an oversight.
- **`channels: split` is not free.** Mono-only effects processed per channel can decorrelate a
  stereo image, because waveset boundaries depend on content and diverge between channels. We
  measured a near-mono source (correlation 0.99991) coming back at **−0.50 correlation and
  −6.03 dB of mono-sum cancellation** through `splinter.into`; `scramble.scramble` cost
  −3.26 dB. 22 of 45 mono-only effects also diverge in per-channel output length (up to 57 ms),
  which `eachChannel` pads with trailing silence. The component **records**
  `stereo_correlation` and `mono_sum_change_db` for every stereo render but does not yet gate
  on them — the right threshold is a musical judgement we have not made. If mono compatibility
  matters for your material, use `channels: mix`, or check the record.
- **Some effects own their output channel count — the catalog flags them `stereoUnsafe`.**
  The installed `cdp-wasm@0.6.0` catalog declares this per effect through two fields (quoted
  from `index.d.ts`): `setsChannels` — *"Output channel count is set by the effect (e.g.
  multichannel reverb), not the source"* — and `input` — *"Fixed input layout
  (spatialisation): source is conformed before processing"*; the four effects with
  `input: 'stereo'` get their input conformed up to stereo. The catalog has **no field named
  `stereoUnsafe`** (checked across all 232 `EFFECTS` entries), so the CLI's `--list-effects`
  derives one and labels it as ours, not upstream's: `stereoUnsafe = setsChannels || input === 'stereo'`.
  We verified the derivation against the installed package by rendering mono input:
  `reverb.reverb` returns **stereo**, `mchanpan.spread` returns **4 channels**,
  `mchshred.shred` and `phasor.phasor` return **stereo**, and each of `phase.stereo`,
  `spin.stereo`, `flutter.flutter`, `modify.shudder` returns **stereo**; the unflagged
  controls (`blur.blur`, `stretch.time`) return the source's channel count exactly. 22 of the
  28 flagged effects are runnable here: `brownian.motion`, `ceracu.cycles`,
  `crumble.crumble`, `crumble.crumble16`, `crystal.rotate`, `flutter.flutter`,
  `fracture.fracture`, `madrid.syncopate`, `mchanpan.spread`, `mchanrev.stadium`,
  `mchshred.shred`, `modify.shudder`, `newtex.drunk`, `phase.stereo`, `phasor.phasor`,
  `reverb.reverb`, `reverb.room`, `rotor.rotor`, `shifter.cycles`, `spin.stereo`,
  `tesselate.tesselate`, `wrappage.wrappage` — the other six (`multimix.spread`,
  `multimix.channels`, `panorama.spatial`, `submix.interleave`, `tangent.tangent`,
  `transit.transit`) are mixChain or two-input and refused before they run. For the flagged
  class neither `split` nor `mix` can promise a mono **output**: `mix` folds the input, but
  the effect then decides the width. If a downstream step assumes mono, avoid these ids or
  gate on `measured_channels` in the transform record.
- **Spectral effects are auto-wrapped** in `pvoc anal → effect → pvoc synth` by the library.
  Output duration quantises to analysis windows, so expect roughly ±30 ms against the input —
  which is why `duration_ratio` is recorded rather than asserted.
- **CDP changes level dramatically.** That is the point of it, and it is why the liveness floor
  exists rather than a loudness target. Chain `normalization` afterwards if you need a target.

### Time-varying parameters

CDP sound design is largely about parameters that move. `values_brk_json` gives any parameter a
breakpoint envelope, which `cdp-wasm` stages as a `.brk` file and reads in place of a constant.

```bash
workchain run-component cdp_transform in.wav -o ./out \
  --param effect=blur.blur \
  --param 'values_brk_json={"windows": "0 1\n2 80"}'
```

Verified before this was exposed: an envelope **materially changes the render** — a rising sweep,
a falling sweep and the constant all hash differently, and each is deterministic across runs. A
parameter that accepted an envelope and quietly ignored it would be a knob that lies, which is
worse than a knob that is absent, so `envelopes_were_applied` asserts that every envelope
requested was actually applied.

**Honest limit:** `cdp-wasm@0.5.3` does not populate the per-parameter `envelope` flag its type
definitions describe, so there is no way to know *in advance* which parameters CDP will accept a
breakpoint file for. What is checked before processing is that the name is a real parameter of the
effect and the curve is well formed; whether CDP honours it is caught afterwards by the output
contract. That is a weaker guarantee than the parameter-range check and is stated here rather than
glossed.

## Tier

`light` — plain Node plus the `cdp-wasm` npm package; no venv, no model weights, no native
toolchain. The bundled WebAssembly is about 11 MB installed.

## Decision log — issue #11 (`stereoUnsafe` catalog flag)

Roadmap, non-blocking. **Decision: surface the flag now, derived and labelled, and keep the
upstream proposal drafted rather than filed from an agent.**

1. **Upstream condition met.** cdp-wasm#4 ("stretch.time below the declared minimum returns a
   zero-length file with exit 0", filed by this repo's owner) was closed by the maintainer and
   the fix shipped in `cdp-wasm@0.6.0`; this repo has been on `^0.6.0` since the wave-0
   dependency bump. The issue asked to revisit the stereo signal once that landed.
2. **Investigation (checkbox 1).** The installed `cdp-wasm@0.6.0` catalog carries **no**
   `stereoUnsafe` field — the top-level key union across all 232 `EFFECTS` entries is `args,
   blurb, category, cdpDoc, collect, data, derive, domain, external, fixedParams, id, in2,
   input, inputs, label, mixChain, mono, multiOut, needs, params, parityExempt, paritySkip,
   pipeline, prefersGrains, prefersHarmonic, program, setsChannels, variadicInputs`. The two
   buildable building blocks are quoted in the mono-compat section above: `setsChannels`
   (24 effects — the effect defines its own output width) and `input: 'stereo'` (4 effects,
   source conformed up to stereo). Both classes were verified against the installed package
   to raise the channel count from a mono source while unflagged effects preserve it exactly.
3. **Decision (checkbox 2) — surface now, derived, labelled.** The CLI's `--list-effects [--json]`
   derives `stereoUnsafe = setsChannels || input === 'stereo'` from the installed catalog and
   names it as our derivation, since the flag name is the issue's vocabulary, not upstream's.
   Informational only: no render path, parameter range or post-condition changes. It closes a
   real gap in this step's own documented contract — the `channels` parameter promises mono
   handling, but its `mix` mode only folds for mono-only effects, and the flagged class sets
   its own output width regardless.
4. **Upstream (checkbox 3) — draft, do not file from an agent.** A proposal to cdp-wasm —
   declare a per-effect output-channel field (e.g. an explicit `stereoUnsafe`/`outChans`) so
   consumers do not derive it from `setsChannels` and `input` — is drafted in the PR that
   shipped this section. Per our submitting-an-issue rule we **never file on behalf of Daniel
   without his review**, and this automation holds no cdp-wasm write scope. **Trigger to
   file:** when this PR merges and the derived semantics survive review, file the drafted
   issue under our existing cdp-wasm#4 relationship.

## Licensing note

`cdp-wasm` is dual-licensed: MIT for Oliver Larkin's JavaScript API, catalog, CLI and tests;
**LGPL-2.1-or-later** for the compiled `wasm/*.wasm` modules and the CDP8 sources they come
from. We consume it as a normal, dynamically-loaded npm dependency and do not statically link
it, which is what LGPL relinking rights require. Any distribution must carry the CDP
attribution (© 1983–2023 Trevor Wishart, Richard Dobson, Martin Atkins and Composers Desktop
Project Ltd) and the LGPL text.

Separately: the `cdp-web` PWA in the same GitHub organisation is **AGPL-3.0-or-later** and must
never be vendored into a hosted LUFS surface. This component does not touch it.
