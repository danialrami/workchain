# embed — archive-ingest component

Part of the `archive-ingest` chain (see `chains/archive-ingest.yaml`) for the LUFS sound archive.
Outputs `archive/<name>.embedding.json`: an L2-normed float32 vector behind a **stable contract** (input: audio → output: vector of declared dim). v0 = `melstats-v0` (numpy log-mel band energies) as a dependency-light stand-in for LAION-CLAP/MuQ-MuLan. Swap the model, keep the contract.

A **fan-out analysis** stage: it reads the original `input_file` and emits sidecars — it does
**not** register a `primary_output`, so `input_file` stays the source audio for every stage.

- Contract: see `step.yaml` `verify:` (enforced by `lib/workchain_verify.py` after `run.sh`).
- Deps: see `step.yaml` `requirements:` (checked by `lib/workchain_preflight.py` before `run.sh`).
- Design record: the shared design notes.
ge` → `docs/product/sound-archive/`.
