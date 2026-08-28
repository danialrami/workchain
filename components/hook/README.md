# hook — archive-ingest component

Part of the `archive-ingest` chain (see `chains/archive-ingest.yaml`) for the LUFS sound archive.
Outputs a 3 s hook clip at the **loudest window** + a 640×120 waveform PNG. This is what makes the archive scan sound-first and <50 ms — you audition hooks, not full takes.

A **fan-out analysis** stage: it reads the original `input_file` and emits sidecars — it does
**not** register a `primary_output`, so `input_file` stays the source audio for every stage.

- Contract: see `step.yaml` `verify:` (enforced by `lib/workchain_verify.py` after `run.sh`).
- Deps: see `step.yaml` `requirements:` (checked by `lib/workchain_preflight.py` before `run.sh`).
- Design record: the shared design notes.
ge` → `docs/product/sound-archive/`.
