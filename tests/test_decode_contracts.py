"""Regression tests for the 2026-08 audio ingest decode-integrity fixes.

These exist because a real 112,696-file ingest halted on WAVs whose RIFF chunk table ffmpeg
refuses, and TWO components reported success on them anyway. Every test below is a replay of
something that actually happened, not a hypothetical:

  1. workchain_decode salvages the malformed-LIST class, and the salvaged audio is
     BIT-IDENTICAL to a clean control (metamorphic — the container changed, the samples did not).
  2. ffprobe_json raises instead of returning {} on a file ffmpeg refuses.
  3. json_fields_within FAILS the exact null-filled probe record that the old
     `json_has`-only contract passed.
  4. json_fields_within FAILS the exact zeroed "insufficient_audio" features record.
  5. json_fields_within is fail-closed: an unparsable or unknown constraint is a failure,
     never a silent skip.
  6. The step.yaml contracts parse under the repo's own YAML parser and reference only
     post-condition checks that exist in POST_CHECKS.

Run: python3 tests/test_decode_contracts.py     (exit 0 = all passed)
"""

import json
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import workchain_decode as D          # noqa: E402
import workchain_verify as V          # noqa: E402
import workchain_yaml                 # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %-64s %s%s" % (name, "PASS" if ok else "FAIL",
                            ("  — " + detail) if detail else ""))


def _fields_check(rec, require, tmpdir, out_name="probe"):
    """Drive check_json_fields_within the way the engine does."""
    path = os.path.join(tmpdir, out_name + ".json")
    with open(path, "w") as f:
        json.dump(rec, f)
    pc = {"id": "t", "check": "json_fields_within", "output": out_name, "require": require}
    return V.check_json_fields_within(pc, {}, "probe", {}, {out_name: path})


