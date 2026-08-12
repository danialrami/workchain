#!/usr/bin/env python3
"""
workchain_verify.py — the single verification authority for LUFS Workchain.

Turns "ran (exit 0)" into "proven correct." A component that exits 0 but violates
its declared contract must FAIL here. This is the enforcer half of the project's
prime directive: "works" means proven correct, not merely exited 0.

Reachable from all three interfaces, exactly like lib/workchain_yaml.py:
  - the bash engine: engine/workchain-engine.sh process_step calls this right after
    the component's exit-code check (before the output becomes the next step's input).
  - the npm CLI: cli/commands/run-component.js calls it after a standalone component run.
  - the MCP server / agents: import or subprocess.

It is stdlib + ffmpeg only (no PyYAML, no numpy) so it works on a bare system — the
same light path the engine itself relies on. (One post-condition, `acoustic_roundtrip`,
additionally shells to the `@lufs/audioqr` decoder as its domain ground-truth tool —
exactly as the loudness checks shell to ffmpeg — but ONLY for components that declare
it; the rest of Workchain stays stdlib+ffmpeg.) The contract is DECLARED in each
component's step.yaml under `verify:`; this file only implements the reusable
assertion primitives so authors (human or agent) rarely hand-write verification code.

CLI:
  workchain_verify.py <workchain_root> <component> <context_file> [--json]

Exit codes:
  0  verified  (contract passed)  ·  also 0 for: no contract declared (tier
     "unverified", non-blocking) and a component that honestly recorded status
     "skipped".
  1  contract violated  (honest failure).
  2  usage / internal error.

Tiers (unverified → verified → certified): this file establishes the first two.
"unverified" = ran but no contract proved it. "verified" = passed its declared
contract automatically. "certified" (a trusted author signs the content hash) is a
later layer and is out of scope here.
"""

import sys
import os
import json
import re
import hashlib
import shutil
import subprocess
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workchain_yaml  # the single source-of-truth parser (PyYAML-optional)


# ─────────────────────────────────────────────────────────────────────────────
# Assertion primitives — the reusable vocabulary contracts are written in.
# Each returns (ok: bool, detail: str).
# ─────────────────────────────────────────────────────────────────────────────

def _assert_exists(path, **_):
    return (bool(path) and os.path.exists(path), "path=%s" % path)


def _assert_non_empty(path, **_):
    if not path or not os.path.exists(path):
        return (False, "missing: %s" % path)
    if os.path.isdir(path):
        n = len(os.listdir(path))
        return (n > 0, "%d entr%s" % (n, "y" if n == 1 else "ies"))
    size = os.path.getsize(path)
    return (size > 0, "%d bytes" % size)


def _assert_audio_valid(path, **_):
    """Decodes as audio with a positive duration (ffprobe ground truth)."""
    if not path or not os.path.exists(path):
        return (False, "missing: %s" % path)
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type:format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams") or []
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        dur = float((data.get("format") or {}).get("duration") or 0.0)
        return (has_audio and dur > 0.0, "audio_stream=%s duration=%.3fs" % (has_audio, dur))
    except Exception as e:
        return (False, "ffprobe error: %s" % e)


def _assert_json_valid(path, **_):
    if not path or not os.path.exists(path):
        return (False, "missing: %s" % path)
    try:
        with open(path) as f:
            json.load(f)
        return (True, "valid json")
    except Exception as e:
        return (False, "invalid json: %s" % e)


def _assert_json_has(path, keys=None, **_):
    keys = keys or []
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return (False, "cannot read json: %s" % e)
    if not isinstance(data, dict):
        return (False, "json root is not an object")
    missing = [k for k in keys if k not in data]
    return (not missing, "missing keys: %s" % missing if missing else "has %s" % keys)


STRUCTURAL = {
    "exists": _assert_exists,
    "non_empty": _assert_non_empty,
    "audio_valid": _assert_audio_valid,
    "json_valid": _assert_json_valid,
}


# ─────────────────────────────────────────────────────────────────────────────
# Audio measurement (ground truth) for numeric post-conditions.
# ─────────────────────────────────────────────────────────────────────────────

