# Workchain

**A YAML-driven, agent-first audio processing engine where "it worked" means proven, not
exited 0.**

```yaml
# chains/deliverable-voice.yaml — prep a recording to a dialogue delivery spec
name: "Deliverable: Voice / Dialogue"
version: "1.0"
steps:
  - name: format_conversion
    params:
      target_format: wav
      sample_rate: 48000
      bit_depth: 24
      channels: 1
  - name: normalization
    params:
      target_lufs: -21
      true_peak: -3.0
  - name: audio_benchmark
    params:
      expected_spec: "24/48000/1"
```

```bash
workchain run deliverable-voice take-07.wav -o ./out
```

If the conversion does not actually come out at 48 kHz / 24-bit / mono, that step **fails**. If
the normalizer misses −21 LUFS, that step **fails**. Not "warns" — fails, with the measured
value, and the chain stops. The component does not get to grade its own homework.

Real output from the second case, on a signal whose crest factor makes the target unreachable
under the peak ceiling:

```
✗ normalization — verification FAILED (1 of 8 checks)
    integrated_loudness_on_target: measured -10.56 LUFS vs target -5.0 (±1.0) → off by 5.56 LU
Chain halted: step 'normalization' failed
```

The component exited 0 and reported "Normalization completed". The verifier disagreed.

---

## The problem this exists for

Audio DSP almost never crashes. It produces *something*: silence, a 6 dB level error, a 30 ms
truncation, a decorrelated stereo image, two seconds of −64 dBFS. Every one of those is a valid
audio file that passes every check a normal pipeline makes.

That was survivable while a human sat in the loop, because the ear is a post-condition — it
fires automatically and it cannot be fooled by a byte count. **Automation deletes that sensor
and, by default, replaces it with nothing.** An agent cannot listen. It reads an exit code, and
an exit code cannot tell the difference between a stretched sound and an empty file.

So a component that runs but produces the wrong output is worse than one that fails, because it
lies to whatever is operating it. A tool that fails is a nuisance. **A tool that lies is a
liability**, because it spends trust it did not earn and the bill arrives later, for someone who
has stopped checking.

Workchain's answer is that every component declares a contract, and a single verifier enforces
it after every run.

## How it works

A **component** is a folder. That is the whole registry — there is no database.

```
components/normalization/
├── step.yaml      # params, outputs, requirements (verified IN), verify (verified OUT)
├── run.sh         # does the work
└── README.md
```

Its `step.yaml` declares two contracts:

**Verified IN** — checked *before* `run.sh` executes. Missing `ffmpeg`, missing model, wrong
Python version: the step fails immediately with a clear message, instead of half-running and
dying somewhere in the middle.

```yaml
requirements:
  commands: [ffmpeg, ffprobe]
```

**Verified OUT** — checked *after* a clean exit, by `lib/workchain_verify.py`:

```yaml
verify:
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
  post_conditions:
    - id: integrated_loudness_on_target
      check: audio_lufs_within
      output: primary_output
      target_param: target_lufs
      tolerance: 1.0
```

`audio_valid` re-measures the file with ffprobe and requires a positive duration.
`audio_lufs_within` **independently re-measures the loudness** and compares it to what was
asked for. The component's own logged value is not evidence.

That distinction is the entire design. `non_empty` asks a filesystem question — a 44-byte WAV
header with zero samples in it passes. `audio_valid` asks an audio question, and it does not.
Most silent-failure bugs live in exactly that gap.

### Creative operations, where there is no right answer

You cannot assert the correct output of a granular texture. So don't — assert **relations**
instead:

- duration preserved, or related to the requested factor
- loudness preserved where the operation should not have changed it
- separated stems recombine to the source within a residual tolerance
- the same input and parameters render byte-identically

One trap worth knowing, because we shipped it: an equality assertion between two absent values
*passes*. `None == None` is true, and CI reported green on a run where the component never
started. Equality fails **open**; inequality fails **closed**. Guard both sides' existence
before comparing.

