"""End-to-end-ish test of the probe / features / hook analysis cores against real malformed WAVs.

SCOPE, stated honestly: this extracts and executes the python block from each component's
run.sh — where all of the measurement logic lives — with the same environment the bash wrapper
provides. It does NOT exercise the engine, the context file, or register_output; the full
chain path is covered by tests/verify_astro_catalog.sh and by a live ingest.

What it proves, on files that reproduce the two classes seen in the 2026-08 the original ingest host failure:
  * a WAV ffmpeg refuses ("too short LIST tag") is SALVAGED and measured, with
    decoder="salvaged-riff" recorded in the sidecar
  * a WAV whose INFO tags hold latin-1 bytes no longer raises UnicodeDecodeError
  * a file that is not audio at all makes every component exit NONZERO and write no sidecar —
    the old code exited 0 with a record full of nulls / zeros
  * numbers measured from a salvaged copy MATCH the numbers from a clean control, so salvage
    does not quietly change the archive's facts

Run: python3 tests/test_component_decode_integration.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import workchain_decode as D          # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %-66s %s%s" % (name, "PASS" if ok else "FAIL",
                            ("  — " + detail) if detail else ""))


def metamorphic_eq(name, a, b, fields):
    """Assert two records agree on `fields` — and REFUSE to pass on absent data.

    A metamorphic relation says "these two must agree", which is trivially satisfied when
    both sides are missing: `None == None` is True, so an unguarded equality check reports
    PASS on a run where neither component executed. That is key-presence masquerading as
    value-correctness — the exact disease this suite exists to catch — so the comparison
    must prove both sides exist before it means anything.

    Note the asymmetry that hid this: equality assertions fail OPEN on empty records, while
    inequality assertions (e.g. "the content hashes differ") fail CLOSED. The metamorphic
    relations are therefore precisely the ones that need the guard.
    """
    missing = [k for k in fields if a.get(k) is None or b.get(k) is None]
    if missing:
        check(name, False,
              "VACUOUS — nothing to compare, absent on one or both sides: %s" % ", ".join(missing))
        return
    check(name, all(a.get(k) == b.get(k) for k in fields),
          "clean=%s salvaged=%s" % ([a.get(k) for k in fields], [b.get(k) for k in fields]))


def extract_python(run_sh):
    """Pull the `python3 <<'PY' ... PY` block out of a component's run.sh."""
    with open(run_sh) as f:
        src = f.read()
    m = re.search(r"python3\s*<<'PY'\n(.*?)\nPY\n", src, re.S)
    if not m:
        raise AssertionError("no python heredoc found in %s" % run_sh)
    return m.group(1)


def run_core(comp, env):
    code = extract_python(os.path.join(ROOT, "components", comp, "run.sh"))
    e = dict(os.environ, WCLIB=os.path.join(ROOT, "lib"), **env)
    p = subprocess.run([sys.executable, "-c", code], env=e,
                       capture_output=True, text=True, errors="replace")
    return p


