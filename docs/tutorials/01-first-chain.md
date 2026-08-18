---
title: "Your first verified chain"
description: "Install the CLI, make a test tone, write a YAML chain, run it, read the result — then deliberately break it and watch the verifier catch the lie."
type: tutorial
---

# Your first verified chain

In Workchain, "succeeded" means *proven*, not *exited 0*. This tutorial walks you through that
distinction by running one component against a test signal: first on target, then deliberately
off target — where the component itself does not notice, but the verifier does.

**Time:** about 10 minutes.
**Requires:** Node 18+, Python 3.10+, and ffmpeg.

---

## 0. Install the CLI

```bash
npm install       # root manifest: the CLI's runtime dependencies
cd workchain/cli
npm install       # cli manifest: vitest only (test tooling)
npm link
cd ..

workchain --version
# → 0.1.0
```

On a stock Linux system you may hit an `EACCES: permission denied` error from `npm link`,
because the global npm prefix defaults to `/usr`. The official workaround is a
user-owned prefix:

```bash
npm config set prefix "$HOME/.npm-global"
export PATH="$HOME/.npm-global/bin:$PATH"
# then run "npm link" again
```

Put the `export` line in your shell rc file so it persists between sessions.

---

## 1. Look around

```bash
workchain components
```

You should see the six built-in components. One — `stem_separation` — is **heavy**: it needs a
Python venv and model weights, and is outside the lean install. The rest are light and run on
system ffmpeg alone.

```bash
workchain doctor
```

The doctor runs every component's inbound preflight (the "Verified IN" contract). On a fresh
install you get something like:

```
✓ audio_benchmark        ok
✓ cdp_transform          ok
✓ content_hash           ok
✓ format_conversion      ok
✓ normalization          ok
✗ stem_separation        missing  missing: python:venv
doctor: 5 ok, 1 missing deps, 0 no-deps (of 6)
```

The `✗` on `stem_separation` is expected and honest. The engine tells you before you try to run
it, rather than failing halfway through. Every light component passes because it only declares
`commands: [ffmpeg, ffprobe]`.

```bash
workchain chains
```

The filesystem under `chains/` *is* the chain list — there is no database. You'll see the
delivery profiles (`deliverable-voice`, `deliverable-broadcast`, `deliverable-streaming`), a
`simple-test`, and the test chains under `chains/tests/`.

---

## 2. Make a test tone

You need a signal to process. A 5-second 440 Hz sine is a good first probe because its behavior
is predictable:

```bash
ffmpeg -f lavfi -i "sine=frequency=440:duration=5" -ar 44100 tone.wav
```

Make a white-noise file too — you will need it at step 6, where the sine turns out to be too
forgiving a test signal:

```bash
ffmpeg -f lavfi -i "anoisesrc=colour=white:duration=5" -ar 44100 noise.wav
```

White noise has a high crest factor — the peak-to-RMS ratio — which makes it genuinely hard to
normalize aggressively. That property is what the failure demo in step 6 depends on.

---

## 3. Write your first chain

A chain is YAML that sequences components. Create `learn-normalize.yaml`:

```yaml
name: "Normalize my test tone"
description: "Bring the tone to -14 LUFS integrated with a -1.5 dBTP ceiling"
version: "1.0"
steps:
  - name: normalization
    params:
      target_lufs: -14
      true_peak: -1.5
```

Every chain needs `name`, `version`, and at least one entry in `steps`. The `params` block is
optional — without it the component uses its schema defaults (for normalization:
`target_lufs: -11`, `two_pass: true`, `lra: 7`, `true_peak: -1.5`, `offset: 0`). By writing
`target_lufs: -14` in the step, you override that default. Parameter precedence is
step `params` > chain `globals` > schema `default`; the engine resolves it and hands the
component the merged result — components never re-resolve it themselves.

**Format note:** keep `description` values on one line in quotes. The parser shared by the
engine, CLI and MCP rejects block scalars (`>` / `|`), YAML anchors (`&`), and inline comments,
and flow collections like `checks: [...]` must open and close on the same line. See
[../format.md](../format.md) for the full list of gotchas.

