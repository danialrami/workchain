#!/usr/bin/env python3
"""workchain_decode — the single audio-decode path for every Workchain component.

WHY THIS EXISTS
---------------
Three components (probe, features, hook) and the CLAP embedder each opened audio with
their own inline ffmpeg call, and each one handled failure differently. probe and features
SWALLOWED a failed decode and wrote a null/zero sidecar, then exited 0 — the exact
"exit 0 but wrong" class this project exists to eliminate:

    probe:    d = json.loads(r.stdout or "{}")   # ffprobe rc=1 -> {} -> all fields null
    features: x = np.frombuffer(raw, ...)        # raw = b"" -> "insufficient_audio" record

Both then passed their contracts, because the contracts only asserted key PRESENCE.
`hook` was the only step that failed honestly, and that honesty is the only reason 112,696
null records never reached the index.

Two real-world failure modes drove this module:

  1. WAV files whose RIFF chunk table ffmpeg refuses outright — "too short LIST tag" ->
     AVERROR_INVALIDDATA. Native Instruments expansion libraries and some Sonniss GDC
     bundles carry these. The audio payload is intact; only the chunk table is malformed.

  2. WAV INFO/LIST tags carrying latin-1 / CP1252 bytes. Decoding ffmpeg's stderr as
     strict UTF-8 raises UnicodeDecodeError, which takes down not just the step but the
     batch driver above it.

THE CONTRACT OF THIS MODULE
---------------------------
  run()               every subprocess call decodes stderr with errors="replace". Always.
  ffprobe_json()      raises DecodeError on a nonzero ffprobe. Never returns a shrug.
  salvage_riff()      stdlib-only RIFF rescue: scan for fmt+data, rewrite canonical PCM.
  decode_mono_f32()   ffmpeg -> salvage -> raise. Returns (pcm_bytes, provenance).

`provenance` is recorded in the sidecar by callers ("decoder": "ffmpeg" | "salvaged-riff"),
the same discipline as served_by / model_rev on embeddings: if a number was measured from a
repaired file, the record says so out loud.

stdlib only — no numpy, no libsndfile, no ffmpeg-python. The light path stays light.

SELFTEST
--------
`python3 lib/workchain_decode.py selftest` synthesizes the two malformed-WAV classes and
asserts the metamorphic property: decode(salvage(malformed)) is bit-identical to
decode(clean control), and salvage is idempotent on already-clean files. No binary fixtures
are committed — they are generated deterministically from source.
"""

import json
import math
import os
import struct
import subprocess
import sys
import tempfile

__all__ = [
    "DecodeError",
    "run",
    "ffprobe_json",
    "salvage_riff",
    "decode_mono_f32",
    "decode_raw",
    "SALVAGE_SUFFIX",
]

SALVAGE_SUFFIX = ".salvaged.wav"

# Plausibility bounds for a RIFF `fmt ` chunk. Deliberately generous — this is a
# "is this a coherent audio header at all" test, not a taste test.
_MAX_SR = 768000
_MIN_SR = 2000
_WAVE_FORMAT_PCM = 1
_WAVE_FORMAT_FLOAT = 3
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


class DecodeError(RuntimeError):
    """A decode that could not be completed honestly. Never swallow this."""


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess: one safe wrapper, used by everything
# ─────────────────────────────────────────────────────────────────────────────

def run(cmd, capture_text=True, **kw):
    """subprocess.run with the two settings every caller in this repo wants.

    - stdin is never inherited (a stray ffmpeg must not eat the driver's stdin)
    - stderr/stdout text decoding uses errors="replace", so a WAV with CP1252 bytes in an
      INFO tag can never raise UnicodeDecodeError and kill a 112k-file run.

    capture_text=False keeps stdout as raw BYTES (for PCM) while still decoding stderr
    safely — the common shape for a decode call.
    """
    kw.setdefault("stdin", subprocess.DEVNULL)
    if capture_text:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)
    p = subprocess.run(cmd, capture_output=True, **kw)
    # hand back a shim with bytes stdout and safely-decoded stderr
    p.stderr_text = (p.stderr or b"").decode("utf-8", "replace")
    return p


