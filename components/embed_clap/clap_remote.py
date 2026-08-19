"""
clap_remote.py — the `remote` backend for embed_clap.

STDLIB + ffmpeg ONLY. No torch, no numpy, no venv. That is the point: a sound-library host
should not need a 2 GB checkpoint or a heavy .venv just to get a vector. It decodes to the
wire contract (48 kHz mono float32 LE), POSTs the PCM to a resident-model serve-embed
endpoint, and writes the SAME embedding.json contract as clap_embed.py.

Two rules it will not bend:

  1. It validates the server's answer BEFORE writing anything. A remote service is an
     untrusted input like any other: the vector must be the declared length, finite, not
     all zeros, and unit-norm when RECOMPUTED — the server's own `l2norm` field is a claim,
     not evidence. A wrong vector that lies about itself is worse than a failure, because
     it flows silently into 337 GB of index.

  2. It writes atomically (tmp + os.replace) so a killed process can never leave a
     half-written JSON that happens to parse.

Usage:
  clap_remote.py <input_audio> <out_json> <model> <endpoint> [timeout_s] [retries]
  clap_remote.py --probe <endpoint> [timeout_s]      # readiness, for operators

Exit codes: 0 ok · 1 honest failure (nothing written) · 2 usage.
"""

import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# The one decode path, shared with probe/features/hook. stdlib-only, so it does not
# break this file's no-torch/no-numpy promise. Without it the remote embedder was the
# last step that still refused WAVs whose RIFF chunk table ffmpeg rejects — the chain
# would sail through probe/features/hook on a salvaged file and then halt here.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lib"))
import workchain_decode as _decode  # noqa: E402

SR = 48000          # the wire contract; not a preference
CHANNELS = 1
L2_TOL = 1e-3       # a unit vector that is off by more than this is not a unit vector


def _fail(msg):
    sys.stderr.write("clap_remote: %s\n" % msg)
    return 1


def decode_48k_mono(src, workdir=None):
    """Decode to the wire contract. Same samples as clap_embed.py's local decode, because the
    two backends must agree; and the same salvage path as every other component, so a malformed
    RIFF chunk table is a container problem rather than a missing embedding.

    Returns (pcm_bytes, provenance). Failure RAISES — never a short or empty buffer.
    """
    try:
        raw, prov = _decode.decode_mono_f32(src, sr=SR, channels=CHANNELS, workdir=workdir)
    except _decode.DecodeError as e:
        raise RuntimeError(str(e))
    if len(raw) % 4 != 0:
        raise RuntimeError("decoded PCM is %d bytes, not a multiple of 4" % len(raw))
    return raw, prov


def _base(endpoint):
    e = (endpoint or "").strip().rstrip("/")
    if not e:
        raise ValueError("empty endpoint")
    if not e.startswith(("http://", "https://")):
        e = "http://" + e
    for suffix in ("/embed", "/embed_batch"):
        if e.endswith(suffix):
            e = e[: -len(suffix)]
    return e