def measure_integrated_lufs(path, probe_target=-14.0):
    """Integrated loudness (LUFS) of `path`, independently measured via ffmpeg
    loudnorm analysis. Returns float (may be float('-inf') for silence) or None on error.
    The I= probe target does not affect the measured input_i; we just need a value."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-i", path,
             "-af", "loudnorm=I=%s:print_format=json" % probe_target,
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=600,
        )
        blob = proc.stderr or ""
        m = re.search(r'"input_i"\s*:\s*"?(-?[0-9.]+|-?inf)"?', blob)
        if not m:
            return None
        val = m.group(1)
        return float(val)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Target resolution — what value did the component actually aim for?
# Precedence mirrors run.sh: recorded output metadata > chain globals
# (+ normalization's lufs_target alias) > step.yaml schema default.
# ─────────────────────────────────────────────────────────────────────────────

def resolve_target(ctx, comp, step_yaml, param):
    step = (ctx.get("steps") or {}).get(comp) or {}
    outputs = step.get("outputs") or {}
    for _name, meta in outputs.items():
        if isinstance(meta, dict) and param in meta:
            try:
                return float(meta[param]), "recorded:%s" % param
            except Exception:
                pass
    # Resolved params the step actually ran with (persisted by the engine plan for a
    # chain, or by the CLI on the direct run-component path). This is the authoritative
    # target — it already reflects params > globals > alias precedence from the single
    # resolver, so it MUST win over the raw globals/alias/schema fallbacks below.
    params = step.get("params") or {}
    if param in params:
        try:
            return float(params[param]), "step.params.%s" % param
        except Exception:
            pass
    g = ctx.get("globals") or {}
    if param in g:
        try:
            return float(g[param]), "globals.%s" % param
        except Exception:
            pass
    if comp == "normalization" and param == "target_lufs" and "lufs_target" in g:
        try:
            return float(g["lufs_target"]), "globals.lufs_target(alias)"
        except Exception:
            pass
    ps = (step_yaml.get("params_schema") or {}).get(param) or {}
    if ps.get("default") is not None:
        try:
            return float(ps["default"]), "schema_default"
        except Exception:
            pass
    return None, "unresolved"


# ─────────────────────────────────────────────────────────────────────────────
# Post-condition checks (component-level, numeric/relational).
# ─────────────────────────────────────────────────────────────────────────────

def check_audio_lufs_within(pc, ctx, comp, step_yaml, output_paths):
    out_name = pc.get("output", "primary_output")
    path = output_paths.get(out_name)
    tol = float(pc.get("tolerance", 1.0))
    param = pc.get("target_param", "target_lufs")
    target, tsrc = resolve_target(ctx, comp, step_yaml, param)
    measured = {"target": target, "target_source": tsrc, "tolerance": tol}
    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)
    if target is None:
        return (False, "could not resolve target (%s)" % param, measured)
    val = measure_integrated_lufs(path, probe_target=target)
    measured["measured_lufs"] = val
    if val is None:
        return (False, "could not measure LUFS of output", measured)
    delta = abs(val - target)
    measured["delta_lu"] = round(delta, 3) if val not in (float("inf"), float("-inf")) else "inf"
    ok = (val == val) and delta <= tol  # NaN-safe; inf delta fails
    detail = "measured %s LUFS vs target %.1f (±%.1f) → off by %s LU" % (
        ("%.2f" % val) if val not in (float("inf"), float("-inf")) else val,
        target, tol, measured["delta_lu"],
    )
    return (ok, detail, measured)


# ─────────────────────────────────────────────────────────────────────────────
# Metamorphic post-conditions (reusable across creative/probabilistic operators).
#
# Neural-audio operators (separation, denoise, restoration) are the canonical
# "exit 0 but wrong" risk: they always emit plausible audio whether or not it is
# correct. For operations with no single right answer we assert INVARIANTS/RELATIONS
# instead of exact outputs (metamorphic testing). These primitives are ffmpeg-only
# so they run on the light path, every execution, like the rest of this file.
# ─────────────────────────────────────────────────────────────────────────────

def measure_duration(path):
    """Duration in seconds via ffprobe, or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=120,
        )
        return float((json.loads(out.stdout or "{}").get("format") or {}).get("duration") or 0.0)
    except Exception:
        return None


