---
title: "content_hash: the one claim a verifier can check perfectly"
description: "A digest is not a measurement with a tolerance — it is an identity. The verifier re-hashes the source file itself and demands exact equality."
type: case-study
---

# content_hash: an identity, not a measurement

`content_hash` computes a reproducible cryptographic digest of the source audio and derives a short identifier from it — "the same bytes always produce the same id, on any machine, forever". It is light: stdlib `hashlib` only, no venv, no ffmpeg, read in 1 MB chunks.

## The problem

A wrong digest looks exactly like the right one. "A component that hashed the wrong file, or a truncated read, would emit an identifier that looks authoritative and means nothing — and no structural assert could tell the difference." A structural check can confirm the JSON record exists and has fields; it cannot confirm the digest means anything.

The component also carries its extraction history as a lesson: "This was extracted from the `catalog` component, where the hashing sat buried alongside release-specific formatting." Alone, it became what the README calls "the one claim in this system a verifier can check *perfectly*, by redoing the work. Everything else we assert is a measurement with a tolerance. This is an identity."

## The decision

**Verified IN**: `requirements.commands: [python3]` — nothing else to install. **Verified OUT**: structural asserts (record exists, non-empty, valid JSON, carrying `algorithm`, `digest`, `bytes_hashed`, `short_id`, `source_name`) plus two post-conditions whose difference in strength is the design:

| id | What it does | Strength |
| --- | --- | --- |
| `digest_reproduces_from_source` | "The verifier **re-hashes the source file itself** and requires the result to equal the recorded digest. Also refuses a zero-byte source" | **Independent** — it redoes the work rather than reading a claim |
| `identifier_is_well_formed` | `bytes_hashed > 0`, `short_id` and `digest` non-empty | "Weaker by design — reads what the component wrote. Catches an absent id, not a wrong digest" |

The first is the point: "Almost every other contract in the system re-*measures* an artifact and allows a tolerance. This one re-*computes* the exact claim and allows none." The digest is over the file's **bytes** — "re-encoding the same performance produces a different digest, which is the intended behaviour for provenance." Parameters: `algorithm` (default `sha256`), `id_prefix` (`lufs-` yields `lufs-a1b2c3d4`), `id_length` (default 8, range 4–64).

## The war story

The README demonstrates both directions — a check passing, and the same check failing on purpose, "because a check nobody has watched fail is not evidence."

Verified behaviour, "on a 576,078-byte 48 kHz stereo WAV":

```
PASS digest_reproduces_from_source | sha256 of 576078 bytes matches the recorded digest (1251ab61f937…)
```

And proven to fail:

```
tampered digest    -> FAIL  sha256 MISMATCH — recorded 000000000000…, recomputed 98254d69ce52…
zero-byte source   -> FAIL  source is zero bytes — a digest of nothing is not provenance
missing field      -> FAIL  record has no usable 'digest' field
```

The zero-byte case is refused twice, by both sides: "`sha256` of nothing is a perfectly valid digest and a meaningless identifier, so the component fails rather than emitting it, and the verifier refuses it independently." The tampered case is the whole point: no consumer that reads the record instead of re-doing the work could tell the recorded digest was wrong.

## Measured verification

Provenance — quoted byte-identically from `components/content_hash/README.md`; no hashing was re-run for this study:

- **576,078 bytes** (the README also writes "576078 bytes") — verified-behaviour block
- recorded digest prefix **1251ab61f937…**; recomputed-after-tamper prefix **98254d69ce52…** — verified-fail block
- short-id arithmetic: 8 hex characters is "4.3 billion values", first birthday-bound collision expected "somewhere around 65,000 items" — edge cases

## What it teaches

**Find the one checkable-perfectly claim and make it exact.** When the output is a pure function of the input, the verifier should redo the work and demand byte-for-byte equality — no tolerance, no re-measurement. And label your weak checks honestly: the README calls `identifier_is_well_formed` "weaker by design" and says what it can and cannot catch. Say which of your checks redo the work and which read the component's own claim, and your readers will know what a green run actually proves.

- [component README](../../components/content_hash/README.md)
- [step.yaml](../../components/content_hash/step.yaml)
- [test chain](../../chains/tests/content_hash_test.yaml)
- [verification philosophy](../explanation/verification.md)
- [architecture](../explanation/architecture.md)