def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_embed(endpoint, pcm, timeout=120.0, retries=2, api_key=None):
    """POST once per clip, with retries that distinguish transient from terminal.

    5xx / connection errors are transient -> back off and retry. 4xx is a contract error:
    the request is wrong and will be wrong again, so retrying only hides the bug. 413 and
    401 in particular must surface immediately.
    """
    url = _base(endpoint) + "/embed"
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Sample-Rate": str(SR),
        "X-Channels": str(CHANNELS),
        "Content-Length": str(len(pcm)),
    }
    key = api_key if api_key is not None else os.environ.get("EMBED_API_KEY", "")
    if key:
        headers["X-API-Key"] = key

    last = None
    for attempt in range(int(retries) + 1):
        try:
            return _post(url, pcm, headers, timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            if 400 <= e.code < 500:
                raise RuntimeError("server rejected the request: HTTP %d %s — not retrying "
                                   "(a contract error is not transient)" % (e.code, detail))
            last = "HTTP %d %s" % (e.code, detail)
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = str(e)
        if attempt < int(retries):
            time.sleep(min(2.0 * (2 ** attempt), 10.0))
    raise RuntimeError("endpoint unreachable after %d attempt(s): %s" % (int(retries) + 1, last))


def validate(resp):
    """Prove the response is a usable vector. Returns (vector, recomputed_l2).

    The server's `l2norm` field is a claim; this recomputes it. Trusting the claim would be
    exactly the 'exit 0 but wrong' failure the whole project exists to refuse.
    """
    if not isinstance(resp, dict):
        raise RuntimeError("response is not a JSON object")
    vec = resp.get("vector")
    dim = resp.get("dim")
    if not isinstance(vec, list) or not vec:
        raise RuntimeError("response has no vector")
    if not isinstance(dim, int) or dim <= 0:
        raise RuntimeError("response dim is not a positive int: %r" % (dim,))
    if len(vec) != dim:
        raise RuntimeError("vector length %d != declared dim %d" % (len(vec), dim))
    try:
        vals = [float(z) for z in vec]
    except (TypeError, ValueError):
        raise RuntimeError("vector contains non-numeric values")
    if not all(math.isfinite(z) for z in vals):
        raise RuntimeError("vector contains NaN or Inf")
    ss = sum(z * z for z in vals)
    if ss <= 0.0:
        raise RuntimeError("vector is all zeros")
    l2 = math.sqrt(ss)
    if abs(l2 - 1.0) > L2_TOL:
        raise RuntimeError("vector is not L2-normed: recomputed |v|=%.6f (tolerance %g)"
                           % (l2, L2_TOL))
    return vals, l2


def probe(endpoint, timeout=10.0):
    """Readiness, not liveness: /readyz is the endpoint that proves the model still agrees
    with its golden. /healthz only proves a process is listening."""
    url = _base(endpoint) + "/readyz"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
            return bool(body.get("ok")), body
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode("utf-8"))
        except Exception:
            return False, {"ok": False, "reason": "HTTP %d" % e.code}
    except Exception as e:
        return False, {"ok": False, "reason": str(e)}


def write_atomic(path, rec):
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(rec, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv):
    if argv and argv[0] == "--probe":
        if len(argv) < 2:
            sys.stderr.write("usage: clap_remote.py --probe <endpoint> [timeout_s]\n")
            return 2
        ok, body = probe(argv[1], float(argv[2]) if len(argv) > 2 else 10.0)
        print(json.dumps(body, indent=2))
        return 0 if ok else 1

    if len(argv) < 4:
        sys.stderr.write("usage: clap_remote.py <input> <out_json> <model> <endpoint> "
                         "[timeout_s] [retries]\n")
        return 2
    src, out, model, endpoint = argv[0], argv[1], argv[2], argv[3]
    timeout = float(argv[4]) if len(argv) > 4 and argv[4] else 120.0
    retries = int(float(argv[5])) if len(argv) > 5 and argv[5] else 2

    try:
        pcm, decode_prov = decode_48k_mono(src, workdir=os.path.dirname(out) or None)
    except Exception as e:
        return _fail(str(e))

    t0 = time.time()
    try:
        resp = post_embed(endpoint, pcm, timeout=timeout, retries=retries)
    except Exception as e:
        return _fail(str(e))

    try:
        vec, l2 = validate(resp)
    except Exception as e:
        return _fail("invalid embedding from %s: %s" % (endpoint, e))

    # Same contract as clap_embed.py, plus provenance. `served_by` is what makes a silent
    # degradation impossible to hide: every record states which backend produced it and
    # which model revision, so the index can always be audited and a re-embed scoped.
    rec = {
        "model": resp.get("model") or model,
        "dim": len(vec),
        "l2norm": round(l2, 6),
        "vector": [round(z, 6) for z in vec],
        "served_by": "remote",
        "endpoint": _base(endpoint),
        "model_rev": resp.get("model_rev"),
        "precision": resp.get("precision"),
        "device": resp.get("device"),
        "server": resp.get("server"),
        "windows": resp.get("windows"),
        "duration_s": resp.get("duration_s"),
        "wire": {"sample_rate": SR, "channels": CHANNELS, "format": "f32le"},
        "decoder": decode_prov.get("decoder"),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    if "salvage" in decode_prov:
        rec["salvage"] = decode_prov["salvage"]
    try:
        write_atomic(out, rec)
    except Exception as e:
        return _fail("could not write %s: %s" % (out, e))

    sys.stderr.write("clap_remote ok: %s dim=%d |v|=%.4f rev=%s device=%s %dms (%s)\n"
                     % (rec["model"], rec["dim"], l2, rec.get("model_rev"),
                        rec.get("device"), rec["elapsed_ms"], rec["endpoint"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
