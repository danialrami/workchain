# acoustic_decode

Recover a text payload from an audio recording carrying an **over-the-air audio-QR**
waveform. Wraps the `audioqr` CLI (ggwave). The inverse of `acoustic_encode`.

## Params

| param | default | notes |
|-------|---------|-------|
| `expected` | `""` | Optional. When set, the step **fails** unless this payload is among the decoded results — turning decode into a verifiable assertion. |

## Output

- `primary_output` — `*_decoded.json`: `{ decoded: [...], count, expected, match }`.

## Verification — honest failure

Decode's one job is to recover a payload, so:

- **nothing decoded → `failed`** (`return 1`). No silent empty success.
- **`expected` supplied but not recovered → `failed`.**

The declared `verify:` contract confirms the sidecar is valid JSON carrying
`decoded` + `count`.

## Dependency

`audioqr` (Node CLI). Resolved via `WORKCHAIN_AUDIOQR_BIN` → `audioqr` on PATH.

## Example

```yaml
# self-check: encode then decode must recover the same pointer
- component: acoustic_decode
  params:
    expected: "https://catalog.lufs.audio/lufs-1a2b3c4d"
```
