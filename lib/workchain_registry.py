#!/usr/bin/env python3
"""
workchain_registry.py — the component registry: a generated index over components/,
each entry carrying a stable content-definition hash, plus `doctor` (preflight-all).

The filesystem under components/ IS the registry (folder-per-component + a step.yaml
manifest). This turns that into a first-class, GENERATED index so agents, the CLI, and
(later) a host can see every puzzle piece at a glance — with its tier, its inbound/outbound
contract status, and its **definition hash**. Generated, never hand-written (a `check` mode
proves it's current), exactly like any generated catalog.

Stdlib only, so it runs on the light path like the parser/verifier/preflight.

Definition hash — the "recipe, not the ingredients":
  SHA-256 over the component folder's source files, sorted by relative path, EXCLUDING
  provisioned/ignored artifacts (.venv/, models/, __pycache__/, *.pyc, .DS_Store, output_*).
  Deterministic and git-independent (so a `check` in CI reproduces it without git surprises),
  and stable across dependency/package updates because the heavy "ingredients" are excluded.
  This is the component's identity/health key and the certified-tier signing target.

Tier: `heavy` if the component declares a `python` or `models` requirement, else `light`.

CLI:
  workchain_registry.py generate <root> [--out <path>]   # write components/index.json
  workchain_registry.py check <root>                      # exit 1 if index.json is missing/stale
  workchain_registry.py doctor <root> [--json] [--deep]   # run preflight for every component
"""

import sys
import os
import json
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workchain_yaml
import workchain_preflight

SCHEMA_VERSION = "1.0"
INDEX_REL = os.path.join("components", "index.json")

_EXCLUDE_DIRS = {".venv", "models", "__pycache__", ".git", "node_modules"}
_EXCLUDE_SUFFIX = (".pyc", ".pyo")
_EXCLUDE_NAMES = {".DS_Store"}


def _iter_source_files(comp_dir):
    """Yield component source files (the 'recipe') as (relpath, abspath), excluding
    provisioned/ignored artifacts. Deterministic + git-independent."""
    for base, dirs, files in os.walk(comp_dir):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDE_DIRS and not d.startswith("output_"))
        for fn in sorted(files):
            if fn in _EXCLUDE_NAMES or fn.endswith(_EXCLUDE_SUFFIX):
                continue
            ap = os.path.join(base, fn)
            rel = os.path.relpath(ap, comp_dir)
            yield rel, ap


def definition_hash(comp_dir):
    """SHA-256 over sorted 'relpath\\0<file-sha256>\\n' — the component-definition hash."""
    entries = []
    for rel, ap in _iter_source_files(comp_dir):
        h = hashlib.sha256()
        with open(ap, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        entries.append("%s\0%s" % (rel.replace(os.sep, "/"), h.hexdigest()))
    entries.sort()
    return "sha256:" + hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def _component_names(root):
    cdir = os.path.join(root, "components")
    if not os.path.isdir(cdir):
        return []
    out = []
    for name in sorted(os.listdir(cdir)):
        d = os.path.join(cdir, name)
        if not os.path.isdir(d) or name.startswith("_") or name.startswith("."):
            continue
        if os.path.exists(os.path.join(d, "step.yaml")):
            out.append(name)
    return out


def _entry(root, name):
    comp_dir = os.path.join(root, "components", name)
    sy = workchain_yaml.load_file(os.path.join(comp_dir, "step.yaml")) or {}
    req = sy.get("requirements") or {}
    req_classes = [k for k in ("commands", "python", "node", "models", "env") if req.get(k)]
    tier = "heavy" if (req.get("python") or req.get("models")) else "light"
    verify = sy.get("verify") or {}
    post = [pc.get("id") or pc.get("check") for pc in (verify.get("post_conditions") or [])]
    return {
        "name": sy.get("name", name),
        "dir": "components/%s" % name,
        "description": sy.get("description", ""),
        "version": sy.get("version"),
        "type": sy.get("type"),
        "tier": tier,
        "params": [p for p in (sy.get("params_schema") or {}).keys()],
        "requirements": req_classes,
        "verify": {
            "has_contract": bool(verify),
            "asserts": [o.get("name") for o in (verify.get("outputs") or [])],
            "post_conditions": post,
        },
        "definition_hash": definition_hash(comp_dir),
    }


def build_index(root):
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "lib/workchain_registry.py",
        "note": "GENERATED — do not hand-edit. Run `workchain_registry.py generate` (or CI) to refresh.",
        "components": [_entry(root, n) for n in _component_names(root)],
    }


def _canonical(obj):
    return json.dumps(obj, indent=2, sort_keys=True)


def cmd_generate(root, out_path):
    idx = build_index(root)
    with open(out_path, "w") as f:
        f.write(_canonical(idx) + "\n")
    sys.stderr.write("✓ wrote %s (%d components)\n" % (out_path, len(idx["components"])))
    return 0


def cmd_check(root):
    out_path = os.path.join(root, INDEX_REL)
    fresh = _canonical(build_index(root))
    if not os.path.exists(out_path):
        sys.stderr.write("✗ %s missing — run `workchain_registry.py generate`\n" % INDEX_REL)
        return 1
    with open(out_path) as f:
        current = f.read().strip()
    if current != fresh.strip():
        sys.stderr.write("✗ %s is stale — regenerate it\n" % INDEX_REL)
        return 1
    sys.stderr.write("✓ %s is current\n" % INDEX_REL)
    return 0


def cmd_doctor(root, want_json, deep):
    names = _component_names(root)
    results = []
    n_ok = n_missing = n_nodep = 0
    for name in names:
        rep = workchain_preflight.preflight(root, name, deep=deep)
        if rep.get("note") == "no requirements declared":
            state = "no-deps"; n_nodep += 1
        elif rep["satisfied"]:
            state = "ok"; n_ok += 1
        else:
            state = "missing"; n_missing += 1
        results.append({"component": name, "state": state,
                        "failures": [f["name"] for f in rep.get("failures", [])]})
    summary = {"total": len(names), "ok": n_ok, "missing_deps": n_missing, "no_deps": n_nodep}
    if want_json:
        print(json.dumps({"summary": summary, "components": results}, indent=2))
    else:
        for r in results:
            mark = {"ok": "✓", "missing": "✗", "no-deps": "•"}[r["state"]]
            extra = ("  missing: " + ", ".join(r["failures"])) if r["failures"] else ""
            sys.stderr.write("  %s %-22s %s%s\n" % (mark, r["component"], r["state"], extra))
        sys.stderr.write("doctor: %d ok, %d missing deps, %d no-deps (of %d)\n"
                         % (n_ok, n_missing, n_nodep, len(names)))
    return 0  # doctor is a report; per-component gating uses `workchain_preflight.py <comp>`.


def main(argv):
    if not argv:
        sys.stderr.write("Usage: workchain_registry.py <generate|check|doctor> <root> [opts]\n")
        return 2
    cmd = argv[0]
    rest = [a for a in argv[1:] if not a.startswith("--")]
    flags = [a for a in argv[1:] if a.startswith("--")]
    root = rest[0] if rest else "."
    try:
        if cmd == "generate":
            out = os.path.join(root, INDEX_REL)
            if "--out" in argv:
                out = argv[argv.index("--out") + 1]
            return cmd_generate(root, out)
        if cmd == "check":
            return cmd_check(root)
        if cmd == "doctor":
            return cmd_doctor(root, "--json" in flags, "--deep" in flags)
        sys.stderr.write("unknown subcommand: %s\n" % cmd)
        return 2
    except Exception as e:
        sys.stderr.write("registry error: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