def _stderr_tail(p, n=4):
    txt = getattr(p, "stderr_text", None)
    if txt is None:
        txt = p.stderr if isinstance(p.stderr, str) else (p.stderr or b"").decode("utf-8", "replace")
    lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) if lines else "(no stderr)"


# ─────────────────────────────────────────────────────────────────────────────
# ffprobe — honest or nothing
# ─────────────────────────────────────────────────────────────────────────────

def ffprobe_json(src, entries=None, select="a:0"):
    """Return parsed ffprobe JSON, or raise DecodeError.

    The old inline version did `json.loads(r.stdout or "{}")`, which turned a hard
    ffprobe failure into a record full of nulls that still satisfied `json_has`.
    """
    entries = entries or (
        "format=duration,format_name:"
        "stream=sample_rate,channels,bits_per_raw_sample,codec_name"
    )
    cmd = ["ffprobe", "-v", "error", "-show_entries", entries,
           "-select_streams", select, "-of", "json", src]
    p = run(cmd)
    if p.returncode != 0:
        raise DecodeError("ffprobe rc=%d on %s: %s" % (p.returncode, src, _stderr_tail(p)))
    try:
        d = json.loads(p.stdout or "")
    except ValueError as e:
        raise DecodeError("ffprobe emitted unparsable JSON for %s: %s" % (src, e))
    if not isinstance(d, dict) or not d.get("streams"):
        raise DecodeError("ffprobe found no audio stream in %s: %s" % (src, _stderr_tail(p)))
    return d


# ─────────────────────────────────────────────────────────────────────────────
# RIFF salvage — stdlib only
# ─────────────────────────────────────────────────────────────────────────────

def _plausible_fmt(body):
    """Parse a candidate `fmt ` payload; return (audio_format, ch, sr, bits) or None."""
    if len(body) < 16:
        return None
    try:
        af, ch, sr, _byte_rate, _block_align, bits = struct.unpack("<HHIIHH", body[:16])
    except struct.error:
        return None
    if af not in (_WAVE_FORMAT_PCM, _WAVE_FORMAT_FLOAT, _WAVE_FORMAT_EXTENSIBLE):
        return None
    if not 1 <= ch <= 64:
        return None
    if not _MIN_SR <= sr <= _MAX_SR:
        return None
    if bits not in (8, 16, 24, 32, 64):
        return None
    return af, ch, sr, bits


