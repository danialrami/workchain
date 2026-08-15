---
title: Run Components
description: How to run a single Workchain component standalone — --params-json for parameters, -r recursive batch over a directory, -e extension filter, and how legacy globals params like lufs_target flow through chains.
type: how-to
---

# Run Components

Sometimes you don't need a chain — you need one component on one file (or many files).
`workchain run-component <component> <input>` runs a component standalone, with the same
preflight (Verified IN) and verifier (Verified OUT) contracts the chain engine applies.

## Run one component on one file

```bash
workchain run-component normalization take-07.wav -o ./out
```

Outputs a flat structure in `./out`:

```
out/
├── context.json
├── logs/normalization.json
└── take-07_normalized.wav
```

## Pass parameters — `--params-json`

```bash
workchain run-component normalization take-07.wav -o ./out \
  --params-json '{"target_lufs":-14}'
```

A JSON object of parameter values; the same keys and ranges as the component's
`params_schema` (see `workchain component <name> --json`). JSON must be valid — a parse
error fails the command. Standalone runs bind the params as `steps.<component>.params` in
`context.json`, so the verifier measures against the exact target you asked for.

Numbers must be JSON numbers: `-14`, not `"-14"`. Booleans too: `true`, not `"true"`.

## Batch a directory — `-r` and `-e`

Pointing the input at a directory switches to batch mode:

```bash
workchain run-component audio_benchmark /path/to/audio/folder -o ./out --json
```

By default this scans **top-level** files with the built-in extension list
(`mp3, wav, aiff, aif, flac, m4a, ogg, mp4, wma`). To recurse into subdirectories add `-r`,
and to restrict extensions use `-e`:

```bash
workchain run-component normalization /path/to/audio/folder -r -e mp3,wav --json
```

`-e` takes a comma-separated list; leading dots are optional (`wav` and `.wav` both work).

In batch mode the stdout JSON has `command: "run-component-batch"`, a `results[]` array
(one entry per file, each with its own `status` and `output_dir`), and a `summary` of
`total` / `completed` / `failed`. The exit code is 0 only if every file succeeded;
any failure exits 1. An empty directory (or no matching extensions) exits 2 with
`No audio files found in <dir>`.

## Component vs chain parameters

Chain steps resolve parameters through three sources, in ascending priority (see
[docs/format.md](../../format.md) for the full rule):

1. Schema default (from the component's `params_schema`)
2. Chain `globals` (filtered to keys the component knows)
3. Step `params` (win unconditionally)

Standalone `run-component` has no chain, so `--params-json` plays the role of both globals
and step params: the values you pass are what the component and verifier use.

## The legacy `lufs_target` global

The delivered chains (and older chains you may meet) set `globals.lufs_target` instead of
`target_lufs`. The resolver keeps a backward-compatibility alias: if `globals.lufs_target`
is set, the step is `normalization`, and the step's own `params` do not set `target_lufs`,
then `globals.lufs_target` is copied into the resolved `target_lufs`.

```yaml
# chains/deliverable-voice.yaml (excerpt)
globals:
  lufs_target: -21     # the legacy alias — flows into normalization's target_lufs

steps:
  - name: normalization
    params:
      target_lufs: -21 # explicit step param shadows the global (same value here)
```

Two practical consequences when you write a chain:

- Setting `globals.lufs_target: -14` and a bare
  `- name: normalization` step gets you a −14 LUFS normalization — the global flows in.
- Setting it in the step's `params` overrides the global for that step, which is why the
  delivered chains set both (explicitly, so the aliased value is visible in `context.json`).

The alias is normalization-only. Other components simply receive `globals` keys that match
their own `params_schema` — anything else is silently dropped.

## Where the truth lives

- `workchain component <name> --json` — the component's params (with types, defaults,
  ranges), inputs, outputs, requirements, and verify summary.
- `workchain components --json` — every component with its tier (`light` / `heavy`).
- `workchain components --filter norm` — substring filter.

Heavy components (`stem_separation`) must be provisioned before a standalone run — see
[Provision Heavy Components](./provision-heavy-components.md). A preflight failure exits
nonzero with a clear `status: failed` reason (`audio_separator_not_found`), never a faked
success.

## What next

- [Run Chains](./run-chains.md) — sequence multiple components over audio.
- [Inspect a Run](./inspect-a-run.md) — read stdout JSON and verify verdicts (batch results reuse the same structures).