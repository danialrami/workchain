# content_hash

## What it does

Computes a reproducible cryptographic digest of the source audio and derives a short
identifier from it. Content-addressed provenance: the same bytes always produce the same id,
on any machine, forever, with no registry to consult and no coordination with anyone.

This was extracted from the `catalog` component, where the hashing sat buried alongside
release-specific formatting. It belongs on its own because a digest is useful independently —
and because it is the one claim in this system a verifier can check *perfectly*, by redoing the
work. Everything else we assert is a measurement with a tolerance. This is an identity.

## Parameters

| Name | Type | Default | Range | Meaning |
| --- | --- | --- | --- | --- |
| `algorithm` | string | `sha256` | — | Digest algorithm, as named by Python's `hashlib` (`sha256`, `sha512`, `blake2b`, `sha1`, `md5`). Use `sha256` unless you have a reason; `sha1` and `md5` exist for interoperating with existing catalogues, not for new provenance |
| `id_prefix` | string | `""` | — | Prefix for the short identifier. `lufs-` yields `lufs-a1b2c3d4`; empty yields the bare hex |
| `id_length` | number | `8` | 4 to 64 | Hex characters of the digest used for the short id. 8 gives ~4 billion values, which starts colliding around the birthday bound (~65k items) — raise it for large catalogues |

## Inputs / Outputs

Input: `wav`, `mp3`, `aiff`, `aif`, `flac`, `m4a`, `ogg`, `opus`. The digest is over the file's
**bytes**, so it is sensitive to container and encoding, not just to the audio — re-encoding the
same performance produces a different digest, which is the intended behaviour for provenance.

| Output | Type | Required | Path | Notes |
| --- | --- | --- | --- | --- |
| `primary_output` | json | yes | `content_hash/content_hash.json` | `algorithm`, `digest`, `bytes_hashed`, `short_id`, `id_length`, `source_name` |

## Verified IN (inbound contract)

```yaml
requirements:
  commands:
    - python3
```

Stdlib `hashlib` only. No ffmpeg, no venv, no model weights, nothing to install. The file is
read in 1 MB chunks, so a multi-gigabyte source never has to fit in memory.

## Verified OUT (outbound contract)

Structural: the record must exist, be non-empty, be valid JSON, and carry `algorithm`,
`digest`, `bytes_hashed`, `short_id` and `source_name`.

Two post-conditions, and the difference between them is worth understanding:

| id | What it does | Strength |
| --- | --- | --- |
| `digest_reproduces_from_source` | The verifier **re-hashes the source file itself** and requires the result to equal the recorded digest. Also refuses a zero-byte source | **Independent** — it redoes the work rather than reading a claim |
| `identifier_is_well_formed` | `bytes_hashed > 0`, `short_id` and `digest` non-empty | Weaker by design — reads what the component wrote. Catches an absent id, not a wrong digest |

The first one is the reason this component exists in a repo about verification. Almost every
other contract in the system re-*measures* an artifact and allows a tolerance. This one
re-*computes* the exact claim and allows none. A component that hashed the wrong file, or a
truncated read, would emit an identifier that looks authoritative and means nothing — and no
structural assert could tell the difference.

Verified behaviour, on a 576,078-byte 48 kHz stereo WAV:

```
PASS digest_reproduces_from_source | sha256 of 576078 bytes matches the recorded digest (1251ab61f937…)
```

And proven to fail, because a check nobody has watched fail is not evidence:

```
tampered digest    -> FAIL  sha256 MISMATCH — recorded 000000000000…, recomputed 98254d69ce52…
zero-byte source   -> FAIL  source is zero bytes — a digest of nothing is not provenance
missing field      -> FAIL  record has no usable 'digest' field
```

## Usage

```bash
workchain run-component content_hash track.wav -o ./out \
  --param algorithm=sha256 --param id_prefix=lufs- --param id_length=8

# In a chain
#   - name: content_hash
#     params:
#       id_prefix: "lufs-"
```

Test chain: `chains/tests/content_hash_test.yaml`.

## Edge cases

- **A zero-byte source is refused**, not hashed. `sha256` of nothing is a perfectly valid
  digest and a meaningless identifier, so the component fails rather than emitting it, and the
  verifier refuses it independently.
- **Short ids collide.** 8 hex characters is 4.3 billion values, and by the birthday bound you
  should expect a first collision somewhere around 65,000 items. The full `digest` is always
  recorded, so a collision is recoverable — but if you are identifying a large archive, raise
  `id_length` rather than relying on luck.
- **`sha1` and `md5` are available and are not collision-resistant.** They are here for reading
  existing catalogues. Do not mint new provenance with them.
- **Byte-identical, not perceptually identical.** Two exports of the same mix with different
  metadata chunks hash differently. That is correct for provenance and wrong for deduplication;
  if you want the latter you want an audio fingerprint, which is a different component.

## Tier

`light` — python3 stdlib only.
