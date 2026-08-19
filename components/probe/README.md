# probe — archive-ingest component

Part of the `archive-ingest` chain (see `chains/archive-ingest.yaml`) for the LUFS sound archive.
Outputs `archive/<name>.probe.json`: full 64-hex content SHA-256 (the index key; the `lufs-<8hex>` catalog number is display-only), duration/samplerate/channels/bit-depth/codec, and peak/mean dBFS. ffprobe + ffmpeg + stdlib only.

A **fan-out analysis** stage: it reads the original `input_file` and emits sidecars — it does
**not** register a `primary_output`, so `input_file` stays the source audio for every stage.

- Contract: see `step.yaml` `verify:` (enforced by `lib/workchain_verify.py` after `run.sh`).
- Deps: see `step.yaml` `requirements:` (checked by `lib/workchain_preflight.py` before `run.sh`).
- Design record: the shared design notes.
ge` → `docs/product/sound-archive/`.
