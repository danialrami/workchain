"""
Fixture test for the acoustic_roundtrip verifier primitive + the acoustic components.

Proves the "proven, not exited-0" gate end to end against lib/workchain_verify.py:
  - a correctly-encoded beacon VERIFIES (structural asserts + acoustic_roundtrip);
  - a beacon whose recorded target differs from what it carries FAILS (the enforcer
    independently re-decodes — it does not trust the component's sidecar);
  - a corrupted beacon FAILS (audio_valid + acoustic_roundtrip).

Domain ground-truth tool is the @lufs/audioqr decoder. If it is not installed, this
test SKIPS (exit 0) rather than failing — the rest of the suite must not depend on a
Node CLI. Provide it via WORKCHAIN_AUDIOQR_BIN or `audioqr` on PATH.

Run: python3 tests/acoustic/test_acoustic_roundtrip.py
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import workchain_verify  # noqa: E402


def _audioqr():
    return os.environ.get("WORKCHAIN_AUDIOQR_BIN") or shutil.which("audioqr")


def _encode(binpath, text, out_wav):
    subprocess.run([binpath, "encode", text, "-o", out_wav,
                    "--protocol", "audible-fast", "--sample-rate", "48000", "--json"],
                   capture_output=True, text=True, timeout=120, check=True)


def _ctx(path, out_wav, recorded_text):
    """A context.json shaped as the engine leaves it: a registered primary_output, a
    valid metadata sidecar, and the resolved params the step ran with. The only variable
    across cases is the beacon audio and the recorded target, so a failure isolates to
    audio_valid / acoustic_roundtrip rather than incidental structural gaps."""
    meta_path = out_wav + ".json"
    with open(meta_path, "w") as f:
        json.dump({"source_text": recorded_text, "decoded_text": recorded_text,
                   "roundtrip_ok": True, "protocol": "audible-fast"}, f)
    ctx = {
        "input_file": out_wav, "output_dir": os.path.dirname(out_wav),
        "input_name": "beacon", "input_ext": "wav", "globals": {},
        "steps": {"acoustic_encode": {
            "params": {"text": recorded_text},
            "outputs": {
                "primary_output": {"path": out_wav, "type": "file", "exists": True},
                "metadata": {"path": meta_path, "type": "json", "exists": True},
            },
        }},
    }
    with open(path, "w") as f:
        json.dump(ctx, f)
    return path


def main():
    binpath = _audioqr()
    if not binpath:
        print("SKIP: audioqr not found (set WORKCHAIN_AUDIOQR_BIN or install @lufs/audioqr)")
        return 0

    text = "https://catalog.lufs.audio/lufs-1a2b3c4d"
    tmp = tempfile.mkdtemp(prefix="wc-acoustic-")
    failures = []
    try:
        beacon = os.path.join(tmp, "beacon.wav")
        _encode(binpath, text, beacon)

        # 1) correct beacon → verified, acoustic_roundtrip passes
        c1 = _ctx(os.path.join(tmp, "c1.json"), beacon, text)
        _rep, ok = workchain_verify.verify(ROOT, "acoustic_encode", c1)
        if not ok:
            failures.append("correct beacon should verify")

        # 2) recorded target != what the beacon carries → must FAIL
        c2 = _ctx(os.path.join(tmp, "c2.json"), beacon, "WRONG-PAYLOAD")
        _rep, ok = workchain_verify.verify(ROOT, "acoustic_encode", c2)
        if ok:
            failures.append("target mismatch should fail")

        # 3) corrupted beacon → must FAIL
        bad = os.path.join(tmp, "bad.wav")
        with open(bad, "wb") as f:
            f.write(b"\x00" * 200)
        c3 = _ctx(os.path.join(tmp, "c3.json"), bad, text)
        _rep, ok = workchain_verify.verify(ROOT, "acoustic_encode", c3)
        if ok:
            failures.append("corrupted beacon should fail")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("FAIL:\n  - " + "\n  - ".join(failures))
        return 1
    print("PASS: acoustic_roundtrip verified (happy path + 2 honest failures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
