---
title: How to publish your own components
description: Build and share Workchain components from your own repository — the filesystem-is-the-registry model, and how to feed back bugs, verification holes, and format issues that move the project.
type: how-to
---

# How to publish your own components

The registry is the filesystem. There is no database, no marketplace, no permission gate: a
component is a folder containing `step.yaml` + `run.sh` + `README.md`, and this repository
discovers components by directory name. That design decision is what makes everything on this
page possible — **you do not need this repo, or our permission, to write a component.**

## A component is a folder

Selecting `normalization` in a chain means "run `components/normalization/`". That is the whole
discovery mechanism. The engine checks that the directory contains `step.yaml` and `run.sh`,
resolves the parameters, preflights the inbound contract, runs the script, and enforces the
outbound contract — regardless of *which* repository the folder lives in.

So "publishing" a component is not a ceremony; it is:

1. Authoring the folder (see [`author-a-component.md`](author-a-component.md) for the walkthrough, [`components/_template/`](../../../components/_template/README.md) for the schema, and [`write-a-verify-block.md`](write-a-verify-block.md) for the contract).
2. Making it reachable from a machine that runs the engine.
3. Telling people it exists.

## Build one in your own repository

The format is declared unencumbered — [`docs/format.md`](../../format.md) is written as the
reference a competing engine implementation should follow, under Apache-2.0. Concretely:

- **Structure.** Create your component directory with the same shape as
  `components/_template/` — `step.yaml` (params, outputs, `requirements:`, `verify:`),
  `run.sh` (`return`, never `exit`; safe `ctx_get_*` helpers; `register_output`),
  `provision.sh` (idempotent setup for declared requirements — light components ship one that
  just says "nothing to provision"), README, and a test chain.
- **Run it locally.** The simplest route is a checkout of this repo: drop your component's
  directory under `components/`, regenerate the registry with `workchain registry generate`
  (`components/index.json` is generated — never hand-edit it), then preflight the whole
  registry with `workchain doctor` and exercise your component with
  `workchain run-component <name> <input> -o ./out` or via your own `chains/` YAML.
- **Keep the contract honest.** `verify:` must be real — `audio_valid` on audio outputs, an
  independent post-condition for any numeric claim, never an empty `verify:` block. The
  doctrine in `.agents/skills/authoring-a-component/SKILL.md` is the standard; components sent
  to other people get judged by it.
- **Version it.** Bump `step.yaml`'s `version` when you change the schema, and keep changes
  backwards-compatible — other people's chains will pin parameters against your schema.

## Tell LUFS Audio it exists

Contributions policy is stated plainly in
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md): **pull requests are not accepted at the moment**,
for an ownership reason the doc explains honestly (Apache-2.0 §5 licenses a contribution to the
project without transferring copyright, which quietly removes future relicensing options —
until that is settled, the door stays closed on purpose).

What **is** wanted, and what is more useful than a patch:

- **Bug reports.** Especially anything where the engine reported success and the audio was
  wrong — that is the failure this project exists to eliminate. Include the chain or component,
  the input's format and duration, what you expected, and what you measured.
- **Holes in the verification model.** If you can describe an audio defect the `verify:`
  vocabulary cannot express, that is the most valuable thing you can send. There is one known
  gap, acknowledged in `CONTRIBUTING.md`: **there is no assertion for "this output is
  audible"** — a render can be structurally perfect, correctly long, and sit at −64 dBFS, and
  every current check passes it. The others are yours to find.
- **Format feedback.** The chain and `step.yaml` format is meant to be implemented by other
  people. If something is ambiguous, awkward, or impossible to implement faithfully, say so
  while the format is still young enough to change.
- **Your own components.** "The filesystem is the registry, so a component is just a folder —
  you do not need our permission or our repo to write one. Tell us it exists and we will link
  it."

## Filing a report that gets fixed

The ground rules from `CONTRIBUTING.md`:

- Search open **and** closed issues first. One issue per issue.
- Include versions: OS, `node --version`, `python3 --version`, `ffmpeg -version`.
- For audio problems, **measurements beat adjectives.** "Peak −64 dBFS" is actionable;
  "sounds broken" needs a round trip.
- Never paste a value you did not measure. A fabricated number in a bug report about
  verification is a special kind of unhelpful.

If you have already written a patch, open an issue *describing* it rather than a PR: for a fix
worth making, the maintainers will make it and credit you by name and link in the commit
message — the fix ships without either side signing anything.

## Also worth reading

- [`author-a-chain.md`](author-a-chain.md) — sequence your component with others.
- [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) — the contribution policy and the reasoning.
- [`LICENSING.md`](../../../LICENSING.md) — licensing, and what is deliberately not published here.