def measure_stream(path):
    """(sample_rate:int|None, channels:int|None) of the first audio stream."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate,channels", "-of", "json", path],
            capture_output=True, text=True, timeout=120,
        )
        s = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
        sr = int(s["sample_rate"]) if s.get("sample_rate") else None
        ch = int(s["channels"]) if s.get("channels") else None
        return sr, ch
    except Exception:
        return None, None


def measure_mean_volume_db(path):
    """RMS-style mean level in dBFS via ffmpeg volumedetect. Silence → float('-inf'); None on error."""
    if not path or not os.path.exists(path):
        return None
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-i", path,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600,
        )
        m = re.search(r"mean_volume:\s*(-?[0-9.]+|-?inf)\s*dB", proc.stderr or "")
        if not m:
            return None
        v = m.group(1)
        return float("-inf") if "inf" in v else float(v)
    except Exception:
        return None


def _resolve_source(ctx, comp, output_paths):
    """The operator's input audio, resolved most-authoritative first:
      1) a `source_input` recorded in any output's metadata,
      2) a `source_input` inside a JSON sidecar output the component wrote,
      3) the chain input at verify time (ctx['input_file']).
    Preferring the component's recorded source over ctx['input_file'] keeps the check
    correct even when re-run post-hoc (the engine advances input_file to the primary
    output only AFTER verification, so a finalized context would otherwise mislead)."""
    step = (ctx.get("steps") or {}).get(comp) or {}
    outs = step.get("outputs") or {}
    for meta in outs.values():
        if isinstance(meta, dict) and meta.get("source_input"):
            return meta["source_input"]
    for meta in outs.values():
        if isinstance(meta, dict) and meta.get("type") == "json":
            p = meta.get("path")
            if p and os.path.exists(p):
                try:
                    with open(p) as f:
                        j = json.load(f)
                    if isinstance(j, dict) and j.get("source_input"):
                        return j["source_input"]
                except Exception:
                    pass
    return ctx.get("input_file")


def _auto_file_outputs(ctx, comp, exclude):
    """All registered file-type outputs for `comp`, minus `exclude` (default the
    `primary_output` pointer, which duplicates one stem's path). Lets a contract say
    `stems: auto` and stay correct for ANY stem count (2 / 4 / 6) without re-listing."""
    outs = ((ctx.get("steps") or {}).get(comp) or {}).get("outputs") or {}
    ex = set(exclude if exclude is not None else ["primary_output"])
    return sorted(n for n, m in outs.items()
                  if isinstance(m, dict) and m.get("type") == "file" and n not in ex)


def _resolve_stem_list(pc, ctx, comp, key):
    """Resolve a post-condition's target output names: an explicit list, a single
    name, or `auto` (→ all file outputs except the primary_output pointer)."""
    v = pc.get(key)
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v != "auto":
        return [v]
    return _auto_file_outputs(ctx, comp, pc.get("exclude"))


def check_audio_duration_matches(pc, ctx, comp, step_yaml, output_paths):
    """Metamorphic invariant: each listed audio output preserves the source duration
    within tolerance. Shared by separation / denoise / restoration / protection."""
    tol = float(pc.get("tolerance_s", pc.get("tolerance", 0.1)))
    names = _resolve_stem_list(pc, ctx, comp, "outputs")
    src = _resolve_source(ctx, comp, output_paths)
    measured = {"tolerance_s": tol, "source": src}
    src_dur = measure_duration(src)
    measured["source_duration"] = src_dur
    if src is None or src_dur is None or src_dur <= 0:
        return (False, "could not measure source duration (%s)" % src, measured)
    per, bad = {}, []
    for n in names:
        d = measure_duration(output_paths.get(n))
        per[n] = d
        if d is None or abs(d - src_dur) > tol:
            bad.append("%s=%s" % (n, "n/a" if d is None else "%.3fs" % d))
    measured["output_durations"] = per
    ok = not bad
    detail = "source=%.3fs; outputs within ±%.2fs → %s" % (
        src_dur, tol, "ok" if ok else "MISMATCH " + ", ".join(bad))
    return (ok, detail, measured)


def _mix_stems_to_wav(stem_paths, sr, ch, out_wav):
    """Sum stems (resampled/reformatted to sr/ch) without amplitude normalization."""
    layout = "mono" if ch == 1 else "stereo"
    inputs = []
    for p in stem_paths:
        inputs += ["-i", p]
    parts = ["[%d:a]aresample=%d,aformat=channel_layouts=%s[a%d]" % (i, sr, layout, i)
             for i in range(len(stem_paths))]
    parts.append("%samix=inputs=%d:normalize=0[mix]" % (
        "".join("[a%d]" % i for i in range(len(stem_paths))), len(stem_paths)))
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-y"] + inputs + \
          ["-filter_complex", ";".join(parts), "-map", "[mix]", out_wav]
    subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def check_stems_recombine(pc, ctx, comp, step_yaml, output_paths):
    """Metamorphic relation for source separation: the stems must DECOMPOSE the input,
    i.e. their sum reconstructs the source. We measure the residual
    (source − Σ stems) and require it to sit at least |max_residual_db| below the
    source level. Catches the classic failure modes a green exit hides — a silent or
    duplicated stem, a mismatched/garbage output, wrong length — without demanding a
    perceptually "correct" split (there is no single right answer)."""
    import tempfile
    import shutil as _sh
    stems = _resolve_stem_list(pc, ctx, comp, "stems")
    max_res = float(pc.get("max_residual_db", -10.0))
    src = _resolve_source(ctx, comp, output_paths)
    measured = {"stems": stems, "max_residual_db": max_res, "source": src}
    paths = [output_paths.get(s) for s in stems]
    if not src or not os.path.exists(src):
        return (False, "source missing: %s" % src, measured)
    if len(paths) < 2 or any(p is None or not os.path.exists(p) for p in paths):
        return (False, "one or more stems missing: %s" % stems, measured)
    sr, ch = measure_stream(src)
    sr, ch = (sr or 44100), (ch or 2)
    src_v = measure_mean_volume_db(src)
    measured["source_mean_db"] = src_v
    if src_v is None:
        return (False, "could not measure source level", measured)
    if src_v == float("-inf"):
        measured["note"] = "silent source"
        return (True, "source is silent; recombination trivially satisfied", measured)
    tmp = tempfile.mkdtemp(prefix="wc-recomb-")
    try:
        recon = os.path.join(tmp, "recon.wav")
        resid = os.path.join(tmp, "residual.wav")
        _mix_stems_to_wav(paths, sr, ch, recon)
        if not os.path.exists(recon):
            return (False, "failed to reconstruct mix from stems", measured)
        layout = "mono" if ch == 1 else "stereo"
        fc = ("[1:a]aresample=%d,aformat=channel_layouts=%s,volume=-1.0[neg];"
              "[0:a][neg]amix=inputs=2:normalize=0[res]" % (sr, layout))
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-i", src, "-i", recon,
             "-filter_complex", fc, "-map", "[res]", resid],
            capture_output=True, text=True, timeout=600,
        )
        res_v = measure_mean_volume_db(resid)
        measured["residual_mean_db"] = res_v
        if res_v is None:
            return (False, "could not measure residual level", measured)
        ratio = res_v - src_v
        measured["residual_ratio_db"] = "-inf" if res_v == float("-inf") else round(ratio, 2)
        ok = (res_v == float("-inf")) or (ratio <= max_res)
        detail = "residual %s dB vs source %.1f dB → %s dB below source (need ≤ %.1f)" % (
            ("-inf" if res_v == float("-inf") else "%.1f" % res_v),
            src_v, measured["residual_ratio_db"], max_res)
        return (ok, detail, measured)
    finally:
        _sh.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Acoustic round-trip (over-the-air audio QR). The enforcer INDEPENDENTLY re-decodes
# the produced waveform and requires it to equal the source text the step was asked to
# encode — it does NOT trust the component's own sidecar. This is the anti-"exit-0-but-
# wrong" gate for acoustic_encode, and the deliberate opposite of a component that
# measures its output but never compares it to the target. Domain ground-truth tool =
# the @lufs/audioqr decoder (resolved via WORKCHAIN_AUDIOQR_BIN or `audioqr` on PATH).
# ─────────────────────────────────────────────────────────────────────────────

def resolve_target_str(ctx, comp, step_yaml, param):
    """The STRING target the step ran with: step.params > globals > schema default.
    Independent of the component's sidecar — we re-derive intent, we don't trust output.
    (String-valued sibling of resolve_target, which coerces to float for numeric checks.)"""
    step = (ctx.get("steps") or {}).get(comp) or {}
    params = step.get("params") or {}
    if param in params and params[param] not in (None, ""):
        return str(params[param]), "step.params.%s" % param
    g = ctx.get("globals") or {}
    if param in g and g[param] not in (None, ""):
        return str(g[param]), "globals.%s" % param
    ps = (step_yaml.get("params_schema") or {}).get(param) or {}
    if ps.get("default") not in (None, ""):
        return str(ps["default"]), "schema_default"
    return None, "unresolved"


def _resolve_audioqr():
    return os.environ.get("WORKCHAIN_AUDIOQR_BIN") or shutil.which("audioqr")


def check_acoustic_roundtrip(pc, ctx, comp, step_yaml, output_paths):
    """Metamorphic/relational: decode(output) must contain the source text. There is no
    single 'right waveform', so we assert the recovery relation, not exact samples."""
    out_name = pc.get("output", "primary_output")
    path = output_paths.get(out_name)
    param = pc.get("target_param", "text")
    target, tsrc = resolve_target_str(ctx, comp, step_yaml, param)
    measured = {"output": out_name, "target": target, "target_source": tsrc}
    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)
    if target is None:
        return (False, "could not resolve source text (param '%s')" % param, measured)
    binpath = _resolve_audioqr()
    measured["decoder"] = binpath
    if not binpath:
        return (False, "audioqr decoder not found (set WORKCHAIN_AUDIOQR_BIN or install @lufs/audioqr)", measured)
    try:
        proc = subprocess.run([binpath, "decode", path, "--json"],
                              capture_output=True, text=True, timeout=120)
        data = json.loads(proc.stdout or "{}")
    except Exception as e:
        return (False, "decode invocation failed: %s" % e, measured)
    decoded = data.get("decoded") or []
    measured["decoded"] = decoded
    ok = target in decoded
    detail = "decoded %s → %s source text %r" % (
        decoded, "matches" if ok else "does NOT match", target)
    return (ok, detail, measured)


# ─────────────────────────────────────────────────────────────────────────────
# Seed provenance. Same stance as acoustic_roundtrip: the enforcer INDEPENDENTLY
# re-runs `lufs-seed verify` against the produced record AND the source recording
# rather than trusting the component's own report. A seed record is a claim about
# where bytes came from, and a component asserting its own provenance is exactly
# the failure this tool was written to end (the January EntropyOrchestrator handed
# back os.urandom while continuing to report hardware).
#
# lufs-seed verify recomputes the seed from the recorded per-source digests,
# re-derives the audio digest from the wav, and checks the ed25519 signature — so
# this single call re-walks the whole chain:
#   recording bytes -> LSB stream -> audio digest -> seed -> signature
# ─────────────────────────────────────────────────────────────────────────────

TIER_ORDER = {"unverified": 0, "verified": 1, "certified": 2}


def _resolve_lufs_seed():
    return os.environ.get("WORKCHAIN_LUFS_SEED_BIN") or shutil.which("lufs-seed")


def check_seed_record_verifies(pc, ctx, comp, step_yaml, output_paths):
    """The seed record must independently verify, and reach the required tier."""
    out_name = pc.get("output", "primary_output")
    path = output_paths.get(out_name)
    require_tier = pc.get("require_tier", "verified")
    measured = {"output": out_name, "require_tier": require_tier}

    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)

    binpath = _resolve_lufs_seed()
    measured["verifier"] = binpath
    if not binpath:
        return (False, "lufs-seed not found (set WORKCHAIN_LUFS_SEED_BIN or install it)",
                measured)

    # The recording we actually minted from. run.sh records it as source_input, which
    # _resolve_source prefers over ctx['input_file'] — important because the engine
    # advances input_file after verification, so a post-hoc re-run must still check
    # the original capture rather than whatever the chain moved on to.
    src = _resolve_source(ctx, comp, output_paths)
    measured["source"] = src

    cmd = [binpath, "verify", path, "--json"]
    if src and os.path.exists(src):
        cmd += ["--audio", src]
    else:
        measured["note"] = ("source recording not available; the full "
                            "recording->seed chain could not be re-walked")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        data = json.loads(proc.stdout or "{}")
    except Exception as e:
        return (False, "lufs-seed verify invocation failed: %s" % e, measured)

    ok = bool(data.get("ok"))
    tier = data.get("tier")
    measured["tier"] = tier
    measured["seed_id"] = data.get("seed_id")
    failed = [c for c in (data.get("checks") or []) if not c.get("ok")]
    measured["failed_checks"] = [c.get("name") for c in failed]

    if not ok:
        return (False, "seed record FAILED verification: %s" % (
            ", ".join("%s (%s)" % (c.get("name"), c.get("detail")) for c in failed)
            or "unknown"), measured)

    have = TIER_ORDER.get(tier, -1)
    need = TIER_ORDER.get(require_tier, 1)
    if have < need:
        return (False, "seed verified but tier '%s' is below the required '%s'"
                % (tier, require_tier), measured)

    n = len(data.get("checks") or [])
    return (True, "seed %s verified independently (%d/%d checks, tier %s)"
            % (data.get("seed_id"), n, n, tier), measured)


def check_embedding_wellformed(pc, ctx, comp, step_yaml, output_paths):
    """The embedding sidecar contains a REAL vector, not merely the right keys.

    The structural asserts prove `vector` and `l2norm` are present. This proves the vector is
    USABLE: declared length, finite, not all zeros, and unit-norm when RECOMPUTED from the
    vector itself. The producer's own `l2norm` field is a CLAIM, not evidence — and on
    a component's `remote` backend the producer is a network service we did not run. A
    component that writes valid-looking JSON full of garbage is exactly the "exited 0 but
    wrong" failure this file exists to refuse, and a bad vector is worse than a missing one
    because it flows silently into a 337 GB index and quietly rots retrieval.

    Params (step.yaml `verify.post_conditions[]`):
      output             output name to inspect (default "embedding")
      expect_dim         required dimensionality (optional). Model-specific, so declaring it
                         IS the point: a swapped embedding space must not pass silently.
      l2_tolerance       max |recomputed_norm - 1.0| (default 0.001)
      require_served_by  if set, the record's `served_by` must equal it — lets a chain ASSERT
                         it got the backend it asked for instead of hoping it did.
    """
    out_name = pc.get("output", "embedding")
    path = output_paths.get(out_name)
    tol = float(pc.get("l2_tolerance", 0.001))
    want_dim = pc.get("expect_dim")
    want_served = pc.get("require_served_by")

    measured = {"output": out_name, "l2_tolerance": tol}
    if want_dim is not None:
        measured["expect_dim"] = int(want_dim)

    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)
    try:
        with open(path) as f:
            rec = json.load(f)
    except Exception as e:
        return (False, "cannot read embedding json: %s" % e, measured)
    if not isinstance(rec, dict):
        return (False, "embedding json root is not an object", measured)

    vec = rec.get("vector")
    dim = rec.get("dim")
    measured.update({
        "declared_dim": dim,
        "claimed_l2norm": rec.get("l2norm"),
        "model": rec.get("model"),
        "served_by": rec.get("served_by"),
        "model_rev": rec.get("model_rev"),
        "device": rec.get("device"),
        "precision": rec.get("precision"),
    })

    if not isinstance(vec, list) or not vec:
        return (False, "no vector in record", measured)
    measured["vector_len"] = len(vec)
    if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
        return (False, "dim is not a positive int: %r" % (dim,), measured)
    if len(vec) != dim:
        return (False, "vector length %d != declared dim %d" % (len(vec), dim), measured)
    if want_dim is not None and dim != int(want_dim):
        return (False, "dim %d != expected %d — that is a DIFFERENT embedding space; if the "
                       "model changed, change the contract deliberately"
                       % (dim, int(want_dim)), measured)
    try:
        vals = [float(z) for z in vec]
    except (TypeError, ValueError):
        return (False, "vector contains non-numeric values", measured)

    inf = float("inf")
    bad = [i for i, z in enumerate(vals) if z != z or z == inf or z == -inf]
    if bad:
        return (False, "vector contains NaN/Inf at %d position(s), first at index %d"
                       % (len(bad), bad[0]), measured)

    ss = sum(z * z for z in vals)
    if ss <= 0.0:
        return (False, "vector is all zeros", measured)
    norm = ss ** 0.5
    measured["recomputed_l2norm"] = round(norm, 9)
    delta = abs(norm - 1.0)
    measured["l2_delta"] = round(delta, 9)
    if delta > tol:
        return (False, "vector is not L2-normed: RECOMPUTED |v|=%.6f (record claims %r, "
                       "tolerance %g)" % (norm, rec.get("l2norm"), tol), measured)

    if want_served and rec.get("served_by") != want_served:
        return (False, "served_by is %r but the contract requires %r — the chain did not get "
                       "the backend it asked for" % (rec.get("served_by"), want_served),
                measured)

    detail = ("dim %d, recomputed |v|=%.6f (within %g), served_by=%s rev=%s device=%s"
              % (dim, norm, tol, rec.get("served_by"), rec.get("model_rev"), rec.get("device")))
    return (True, detail, measured)


# ─────────────────────────────────────────────────────────────────────────────
# json_fields_within — the reusable VALUE contract
#
# Every other check above is a hand-written function answering one audio question. This one
# is DECLARATIVE, because the failure it catches is the most common and the most boring:
# a component that writes the right KEYS with wrong VALUES and exits 0.
#
# `json_has` proved `samplerate` was present. It could not tell you it was null. probe and
# features both shipped for months writing null/zero sidecars that passed their contracts —
# on WAV files ffmpeg had refused outright — because key-presence is not correctness. That
# is the gap this primitive closes, without asking every component author to write Python.
#
#   verify:
#     post_conditions:
#       - id: probe_facts_plausible
#         check: json_fields_within
#         output: probe
#         require:
#           - "duration_s > 0"
#           - "samplerate >= 2000"
#           - "codec is non_empty"
#           - "decoder one_of ffmpeg|salvaged-riff"
#
# Grammar (fail-closed — an unparsable constraint is a FAILURE, never a skip):
#   FIELD <op> NUMBER     ops: > >= < <= == !=   (== and != also compare strings)
#   FIELD is <kind>       kinds: number string bool array object non_empty not_null
#   FIELD one_of A|B|C    membership; pipe-separated so commas stay legal inside values
#   FIELD.SUB ...         dotted paths reach into nested objects
# ─────────────────────────────────────────────────────────────────────────────

_MISSING = object()

_KINDS = {
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "bool": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}

_OPS = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _dig(rec, dotted):
    cur = rec
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _eval_constraint(rec, expr):
    """Return (ok, detail, field, value). Unparsable => not ok. Never raises."""
    text = str(expr).strip()
    if not text:
        return (False, "empty constraint", None, None)
    parts = text.split(None, 2)
    if len(parts) < 3:
        return (False, "cannot parse constraint %r (want 'FIELD OP VALUE')" % text, None, None)
    field, op, rhs = parts[0], parts[1], parts[2].strip()
    val = _dig(rec, field)

    if val is _MISSING:
        return (False, "%s: missing from record" % field, field, None)

    if op == "is":
        kind = rhs
        if kind == "not_null":
            ok = val is not None
            return (ok, "%s: %s" % (field, "not null" if ok else "IS NULL"), field, val)
        if kind == "non_empty":
            if val is None:
                return (False, "%s: IS NULL" % field, field, val)
            if isinstance(val, str):
                ok = bool(val.strip())
            elif isinstance(val, (list, dict, tuple)):
                ok = len(val) > 0
            else:
                ok = True
            return (ok, "%s: %s" % (field, "non-empty" if ok else "EMPTY"), field, val)
        fn = _KINDS.get(kind)
        if fn is None:
            return (False, "unknown kind '%s' in constraint %r" % (kind, text), field, val)
        ok = fn(val)
        return (ok, "%s: %s %s %s" % (field, type(val).__name__, "is" if ok else "IS NOT", kind),
                field, val)

    if op == "one_of":
        allowed = [a.strip() for a in rhs.split("|") if a.strip()]
        if not allowed:
            return (False, "one_of has no alternatives in %r" % text, field, val)
        ok = str(val) in allowed
        return (ok, "%s: %r %sin {%s}" % (field, val, "" if ok else "NOT ", ", ".join(allowed)),
                field, val)

    fn = _OPS.get(op)
    if fn is None:
        return (False, "unknown operator '%s' in constraint %r" % (op, text), field, val)
    if val is None:
        return (False, "%s: IS NULL, cannot compare %s %s" % (field, op, rhs), field, val)
    # Booleans first. A JSON `true` is the most natural thing a contract wants to assert, and
    # without this branch it could not be done: float("true") raises, the fallback compared
    # str(True) == "true" -- 'True' against 'true', a case mismatch that always failed -- and
    # _KINDS["number"] deliberately excludes bool, so the numeric path was closed too. It failed
    # CLOSED, so nothing unsafe shipped, but a contract that cannot express `== true` while
    # reporting `True == 'true'` is a gate that is simply broken and baffling to read.
    if isinstance(val, bool) or rhs.lower() in ("true", "false"):
        if rhs.lower() not in ("true", "false"):
            return (False, "%s: %r is a boolean, cannot compare to %r" % (field, val, rhs), field, val)
        if not isinstance(val, bool):
            return (False, "%s: %r is %s, not a boolean" % (field, val, type(val).__name__), field, val)
        if op not in ("==", "!="):
            return (False, "%s: booleans support only == and !=, not %s" % (field, op), field, val)
        want_b = rhs.lower() == "true"
        ok = (val == want_b) if op == "==" else (val != want_b)
        return (ok, "%s: %s %s %s%s" % (field, str(val).lower(), op, rhs.lower(),
                                        "" if ok else "  <- VIOLATED"), field, val)
    try:
        want = float(rhs)
    except ValueError:
        if op not in ("==", "!="):
            return (False, "%s: rhs %r is not numeric, cannot use %s" % (field, rhs, op), field, val)
        ok = fn(str(val), rhs)
        return (ok, "%s: %r %s %r" % (field, val, op, rhs), field, val)
    if not _KINDS["number"](val):
        return (False, "%s: %r is %s, not a number" % (field, val, type(val).__name__), field, val)
    ok = fn(float(val), want)
    return (ok, "%s: %g %s %s%s" % (field, float(val), op, rhs, "" if ok else "  <- VIOLATED"),
            field, val)


def check_json_fields_within(pc, ctx, comp, step_yaml, output_paths):
    """Assert declared VALUE constraints hold in a JSON output. See the block comment above.

    Params (step.yaml `verify.post_conditions[]`):
      output    output name to inspect (required)
      require   list of constraint strings (required; an empty contract proves nothing)
    """
    out_name = pc.get("output")
    require = pc.get("require") or []
    if isinstance(require, str):
        require = [require]
    measured = {"output": out_name, "constraints": len(require)}

    if not out_name:
        return (False, "post-condition needs an `output` name", measured)
    if not require:
        return (False, "post-condition declares no `require` constraints — "
                       "an empty contract proves nothing", measured)

    path = output_paths.get(out_name)
    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)
    try:
        with open(path) as f:
            rec = json.load(f)
    except Exception as e:
        return (False, "cannot read json: %s" % e, measured)
    if not isinstance(rec, dict):
        return (False, "json root is not an object", measured)

    violations, values = [], {}
    for expr in require:
        ok, detail, field, val = _eval_constraint(rec, expr)
        if field is not None:
            values[field] = val
        if not ok:
            violations.append(detail)
    measured["values"] = values

    if violations:
        return (False, "; ".join(violations), measured)
    return (True, "%d value constraint(s) hold" % len(require), measured)


def measure_bit_depth(path):
    """Bits per sample of the first audio stream, or None.

    `bits_per_raw_sample` is authoritative for PCM but absent for some codecs, so
    fall back to mapping the sample format. Float formats report their storage width
    (32/64), which is what a deliverable spec means by "bit depth".
    """
    if not path or not os.path.exists(path):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bits_per_raw_sample,sample_fmt",
             "-of", "json", path],
            capture_output=True, text=True, timeout=120,
        )
        s = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
        raw = s.get("bits_per_raw_sample")
        if raw and int(raw) > 0:
            return int(raw)
        fmt = (s.get("sample_fmt") or "").rstrip("p")
        return {"u8": 8, "s16": 16, "s32": 32, "flt": 32, "dbl": 64}.get(fmt)
    except Exception:
        return None


def check_audio_format_matches(pc, ctx, comp, step_yaml, output_paths):
    """Independently re-probe an audio output and confirm it conforms to the format the
    step ASKED for — sample rate, channel count, bit depth.

    This exists because "converted successfully" is not the same claim as "is now
    48 kHz / 24-bit / mono". A conversion component can exit 0, write a perfectly valid
    file, and silently preserve the source's rate because a parameter never reached
    ffmpeg. Every structural assert passes and the deliverable is out of spec — which
    the client discovers, not you.

    Each dimension is named by the component parameter carrying it. A dimension whose
    parameter resolves to nothing is NOT asserted: the component was asked to preserve
    it, so there is no claim to check. If no dimension resolves at all the check FAILS
    rather than passing vacuously — an empty contract proves nothing.

    Params (step.yaml `verify.post_conditions[]`):
      output              output name to probe (default 'primary_output')
      sample_rate_param   component param naming the target sample rate
      channels_param      component param naming the target channel count
      bit_depth_param     component param naming the target bit depth
    """
    out_name = pc.get("output", "primary_output")
    path = output_paths.get(out_name)
    param_of = {
        "sample_rate": pc.get("sample_rate_param"),
        "channels": pc.get("channels_param"),
        "bit_depth": pc.get("bit_depth_param"),
    }
    measured = {"output": out_name, "params": {k: v for k, v in param_of.items() if v}}

    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)

    wanted = {}
    for dim, param in param_of.items():
        if not param:
            continue
        val, _src = resolve_target(ctx, comp, step_yaml, param)
        if val is None or str(val).strip() == "":
            continue
        try:
            wanted[dim] = int(float(val))
        except (TypeError, ValueError):
            return (False, "param '%s' is not a number: %r" % (param, val), measured)
    measured["requested"] = wanted

    if not wanted:
        # Two different situations, and conflating them was a bug caught by
        # tools/release-check.sh: a chain that deliberately preserves the source format
        # is not the same as a post-condition that declares nothing to check.
        #
        #   - No param NAMES declared  → the contract itself is empty. Author error, and
        #     an empty contract proves nothing, so fail.
        #   - Names declared but all resolve empty → the step asked to preserve every
        #     dimension. There is no claim to check, and inventing a failure here would
        #     punish the documented default. Pass, and say plainly that nothing was proven.
        if not any(param_of.values()):
            return (False,
                    "post-condition declares no format dimension to check (expected one of "
                    "sample_rate_param / channels_param / bit_depth_param) — an empty "
                    "contract proves nothing, so this fails rather than passing vacuously",
                    measured)
        named = ", ".join(p for p in param_of.values() if p)
        return (True,
                "no conform target requested (%s all unset) — format preserved from the "
                "source, so there is no format claim to verify" % named,
                measured)

    sr, ch = measure_stream(path)
    got = {"sample_rate": sr, "channels": ch, "bit_depth": measure_bit_depth(path)}
    measured["measured"] = got

    bad = []
    for dim, want in sorted(wanted.items()):
        have = got.get(dim)
        if have is None:
            bad.append("%s=unmeasurable" % dim)
        elif have != want:
            bad.append("%s=%s (wanted %s)" % (dim, have, want))

    ok = not bad
    detail = "requested %s; measured %s → %s" % (
        ", ".join("%s=%s" % (k, v) for k, v in sorted(wanted.items())),
        ", ".join("%s=%s" % (k, got.get(k)) for k in sorted(wanted)),
        "ok" if ok else "MISMATCH " + ", ".join(bad),
    )
    return (ok, detail, measured)


def check_content_hash_matches(pc, ctx, comp, step_yaml, output_paths):
    """Re-compute the content hash of the source and confirm it equals the recorded digest.

    Provenance is the one claim in this system that can be checked perfectly, because a
    hash is reproducible by anyone with the bytes. So we do not take the component's word
    for it: read the digest it recorded, hash the source again here, and compare.

    This matters more than it looks. A catalog number derived from a content hash is the
    substrate that release identity — and, later, signing — rests on. A component that
    recorded a digest of the wrong file, or of a truncated read, would produce an identifier
    that looks authoritative and means nothing, and no structural assert could tell.

    Params (step.yaml `verify.post_conditions[]`):
      output          name of the JSON output holding the digest (default 'primary_output')
      digest_field    key in that JSON holding the hex digest (default 'digest')
      algorithm_field key holding the algorithm name (default 'algorithm')
    """
    out_name = pc.get("output", "primary_output")
    digest_field = pc.get("digest_field", "digest")
    algo_field = pc.get("algorithm_field", "algorithm")
    path = output_paths.get(out_name)
    measured = {"output": out_name}

    if not path or not os.path.exists(path):
        return (False, "output '%s' missing" % out_name, measured)
    try:
        with open(path) as f:
            rec = json.load(f)
    except Exception as e:
        return (False, "cannot read json: %s" % e, measured)
    if not isinstance(rec, dict):
        return (False, "json root is not an object", measured)

    recorded = rec.get(digest_field)
    algo = (rec.get(algo_field) or "sha256").lower()
    measured["algorithm"] = algo
    measured["recorded"] = recorded
    if not recorded or not isinstance(recorded, str):
        return (False, "record has no usable '%s' field" % digest_field, measured)

    src = _resolve_source(ctx, comp, output_paths)
    measured["source"] = src
    if not src or not os.path.exists(src):
        return (False, "could not resolve the source file to re-hash (%s)" % src, measured)

    try:
        h = hashlib.new(algo)
    except Exception:
        return (False, "unsupported algorithm '%s'" % algo, measured)
    try:
        n = 0
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
                n += len(chunk)
    except Exception as e:
        return (False, "could not read source to re-hash: %s" % e, measured)

    recomputed = h.hexdigest()
    measured["recomputed"] = recomputed
    measured["bytes_hashed"] = n

    if n == 0:
        return (False, "source is zero bytes — a digest of nothing is not provenance", measured)

    ok = recomputed == recorded.lower()
    detail = ("%s of %d bytes matches the recorded digest (%s…)" % (algo, n, recomputed[:12])
              if ok else
              "%s MISMATCH — recorded %s…, recomputed %s… over %d bytes"
              % (algo, str(recorded)[:12], recomputed[:12], n))
    return (ok, detail, measured)


POST_CHECKS = {
    "json_fields_within": check_json_fields_within,
    "audio_format_matches": check_audio_format_matches,
    "content_hash_matches": check_content_hash_matches,
    "audio_lufs_within": check_audio_lufs_within,
    "audio_duration_matches": check_audio_duration_matches,
    "stems_recombine": check_stems_recombine,
    "acoustic_roundtrip": check_acoustic_roundtrip,
    "seed_record_verifies": check_seed_record_verifies,
    "embedding_wellformed": check_embedding_wellformed,
}


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def verify(root, comp, context_file):
    report = {
        "component": comp,
        "tier": "unverified",
        "verified": True,
        "checks": [],
        "failures": [],
        "measured": {},
        "verified_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(context_file) as f:
        ctx = json.load(f)

    step_yaml_path = os.path.join(root, "components", comp, "step.yaml")
    step_yaml = workchain_yaml.load_file(step_yaml_path) or {}
    contract = step_yaml.get("verify") or {}

    step = (ctx.get("steps") or {}).get(comp) or {}

    # Honest skip: a component that recorded "skipped" wasn't asked to produce a
    # contract-bearing output (e.g. silent input). Respect it; don't fail.
    if step.get("status") == "skipped":
        report["tier"] = "skipped"
        report["note"] = "component reported status=skipped; verification not applicable"
        _persist(ctx, context_file, comp, report)
        return report, True

    # No contract declared → unverified tier (non-blocking). Honest about the gap.
    if not contract:
        report["note"] = "no verify contract declared for this component"
        _persist(ctx, context_file, comp, report)
        return report, True

    outputs_meta = step.get("outputs") or {}
    output_paths = {n: (m.get("path") if isinstance(m, dict) else None)
                    for n, m in outputs_meta.items()}

    # 1) Per-output structural asserts
    for od in (contract.get("outputs") or []):
        oname = od.get("name")
        path = output_paths.get(oname)
        for a in (od.get("assert") or []):
            fn = STRUCTURAL.get(a)
            if fn is None:
                _record(report, "%s.%s" % (oname, a), False, "unknown assert primitive '%s'" % a)
                continue
            ok, detail = fn(path)
            _record(report, "%s.%s" % (oname, a), ok, detail)
        if od.get("json_has"):
            ok, detail = _assert_json_has(path, keys=od["json_has"])
            _record(report, "%s.json_has" % oname, ok, detail)

    # 2) Component-level post-conditions
    for pc in (contract.get("post_conditions") or []):
        cid = pc.get("id") or pc.get("check") or "post_condition"
        kind = pc.get("check")
        fn = POST_CHECKS.get(kind)
        if fn is None:
            _record(report, cid, False, "unknown post-condition check '%s'" % kind)
            continue
        ok, detail, measured = fn(pc, ctx, comp, step_yaml, output_paths)
        report["measured"][cid] = measured
        _record(report, cid, ok, detail)

    report["verified"] = len(report["failures"]) == 0
    report["tier"] = "verified" if report["verified"] else "unverified"
    _persist(ctx, context_file, comp, report)
    return report, report["verified"]


def _record(report, name, ok, detail):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        report["failures"].append({"name": name, "detail": detail})


def _persist(ctx, context_file, comp, report):
    ctx.setdefault("steps", {}).setdefault(comp, {})
    ctx["steps"][comp]["verification"] = report
    if not report["verified"] and report["tier"] != "skipped":
        ctx["steps"][comp]["status"] = "failed"
        ctx["steps"][comp]["verification_failed"] = True
    with open(context_file, "w") as f:
        json.dump(ctx, f, indent=2)


def main(argv):
    want_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if len(argv) < 3:
        sys.stderr.write("Usage: workchain_verify.py <workchain_root> <component> <context_file> [--json]\n")
        return 2
    root, comp, context_file = argv[0], argv[1], argv[2]
    try:
        report, ok = verify(root, comp, context_file)
    except Exception as e:
        sys.stderr.write("verify error (%s): %s\n" % (comp, e))
        return 2

    if want_json:
        print(json.dumps(report, indent=2))

    if report["tier"] == "skipped":
        sys.stderr.write("• %s — verification skipped (component status=skipped)\n" % comp)
    elif report["tier"] == "unverified" and not report.get("failures"):
        sys.stderr.write("• %s — unverified (no contract declared)\n" % comp)
    elif ok:
        n = len(report["checks"])
        sys.stderr.write("✓ %s — verified (%d/%d checks passed)\n" % (comp, n, n))
    else:
        nf = len(report["failures"])
        nt = len(report["checks"])
        sys.stderr.write("✗ %s — verification FAILED (%d of %d checks)\n" % (comp, nf, nt))
        for fail in report["failures"]:
            sys.stderr.write("    %s: %s\n" % (fail["name"], fail["detail"]))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
