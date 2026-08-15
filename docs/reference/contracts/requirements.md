---
title: "requirements: dependency classes"
description: "Quick-lookup catalog of the inbound verify contract — the five requirement classes (commands, python, node, models, env) implemented in lib/workchain_preflight.py, their fields, preflight semantics, `when:` guards, and real examples from shipped step.yaml files."
type: reference
---

# Requirements: the inbound dependency contract

`requirements` is the **verified IN** half of the component contract, checked by
`lib/workchain_preflight.py` **before** `run.sh` executes. Its symmetric bookend is the
`verify` block (verified OUT, checked after a clean exit) — together they make a
component a verified transform:

```
requirements (verified IN)  →  run.sh  →  verify (verified OUT)
```

The canonical format spec is [`docs/format.md#requirements`](../format.md). This page is
the quick-lookup catalog: the five classes, their fields, preflight semantics, and
copied examples from shipped `step.yaml` files. Everything here is derived from the
docstring and `CHECKS` list of `lib/workchain_preflight.py`; if they disagree, the
source wins.

## Preflight semantics

- **Every class is optional.** A component declares only what it needs; a component with
  no `requirements:` key has "no dependency contract declared" and preflight returns 0.
- **Runs every execution, and stays cheap** so it can: `commands` is a PATH lookup
  (`shutil.which`), `python`/`node` are import/resolve checks, `env` is presence-only,
  and `models` is existence + size. The expensive check — full model sha256 — runs only
  when asked: pass `--deep`, or mark a model `always_hash: true`. Cheap relations every
  run; expensive proof at certify time.
- **Fail fast, fail honest**: a missing dependency fails the step *before* it executes
  with a clear message, never a half-run.
- **Exit codes**: `0` = satisfied (also when nothing is declared); `1` = a declared
  requirement is unmet; `2` = usage/internal error.
- **The report is persisted** into `context.json` under `steps.<name>.preflight`
  (`satisfied`, `checks[]`, `failures[]`, `resolved_params`, `checked_at`); an unmet
  requirement marks the step `status: failed` with `reason: missing_dependency`.
- **`when:` guards fail closed.** Any group may carry a `when: { param: [values] }`
  guard; the group is required only when the guard matches. If the guarded param cannot
  be resolved, the group is treated as **applicable** — an ambiguous config must never
  quietly weaken a dependency contract. A guarded-out group is recorded as a *passing*
  check ("not required here"), so skipped requirements stay visible in the report
  instead of silently vanishing.

## The five classes

| Class | What it verifies | Fields | Checked by |
|---|---|---|---|
| `commands` | PATH binaries | `commands: [name, …]` | `shutil.which` |
| `python` | a component-local venv, its python version, its importable packages | `venv`, `python_version`, `packages[]`, `provision`, `when` | import *in that venv* |
| `node` | node package resolvability from the component dir | `packages[]` (`require`, `version`), `when` | `require.resolve` |
| `models` | heavy artifacts: exist, right size, optionally exact sha256 | `name`, `path`, `bytes`, `sha256`, `optional`, `always_hash`, `when` | exists + size every run; sha256 only `--deep`/`always_hash` |
| `env` | required environment variables — **presence only, never the value** | `env: [VAR, …]` | `os.environ.get` |

### commands

```yaml
requirements:
  commands:
    - ffmpeg
    - ffprobe
```

- Each name must resolve via `shutil.which`; a miss reports `NOT on PATH — install it,
  then re-run`.
- **Real example**: `components/normalization/step.yaml` (above), `ffmpeg` + `ffprobe`.
  `components/cdp_transform/step.yaml` also declares `node`; `components/audio_benchmark/step.yaml`
  declares `ffmpeg`, `ffprobe`, and `python3`; `components/content_hash/step.yaml` needs
  nothing but `python3` (stdlib hashlib — "no ffmpeg, no venv, nothing to install").

### python

```yaml
# components/stem_separation/step.yaml (verbatim — the python group)
  python:
    venv: ".venv"
    python_version: ">=3.10"
    packages:
      - { import: "audio_separator", dist: "audio-separator" }
    provision: "python3 -m venv .venv && .venv/bin/pip install 'audio-separator[cpu]' (use Python 3.10 — Demucs diffq has no cp311 wheel)"
```

- **`venv`** — path to the component-local venv, relative to the component dir
  (default `".venv"`); its `bin/python` is located and run.
- **`python_version`** — optional floor (`>=3.10`, `^3`, bare `3.10`); best-effort
  comparison of the venv's actual version.
- **`packages`** — verified by **importing the module inside that venv** with the venv's
  own interpreter. A string shorthand (`"soundfile"`) means "import name only"; a dict
  adds `dist` (importlib.metadata name) and an optional `version` floor.
- **`provision`** — optional recipe hint **shown in the failure message** when the venv
  is missing or a package fails to import. See the provision convention below.