def salvage_riff(src, dst):
    """Rescue a WAV whose chunk table ffmpeg rejects. Returns (ok, reason).

    The defining decision: this NEVER trusts a chunk's declared size to walk the file,
    because a bogus size field is exactly what is broken in these files. It scans forward
    on even offsets for a plausible `fmt `, then for the first `data` after it, and writes
    a canonical two-chunk PCM WAV containing only those. Metadata is discarded by design —
    the archive's facts come from the sidecars, not from the file's LIST tags.

    Deterministic and idempotent: salvaging an already-clean file yields the same PCM.
    """
    try:
        with open(src, "rb") as f:
            blob = f.read()
    except OSError as e:
        return False, "unreadable: %s" % e

    n = len(blob)
    if n < 44:
        return False, "too small to be a WAV (%d bytes)" % n
    if blob[:4] not in (b"RIFF", b"RF64") or blob[8:12] != b"WAVE":
        return False, "not a RIFF/WAVE container"

    fmt = fpos = None
    i = 12
    while i + 24 <= n:
        if blob[i:i + 4] == b"fmt " and _plausible_fmt(blob[i + 8:i + 48]):
            fmt, fpos = blob[i + 8:i + 24], i
            break
        i += 2
    if fmt is None:
        return False, "no plausible fmt chunk found"

    af, ch, sr, bits = _plausible_fmt(fmt)

    j = fpos + 24
    dpos = None
    while j + 8 <= n:
        if blob[j:j + 4] == b"data":
            dpos = j
            break
        j += 2
    if dpos is None:
        return False, "no data chunk found after fmt"

    size = struct.unpack("<I", blob[dpos + 4:dpos + 8])[0]
    start = dpos + 8
    if size == 0 or size == 0xFFFFFFFF or start + size > n:
        size = n - start                       # truncated or streaming sentinel: take the rest
    frame = max(1, ch * bits // 8)
    size -= size % frame                       # whole frames only
    if size < frame:
        return False, "data chunk holds no complete frame"

    if af == _WAVE_FORMAT_EXTENSIBLE:          # declare it plainly
        af = _WAVE_FORMAT_FLOAT if bits in (32, 64) else _WAVE_FORMAT_PCM

    fmt_out = struct.pack("<HHIIHH", af, ch, sr, sr * frame, frame, bits)
    body = (b"fmt " + struct.pack("<I", 16) + fmt_out +
            b"data" + struct.pack("<I", size) + blob[start:start + size])
    tmp = dst + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
        os.replace(tmp, dst)                   # atomic: a partial salvage is never visible
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False, "could not write salvaged copy: %s" % e
    return True, "salvaged %dch/%dHz/%dbit, %d data bytes" % (ch, sr, bits, size)


def _salvage_target(src, workdir):
    base = os.path.basename(src) + SALVAGE_SUFFIX
    if workdir:
        d = os.path.join(workdir, "salvaged")
    else:
        d = tempfile.mkdtemp(prefix="workchain-salvage-")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, base)


# ─────────────────────────────────────────────────────────────────────────────
# Decode
# ─────────────────────────────────────────────────────────────────────────────

