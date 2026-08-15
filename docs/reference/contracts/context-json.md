---
title: "context.json: the run-state contract"
description: "What context.json contains across a run — input, globals, per-step params, outputs, preflight and verification verdicts — how the primary output advances to the next step, and how resolved params reach run.sh via STEP_CONFIG."
type: reference
---

# context.json: the run-state contract

`context.json` is the single run-state file the engine writes and reads all run long.
One per run, at `<output_dir>/context.json`, it is the shared memory between the Bash
engine, the components' `run.sh` scripts, the preflight verifier, and the output
verifier. If you want to know *what happened to what, in what order, and whether it was
proven*, you read this file.

Writers of `context.json` (all in the Bash engine, except where noted):

| Who | When | Writes |
|---|---|---|
| `engine/workchain-engine.sh` — `initialize_context` | start of run | top-level fields (see below) |
| `engine/workchain-engine.sh` — `load_globals` | before steps | `globals` from the chain YAML |
| `engine/workchain-engine.sh` — `record_step_params` | before each step's preflight | `steps.<name>.params` (resolved params, from the single Python resolver) |
| `lib/workchain_preflight.py` — `_persist` | after preflight | `steps.<name>.preflight` (and `status`/`reason` on failure) |
| `lib/common-utils.sh` — `register_output` | during `run.sh` | `steps.<name>.outputs.<name>` entries (+ back-compat `output`, `output_dir`, `status`) |
| `lib/workchain_verify.py` — `_persist` | after a clean exit | `steps.<name>.verification` (and `status` on failure) |
| `engine/workchain-engine.sh` — `update_input_file` | after verification passes | `input_file` / `input_name` / `input_ext` advanced to the primary output |
| `engine/workchain-engine.sh` — `finalize` / `mark_chain_failed` | end | `status`, `end_time`, `failed_step` |

Readers use the special-char-safe helpers in `lib/common-utils.sh` (`ctx_get`,
`ctx_set_status`, …) and `engine/step-runner.sh` (`get_context_value`,
`set_context_value`) — never shell-interpolate a path out of the file.

## Top-level fields

Created by `initialize_context` (field names verbatim from the engine):

```json
{
  "input_file":  "/abs/path/input.wav",
  "input_name":  "input",
  "input_ext":   "wav",
  "output_dir":  "/abs/path/out",
  "chain_file":  "/abs/path/chains/standard.yaml",
  "chain_name":  "standard",
  "start_time":  "2026-08-15T06:53:31Z",
  "globals":     {},
  "steps":       {}
}
```

- `input_file` / `input_name` / `input_ext` describe **the current input** — which is
  not necessarily the chain's original input: each passing step advances all three to
  that step's primary output (the handoff below).
- `globals` is the chain's `globals:` block (only keys that name a known param are
  applied; see parameter precedence).
- `status`, `end_time`, and (on failure) `failed_step` are added at the end by
  `finalize` / `mark_chain_failed`: `"completed"`, or `"failed"` naming the step that
  halted the chain.

## steps.<name> — one entry per step in run order

Each step's entry accumulates, in this order:

| Key | Written by | Contents |
|---|---|---|
| `params` | `record_step_params` | the resolved params the step actually ran with (JSON, from `lib/workchain_yaml.py` `engine-plan` — see STEP_CONFIG below) |
| `preflight` | preflight `_persist` | the inbound report: `satisfied`, `checks[]` (`name`/`ok`/`detail`), `failures[]`, `resolved_params`, `checked_at` |
| `outputs` | `register_output` | one entry per named output (below) |
| `status` | `register_output` / preflight / verifier | `"completed"`, `"skipped"`, or `"failed"` (+ `reason`, `preflight_failed`, `verification_failed`) |
| `verification` | verifier `_persist` | the outbound report: `tier`, `verified`, `checks[]`, `failures[]`, `measured{}`, `verified_at` (below) |
| `output`, `output_dir` | `register_output` (back-compat) | first file path / directory, kept for older consumers |

