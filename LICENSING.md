# Licensing

Workchain is licensed to everyone under the **Apache License, Version 2.0**
(see [`LICENSE`](./LICENSE)).

This document exists because "open core" is usually used as a fog machine. If a project
publishes one half of itself and stays vague about the other half, you cannot tell whether you
are looking at a foundation or a lead generator. So the boundary is written down here, on
purpose, including the parts that are not published and why.

## Why Apache-2.0 and not MIT

Apache-2.0 carries an explicit patent grant (§3) and a clear statement about contributions
(§5). MIT would be simpler, but this project's whole ambition is that **other people implement
the format** — including inside companies whose lawyers will ask about patents before their
engineers are allowed to adopt a file format. Apache-2.0 answers that question in the licence
instead of in an email.

## The format itself is unencumbered

The chain and component **format** — the YAML shape of a chain, a `step.yaml`, its
`requirements:` block and its `verify:` contract — is a specification, and we want competing
implementations of it.

**You may implement the Workchain format in any language, under any licence, commercial or
not, with no permission from us and no obligation to us.** We claim no exclusivity over the
format, the file names, or the vocabulary of assertions. If someone writes a better engine for
these files, that is the format succeeding, which is the point.

Apache-2.0 covers *our implementation*. It is not a claim on the idea of a verified audio step.

## What is published here

| | |
| --- | --- |
| `engine/` | The Bash execution engine: preflight → `run.sh` → verify |
| `cli/` | The Node CLI (`@lufs/workchain`) |
| `mcp-server/` | The Python MCP server (FastMCP) |
| `lib/` | The single parser/resolver, the preflight checker, the **verifier**, the registry generator |
| `components/` | The light components: normalization, format conversion, benchmarking, cataloguing, plus the scaffold template |
| `chains/` | Example chains |
| `docs/` | The format specification and component-authoring guide |

That is a complete, runnable system. It is not a demo, a trial, or a crippled build. You can
process real audio with it, author your own components against the documented contract, and
never talk to us.

## What is not published, and why

Being specific is the point of this section.

**Creative and heavy components.** Psychoacoustic protection against AI training, spectrogram-derived
artwork, Canvas video generation, audio embeddings and archive indexing, source separation.
These are held back for two different reasons and it is worth separating them: some are
genuinely entangled with a private catalogue and model set, and some are simply the work we
sell. Both are honest reasons. Neither is "the community version is missing a feature."

**Certification and signing.** The trust ladder runs `unverified → verified → certified`. The
first two rungs are **fully implemented here** — a component is *verified* when it passes its own
declared `verify:` contract, automatically, on every run, and you get that for free. The third
rung, where a named author signs a component's definition hash and stakes their reputation on
it, is the product. That infrastructure is not published.

**Hosted execution.** Running chains on someone else's machine, for people who will not run
them locally. Also the product.

The line, stated plainly: **the engine, the format, and the proof are open. The reputation
layer and the hosting are not.** Verification is not the upsell — it is the part we think
should be free, because an audio tool that cannot prove its output is worse than no tool, and
we do not want to be paid for withholding that.

## Additional licences we may grant

We are the sole copyright holder in this repository (see [`CONTRIBUTING.md`](./CONTRIBUTING.md)
for how we intend to keep that true, and what it costs you). A sole copyright holder is not
bound by the terms it offers to everyone else, and may license the same work differently to
specific parties.

If we ever do that — to ship through a distribution channel whose terms conflict with
Apache-2.0, or to let a partner embed the engine under different terms — **it will be recorded
in this file**, as an additional licence running *alongside* the Apache grant, never as an
amendment to it. Your rights under Apache-2.0 cannot be narrowed retroactively.

No such grants exist today.

## Third-party components

Some components wrap third-party libraries with their own terms. Where that happens, the
component's own README carries the details and the obligations. The one to know about:

- **`cdp_transform`** wraps [`cdp-wasm`](https://github.com/cdp-wasm-suite/cdp-wasm) (© Oliver
  Larkin), which is MIT for its JavaScript API and **LGPL-2.1-or-later** for the compiled
  WebAssembly modules built from the CDP8 sources. We consume it as a normal, dynamically
  loaded npm dependency and do not statically link it, which is what LGPL relinking rights
  require. Distribution must carry the CDP attribution (© 1983–2023 Trevor Wishart, Richard
  Dobson, Martin Atkins and Composers Desktop Project Ltd) and the LGPL text.

## Prior art on this approach

The structure of this document is borrowed, deliberately and with credit, from Oliver Larkin's
[`EXCEPTIONS.md`](https://github.com/cdp-wasm-suite/cdp-web/blob/main/EXCEPTIONS.md) in the
cdp-wasm suite: licence by strategic role rather than by ideology, and then *publish the
boundary* so nobody has to guess. It is the clearest treatment of the problem we have seen from
an independent audio developer, and we would rather say where we got it than pretend we arrived
at it alone.
