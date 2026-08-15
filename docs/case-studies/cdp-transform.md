---
title: "cdp_transform: the fail-closed wrapper around an advisory library"
description: "cdp-wasm treats parameter ranges as advisory and only checks bytes.length === 0; a 2130-byte silent WAV ships as success. This component supplies the enforcement."
type: case-study
---

# cdp_transform: when the library calls silence a success, enforce it yourself

`cdp_transform` runs one Composers Desktop Project sound transformation on the input, via `cdp-wasm` — Oliver Larkin's WebAssembly port of CDP (Trevor Wishart, Richard Dobson, Martin Atkins, Composers Desktop Project Ltd, 1983–2023), "215 of its programs as WebAssembly", "232 of them" in a curated typed catalog.

## The problem

Why is a *wrapper* the useful thing to build? Because the library's idea of success is not audio. "`cdp-wasm` deliberately treats its declared parameter ranges as advisory — `src/effects.js:147–158` says so, so a consuming UI can offer to unlock the full span — and its only output check is `bytes.length === 0`." That check passes a well-formed WAV containing nothing: "A 44-byte-header WAV containing zero samples passes that." The result is a whole class of silent failure: "`stretch.time` at `factor: 0.02` (declared minimum 0.25) renders silence, and the library's own agent-facing chain runner reports `step 1 stretch.time: ok (0.00s, 1ch)` and exits 0." Every layer green; nothing audible. A wrapper that blindly forwarded would ship silence as success.

## The decision

A fail-closed contract — "This component supplies the enforcement the catalog leaves to the caller." **Verified IN**: `requirements.commands: [node, ffmpeg, ffprobe]` (the `cdp-wasm` package itself is resolved explicitly by `transform.mjs`, with install instructions if absent). **Verified OUT**: structural asserts plus three post-conditions:

| id | Guards against |
| --- | --- |
| `params_within_declared_range` | a parameter outside the catalog's declared range, or a parameter that does not exist — "Refused before processing" |
| `output_is_live_audio` | `measured_duration_s > 0` and `measured_peak_dbfs > -60` — empty *or* inaudible renders |
| `render_is_deterministic` | `determinism_ok == true` — "Same input and parameters render byte-identically" |

`audio_valid` is the load-bearing structural assert: "It re-measures duration from the file with ffprobe and requires it to be greater than zero, which is exactly what kills the zero-length class — `non_empty` alone passes the bad file at 2130 bytes, the same way `requireOutput` does upstream."

The README is equally explicit about the contract's limits: `audio_valid` and the duration check are independent re-measurements, but "the peak floor and the determinism relation are asserted through `json_fields_within`, which evaluates values *this component measured and wrote*. That is weaker than a re-measuring check." The `-60` floor "is a deliberate literal rather than a reference to `min_peak_dbfs`, so loosening the parameter cannot silently loosen the contract." Effects the catalog marks `parityExempt` or `paritySkip` (seeded RNG, randomised placement) get `determinism_ok` true with a note that equality was not claimed — "rather than manufacturing a passing comparison" — and the field is emitted only when both renders actually completed: "it cannot pass on `None == None`."

## The war story

The confirmed silence is the README's central measurement, not a hypothesis: "The behaviour was confirmed against the published `cdp-wasm@0.5.3`: `stretch.time` at `factor: 0.02` returns a 2130-byte WAV containing zero sample frames, and every layer reports success." A second, related failure mode is documented in the `output_is_live_audio` description in `step.yaml`: `filter.lohi` with passband 20 / stopband 22 "produces two full seconds of -63.97 dBFS and exits 0" — well-formed *and* full-length, but inaudible. Duration alone cannot catch that one; the peak floor exists because of it.

The README also records measurements the component does **not** gate on — `channels: split` is not free: "a near-mono source (correlation 0.99991) coming back at **−0.50 correlation and −6.03 dB of mono-sum cancellation** through `splinter.into`; `scramble.scramble` cost −3.26 dB." The component records `stereo_correlation` and `mono_sum_change_db` for every stereo render but does not gate — "the right threshold is a musical judgement we have not made." Recording without gating is itself a documented decision.

## Measured verification

Provenance — every value below is quoted byte-identically from `components/cdp_transform/README.md` (or `step.yaml` where noted); this study did **not** re-run any transform:

- **2130-byte WAV**, zero sample frames, every layer reports success — confirmed against `cdp-wasm@0.5.3` (README)
- **-63.97 dBFS** over two full seconds from `filter.lohi` passband 20 / stopband 22, exits 0 — `step.yaml`, `output_is_live_audio` description
- correlation **0.99991** → **−0.50** and **−6.03 dB** mono-sum cancellation through `splinter.into`; **−3.26 dB** through `scramble.scramble`; per-channel divergence up to **57 ms** for 22 of 45 mono-only effects (README, `channels: split` edge case)
- "The bundled WebAssembly is about **11 MB** installed." (README, tier note)

## What it teaches

**A green exit is not evidence — especially when the green exit is someone else's.** A dependency that only checks `bytes.length === 0` calls silence success, and its own runner agrees. Enforcement is the wrapper's job: fail-closed parameter checks *before* processing, independent re-measurement of the artifact, and honest scoping of which checks are independent and which read the component's own arithmetic. And when a comparison could vacuously pass — `None == None` *is* true — arrange for the field to be absent-and-failing rather than present-and-true.

- [component README](../../components/cdp_transform/README.md)
- [step.yaml](../../components/cdp_transform/step.yaml)
- [verification philosophy](../explanation/verification.md)
- [architecture](../explanation/architecture.md)