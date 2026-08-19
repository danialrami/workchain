# features — archive-ingest component

Part of the `archive-ingest` chain (see `chains/archive-ingest.yaml`) for the LUFS sound archive.
Outputs `archive/<name>.features.json`: spectral centroid/rolloff, rms dBFS, zero-crossing, brightness. `bpm`/`key` are declared **null in v0** (deferred to librosa/essentia or the sononym DuckDB warm-start) — honest about what it does not compute.

A **fan-out analysis** stage: it reads the original `input_file` and emits sidecars — it does
**not** register a `primary_output`, so `input_file` stays the source audio for every stage.

- Contract: see `step.yaml` `verify:` (enforced by `lib/workchain_verify.py` after `run.sh`).
- Deps: see `step.yaml` `requirements:` (checked by `lib/workchain_preflight.py` before `run.sh`).
- Design record: the shared design notes.
ge` → `docs/product/sound-archive/`.