### outputs.<name>

`register_output` writes, per registered output (keys verbatim):

```json
"outputs": {
  "primary_output": {
    "path": "/abs/path/out/input_normalized.wav",
    "type": "file",
    "exists": true,
    "description": "Normalized audio file (WAV format)",
    "path_template": "{input_name}_normalized.{input_ext}",
    "target_lufs": -11,
    "measured_lufs": -10.92
  }
}
```

- `type` is one of `file`, `directory`, `json`, `number`, `string`, `boolean`.
- **Any metadata JSON the component passed is merged into the entry** — this is where
  recorded values like `target_lufs` / `final_lufs` land, which is exactly what the
  verifier's target-resolution chain reads first (recorded output metadata beats step
  params beats globals beats schema default).
- `description` and `path_template` are scraped live from the component's `step.yaml`
  `outputs:` block (the same single-file source of truth).

### preflight report (verified IN)

Keyed under `steps.<name>.preflight`:

```json
"preflight": {
  "component": "stem_separation",
  "satisfied": true,
  "checks": [ {"name": "python:venv", "ok": true, "detail": "venv python at /…/.venv/bin/python"}, … ],
  "failures": [],
  "resolved_params": { "preset": "hybrid" },
  "checked_at": "2026-08-15T06:53:31Z"
}
```

An unmet requirement flips `satisfied` to false and the step entry to
`"status": "failed"`, `"preflight_failed": true`, `"reason": "missing_dependency"` — a
component with missing deps never half-runs. `"no requirements declared"` appears in
`note` for components with no inbound contract (still `satisfied: true`).

### verification report (verified OUT)

Keyed under `steps.<name>.verification`:

```json
"verification": {
  "component": "normalization",
  "tier": "verified",
  "verified": true,
  "checks": [ {"name": "primary_output.audio_valid", "ok": true, "detail": "audio_stream=True duration=124.002s"}, … ],
  "failures": [],
  "measured": {
    "integrated_loudness_on_target": {
      "target": -11.0, "target_source": "step.params.target_lufs",
      "tolerance": 1.0, "measured_lufs": -10.92, "delta_lu": 0.08
    }
  },
  "verified_at": "2026-08-15T06:53:31Z"
}
```

- `tier` is `"unverified"` (ran, no contract declared — non-blocking), `"verified"`
  (declared contract passed), or `"skipped"` (component honestly recorded
  `status: skipped`, e.g. silent input — verification not applicable).
- `checks` are named `outputs.ASSERT` (e.g. `primary_output.audio_valid`) or the
  post-condition `id`; `measured` holds every post-condition's measured quantities, so
  the file is both the gate and the audit log.
- A failed contract flips `verified` to false and the step to
  `"status": "failed"`, `"verification_failed": true` — the chain halts *before* the
  output advances.

## The primary-output handoff

After a step's exit-code check **and** verification both pass, the engine advances the
input for the next step:

1. `verify_step` runs `lib/workchain_verify.py` against `context.json` — the verdict is
   written back into `steps.<name>.verification` **before** the advance.
2. `update_input_file` reads `steps.<name>.outputs.primary_output.path` and rewrites
   the top-level `input_file` / `input_name` / `input_ext` to point at it.
3. The next step's `run.sh` reads `input_file` from context and receives the previous
   primary output as its input.

**The ordering is load-bearing.** Because `input_file` advances only *after*
verification, a post-hoc re-run of the verifier on a finalized context would see the
*last* step's output as `input_file` — which is why the checks resolve their source from
recorded evidence first: recorded `source_input` metadata on an output > a `source_input`
field inside a JSON sidecar output > `context.json.input_file`. Preferring the recorded
source keeps every re-measuring check correct when re-run on a finalized context.

## STEP_CONFIG: how resolved params reach run.sh

The engine never lets a component (or a fourth parser) resolve its own params.