def main():
    d = tempfile.mkdtemp(prefix="workchain-contract-tests-")
    print("decode + contract regression tests  (%s)" % d)

    # ── 1-2. the decoder itself (delegates to the module's own selftest) ──────────────
    print("\n[decode] workchain_decode selftest")
    failures = D.selftest(verbose=True)
    check("workchain_decode selftest", not failures, "; ".join(failures))

    # ── 3. the null probe record that used to pass ────────────────────────────────────
    print("\n[contract] the records that used to pass")
    probe_require = [
        "content_sha256 is non_empty", "duration_s > 0",
        "samplerate >= 2000", "samplerate <= 768000",
        "channels >= 1", "channels <= 64",
        "peak_dbfs >= -144", "peak_dbfs <= 60",
        "codec is non_empty", "container is non_empty",
        "decoder one_of ffmpeg|salvaged-riff",
    ]
    # verbatim shape of what probe wrote when ffprobe returned rc=1 with empty stdout
    null_probe = {"content_sha256": "a" * 64, "catalog_number": "lufs-aaaaaaaa",
                  "path": "/x.wav", "filename": "x.wav", "duration_s": 0.0,
                  "samplerate": None, "channels": None, "bits_per_raw_sample": None,
                  "codec": None, "container": None, "peak_dbfs": None, "mean_dbfs": None,
                  "decoder": "ffmpeg"}
    ok, detail, _ = _fields_check(null_probe, probe_require, d)
    check("null-filled probe record is REJECTED", not ok, detail[:160])
    # and json_has — the old contract — would have passed it
    old_ok, _ = V._assert_json_has(
        os.path.join(d, "probe.json"),
        keys=["content_sha256", "duration_s", "samplerate", "channels", "peak_dbfs"])
    check("...while the old json_has contract PASSED it (the gap)", old_ok)

    good_probe = dict(null_probe, duration_s=1.9994, samplerate=44100, channels=2,
                      codec="pcm_s24le", container="wav", peak_dbfs=-1.2, mean_dbfs=-18.4)
    ok, detail, measured = _fields_check(good_probe, probe_require, d)
    check("a real probe record is ACCEPTED", ok, detail)
    check("...and the measured values are reported for the run log",
          measured.get("values", {}).get("samplerate") == 44100)

    salvaged_probe = dict(good_probe, decoder="salvaged-riff")
    ok, _, _ = _fields_check(salvaged_probe, probe_require, d)
    check("a salvaged-riff probe record is ACCEPTED", ok)

    ok, detail, _ = _fields_check(dict(good_probe, decoder="melstats-guess"),
                                  probe_require, d)
    check("an unknown decoder is REJECTED (provenance is enforced)", not ok, detail[:90])

    # ── 4. the zeroed features record that used to pass ───────────────────────────────
    feat_require = ["decoded_duration_s > 0", "feature_source is non_empty",
                    "decoder one_of ffmpeg|salvaged-riff",
                    "rms_dbfs >= -144", "rms_dbfs <= 24",
                    "spectral_centroid_hz >= 0", "spectral_centroid_hz <= 11025",
                    "brightness >= 0", "brightness <= 1"]
    zeroed = {"feature_source": "native-melstats-v0", "spectral_centroid_hz": 0.0,
              "rms_dbfs": -120.0, "zero_crossing_rate": 0.0, "brightness": 0.0,
              "bpm": None, "key": None, "note": "insufficient_audio",
              "decoder": "ffmpeg", "decoded_duration_s": 0.0}
    ok, detail, _ = _fields_check(zeroed, feat_require, d, "features")
    check("zeroed 'insufficient_audio' features record is REJECTED", not ok, detail[:120])
    real = dict(zeroed, decoded_duration_s=1.9994, spectral_centroid_hz=3184.22,
                rms_dbfs=-14.8, brightness=0.2888, note="ok")
    ok, detail, _ = _fields_check(real, feat_require, d, "features")
    check("a real features record is ACCEPTED", ok, detail)
    ok, _, _ = _fields_check(dict(real, spectral_centroid_hz=48000.0), feat_require, d, "features")
    check("a centroid above Nyquist is REJECTED", not ok)

    # ── 5. fail-closed on a broken contract ──────────────────────────────────────────
    print("\n[contract] fail-closed behaviour")
    for bad, label in [(["duration_s"], "unparsable constraint"),
                       (["duration_s ~~ 3"], "unknown operator"),
                       (["duration_s is weasel"], "unknown kind"),
                       (["nope > 0"], "field missing from record"),
                       (["duration_s one_of"], "one_of with no alternatives")]:
        ok, detail, _ = _fields_check(good_probe, bad, d)
        check("REJECTS %s" % label, not ok, detail[:80])
    ok, detail, _ = _fields_check(good_probe, [], d)
    check("REJECTS an empty require list (a contract that proves nothing)", not ok, detail[:60])
    ok, _, _ = _fields_check(good_probe, ["codec == pcm_s24le"], d)
    check("string equality works", ok)
    ok, _, _ = _fields_check({"salvage": {"reason": "salvaged 2ch"}, "d": 1},
                             ["salvage.reason is non_empty"], d)
    check("dotted paths reach into nested objects", ok)

    # ── 6. the shipped contracts are real ────────────────────────────────────────────
    print("\n[contract] shipped step.yaml contracts")
    for comp in ("probe", "features", "hook", "embed_clap", "archive_index"):
        p = os.path.join(ROOT, "components", comp, "step.yaml")
        if not os.path.exists(p):
            continue
        y = workchain_yaml.load_file(p) or {}
        contract = y.get("verify") or {}
        pcs = contract.get("post_conditions") or []
        unknown = [pc.get("check") for pc in pcs if pc.get("check") not in V.POST_CHECKS]
        check("%s/step.yaml parses and its post-conditions exist" % comp,
              bool(contract) and not unknown,
              "unknown checks: %s" % unknown if unknown else "%d post-condition(s)" % len(pcs))
        for pc in pcs:
            if pc.get("check") == "json_fields_within":
                req = pc.get("require") or []
                check("  %s.%s declares %d constraints as a list of strings"
                      % (comp, pc.get("id"), len(req)),
                      isinstance(req, list) and len(req) > 0
                      and all(isinstance(r, str) for r in req))
                # every constraint must be well-formed against a permissive record
                probe_rec = {k: 1 for k in
                             set(r.split()[0].split(".")[0] for r in req if r.split())}
                _, det, _ = _fields_check(probe_rec, req, d, "syntaxprobe")
                check("  %s.%s has no unparsable constraint" % (comp, pc.get("id")),
                      "cannot parse" not in det and "unknown operator" not in det
                      and "unknown kind" not in det, det[:80])

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: %s" % ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
