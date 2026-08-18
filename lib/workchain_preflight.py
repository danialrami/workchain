#!/usr/bin/env python3
"""
workchain_preflight.py — the single INBOUND dependency authority for LUFS Workchain.

The symmetric bookend to lib/workchain_verify.py. Where the verifier proves a component's
OUTPUTS are correct ("verified out"), this proves its INPUTS/dependencies are present and
correct ("verified in") BEFORE run.sh executes — so a component is a verified transform:

    requirements (verified IN)  →  run.sh  →  verify (verified OUT)

Reachable from all three interfaces exactly like the parser and the verifier:
  - the bash engine: engine/workchain-engine.sh process_step calls this before sourcing run.sh.
  - the npm CLI: cli/commands/run-component.js calls it before executing a standalone component.
  - the MCP server / agents / `doctor`: import or subprocess.

Stdlib only (no PyYAML, no numpy) so it runs on the same light path as the engine. The contract
is DECLARED in each component's step.yaml under `requirements:`; this file implements the reusable
dependency-class checks so authors rarely hand-write dependency logic (the way stem_separation
currently must).

Dependency classes (all optional; a component declares only what it needs):

    requirements:
      commands: [ffmpeg, ffprobe]              # PATH binaries (shutil.which)
      python:                                  # a component-local venv
        venv: ".venv"                          # relative to the component dir
        python_version: ">=3.10"               # optional floor (major.minor)
        packages:                              # verified by IMPORT in that venv
          - { import: "audio_separator", dist: "audio-separator", version: ">=0.44" }
          - "soundfile"                        # shorthand: import name only
        provision: "provision.sh"              # optional recipe hint (shown on failure)
          # Any group may carry a `when:` guard; the group is required only when it matches.
          # Guards FAIL CLOSED — an unresolvable param still requires the group.
        when: { backend: [local, auto] }        # guard: only required for these param values
      node:                                    # node packages (require.resolve)
        packages: [ { require: "jdenticon", version: "^3" }, "some-pkg" ]
      models:                                  # heavy artifacts
        - { name: "m", path: "models/x.ckpt", bytes: 670000000, sha256: "…", optional: false, always_hash: false }
      env: [ ARTYSHIELD_API_KEY ]              # required env vars — presence only, never value

Cost policy: preflight runs EVERY execution, so it stays cheap — commands (which), python/node
(import/resolve), env (presence), and models (exists + size). Full model sha256 is EXPENSIVE and
runs only when asked: pass --deep, or mark a model `always_hash: true`. (Certify/`doctor --deep`
is where deep hashing belongs — mirrors "cheap relations every run; expensive at certify time".)

CLI:
  workchain_preflight.py <workchain_root> <component> [context_file] [step_id] [--json] [--deep]
      step_id  option: the step's effective id — the key the record lives
               under in context.json `steps` (defaults to the component name;
               also readable from the __WC_STEP env var the engine exports)

Exit codes:
  0  satisfied  (all declared requirements met; also 0 when nothing is declared).
  1  unmet      (a declared requirement is missing — honest failure).
  2  usage / internal error.
"""

import sys
import os
import json
import re
import shutil
import subprocess
import hashlib
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workchain_yaml  # the single source-of-truth parser (PyYAML-optional)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ver_tuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def _cmp_floor(actual, spec):
    """True if `actual` satisfies a `>=X.Y` / `^X` / bare `X.Y` floor `spec` (best-effort)."""
    if not spec:
        return True
    nums = re.findall(r"\d+", spec)
    if not nums:
        return True
    want = tuple(int(x) for x in nums[:3])
    got = _ver_tuple(actual)
    got = got + (0,) * (len(want) - len(got))
    want = want + (0,) * (len(got) - len(want))
    if spec.strip().startswith("^"):  # caret: same major, >= minor.patch
        return got[0] == want[0] and got >= want
    return got >= want  # treat >=, bare, ~ as a floor


def _norm_pkg(p, key):
    """Normalize a package entry (string shorthand or dict) to a dict with `key`/version/dist."""
    if isinstance(p, str):
        return {key: p}
    return p or {}