def main():
    d = tempfile.mkdtemp(prefix="workchain-component-integration-")
    fx = D._write_fixtures(d)
    print("component decode integration  (%s)" % d)

    # a file that is a RIFF header and nothing else — unrecoverable
    junk = os.path.join(d, "junk.wav")
    with open(junk, "wb") as f:
        f.write(b"RIFF" + (100).to_bytes(4, "little") + b"WAVE" + b"\x00" * 100)

    cases = [("clean", fx["clean"], "ffmpeg"),
             ("malformed-LIST", fx["shortlist"], "salvaged-riff"),
             ("latin-1 metadata", fx["latin1"], "ffmpeg"),
             ("over-declared data size", fx["truncated"], None)]

    print("\n[probe]")
    probe_recs = {}
    for label, path, want_decoder in cases:
        out = os.path.join(d, "probe.%s.json" % label.replace(" ", "_"))
        p = run_core("probe", {"IN": path, "OUT": out, "WORKDIR": d})
        ok = p.returncode == 0 and os.path.exists(out)
        rec = json.load(open(out)) if ok else {}
        probe_recs[label] = rec
        check("probe succeeds on %s" % label, ok,
              (p.stderr.strip().splitlines() or [""])[-1][:90] if not ok else
              "sr=%s ch=%s dur=%s decoder=%s" % (rec.get("samplerate"), rec.get("channels"),
                                                 rec.get("duration_s"), rec.get("decoder")))
        if ok and want_decoder:
            check("  ...via decoder=%s" % want_decoder, rec.get("decoder") == want_decoder,
                  str(rec.get("decoder")))
        if ok:
            check("  ...and no field is null", all(
                rec.get(k) is not None for k in
                ("duration_s", "samplerate", "channels", "codec", "container", "peak_dbfs")))

    out = os.path.join(d, "probe.junk.json")
    p = run_core("probe", {"IN": junk, "OUT": out, "WORKDIR": d})
    check("probe FAILS on a non-audio file (exit nonzero)", p.returncode != 0,
          "rc=%d" % p.returncode)
    check("  ...and writes no sidecar at all", not os.path.exists(out))

    # the metamorphic property, at the level the archive actually cares about: the FACTS
    a, b = probe_recs.get("clean", {}), probe_recs.get("malformed-LIST", {})
    metamorphic_eq("salvaged facts == clean-control facts (sr/ch/duration/peak)", a, b,
                   ("samplerate", "channels", "duration_s", "peak_dbfs"))
    check("salvaged record carries a salvage provenance block", "salvage" in b,
          str(b.get("salvage", {}).get("reason"))[:60])
    check("content hash is of the ORIGINAL bytes, not the salvaged copy",
          a.get("content_sha256") != b.get("content_sha256"))

    print("\n[features]")
    feat = {}
    for label, path, want_decoder in cases:
        out = os.path.join(d, "features.%s.json" % label.replace(" ", "_"))
        p = run_core("features", {"IN": path, "OUT": out, "WORKDIR": d})
        ok = p.returncode == 0 and os.path.exists(out)
        rec = json.load(open(out)) if ok else {}
        feat[label] = rec
        check("features succeeds on %s" % label, ok,
              (p.stderr.strip().splitlines() or [""])[-1][:90] if not ok else
              "centroid=%.0fHz rms=%.1f decoded=%.3fs decoder=%s"
              % (rec.get("spectral_centroid_hz", -1), rec.get("rms_dbfs", 0),
                 rec.get("decoded_duration_s", 0), rec.get("decoder")))
        if ok:
            check("  ...decoded_duration_s > 0 (a real measurement)",
                  (rec.get("decoded_duration_s") or 0) > 0)
            check("  ...centroid is not the zeroed placeholder",
                  (rec.get("spectral_centroid_hz") or 0) > 0)

    out = os.path.join(d, "features.junk.json")
    p = run_core("features", {"IN": junk, "OUT": out, "WORKDIR": d})
    check("features FAILS on a non-audio file (no zeroed record)", p.returncode != 0,
          "rc=%d" % p.returncode)
    check("  ...and writes no sidecar at all", not os.path.exists(out))

    a, b = feat.get("clean", {}), feat.get("malformed-LIST", {})
    metamorphic_eq("salvaged features == clean-control features", a, b,
                   ("spectral_centroid_hz", "rms_dbfs"))

    print("\n[hook]")
    for label, path, want_decoder in cases:
        prep = os.path.join(d, "hook.prep.%s.json" % label.replace(" ", "_"))
        p = run_core("hook", {"IN": path, "PREP": prep, "LEN": "3", "WORKDIR": d})
        ok = p.returncode == 0 and os.path.exists(prep)
        rec = json.load(open(prep)) if ok else {}
        check("hook prep succeeds on %s" % label, ok,
              (p.stderr.strip().splitlines() or [""])[-1][:90] if not ok else
              "start=%ss decoder=%s read_path=%s"
              % (rec.get("start_s"), rec.get("decoder"), os.path.basename(rec.get("read_path", ""))))
        if ok and want_decoder == "salvaged-riff":
            check("  ...hands the RENDERS a salvaged path, not the refused original",
                  rec.get("read_path", "").endswith(D.SALVAGE_SUFFIX))

    prep = os.path.join(d, "hook.prep.junk.json")
    p = run_core("hook", {"IN": junk, "PREP": prep, "LEN": "3", "WORKDIR": d})
    check("hook FAILS on a non-audio file", p.returncode != 0, "rc=%d" % p.returncode)

    # and the renders themselves, on the file that halted the real ingest.
    # Guarded: if hook never produced the prep sidecar, record that as a FAIL and keep going.
    # An unguarded json.load() here raises FileNotFoundError, which kills the process before
    # the summary prints — one missing artifact then hides the verdict of every later check.
    prep_malformed = os.path.join(d, "hook.prep.malformed-LIST.json")
    if not os.path.exists(prep_malformed):
        for nm in ("hook clip renders from the malformed file (the exact step that halted)",
                   "waveform PNG renders from the malformed file"):
            check(nm, False, "no prep sidecar — hook did not get far enough to render")
    else:
        rec = json.load(open(prep_malformed))
        clip = os.path.join(d, "out.hook.wav")
        wave = os.path.join(d, "out.waveform.png")
        r1 = D.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y",
                    "-ss", str(rec["start_s"]), "-t", "3", "-i", rec["read_path"],
                    "-ac", "1", "-ar", "44100", clip])
        r2 = D.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", rec["read_path"],
                    "-filter_complex",
                    "aformat=channel_layouts=mono,showwavespic=s=640x120:colors=#78BEBA",
                    "-frames:v", "1", wave])
        check("hook clip renders from the malformed file (the exact step that halted)",
              r1.returncode == 0 and os.path.getsize(clip) > 44,
              "rc=%d %d bytes" % (r1.returncode, os.path.getsize(clip) if os.path.exists(clip) else 0))
        check("waveform PNG renders from the malformed file",
              r2.returncode == 0 and os.path.getsize(wave) > 100,
              "rc=%d %d bytes" % (r2.returncode, os.path.getsize(wave) if os.path.exists(wave) else 0))

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: %s" % ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
