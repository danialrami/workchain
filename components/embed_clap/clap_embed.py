"""
clap_embed.py — the `local` backend for embed_clap (run inside embed_clap/.venv).

Loads LAION-CLAP in-process and embeds ONE file. That means it pays a full ~2 GB checkpoint
load per invocation: correct, but 259k files is 259k model loads. For a library-scale run
use `backend: remote` against a serve-embed endpoint (lufs-audio/serve-embed), which keeps
the model resident. This path stays because it is the reference implementation — the thing
`parity.py` proves the remote server against, and the fallback when no endpoint exists.

Emits the IDENTICAL record shape as clap_remote.py: same keys, same windowing, same decode.
If these two ever diverge, the archive is being built out of two incompatible spaces, so
treat any change here as a change to both.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np

SR = 48000
WINDOW_SECONDS = 10
L2_TOL = 1e-3
BACKEND_VERSION = "clap_embed/0.2"


def decode_48k_mono(src):
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", src,
                        "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg decode failed: %s"
                           % p.stderr.decode("utf-8", "replace").strip()[:400])
    x = np.frombuffer(p.stdout, dtype=np.float32).copy()
    if x.size == 0:
        raise RuntimeError("ffmpeg produced no PCM")
    return x


def windows(x):
    """10 s non-overlapping, zero-padded. Must stay identical to serve-embed's Holder._windows."""
    W = SR * WINDOW_SECONDS
    if x.size <= W:
        wins = [x if x.size else np.zeros(W, dtype=np.float32)]
    else:
        wins = [x[i:i + W] for i in range(0, x.size - W + 1, W)]
    return np.stack([np.pad(w, (0, max(0, W - w.size)))[:W].astype(np.float32) for w in wins])


def write_atomic(path, rec):
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(rec, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: clap_embed.py <input> <out_json> [model]\n")
        return 2
    src, out = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "laion-clap-630k"
    t0 = time.time()

    # laion_clap parses sys.argv at import time; our own argv makes it misbehave.
    # Known bug — see shared design notes docs/infra/audio-ml-stack/04-*.
    saved_argv = sys.argv
    sys.argv = [saved_argv[0]]
    try:
        import torch
        import laion_clap
        m = laion_clap.CLAP_Module(enable_fusion=False)   # HTSAT-base / 630k
        m.load_ckpt()                                     # ~2GB, EVERY invocation
    finally:
        sys.argv = saved_argv

    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device = "mps"

    x = decode_48k_mono(src)
    batch = windows(x)
    embs = m.get_audio_embedding_from_data(x=batch, use_tensor=False)
    v = np.asarray(embs, dtype=np.float64).mean(axis=0)     # mean-pool windows
    v = v / (np.linalg.norm(v) + 1e-12)                     # L2 normalize

    # Prove our own output before writing it. Same standard we hold the remote server to —
    # the local path does not get to skip verification just because we wrote it.
    l2 = float(np.linalg.norm(v))
    if not np.all(np.isfinite(v)):
        raise RuntimeError("embedding contains NaN or Inf")
    if float(np.abs(v).max()) == 0.0:
        raise RuntimeError("embedding is all zeros")
    if abs(l2 - 1.0) > L2_TOL:
        raise RuntimeError("embedding is not L2-normed: |v|=%.6f" % l2)

    # Cheap, honest local revision id: it identifies the execution environment without
    # hashing 2 GB. It will NOT equal a serve-embed model_rev even for the same checkpoint,
    # because they genuinely are different environments — parity.py is what proves the two
    # agree numerically.
    rev_src = "|".join([model, "fp32", device,
                        "laion_clap=%s" % getattr(laion_clap, "__version__", "unknown"),
                        "torch=%s" % torch.__version__])
    rec = {
        "model": model,
        "dim": int(v.size),
        "l2norm": round(l2, 6),
        "vector": [round(float(z), 6) for z in v],
        "served_by": "local",
        "endpoint": None,
        "model_rev": "local-" + hashlib.sha256(rev_src.encode()).hexdigest()[:12],
        "precision": "fp32",
        "device": device,
        "server": BACKEND_VERSION,
        "windows": int(batch.shape[0]),
        "duration_s": round(x.size / SR, 3),
        "wire": {"sample_rate": SR, "channels": 1, "format": "f32le"},
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    write_atomic(out, rec)
    sys.stderr.write("clap embed ok: %s dim=%d |v|=%.4f windows=%d device=%s %dms\n"
                     % (model, rec["dim"], l2, rec["windows"], device, rec["elapsed_ms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
