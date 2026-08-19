# archive_index — archive-ingest component

Part of the `archive-ingest` chain (see `chains/archive-ingest.yaml`) for the LUFS sound archive.
Terminal stage. Upserts one fully-analyzed file into the shared index (sqlite; sqlite-vec in prod), keyed on the **full 64-hex hash**. Idempotent (re-run = no-op update). Scope precedence: `ARCHIVE_SCOPE` env (batch driver) > param > global > `archive`.

A **fan-out analysis** stage: it reads the original `input_file` and emits sidecars — it does
**not** register a `primary_output`, so `input_file` stays the source audio for every stage.

- Contract: see `step.yaml` `verify:` (enforced by `lib/workchain_verify.py` after `run.sh`).
- Deps: see `step.yaml` `requirements:` (checked by `lib/workchain_preflight.py` before `run.sh`).
- Design record: the shared design notes.
ge` → `docs/product/sound-archive/`.
