# acoustic_encode

Encode a short **text pointer** into a WAV that survives **over-the-air** (speaker →
air → microphone). Wraps the `audioqr` CLI (ggwave: multi-FSK + Reed-Solomon,
direct-sequence spread).

## Payload philosophy: pointer, not file

Like a visual QR code carries a URL and not the webpage, this carries a short
identifier — a URL, a `lufs-<hex>` catalog number, a pairing token. Over-the-air
channel capacity is small; small payloads are what survive.

## Params

| param | default | notes |
|-------|---------|-------|
| `text` | `""` | The payload. Empty **fails honestly**. |
| `protocol` | `audible-fast` | `audible-{normal,fast,fastest}` / `ultrasound-{normal,fast,fastest}` |
| `volume` | `15` | 1–100 |
| `sample_rate` | `48000` | Hz |

## Outputs

- `primary_output` — the encoded `*_beacon.wav` (play through a speaker).
- `metadata` — `acoustic_encode.json`: `source_text`, `decoded_text`, `roundtrip_ok`, `protocol`, `duration_s`.

## Verification — proven, not exited-0

`run.sh` encodes, then **decodes its own output and requires it to equal the source
text**. A beacon that does not decode back is a `failed` step (`return 1`), never a
silent success — this is deliberately the opposite of the "measure but never compare"
bug. The declared `verify:` contract (enforced by `lib/workchain_verify.py`) checks
the waveform is real audio and the sidecar records a passing round-trip.

## Dependency

`audioqr` (Node CLI). Resolved via `WORKCHAIN_AUDIOQR_BIN` → `audioqr` on PATH. Only
acoustic chains need it; the rest of Workchain stays stdlib + ffmpeg.

## Example

```yaml
- component: acoustic_encode
  params:
    text: "https://catalog.lufs.audio/lufs-1a2b3c4d"
    protocol: audible-fast
```

Pairs with `catalog` (encode the catalog number it mints) and `acoustic_decode`.
