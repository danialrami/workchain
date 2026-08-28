# catalog

Stamps a processed audio file with a content-derived catalog number. No config, no drama.

## What it does

`catalog` hunts the run context for the most-processed audio available — `protection` output first, then `normalization`, falling back to the raw input — hashes it with SHA-256 (via stdlib `hashlib`, streamed in 1MB chunks, no external `shasum`/`sha256sum` dependency), and writes `catalog_info.txt` with a generated catalog number (`lufs-<first 8 hex chars of hash>`), the full hash, a timestamp, and a summary of every step's status pulled from the run context. It's provenance, not metadata enrichment: the catalog number is entirely a function of the bytes it's given, so identical audio always gets the identical number.

## Parameters

None. `params_schema: {}` — there is nothing to configure.

## Inputs / Outputs

- Input: `type: data`. No `input_types` restriction declared; `run.sh` resolves source audio from context (`protection` → `normalization` → raw `input_file`, in that order).
- Outputs (`outputs.items`, schema v1.0):

| Name | Type | Path template | Required |
|---|---|---|---|
| `primary_output` | file | `catalog/catalog_info.txt` | yes |
| `metadata` | json | `catalog/metadata.json` | no |

`metadata` is declared but not required — a given run may or may not emit it.

## Verified IN (inbound contract)

```yaml
requirements:
  commands:
    - python3
```

That's the entire inbound contract — content hashing rides on stdlib `hashlib`, so there's no heavier python venv/package requirement, no node, no models, no env vars. `lib/workchain_preflight.py` just confirms `python3` is on `PATH` before `run.sh` runs.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty]
```

`lib/workchain_verify.py` checks `primary_output` exists and is non-empty after a clean exit — "proven correct," not merely "exited 0." Note `metadata` is intentionally left unasserted: since it's an optional output, asserting on it would fail runs that legitimately don't produce it. There are no `post_conditions` — the contract doesn't (and can't, sensibly) assert anything about hash correctness beyond "a file got written."

## Usage

```bash
workchain run-component catalog input.wav
```

In a chain (no params to pass):

```yaml
steps:
  - name: catalog
    enabled: true
    params: {}
```

## Tier

**Light.** `catalog` declares no Python venv and no models — stdlib `python3` only — so the registry classifies it light, same as `normalization` or `format_conversion`. (Registry tier is purely a runtime-weight label: `heavy` iff a component declares `python`/`models`. It is orthogonal to the open-core business model — `catalog` happens to be an internal/product component that powers catalog.lufs.audio rather than a general-purpose processing step, but that's a product distinction, not a registry tier.)