---

## 4. Preview without running

```bash
workchain run ./learn-normalize.yaml tone.wav --dry-run
```

The engine prints the plan — which component will run, what it declares it produces — and
touches nothing:

```
── Dry Run ──
No files were processed.
```

---

## 5. Run the chain

```bash
workchain run ./learn-normalize.yaml tone.wav -o ./out --json
```

This produces two streams:

- **stdout** — one JSON document with the full result (machine-readable)
- **stderr** — newline-delimited JSON progress events (for humans and agents)

Without `--json` you get a formatted summary:

```
╭─────────────────────────────────────────╮
│  LUFS Workchain                         │
│  Chain: ./learn-normalize.yaml          │
│  Input: tone.wav                        │
╰─────────────────────────────────────────╯

Executing steps...
✔ normalization ...............................
── Complete ──
Output: ./out
Duration: 1.4s
Status: completed
```

### Reading the JSON result (abridged)

The top-level is `status`, followed by `steps`, keyed by component name. The part that matters
is the `verification` block:

```json
{
  "status": "completed",
  "duration_ms": 1942,
  "steps": {
    "normalization": {
      "status": "completed",
      "verification": {
        "tier": "verified",
        "verified": true,
        "checks": [
          { "name": "primary_output.exists",          "ok": true, "detail": "path=..." },
          { "name": "primary_output.non_empty",       "ok": true, "detail": "441078 bytes" },
          { "name": "primary_output.audio_valid",     "ok": true, "detail": "audio_stream=True duration=5.000s" },
          { "name": "loudness_metadata.exists",       "ok": true, "detail": "path=..." },
          { "name": "loudness_metadata.non_empty",    "ok": true, "detail": "222 bytes" },
          { "name": "loudness_metadata.json_valid",   "ok": true, "detail": "valid json" },
          { "name": "loudness_metadata.json_has",     "ok": true, "detail": "has ['target_lufs', 'final_lufs']" },
          { "name": "integrated_loudness_on_target",  "ok": true, "detail": "measured -14.04 LUFS vs target -14.0 (±1.0) → off by 0.04 LU" }
        ],
        "failures": []
      }
    }
  }
}
```

Three groups of checks:

1. **Structural** — `exists`, `non_empty`, `audio_valid` asked of the audio output.
   `audio_valid` re-probes with ffprobe and demands a positive duration; it is the check that
   distinguishes "a file with bytes" from "an actual sound".
2. **Metadata** — the JSON sidecar exists, decodes, and carries the declared keys.
3. **Numeric** — `integrated_loudness_on_target` re-measures the output's integrated LUFS
   independently and compares it to the `target_lufs` the step actually ran with, within ±1.0
   LU.

The sidecar the component wrote lives at `out/logs/normalization.json`:

```json
{
  "target_lufs": -14,
  "final_lufs": "-14.04",
  "lra": 7,
  "true_peak": -1.5,
  "input_i": "-21.75",
  "input_tp": "-18.06",
  "input_lra": "0.00",
  "input_thresh": "-31.75",
  "sample_rate": 44100,
  "channels": 1
}
```

Notice the design: the component wrote `final_lufs` into that file, and the verifier **did not
trust it**. The `integrated_loudness_on_target` check re-measured the output itself. The
component's own logged value is metadata; the verifier's measurement is the gate. That is the
whole product.

---

## 6. Break it on purpose

Now set up the case where a component exits 0 while producing the wrong result.

Open `learn-normalize.yaml` and change the target:

```yaml
steps:
  - name: normalization
    params:
      target_lufs: -5
      true_peak: -1.5
```

Why `-5`? ffmpeg's `loudnorm` filter only accepts an integrated-loudness target in
`[-70, -5]` LUFS — `-5` is as hot as it goes. Combined with the `-1.5` dBTP ceiling, that
combination is physically unreachable for any signal with real crest factor. The component will
run, apply maximum gain, miss, and — historically — still report success.