- Recorded checks: `python:venv`, `python:version`, `python:pkg:<module>`.
- **Real example**: only `stem_separation` in the current registry declares `python`.
  It is the one heavy component: its own venv, Demucs-grade model code, off the light
  path.

### node

No shipped component declares the `node` class. The field-level shape is documented by
`components/_template/step.yaml`, which ships them as commented fixtures — quoted verbatim:

```yaml
# components/_template/step.yaml (verbatim comment block)
  # node:                        # node packages (checked via require.resolve)
  #   packages: [ { require: "jdenticon", version: "^3" } ]
  # models:                      # heavy artifacts (exists+size every run; sha256 only --deep)
  #   - { name: "weights", path: "models/weights.bin", bytes: 12345678, sha256: "…" }
  # env:                         # required env vars — presence only, never the value
  #   - SOME_API_KEY
```

- Packages are verified with `require.resolve` run from the component directory; the
  node runtime must itself be on PATH (`node:runtime` check).
- **Registry note, stated plainly**: no shipped component currently declares `node`.
  The snippet above is the template's commented fixture verbatim from
  `components/_template/step.yaml` — the field-level contract is real, the example
  component is not. Copy the shape; do not imply a shipped precedent.

### models

See the verbatim `_template` fixture under [node](#node). Field semantics:

- **`path`** — resolved relative to the component dir, or to the
  `WORKCHAIN_AUDIO_SEPARATOR_MODELS` env base if one is set.
- **Cheap every run**: existence + size within tolerance (≈2%). **Expensive** full
  sha256 runs only with `--deep` or per-model `always_hash: true`.
- **`optional: true`** — missing is fine ("auto-provisioned on use").
- **Registry note, stated plainly**: no shipped component declares `models` — and
  `stem_separation` documents *why* in its own `step.yaml`: its model weights are
  auto-provisioned on first use and preset-dependent, so exact-weights pinning (sha256
  via `models:`) is deliberately a certified-tier concern, not a hard preflight gate:

```yaml
# components/stem_separation/step.yaml (verbatim)
  # NOTE: model weights are auto-provisioned on first use by audio-separator and are
  # preset-dependent (hybrid needs RoFormer + Demucs; mdx needs only the MDX .onnx), so they
  # are intentionally NOT a hard preflight gate here. Exact-weights pinning (sha256 via the
  # `models:` class) is a certified-tier concern — see docs/product/workchain/.
```

### env

See the verbatim `_template` fixture under [node](#node). Presence only, **never the
value**: the check is `os.environ.get(var)` truthy. A miss reports
`NOT set — export <VAR>`.

- Presence only, **never the value**: the check is `os.environ.get(var)` truthy. A miss
  reports `NOT set — export <VAR>`.
- **Registry note**: no shipped component declares `env`. Template fixture as above.

## The provision convention

In the current code, `provision` is a **free-text recipe hint** on the `python:` and
`models:` groups — exactly one string, rendered into the preflight failure message so the
operator (human or agent) sees the known-good install command. It is not a script file
the engine executes: preflight only *shows* it. The convention in the registry:

- One line, shell-pasteable, ending with the reason a non-obvious choice was made:

```yaml
provision: "python3 -m venv .venv && .venv/bin/pip install 'audio-separator[cpu]' (use Python 3.10 — Demucs diffq has no cp311 wheel)"
```

- A component needs a heavier provisioning story than a hint (multi-file setup, model
  downloads) and currently wraps it in its own `run.sh` or docs instead — preflight
  stays a *declared-requirements* gate plus an actionable hint.

> If you intend a `provision.sh` *file* convention, it does not exist in this codebase
> yet. Implement it deliberately (engine, preflight, docs together), or keep the hint
> string. Never document a convention the engine does not honor.

## Choosing what to declare

- **Always** declare the binaries you run: `ffmpeg`/`ffprobe` for anything that touches
  audio, `python3` for anything that spawns python outside the engine, `node` for
  cdp-wasm.
- **`python`** only when the component genuinely needs its own venv (imports that do not
  exist on the light path) — `stem_separation` is the standard.
- **`models`** when weights are a hard dependency of the transform. If they are
  auto-provisioned and preset-dependent, say so in a comment (as `stem_separation` does)
  rather than forcing a brittle gate.
- **`env`** when a step cannot function without a caller-supplied secret or endpoint,
  and only for presence — never put the value in `step.yaml`.
- Guard provider-specific requirements with `when:` so a chain can run its light backend
  without satisfying a heavy one — and remember the guard fails closed, so an
  unresolvable param still demands the group.

## Source of truth

- Classes and fields: the `workchain_preflight.py` module docstring.
- Implementation: the `CHECKS` list (`check_commands`, `check_python`, `check_node`,
  `check_models`, `check_env`) and `_when_satisfied` in the same file.
- Field-level shape fixtures: `components/_template/step.yaml` (requirements block).
- Runtime examples: `components/{normalization,format_conversion,cdp_transform,
  audio_benchmark,content_hash,stem_separation}/step.yaml`.
- Canonical syntax: `docs/format.md#requirements`.