def resolve_effective_step_key(comp, step_id=None):
    """The key this step's record lives under in context.json `steps`: the effective
    step id (passed by the engine as argv[3] / __WC_STEP), else the component name.

    Never mixes the two: the engine WROTE the record under the id (record_step_params /
    register_output), so reading it back through a component-name fallback would
    resurrect exactly the silent overwrite per-step identity exists to prevent."""
    if step_id not in (None, ""):
        return step_id
    env_id = os.environ.get("__WC_STEP")
    if env_id not in (None, ""):
        return env_id
    return comp


def _resolve_params(step_yaml, ctx, step_key):
    """Resolved step params, for `when:` guard evaluation.

    Precedence: recorded step params > chain globals > step.yaml `params_schema` defaults.
    Deliberately the same precedence lib/workchain_verify.py's resolve_target uses, so a
    dependency guard and a post-condition can never disagree about what a param is.
    `step_key` is the effective step id the record was written under (defaults to the
    component name).
    """
    params = {}
    for name, spec in (step_yaml.get("params_schema") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            params[name] = spec["default"]
    if isinstance(ctx, dict):
        for k, v in (ctx.get("globals") or {}).items():
            if v is not None and v != "":
                params[k] = v
        step = ((ctx.get("steps") or {}).get(step_key) or {})
        for k, v in ((step.get("params") or {})).items():
            if v is not None and v != "":
                params[k] = v
    return params


def _when_satisfied(when, params):
    """Evaluate a requirement group's optional `when:` guard.

        requirements:
          python:
            when: { backend: [local, auto] }   # group applies only for those values

    FAILS CLOSED. If a guarded param cannot be resolved, the group is treated as APPLICABLE
    — i.e. still required. An ambiguous config must never be able to quietly WEAKEN a
    dependency contract; the acceptable worst case is "you were asked for a dependency you
    did not need", never "we skipped the check and assumed you were fine".
    """
    if not when or not isinstance(when, dict):
        return True
    for key, expected in when.items():
        actual = params.get(key)
        if actual is None or actual == "":
            return True  # unresolvable -> require the group (fail closed)
        accepted = expected if isinstance(expected, (list, tuple)) else [expected]
        if str(actual) not in [str(e) for e in accepted]:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Dependency-class checks — each appends (name, ok, detail) via _rec.
# ─────────────────────────────────────────────────────────────────────────────

def check_commands(rep, comp_dir, req, deep, params):
    for cmd in (req.get("commands") or []):
        ok = shutil.which(cmd) is not None
        _rec(rep, "command:%s" % cmd, ok,
             "on PATH" if ok else "NOT on PATH — install it, then re-run")


def check_python(rep, comp_dir, req, deep, params):
    py = req.get("python")
    if not py:
        return

    if not _when_satisfied(py.get("when"), params):
        # Recorded as a PASSING check rather than silently omitted: a skipped
        # requirement must still be visible in the report.
        _rec(rep, "python:venv", True,
             "not required here (when: %r not satisfied by resolved params)" % (py.get("when"),))
        return

    venv = py.get("venv") or ".venv"
    venv_dir = venv if os.path.isabs(venv) else os.path.join(comp_dir, venv)
    py_bin = os.path.join(venv_dir, "bin", "python")
    if not os.path.exists(py_bin):
        py_bin = os.path.join(venv_dir, "bin", "python3")
    prov = py.get("provision")
    hint = (" — provision: %s" % prov) if prov else ""
    if not os.path.exists(py_bin):
        _rec(rep, "python:venv", False, "venv python not found at %s%s" % (venv_dir, hint))
        return
    _rec(rep, "python:venv", True, "venv python at %s" % py_bin)

    want_py = py.get("python_version")
    if want_py:
        try:
            out = subprocess.run([py_bin, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                                  capture_output=True, text=True, timeout=30)
            actual = (out.stdout or "").strip()
            ok = _cmp_floor(actual, want_py)
            _rec(rep, "python:version", ok, "venv %s vs required %s" % (actual or "?", want_py))
        except Exception as e:
            _rec(rep, "python:version", False, "could not read venv python version: %s" % e)

    for raw in (py.get("packages") or []):
        pk = _norm_pkg(raw, "import")
        mod = pk.get("import") or pk.get("name")
        if not mod:
            continue
        want = pk.get("version")
        # Import the module in the venv; read its version via importlib.metadata if a dist is known.
        dist = pk.get("dist") or mod.replace("_", "-")
        code = (
            "import importlib,sys\n"
            "m=importlib.import_module(%r)\n"
            "v=''\n"
            "try:\n"
            "    import importlib.metadata as md; v=md.version(%r)\n"
            "except Exception:\n"
            "    v=getattr(m,'__version__','')\n"
            "print(v)\n" % (mod, dist)
        )
        try:
            out = subprocess.run([py_bin, "-c", code], capture_output=True, text=True, timeout=120)
            if out.returncode != 0:
                _rec(rep, "python:pkg:%s" % mod, False,
                     "import failed in venv%s" % hint)
                continue
            ver = (out.stdout or "").strip()
            if want and ver and not _cmp_floor(ver, want):
                _rec(rep, "python:pkg:%s" % mod, False,
                     "%s==%s does not satisfy %s" % (dist, ver, want))
            else:
                _rec(rep, "python:pkg:%s" % mod, True,
                     "import ok%s" % (" (%s %s)" % (dist, ver) if ver else ""))
        except Exception as e:
            _rec(rep, "python:pkg:%s" % mod, False, "import check error: %s" % e)


def check_node(rep, comp_dir, req, deep, params):
    node = req.get("node")
    if not node:
        return

    if not _when_satisfied(node.get("when"), params):
        _rec(rep, "node:runtime", True,
             "not required here (when: %r not satisfied by resolved params)" % (node.get("when"),))
        return

    node_bin = shutil.which("node")
    if not node_bin:
        _rec(rep, "node:runtime", False, "node not on PATH (required for node packages)")
        return
    for raw in (node.get("packages") or []):
        pk = _norm_pkg(raw, "require")
        name = pk.get("require") or pk.get("name")
        if not name:
            continue
        try:
            out = subprocess.run([node_bin, "-e", "require.resolve(%r)" % name],
                                 capture_output=True, text=True, timeout=30, cwd=comp_dir)
            ok = out.returncode == 0
            _rec(rep, "node:pkg:%s" % name, ok,
                 "resolvable" if ok else "not resolvable (npm i %s)" % name)
        except Exception as e:
            _rec(rep, "node:pkg:%s" % name, False, "resolve error: %s" % e)


def check_models(rep, comp_dir, req, deep, params):
    models_base = os.environ.get("WORKCHAIN_AUDIO_SEPARATOR_MODELS")
    for m in (req.get("models") or []):
        if not _when_satisfied(m.get("when"), params):
            continue
        name = m.get("name") or m.get("path") or "model"
        path = m.get("path") or ""
        if not os.path.isabs(path):
            path = os.path.join(models_base, os.path.basename(path)) if models_base else os.path.join(comp_dir, path)
        optional = bool(m.get("optional"))
        prov = m.get("provision")
        hint = (" — provision: %s" % prov) if prov else ""
        if not os.path.exists(path):
            if optional:
                _rec(rep, "model:%s" % name, True, "absent but optional (auto-provisioned on use)")
            else:
                _rec(rep, "model:%s" % name, False, "missing: %s%s" % (path, hint))
            continue
        size = os.path.getsize(path)
        want_bytes = m.get("bytes")
        if want_bytes and abs(size - int(want_bytes)) > max(1024, int(want_bytes) * 0.02):
            _rec(rep, "model:%s" % name, False,
                 "size %d bytes != expected ~%s" % (size, want_bytes))
            continue
        want_sha = m.get("sha256")
        if want_sha and (deep or m.get("always_hash")):
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            got = h.hexdigest()
            ok = got == want_sha
            _rec(rep, "model:%s" % name, ok,
                 "sha256 match" if ok else "sha256 MISMATCH (got %s…)" % got[:12])
        else:
            note = "exists, %d bytes" % size
            if want_sha:
                note += " (sha256 deferred — run with --deep to verify)"
            _rec(rep, "model:%s" % name, True, note)


def check_env(rep, comp_dir, req, deep, params):
    for var in (req.get("env") or []):
        ok = bool(os.environ.get(var))
        _rec(rep, "env:%s" % var, ok, "set" if ok else "NOT set — export %s" % var)


CHECKS = [check_commands, check_python, check_node, check_models, check_env]


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def _rec(rep, name, ok, detail):
    rep["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        rep["failures"].append({"name": name, "detail": detail})


def preflight(root, comp, deep=False, context_file=None, step_id=None):
    step_key = resolve_effective_step_key(comp, step_id)
    rep = {
        "component": comp,
        "satisfied": True,
        "checks": [],
        "failures": [],
        "checked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    comp_dir = os.path.join(root, "components", comp)
    step_yaml_path = os.path.join(comp_dir, "step.yaml")
    step_yaml = workchain_yaml.load_file(step_yaml_path) or {}
    req = step_yaml.get("requirements") or {}
    if not req:
        rep["note"] = "no requirements declared"
        return rep
    # Resolve step params so requirement groups can carry a `when:` guard (fail-closed).
    ctx = None
    if context_file and os.path.exists(context_file):
        try:
            with open(context_file) as f:
                ctx = json.load(f)
        except Exception:
            ctx = None
    params = _resolve_params(step_yaml, ctx, step_key)
    rep["resolved_params"] = params
    for fn in CHECKS:
        try:
            fn(rep, comp_dir, req, deep, params)
        except Exception as e:
            _rec(rep, fn.__name__, False, "check error: %s" % e)
    rep["satisfied"] = len(rep["failures"]) == 0
    return rep


def _persist(context_file, step_key, rep):
    if not context_file or not os.path.exists(context_file):
        return
    try:
        with open(context_file) as f:
            ctx = json.load(f)
    except Exception:
        return
    ctx.setdefault("steps", {}).setdefault(step_key, {})
    ctx["steps"][step_key]["preflight"] = rep
    if not rep["satisfied"]:
        ctx["steps"][step_key]["status"] = "failed"
        ctx["steps"][step_key]["preflight_failed"] = True
        ctx["steps"][step_key].setdefault("reason", "missing_dependency")
    with open(context_file, "w") as f:
        json.dump(ctx, f, indent=2)


def main(argv):
    deep = "--deep" in argv
    want_json = "--json" in argv
    argv = [a for a in argv if a not in ("--deep", "--json")]
    if len(argv) < 2:
        sys.stderr.write("Usage: workchain_preflight.py <root> <component> [context_file] [--json] [--deep]\n")
        return 2
    root, comp = argv[0], argv[1]
    context_file = argv[2] if len(argv) > 2 and argv[2] not in ("", "-") else None
    # Optional 4th positional: the step's effective id (the engine passes it; the CLI
    # run-component path does not, so a standalone run keys by the component name).
    step_id = argv[3] if len(argv) > 3 and argv[3] not in ("", "-") else None
    try:
        rep = preflight(root, comp, deep=deep, context_file=context_file, step_id=step_id)
    except Exception as e:
        sys.stderr.write("preflight error (%s): %s\n" % (comp, e))
        return 2

    _persist(context_file, resolve_effective_step_key(comp, step_id), rep)

    if want_json:
        print(json.dumps(rep, indent=2))

    if rep.get("note") == "no requirements declared":
        sys.stderr.write("• %s — no dependency contract declared\n" % comp)
        return 0
    if rep["satisfied"]:
        n = len(rep["checks"])
        sys.stderr.write("✓ %s — dependencies satisfied (%d/%d checks)\n" % (comp, n, n))
        return 0
    nf, nt = len(rep["failures"]), len(rep["checks"])
    sys.stderr.write("✗ %s — dependency preflight FAILED (%d of %d checks)\n" % (comp, nf, nt))
    for fail in rep["failures"]:
        sys.stderr.write("    %s: %s\n" % (fail["name"], fail["detail"]))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
