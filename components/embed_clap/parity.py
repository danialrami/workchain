"""
parity.py — prove the two backends agree.

The metamorphic check for embed_clap. There is no "correct" 512-d vector for a sound, so we
cannot assert an exact output. What we CAN assert is a RELATION: the local checkpoint and
the remote resident-model server, given the same input, must land in the same place. If they
do not, one of them is wrong and the archive is being built out of two incompatible spaces.

This is the claim /readyz cannot make. /readyz proves a server still agrees with its OWN
past self (drift). This proves two independent implementations, on two devices, agree with
EACH OTHER (parity). Both are needed; neither substitutes for the other.

Run it on a host that has both (the ingest host), pointed at the endpoint you intend to cut over to:

    python3 parity.py --endpoint http://100.x.y.z:8770 ~/Samples/some/take.wav
    python3 parity.py --endpoint http://127.0.0.1:8770 --min-cosine 0.9999 a.wav b.wav c.aif

Exit codes: 0 all pairs within tolerance · 1 a parity violation · 2 usage / setup error.

WHY 0.9999 AND NOT 1.0: fp32 matmul on CUDA vs MPS vs CPU differs in the last few ULPs, and
mean-pooling accumulates that. 0.9999 cosine is far tighter than any semantically meaningful
difference while tolerating device noise. A precision change (fp16) or a different checkpoint
lands nowhere near it — which is exactly what this is built to catch.
"""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_vec(path):
    with open(path) as f:
        rec = json.load(f)
    v = rec.get("vector") or []
    if not v:
        raise RuntimeError("no vector in %s" % path)
    return [float(z) for z in v], rec


def cosine(a, b):
    if len(a) != len(b):
        raise RuntimeError("dim mismatch: %d vs %d — these are not the same embedding space"
                           % (len(a), len(b)))
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        raise RuntimeError("zero-norm vector")
    return dot / (na * nb)


def run_local(src, out, model):
    venv_py = os.path.join(HERE, ".venv", "bin", "python")
    if not os.access(venv_py, os.X_OK):
        raise RuntimeError("local backend not provisioned (%s missing) — parity needs BOTH "
                           "backends on this host; run provision.sh" % venv_py)
    p = subprocess.run([venv_py, os.path.join(HERE, "clap_embed.py"), src, out, model],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("local backend failed: %s" % (p.stderr or p.stdout)[-400:])


def run_remote(src, out, model, endpoint, timeout, retries):
    p = subprocess.run([sys.executable, os.path.join(HERE, "clap_remote.py"),
                        src, out, model, endpoint, str(timeout), str(retries)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("remote backend failed: %s" % (p.stderr or p.stdout)[-400:])


def main():
    ap = argparse.ArgumentParser(description="Prove embed_clap's local and remote backends agree.")
    ap.add_argument("inputs", nargs="+", help="audio files to compare through both backends")
    ap.add_argument("--endpoint", required=True, help="serve-embed base URL")
    ap.add_argument("--model", default="laion-clap-630k")
    ap.add_argument("--min-cosine", type=float, default=0.9999)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = ap.parse_args()

    # Readiness first: comparing against a server that has not proved itself against its
    # golden would make a green parity run meaningless.
    sys.path.insert(0, HERE)
    try:
        from clap_remote import probe
        ok, body = probe(args.endpoint)
        if not ok:
            sys.stderr.write("✗ endpoint is not READY: %s\n" % body.get("reason"))
            sys.stderr.write("  parity against an unproven server proves nothing. Fix /readyz first.\n")
            return 2
        sys.stderr.write("• endpoint ready: rev=%s device=%s precision=%s\n"
                         % (body.get("model_rev"), body.get("device"), body.get("precision")))
    except Exception as e:
        sys.stderr.write("✗ could not probe endpoint: %s\n" % e)
        return 2

    results, violations = [], 0
    with tempfile.TemporaryDirectory(prefix="clap-parity-") as td:
        for src in args.inputs:
            row = {"input": src}
            if not os.path.exists(src):
                row.update(ok=False, error="missing input")
                violations += 1
                results.append(row)
                sys.stderr.write("✗ %s — missing\n" % src)
                continue
            lo = os.path.join(td, "local.json")
            ro = os.path.join(td, "remote.json")
            try:
                run_local(src, lo, args.model)
                run_remote(src, ro, args.model, args.endpoint, args.timeout, args.retries)
                lv, lrec = _load_vec(lo)
                rv, rrec = _load_vec(ro)
                cos = cosine(lv, rv)
                ok = cos >= args.min_cosine
                row.update(ok=ok, cosine=round(cos, 9), dim=len(lv),
                           local_model=lrec.get("model"), local_device=lrec.get("device"),
                           remote_model_rev=rrec.get("model_rev"),
                           remote_device=rrec.get("device"),
                           remote_precision=rrec.get("precision"))
                if not ok:
                    violations += 1
                    sys.stderr.write(
                        "✗ PARITY VIOLATION %s — cosine %.9f < %.9f (local device=%s, "
                        "remote device=%s precision=%s). The two backends are NOT producing "
                        "the same embedding space; do not mix them in one index.\n"
                        % (src, cos, args.min_cosine, lrec.get("device"),
                           rrec.get("device"), rrec.get("precision")))
                else:
                    sys.stderr.write("✓ %s — cosine %.9f (dim %d)\n" % (src, cos, len(lv)))
            except Exception as e:
                row.update(ok=False, error=str(e))
                violations += 1
                sys.stderr.write("✗ %s — %s\n" % (src, e))
            results.append(row)

    report = {"min_cosine": args.min_cosine, "endpoint": args.endpoint,
              "n": len(results), "violations": violations,
              "parity": violations == 0, "results": results}
    if args.json:
        print(json.dumps(report, indent=2))
    n_ok = len(results) - violations
    sys.stderr.write("%s parity: %d/%d within cosine >= %g\n"
                     % ("✓" if violations == 0 else "✗", n_ok, len(results), args.min_cosine))
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