### Run against the sine first

```bash
workchain run ./learn-normalize.yaml tone.wav -o ./out_sine5 --json
```

**It passes:**

```
integrated_loudness_on_target  ok   measured -5.25 LUFS vs target -5.0 (±1.0) → off by 0.25 LU
```

The verifier did its job. A pure sine has a crest factor of only ~3 dB, so `loudnorm` can
almost reach the ceiling without breaching the peak limit. The target *is* reachable for this
signal. On-target files legitimately pass.

### Now run against the noise

```bash
workchain run ./learn-normalize.yaml noise.wav -o ./out_noise5 --json
```

Real audio — voice, music, noise — has a crest factor of 10–20 dB, and with that ceiling the
target is physically impossible. The run fails:

```json
{
  "status": "error",
  "code": 1,
  "message": "Chain halted: step 'normalization' failed verification",
  "failures": [
    {
      "step": "normalization",
      "tier": "unverified",
      "total_checks": 8,
      "failed_checks": [
        {
          "name": "integrated_loudness_on_target",
          "detail": "measured -8.95 LUFS vs target -5.0 (±1.0) → off by 3.95 LU"
        }
      ]
    }
  ]
}
```

*(Freshly measured on this tutorial's sandbox: Ubuntu container, ffmpeg 6.1.1, CLI 0.1.0. The
exact noise value will differ on your machine — noise is random — but the miss will be several
LU above the ±1.0 tolerance.)*

On stderr you watch it happen in real time:

```json
{"progress":{"step":"normalization","status":"failed","error":"verification","checks":["integrated_loudness_on_target: measured -8.95 LUFS vs target -5.0 (±1.0) → off by 3.95 LU"]}}
{"progress":{"status":"chain_halted","step":"normalization"}}
```

The component exited 0 and logged `Normalization completed`. It wrote a sidecar claiming a
`final_lufs` value. And it was wrong — the loudness target sits 3.95 LU away, outside the
tolerance. The verifier caught it, the step was marked `failed` (tier `unverified`), and the
chain halted with exit code 1 before the wrong audio could feed anything downstream.

That difference — `completed` vs `failed` — is the entire reason Workchain exists. A tool that
exits 0 while producing the wrong answer is worse than one that fails, because it lies to
whatever is operating it. The verifier stops the lie from travelling further down the pipeline.

For comparison, this exact scenario with a realistic signal is what the repo's negative test
chain `../../chains/tests/normalization_offtarget.yaml` exercises. The main
[README](../../README.md) shows the same mechanism on a different signal: it quotes
`integrated_loudness_on_target: measured -10.56 LUFS vs target -5.0 (±1.0) → off by 5.56 LU`.
Same verifier, same miss class, signal with a higher crest factor. (That value is quoted
verbatim from the README, not re-measured here.)

---

## What you just proved

- A component that runs and produces the wrong output is caught *before* its output feeds the
  next step.
- The verifier does not trust the component's own measurements — it re-measures with ffprobe
  and an independent loudness computation.
- Structural asserts (`exists`, `non_empty`, `audio_valid`) catch missing or corrupt files;
  numeric post-conditions (`audio_lufs_within`) catch target misses.
- Test signals are not interchangeable: a sine is forgiving, real material is not. Choose your
  probe honestly or a check that "works" on a sine may be decoration.

## Related

- [Write your own verified component](02-write-a-component.md) — build a minimal component with
  its own contract in about ten minutes.
- [Drive Workchain as an agent](03-drive-workchain-as-an-agent.md) — the `--json` discipline,
  exit codes, and MCP door, from a machine's perspective.
- [../format.md](../format.md) — the chain and `step.yaml` specification.
- [../../components/normalization/README.md](../../components/normalization/README.md) — the
  canonical worked example of the component contract.
- [../../chains/tests/normalization_offtarget.yaml](../../chains/tests/normalization_offtarget.yaml)
  — the negative test chain that must catch the miss.