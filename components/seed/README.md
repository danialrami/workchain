# seed

Mints a verifiable, provenanced seed from a preamp noise-floor recording. The chain step that turns "a number somebody typed" into an object you can prove things about.

## What it does

`seed` hands the run's input recording to the external `lufs-seed` entropy-source CLI, which harvests the low bits of a preamp noise floor (Johnson–Nyquist thermal noise — genuinely physical), health-tests them per NIST SP 800-90B, conditions them with SHA-256, mixes in CPU timing jitter and the kernel CSPRNG, and emits a signed record. It writes `seed/seed_record.json` plus a human-readable `seed/seed_info.txt`, and registers the seed id, tier, entropy assessment and the recording's catalog number into the run context.

**This is not a better RNG.** `os.urandom` is unbeatable on raw unpredictability and this does not try to beat it. What a seed record buys is *identity, reproducibility across runtimes, portability, and provenance* — the chain becomes able to say **which** randomness a process ran on, and prove it.

```
recording bytes -> LSB stream -> audio digest -> seed -> signature
```

Change one sample of the recording and the whole chain breaks.

## It must run FIRST

Unlike `catalog`, which hunts the context for the *most-processed* audio available, `seed` deliberately takes the **rawest** audio it can justify — because every processing step destroys the thing it harvests. Normalizing a noise floor applies gain to the LSBs; a lossy transcode replaces them with codec noise. Either would leave a step that still "succeeds" while seeding from something that is no longer thermal noise.

So if `seed` detects that an earlier step has already produced audio (the engine advances `input_file` to each step's primary output), it **fails honestly** rather than quietly minting from a derivative.

## Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `lsb_bits` | number | 8 | Low bits harvested per sample. **Untuned** — a conservative guess pending a mint from real hardware. |
| `floor_max_dbfs` | number | -30 | Reject if peak is louder — a signal is plugged in. |
| `floor_min_dbfs` | number | -110 | Reject if peak is quieter — muted input or dead converter. |
| `min_duration_s` | number | 5 | 20–30s recommended in practice. |
| `min_entropy_bits` | number | 256 | Required assessed min-entropy from **physical** sources. |
| `jitter` | boolean | true | Also mix in CPU timing jitter. |
| `sign` | string | `""` | Path to an ed25519 key. Empty → `verified`; a key → `certified`. |
| `note` | string | `""` | Human note stored inside the signed payload. |

The two-sided level gate is the part a generic RNG library cannot have — it requires knowing what a preamp is. Duration is not set by the entropy math (20s yields ~7.5M assessed bits against a 256-bit requirement, four orders of magnitude of headroom) but by giving the health tests a decent window and making the recording a keepable artifact.

## Inputs / Outputs

- Input: a `wav` noise-floor recording. `type: data` — takes audio in, emits a provenance record out, like `catalog`.
- Outputs (`outputs.items`, schema v1.0):

| Name | Type | Path template | Required |
|---|---|---|---|
| `primary_output` | json | `seed/seed_record.json` | yes |
| `summary` | file | `seed/seed_info.txt` | no |

Registered metadata on `primary_output`: `seed_id`, `tier`, `entropy_bits`, `catalog_number`, `content_sha256`, `lsb_bits`, `sources`, `source_input`.

The `catalog_number` uses the archive's exact convention (`lufs-<first 8 hex of SHA-256>`, same formula as `components/catalog/run.sh`), so a noise-floor recording drops into the sound archive with an identifier that already lines up.

## Verified IN (inbound contract)

```yaml
requirements:
  commands:
    - python3
    - lufs-seed
```

`lufs-seed` is a separate tool, exactly as `@lufs/audioqr` is for `acoustic_encode`. Preflight fails honestly if it is absent rather than letting the step invent a seed.

## Verified OUT (outbound contract)

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, json_valid]
      json_has: [payload]
  post_conditions:
    - id: seed_record_verifies
      check: seed_record_verifies
      output: primary_output
      require_tier: verified
```

The structural asserts prove a record was written. **The post-condition is the one that matters.** It re-runs `lufs-seed verify` *independently* against the record **and** the source recording — the same stance as `acoustic_roundtrip` re-decoding rather than trusting a sidecar. A component asserting its own provenance is precisely the failure this tool was written to end: the January `EntropyOrchestrator` returned `os.urandom` while continuing to report hardware.

That one call re-walks the entire chain: it recomputes the seed from the recorded per-source digests, re-derives the audio digest from the wav, checks `content_sha256` over the whole file, and validates the ed25519 signature.

`require_tier` accepts `unverified` / `verified` / `certified`. Set it to `certified` to require a signed seed — the step then fails if the seed was minted unsigned.

## Usage

```bash
workchain run-component seed floor.wav
```

In a chain (`seed` first, always):

```yaml
steps:
  - name: seed
    enabled: true
    params:
      jitter: true
      sign: ~/.config/lufs-seed/signing.key
      note: "kitchen preamp, nothing plugged in"
```

Then derive from the record, constantly and offline:

```bash
lufs-seed derive "study-07/palette" --record out/seed/seed_record.json --floats 4
```

One mint feeds unlimited independent streams — two labels give streams that cannot be distinguished from independent. You never mint per-render.

## Failure modes

All honest, all with a named reason:

| Situation | Result |
|---|---|
| A signal is plugged in (peak > `floor_max_dbfs`) | step fails, `not_a_signal` |
| Muted input / dead converter | step fails, `floor_present` |
| Recording too short | step fails, `duration` |
| Assessed entropy below budget | step fails, exit 5 |
| Signing key missing | step fails, exit 7 |
| `seed` is not the first step | step fails, refuses to seed from a derivative |
| Record or recording altered after minting | **verification** fails, naming the broken link |

## Tier

**Light.** No Python venv, no models — `python3` plus the `lufs-seed` binary, which is itself stdlib-only for minting (`cryptography` only for signing). Runs on a bare Pi.