1. **Resolve once, upstream**: `lib/workchain_yaml.py engine-plan` resolves every step's
   params — precedence **step params > chain `globals` > component schema `default`**
   (plus the legacy alias `normalization.target_lufs ← globals.lufs_target`) — and emits
   one tab-separated line per step:
   `STEP\t<name>\t<base64 step_config YAML>\t<base64 params_json>`
2. **Two payloads, two consumers**:
   - the **STEP_CONFIG YAML block** (`enabled: true` + `param: value` lines, built by
     `build_step_config`) is decoded by `run_steps` and passed to `run.sh` as its second
     argument — components read it with `get_param` (`engine/step-runner.sh`), a grep
     over the block, exactly as the parameter-precedence rules intend. Components never
     re-implement resolution.
   - the **params JSON** is persisted verbatim (never re-parsed as YAML by the engine)
     into `steps.<name>.params`, which both bookends read: preflight's `when:` guards
     resolve from it, and the verifier's target resolution reads it after the step
     records output metadata.
3. **One write serves both gates**: `record_step_params` runs **before** preflight, so a
   `when:`-guarded requirement already sees the resolved param — ordered the other way,
   every guard would hit its fail-closed path and force heavy dependencies on light
   code paths.
4. On the standalone CLI path (`workchain run-component … --params-json …`),
   `lib/workchain_yaml.py step-config` builds the same STEP_CONFIG block from the same
   resolver, and the CLI runs preflight / run.sh / verify against the same context file
   contract — one parser, three interfaces.

## Parameter precedence, in one place

| Source | Wins over |
|---|---|
| step `params` | everything |
| chain `globals` (only keys that name a known param; `target_lufs` ← `lufs_target` alias for `normalization`) | schema defaults |
| schema `params_schema[].default` | nothing (floor) |

Component `run.sh` must not re-implement this — the resolved value arrives via
STEP_CONFIG / `steps.<name>.params`. The verifier's `resolve_target` uses the same
precedence extended with recorded output metadata first, so a post-condition and the
run can never disagree about what the step aimed at.

## A minimal annotated run (sketch)

```json
{
  "input_file": "/data/voice.wav", "input_name": "voice", "input_ext": "wav",
  "output_dir": "/out/run_1", "chain_name": "standard", "globals": {},
  "status": "completed", "end_time": "…",
  "steps": {
    "normalization": {
      "params": { "target_lufs": -11, "two_pass": true },
      "preflight": { "satisfied": true, "checks": [ { "name": "command:ffmpeg", "ok": true } ] },
      "outputs": { "primary_output": { "path": "/out/run_1/voice_normalized.wav", "type": "file", "exists": true, "target_lufs": -11, "final_lufs": -10.92 } },
      "status": "completed",
      "verification": { "tier": "verified", "verified": true, "checks": [ … ], "measured": { … } }
    },
    "stem_separation": { /* params, preflight, outputs, status, verification */ }
  }
}
```

After step 1, `input_file` was advanced to `/out/run_1/voice_normalized.wav`, so step 2
operated on the normalized file — which is why step 2's recorded `source_input`
metadata is the trustworthy provenance, not the top-level `input_file` of a finalized
context.

## Source of truth

- Engine lifecycle: `engine/workchain-engine.sh` (`initialize_context`, `load_globals`,
  `record_step_params`, `process_step`, `update_input_file`, `finalize`,
  `mark_chain_failed`).
- Step IO helpers: `engine/step-runner.sh` and `lib/common-utils.sh`
  (`ctx_get`, `ctx_set_status`, `register_output`).
- Params/STEP_CONFIG: `lib/workchain_yaml.py` (`resolve_params`,
  `build_step_config`, `engine-plan`, `step-config`).
- Inbound report: `lib/workchain_preflight.py` (`_persist`);
  outbound report: `lib/workchain_verify.py` (`_persist`, `resolve_target`,
  `resolve_target_str`, `_resolve_source`).
- Canonical format spec: `docs/format.md`.