def decode_raw(src, sr, channels=1, fmt="f32le", extra=None):
    """One ffmpeg decode attempt. Returns (rc, pcm_bytes, stderr_text)."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", src,
           "-ac", str(channels), "-ar", str(sr), "-f", fmt]
    if extra:
        cmd += list(extra)
    cmd.append("-")
    p = run(cmd, capture_text=False)
    return p.returncode, (p.stdout or b""), p.stderr_text


def decode_mono_f32(src, sr=22050, channels=1, workdir=None, allow_salvage=True):
    """Decode to interleaved float32 PCM. Returns (pcm_bytes, provenance dict).

    Order: ffmpeg -> salvage_riff + ffmpeg -> raise DecodeError.
    Never returns empty bytes silently: a zero-length decode of a file that is not
    genuinely empty is a failure, and it is raised as one.

    provenance keys:
      decoder        "ffmpeg" | "salvaged-riff"
      sample_rate    the sr actually requested of ffmpeg
      channels       channels requested
      frames         decoded frame count
      salvage        (only when salvaged) {"reason", "original_error", "path"}
    """
    rc, pcm, errtxt = decode_raw(src, sr, channels)
    if rc == 0 and pcm:
        return pcm, {"decoder": "ffmpeg", "sample_rate": sr, "channels": channels,
                     "frames": len(pcm) // (4 * channels)}

    first_error = (errtxt.strip().splitlines() or ["(no stderr)"])[-1]

    if not allow_salvage:
        raise DecodeError("ffmpeg rc=%d, %d bytes decoded from %s: %s"
                          % (rc, len(pcm), src, first_error))

    dst = _salvage_target(src, workdir)
    if not (os.path.exists(dst) and os.path.getsize(dst) > 44
            and os.path.getmtime(dst) >= os.path.getmtime(src)):
        ok, reason = salvage_riff(src, dst)
        if not ok:
            raise DecodeError("ffmpeg refused %s (%s) and salvage failed (%s)"
                              % (src, first_error, reason))
    else:
        reason = "reused existing salvaged copy"

    rc2, pcm2, errtxt2 = decode_raw(dst, sr, channels)
    if rc2 != 0 or not pcm2:
        tail = (errtxt2.strip().splitlines() or ["(no stderr)"])[-1]
        raise DecodeError("ffmpeg refused %s (%s); salvaged copy also failed rc=%d (%s)"
                          % (src, first_error, rc2, tail))
    return pcm2, {"decoder": "salvaged-riff", "sample_rate": sr, "channels": channels,
                  "frames": len(pcm2) // (4 * channels),
                  "salvage": {"reason": reason, "original_error": first_error, "path": dst}}


def decodable_path(src, workdir=None):
    """Return a path ffmpeg will accept for `src` — the original, or a salvaged copy.

    For components that must hand a FILE to ffmpeg rather than read PCM (hook's clip and
    waveform renders). Raises DecodeError if neither works.
    """
    rc, _, errtxt = decode_raw(src, 8000, 1, extra=["-t", "0.05"])
    if rc == 0:
        return src, {"decoder": "ffmpeg"}
    first_error = (errtxt.strip().splitlines() or ["(no stderr)"])[-1]
    dst = _salvage_target(src, workdir)
    ok, reason = salvage_riff(src, dst)
    if not ok:
        raise DecodeError("ffmpeg refused %s (%s) and salvage failed (%s)"
                          % (src, first_error, reason))
    rc2, _, errtxt2 = decode_raw(dst, 8000, 1, extra=["-t", "0.05"])
    if rc2 != 0:
        tail = (errtxt2.strip().splitlines() or ["(no stderr)"])[-1]
        raise DecodeError("ffmpeg refused %s (%s); salvaged copy also failed (%s)"
                          % (src, first_error, tail))
    return dst, {"decoder": "salvaged-riff",
                 "salvage": {"reason": reason, "original_error": first_error, "path": dst}}


# ─────────────────────────────────────────────────────────────────────────────
# Selftest — generated fixtures, metamorphic assertions
# ─────────────────────────────────────────────────────────────────────────────

def _write_fixtures(d, sr=44100, nsamp=22050):
    def chunk(tag, payload):
        b = tag + struct.pack("<I", len(payload)) + payload
        return b + (b"\x00" if len(payload) % 2 else b"")

    def riff(body):
        return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body

    data = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / sr)))
                    for i in range(nsamp))
    fmt = chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, sr, sr * 2, 2, 16))
    dat = chunk(b"data", data)
    paths = {}

    paths["clean"] = os.path.join(d, "clean.wav")
    with open(paths["clean"], "wb") as f:
        f.write(riff(fmt + dat))

    # class 1: LIST chunk with size < 4 -> ffmpeg "too short LIST tag", hard refusal
    paths["shortlist"] = os.path.join(d, "shortlist.wav")
    with open(paths["shortlist"], "wb") as f:
        f.write(riff(fmt + b"LIST" + struct.pack("<I", 2) + b"IN" + dat))

    # class 2: latin-1 bytes in INFO tags -> UnicodeDecodeError on strict stderr decode
    info = chunk(b"LIST", b"INFO"
                 + chunk(b"IART", b"Bj\xf6rk Gu\xf0mundsd\xf3ttir\x00")
                 + chunk(b"ICMT", b"Medizin \xe4\xe6\xa6\x00"))
    paths["latin1"] = os.path.join(d, "latin1meta.wav")
    with open(paths["latin1"], "wb") as f:
        f.write(riff(fmt + info + dat))

    # class 3: data chunk claiming more bytes than the file holds
    paths["truncated"] = os.path.join(d, "truncated.wav")
    with open(paths["truncated"], "wb") as f:
        f.write(riff(fmt + b"data" + struct.pack("<I", len(data) * 4) + data))
    return paths


def selftest(verbose=True):
    failures = []

    def check(name, ok, detail=""):
        if verbose:
            print("  %-52s %s%s" % (name, "PASS" if ok else "FAIL",
                                    ("  — " + detail) if detail else ""))
        if not ok:
            failures.append("%s: %s" % (name, detail))

    d = tempfile.mkdtemp(prefix="workchain-decode-selftest-")
    fx = _write_fixtures(d)
    if verbose:
        print("workchain_decode selftest  (fixtures in %s)" % d)

    ref, prov = decode_mono_f32(fx["clean"], sr=22050, workdir=d)
    check("clean control decodes via ffmpeg", prov["decoder"] == "ffmpeg" and len(ref) > 0,
          prov["decoder"])

    # 1. ffmpeg genuinely refuses the malformed-LIST file (the bug's precondition)
    rc, _, _ = decode_raw(fx["shortlist"], 22050, 1)
    check("ffmpeg refuses malformed-LIST wav (precondition)", rc != 0, "rc=%d" % rc)

    # 2. THE metamorphic property: salvage changes the container, never the samples
    got, prov = decode_mono_f32(fx["shortlist"], sr=22050, workdir=d)
    check("salvage rescues malformed-LIST wav", prov["decoder"] == "salvaged-riff",
          prov["decoder"])
    check("decode(salvage(malformed)) == decode(clean control)", got == ref,
          "%d vs %d bytes" % (len(got), len(ref)))

    # 3. idempotence: salvaging a clean file must not alter the audio
    tgt = os.path.join(d, "clean.resalvaged.wav")
    ok, reason = salvage_riff(fx["clean"], tgt)
    _, again, _ = decode_raw(tgt, 22050, 1)
    check("salvage is idempotent on already-clean input", ok and again == ref, reason)

    # 4. latin-1 metadata must not raise; stderr decoding is errors="replace"
    try:
        p = run(["ffmpeg", "-nostdin", "-hide_banner", "-i", fx["latin1"],
                 "-af", "volumedetect", "-f", "null", "-"])
        check("latin-1 INFO tags do not raise UnicodeDecodeError", True,
              "%d stderr chars" % len(p.stderr))
    except UnicodeDecodeError as e:
        check("latin-1 INFO tags do not raise UnicodeDecodeError", False, str(e))

    # 5. a lying data size is clamped, not trusted
    got, prov = decode_mono_f32(fx["truncated"], sr=22050, workdir=d)
    check("over-declared data size is clamped to EOF", len(got) > 0, prov["decoder"])

    # 6. honest failure: a file that is not audio must RAISE, not return empty
    junk = os.path.join(d, "junk.wav")
    with open(junk, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 100) + b"WAVE" + b"\x00" * 100)
    try:
        decode_mono_f32(junk, sr=22050, workdir=d)
        check("non-audio input raises DecodeError (no silent empty)", False,
              "returned instead of raising")
    except DecodeError:
        check("non-audio input raises DecodeError (no silent empty)", True)

    # 7. ffprobe_json refuses to shrug
    try:
        ffprobe_json(junk)
        check("ffprobe_json raises instead of returning {}", False, "returned a dict")
    except DecodeError:
        check("ffprobe_json raises instead of returning {}", True)

    if verbose:
        print("selftest: %d checks, %d failed" % (7 + 2, len(failures)))
    return failures


def _main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print("usage: workchain_decode.py <selftest|salvage SRC DST|probe SRC>")
        return 2
    cmd = argv[1]
    if cmd == "selftest":
        return 1 if selftest() else 0
    if cmd == "salvage":
        if len(argv) != 4:
            print("usage: workchain_decode.py salvage SRC DST", file=sys.stderr)
            return 2
        ok, reason = salvage_riff(argv[2], argv[3])
        print(json.dumps({"ok": ok, "reason": reason, "dst": argv[3]}))
        return 0 if ok else 1
    if cmd == "probe":
        try:
            print(json.dumps(ffprobe_json(argv[2]), indent=2))
            return 0
        except DecodeError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            return 1
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
