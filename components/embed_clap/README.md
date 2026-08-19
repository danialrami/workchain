# embed_clap — production LAION-CLAP embedder (two backends, one contract)

Drop-in for `embed` behind the **identical output contract** (`embedding.json` with
`model/dim/vector/l2norm`), so nothing downstream changes — only the vector quality.

## The two backends

| | `local` | `remote` |
| --- | --- | --- |
| Runs | `clap_embed.py` in this component's `.venv` | `clap_remote.py` → a resident embedding service endpoint |
| Needs | torch + laion-clap + a ~2 GB checkpoint | **nothing but python3 + ffmpeg** |
| Model load | **every invocation** | once, on the server, resident |
| Good for | reference / parity / no-network | library-scale runs |

`local` is correct and it is also the wrong shape at scale: 259k files means 259k
checkpoint loads. That is not hypothetical — it is what the ingest host spent a week doing before
this backend existed. `remote` makes an embedding a round-trip instead of a reload.

`auto` tries remote and falls back to local **loudly** (`log_warn`). It is opt-in on
purpose: a silent fallback to the slow path is precisely how a week of 2 GB-per-file
reloads goes unnoticed. If you want a bad endpoint to be fatal, use `backend: remote`.

## Usage

```yaml
# chains/archive-ingest-clap-remote.yaml
- name: embed_clap
  params:
    backend: "remote"
    endpoint: "http://127.0.0.1:8770"    # or $EMBED_CLAP_ENDPOINT
```

```bash
# the ingest host today: resident model on loopback. the remote GPU host tomorrow: change one variable.
export EMBED_CLAP_ENDPOINT=http://127.0.0.1:8770
export EMBED_API_KEY=…                   # matches the server's key
workchain run chains/archive-ingest-clap-remote.yaml "$f"
```

**Standing the server up?** Follow the deployment playbook for your resident embedding service:
install it on the ingest host or the remote GPU host, wire this client, prove parity, and cut the
ingest over.

The local backend still needs its venv:

```bash
cd components/embed_clap && bash provision.sh   # first run pulls the ~2GB ckpt
```

Until provisioned, the **local** backend fails honestly (preflight catches the missing
venv). The **remote** backend does not require it at all — `step.yaml`'s `requirements`
carry a `when: {backend: [local, auto]}` guard so a thin host is never asked for a
checkpoint it will never load. Guards **fail closed**: if `backend` cannot be resolved, the
venv is still required, so an ambiguous config can never quietly weaken a dependency
contract.

## What the record says now

`schema_version` 1.0 → **1.1**, purely additive:

```jsonc
{
  "model": "laion-clap-630k", "dim": 512, "l2norm": 1.0, "vector": [ ... ],
  "served_by": "remote",              // which backend actually produced this
  "endpoint": "http://127.0.0.1:8770",
  "model_rev": "9f2c1ab44de0",        // identity of the producing environment
  "precision": "fp32", "device": "cuda", "server": "serve-embed/0.1.0",
  "windows": 3, "duration_s": 24.5,
  "wire": { "sample_rate": 48000, "channels": 1, "format": "f32le" }
}
```

`served_by` is the point. A vector with no provenance is a vector you cannot audit, and an
archive of 259k unauditable vectors is one you eventually have to rebuild from scratch. With
it, a re-embed can be *scoped* — "every record whose `model_rev` is X" — instead of "all of
them, and hope".

## How this is verified

Three different claims, three different mechanisms. None substitutes for another.

**1. The output is a real vector** — `verify.post_conditions.embedding_wellformed`, enforced
by `lib/workchain_verify.py` after `run.sh`. Right length, finite, not all zeros, and
unit-norm **recomputed from the vector** rather than read from the `l2norm` field. On the
remote backend the producer is a service we did not run, so its self-report is a claim, not
evidence. `clap_remote.py` checks the same things before it writes anything, so a bad
response never reaches disk — the verifier is the independent second opinion.

**2. The server still agrees with itself** — `GET /readyz` on serve-embed runs a
deterministic fixture through a real forward pass and compares to a committed golden. Catches
a swapped checkpoint, a changed precision, a silent CPU fallback.

**3. The two backends agree with each other** — `parity.py`. This is the metamorphic check:
there is no "correct" 512-d vector for a sound, so we assert a **relation** instead of a
value. Same input through both backends must land in the same place.

```bash
python3 parity.py --endpoint http://127.0.0.1:8770 ~/Samples/some/take.wav
```

Run it on a host with both backends (the ingest host) before cutting an ingest over, and after any
server upgrade. It refuses to run against an endpoint that is not `/readyz`-clean, because
parity against an unproven server proves nothing.

Cosine threshold is 0.9999: fp32 matmul differs in the last few ULPs across CUDA/MPS/CPU and
mean-pooling accumulates that, but a precision change or a different checkpoint lands
nowhere near it.

## If you change the windowing, change it in three places

`clap_embed.py:windows()`, serve-embed's `Holder._windows()`, and this README. They are 10 s
non-overlapping and zero-padded. Divergence there silently splits the index into two
embedding spaces — the failure mode that looks like nothing at all until retrieval quality
quietly rots.

Design record: keep the embedding contract and the deployment playbook together in the shared
technical notes.