## Three interfaces, one parser

```
engine/       Bash        ./engine/workchain-engine.sh -c chain.yaml in.wav -o out/
cli/          Node        workchain run <chain> <input> --json
mcp-server/   Python      list_components · get_step_schema · validate_chain · run_chain
```

All three parse and resolve through `lib/workchain_yaml.py`. There is no fourth parser, and
adding one is the architectural mistake this layout exists to prevent — three interfaces that
disagree about what a chain means are three different products.

## Base-native x402 demo

`demo/x402-mcp/` is the first hosted-payment slice: a Cloudflare Agents SDK Worker exposes one
paid `render_verified_demo` MCP tool, defaults to Base mainnet USDC, and calls a separate
Workchain origin. The origin generates a deterministic fixture, runs
`chains/base-demo-normalization.yaml`, and returns only when every step's `verification.verified`
record is true. The Worker never turns a non-zero origin result or an unverified context into a
paid success.

Run the origin locally with `python3 demo/x402-mcp/origin/src/server.py`. The Worker deployment
and a screen-shareable buyer live in `demo/x402-mcp/worker/` and `demo/x402-mcp/client/`. Base
Sepolia is the explicit fallback for the first funded test; the production configuration is
`eip155:8453`. The repository contains the code and dry-run validation, not a fabricated mainnet
receipt — deployment still requires a configured Cloudflare account, recipient wallet, reachable
origin, and an intentional funded buyer.

## Built for agents, on purpose

`--json` on everything. NDJSON progress on stderr, final JSON on stdout. Schema-validated
params with declared types and ranges. Meaningful exit codes. `--dry-run`. `validate --strict`
before you run. Machine-readable discovery in `llms.txt` and `agent.json`.

And the part that matters more than any of it: when an agent reports that a step succeeded, that
claim has been independently checked.

## Quick start

```bash
git clone https://github.com/lufs-audio/workchain
npm install                            # root manifest: the CLI's runtime dependencies
cd workchain/cli && npm install && npm link
cd ..

workchain components                     # what's installed
workchain doctor                         # can this machine run them?
workchain chains                         # available chains
workchain run deliverable-voice in.wav -o ./out --json
```

Requires Node 18+, Python 3.10+, and ffmpeg. The light components need nothing else — no venv,
no model weights, no native toolchain.

This fork also carries the verified asset/archive additions from the personal tree: acoustic
encode/decode, catalog, artwork, Canvas, probing, feature extraction, hook clips, melstats and
CLAP embeddings, protection, seed, and the archive-ingest chains. Heavy components still declare
their own runtime requirements; `workchain doctor` is the honest machine-specific report.

Write your own:

```bash
workchain generate component --name my_thing --description "..."
```

The scaffold **fails until you implement it** — the sentinel is in the file, not in a comment —
so a generated component can never be mistaken for a working one.

## Where to look first

If you only read three files, read these in order:

1. **`lib/workchain_verify.py`** — the whole idea, in one file.
2. **`components/normalization/step.yaml`** — a real contract, including the post-condition that
   closes the "measured it and never compared it" bug we shipped in this very component.
3. **`docs/format.md`** — the chain and `step.yaml` specification.

## Licensing

Apache-2.0. The format is unencumbered and we want other implementations of it. What is
published, what is not, and why: [`LICENSING.md`](./LICENSING.md).

Pull requests are not being accepted yet, for ownership reasons explained plainly in
[`CONTRIBUTING.md`](./CONTRIBUTING.md). Bug reports — especially "it said it worked and it
didn't" — are wanted.

## Lineage

Workchain descends from a tradition it did not invent. The
[Composers Desktop Project](https://www.composersdesktop.com) (Trevor Wishart, Richard Dobson,
Martin Atkins, Archer Endrich, Richard Orton and others, from 1983) established that serious
sound transformation could be a set of small composable command-line programs a composer drives
directly. That is the shape of this engine, forty years later, with the operator changed and a
contract added.

Built by [LUFS Audio](https://lufs.audio).
