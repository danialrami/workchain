#!/usr/bin/env python3
"""
workchain_yaml.py — the single YAML parsing / param-resolution / validation
authority for LUFS Workchain.

Used by:
  - the engine (engine/workchain-engine.sh, chain-validator.sh) via `python3 ...`
  - the npm CLI (cli/) via subprocess
  - the MCP server (mcp-server/server.py) via import

Why this exists: the project previously had THREE independent YAML parsers
(bash grep in the engine, hand-rolled JS regex in the CLI, PyYAML in the MCP)
that drifted (e.g. param `range` bounds were dropped only in the CLI). This
module is the one source of truth.

It prefers PyYAML when available and falls back to a dependency-free parser for
the constrained YAML subset the workchain uses, so it works on a bare system
(no `uv sync`, no PyYAML) — which is exactly where agents land first.

CLI:
  workchain_yaml.py parse <file>
  workchain_yaml.py component-schema <root> <component>
  workchain_yaml.py resolve-steps <root> <chain_file>
  workchain_yaml.py engine-plan <root> <chain_file>      # base64 STEP_CONFIG lines for the bash engine (component name, step id, config, params)
  workchain_yaml.py resolve-params <root> <component> <params_json> [globals_json]
  workchain_yaml.py validate <root> <chain_file> [--strict] [--require-commands]
      --strict            also check params against the component schema (types,
                          ranges, unknown keys) and REPORT missing required commands
      --require-commands  additionally FAIL when a declared command is absent from
                          this machine's PATH (an environment fact, not an
                          authoring error — off by default so a static lint stays
                          portable across machines)
  workchain_yaml.py list-chains <root>
"""

import sys
import os
import json
import re
import base64
import shutil

try:
    import yaml as _pyyaml
except Exception:
    _pyyaml = None


# ─────────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────────

_BLOCK_SCALAR = re.compile(r":\s*[|>][+-]?\d*\s*$")
_ANCHOR = re.compile(r":\s*&\S+")
_ALIAS = re.compile(r":\s*\*\S+")
_MERGE_KEY = re.compile(r"^\s*<<\s*:")


def _reject_unsupported(text, where="<yaml>"):
    """Refuse YAML constructs the dependency-free parser cannot read.

    PyYAML understands block scalars, anchors, aliases and merge keys; the stdlib
    fallback does not, and it used to fail *silently* — a folded `description: >` had
    its continuation lines dropped, after which the validator complained that
    `version` was missing when `version` was plainly right there. Anchors were worse:
    the value came back as the literal string "&tgt -21" with no error at all.

    That made the format machine-dependent — the same chain parsed differently
    depending on whether PyYAML happened to be installed — which is precisely the
    divergence one shared parser exists to prevent. So the rule is: **the format is
    what the weakest supported parser can read**, and anything outside it is rejected
    explicitly, on every path, with a message that names the construct and the line.

    Raises ValueError. Never silently repairs anything.
    """
    problems = []
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.split("#", 1)[0] if raw.lstrip().startswith("#") else raw
        if _BLOCK_SCALAR.search(line):
            problems.append(
                "line %d: block scalar (`|` or `>`) is not supported — use a "
                "single-line quoted string" % n)
        elif _ALIAS.search(line):
            problems.append(
                "line %d: YAML alias (`*name`) is not supported — write the value out" % n)
        elif _ANCHOR.search(line):
            problems.append(
                "line %d: YAML anchor (`&name`) is not supported — write the value out" % n)
        if _MERGE_KEY.match(line):
            problems.append(
                "line %d: merge key (`<<:`) is not supported — write the keys out" % n)
    if problems:
        raise ValueError(
            "%s uses YAML this engine deliberately does not support:\n  %s\n"
            "These parse under PyYAML but not under the dependency-free fallback, so "
            "allowing them would make the file mean different things on different "
            "machines. See docs/format.md." % (where, "\n  ".join(problems)))


def load_yaml(text, where="<yaml>"):
    """Parse YAML text → Python object. PyYAML if available, else mini-parser.

    Unsupported constructs are rejected first, identically on both paths, so the
    format does not depend on which parser is installed.
    """
    _reject_unsupported(text, where)
    if _pyyaml is not None:
        return _pyyaml.safe_load(text)
    return _MiniYAML(text).parse()


def load_file(path):
    with open(path, "r") as f:
        return load_yaml(f.read(), where=path)


def _split_flow(s):
    """Split a flow collection body on top-level commas (ignores commas in nested [] {} or quotes)."""
    parts, depth, buf, quote = [], 0, [], None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip() != ""]


def _strip_inline_comment(line):
    """Drop a trailing ` # comment` from a line, honouring quotes.

    Per YAML, a `#` begins a comment only when preceded by whitespace and outside a
    quoted scalar — `name: a#b` is the literal `a#b`, while `name: a # b` is `a`.
    PyYAML has always done this; the fallback did not, so `name: test # note` came
    back with the comment glued onto the value. Same file, two meanings, depending on
    what happened to be installed.
    """
    out, quote, prev = [], None, ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == "#" and (prev == "" or prev.isspace()):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


class _MiniYAML:
    """Dependency-free parser for the workchain's YAML subset:
    nested maps, block lists, lists-of-maps, flow [..] / {..}, scalars with
    type inference, quoted strings, and full-line comments."""

    def __init__(self, text):
        self.lines = []
        for raw in text.replace("\t", "  ").split("\n"):
            line = _strip_inline_comment(raw).rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            self.lines.append((indent, stripped))
        self.i = 0

    def _peek(self):
        return self.lines[self.i] if self.i < len(self.lines) else (None, None)

    def parse(self):
        if not self.lines:
            return None
        return self._parse_block(self.lines[0][0])

    def _parse_block(self, indent):
        ind, content = self._peek()
        if ind is None or ind < indent:
            return None
        if content.startswith("- ") or content == "-":
            return self._parse_list(indent)
        return self._parse_map(indent)

    def _parse_map(self, indent):
        result = {}
        while True:
            ind, content = self._peek()
            if ind is None or ind < indent or ind > indent:
                break
            if content.startswith("- "):
                break
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()
            self.i += 1
            if val == "":
                nind, _nc = self._peek()
                if nind is not None and nind > indent:
                    result[key] = self._parse_block(nind)
                else:
                    result[key] = None
            else:
                result[key] = self._scalar(val)
        return result

    def _parse_list(self, indent):
        result = []
        while True:
            ind, content = self._peek()
            if ind is None or ind != indent or not (content.startswith("- ") or content == "-"):
                break
            item = content[1:].strip() if content != "-" else ""
            self.i += 1
            if item and ":" in item and not item.startswith(('"', "'", "[", "{")):
                # map item; first key is inline, further keys are more-indented lines
                m = {}
                key, _, val = item.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "":
                    nind, _nc = self._peek()
                    if nind is not None and nind > indent:
                        m[key] = self._parse_block(nind)
                    else:
                        m[key] = None
                else:
                    m[key] = self._scalar(val)
                while True:
                    nind, ncontent = self._peek()
                    if nind is None or nind <= indent or ncontent.startswith("- "):
                        break
                    k2, _, v2 = ncontent.partition(":")
                    k2 = k2.strip()
                    v2 = v2.strip()
                    self.i += 1
                    if v2 == "":
                        n2, _n2c = self._peek()
                        if n2 is not None and n2 > nind:
                            m[k2] = self._parse_block(n2)
                        else:
                            m[k2] = None
                    else:
                        m[k2] = self._scalar(v2)
                result.append(m)
            else:
                result.append(self._scalar(item))
        return result

    def _scalar(self, v):
        if v == "":
            return None
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            return [self._scalar(x) for x in _split_flow(inner)] if inner else []
        if v.startswith("{") and v.endswith("}"):
            inner = v[1:-1].strip()
            d = {}
            if inner:
                for pair in _split_flow(inner):
                    k, _, val = pair.partition(":")
                    d[k.strip()] = self._scalar(val.strip())
            return d
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        low = v.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low in ("null", "~"):
            return None
        try:
            if v.lstrip("-+").isdigit():
                return int(v)
        except Exception:
            pass
        try:
            return float(v)
        except Exception:
            pass
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Component schema + parameter resolution
# ─────────────────────────────────────────────────────────────────────────────

def component_schema(root, name):
    path = os.path.join(root, "components", name, "step.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError("Component not found: %s" % name)
    data = load_file(path) or {}
    params = []
    ps = data.get("params_schema") or {}
    if isinstance(ps, dict):
        for pname, pdef in ps.items():
            pdef = pdef or {}
            params.append({
                "name": pname,
                "type": pdef.get("type", "string"),
                "default": pdef.get("default"),
                "description": pdef.get("description", ""),
                "range": pdef.get("range") or {},
            })
    return {
        "name": data.get("name", name),
        "description": data.get("description", ""),
        "version": data.get("version"),
        "type": data.get("type"),
        "input_types": data.get("input_types") or [],
        "output_type": data.get("output_type"),
        "outputs": data.get("outputs") or {},
        "params": params,
        "requirements": data.get("requirements") or {},
        "dependencies": data.get("dependencies") or [],
    }


def resolve_params(root, comp, step_params, chain_globals, include_defaults=True):
    """Resolve effective params with precedence: step params > chain globals > schema default.

    include_defaults=True  → seed schema defaults (use for introspection/validation).
    include_defaults=False → only user intent (params > globals); let the component's own
                             get_param defaults apply at runtime (preserves component-local
                             defaults like audio_benchmark's checks="all")."""
    schema = component_schema(root, comp)
    step_params = step_params or {}
    chain_globals = chain_globals or {}
    known = {p["name"]: p for p in schema["params"]}
    resolved = {}
    # 1) schema defaults (only when requested)
    if include_defaults:
        for p in schema["params"]:
            if p.get("default") is not None:
                resolved[p["name"]] = p["default"]
    # 2) chain globals — only those whose key is a known param name
    for k, v in chain_globals.items():
        if k in known:
            resolved[k] = v
    # 2b) legacy alias: normalization.target_lufs <- globals.lufs_target
    if comp == "normalization" and "lufs_target" in chain_globals and "target_lufs" not in step_params:
        resolved["target_lufs"] = chain_globals["lufs_target"]
    # 3) step params (highest precedence)
    for k, v in step_params.items():
        resolved[k] = v
    return resolved, schema


def _bash_str(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    return str(v)


def build_step_config(resolved):
    """Build the legacy STEP_CONFIG YAML block that components grep with get_param."""
    lines = ["  enabled: true"]
    for k, v in resolved.items():
        if v is None:
            continue
        lines.append("  %s: %s" % (k, _bash_str(v)))
    return "\n".join(lines)


def _check_param(comp, key, value, pdef):
    errs = []
    ptype = pdef.get("type", "string")
    if ptype == "number":
        try:
            num = float(value)
        except Exception:
            errs.append("Step '%s': param '%s' must be a number, got '%s'" % (comp, key, value))
            return errs
        rng = pdef.get("range") or {}
        if "min" in rng and num < float(rng["min"]):
            errs.append("Step '%s': param '%s'=%s below min %s" % (comp, key, value, rng["min"]))
        if "max" in rng and num > float(rng["max"]):
            errs.append("Step '%s': param '%s'=%s above max %s" % (comp, key, value, rng["max"]))
    elif ptype == "boolean":
        if str(value).lower() not in ("true", "false"):
            errs.append("Step '%s': param '%s' must be boolean, got '%s'" % (comp, key, value))
    return errs


# ─────────────────────────────────────────────────────────────────────────────
# Chain validation + resolution
# ─────────────────────────────────────────────────────────────────────────────

def effective_step_id(step, name):
    """The step's record key in context.json's `steps` map: the explicit `id:` when
    present and non-empty, else the step's `name` (the component name).

    `name` stays the component to EXECUTE and to resolve files for; `id` is purely the
    record key. Uniqueness across a chain is enforced by validate_chain (two steps
    resolving to the same id would overwrite each other's record), so this helper only
    resolves the value. For chains written before `id:` existed — and for any chain
    whose id equals its name — the key is byte-identical to today."""
    raw = step.get("id") if isinstance(step, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return name


def validate_chain(root, chain_file, strict=False, require_commands=False):
    """Validate a chain.

    Two kinds of finding, deliberately kept apart:

      errors       — the CHAIN IS WRONG. Unknown param, out-of-range value,
                     missing component, bad YAML. Travels with the file: wrong
                     on every machine, forever, until someone edits the YAML.
                     Fatal.

      environment  — THIS MACHINE lacks something the chain declares (a required
                     command is not on PATH). Says nothing about whether the
                     chain is correct; a CI runner without `audioqr` and a Mac
                     with it disagree about the same unchanged file. Reported,
                     never fatal by default.

    Conflating the two is what made `validate all --strict` fail in CI for
    every component that wraps an external tool — first `audioqr`, then
    `lufs-seed` — while the chains themselves were perfectly valid. Installing
    each tool in CI treats the symptom and does not scale: every future
    component with a domain binary would break the gate for everyone.

    Pass require_commands=True to opt back into the old behaviour and gate on
    tool availability too — the right call immediately before executing a chain
    on the machine that will run it, which is exactly what `run --dry-run` and
    `doctor` are for.

    NOTE this changes nothing about runtime safety. The engine's process_step
    calls lib/workchain_preflight.py before any component executes, and that
    still fails closed on a missing dependency. A step can never run without
    its declared tools; it simply no longer fails a static YAML lint on a
    machine that was never going to run it.
    """
    errors = []
    environment = []
    try:
        data = load_file(chain_file)
    except Exception as e:
        return {"valid": False, "errors": ["Cannot read chain: %s" % e],
                "environment": [], "steps": []}
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["Chain is not a valid YAML mapping"],
                "environment": [], "steps": []}

    for field in ("name", "version", "steps"):
        if field not in data:
            errors.append("Missing required field: %s" % field)

    steps = data.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        errors.append("Chain must have at least one step")
        steps = steps if isinstance(steps, list) else []

    g = data.get("globals") or {}
    resolved_steps = []
    seen_ids = {}  # effective id -> 1-based step number of its first occurrence
    for idx, st in enumerate(steps):
        if not isinstance(st, dict) or "name" not in st:
            errors.append("Step #%d is missing a name" % (idx + 1))
            continue
        name = st["name"]
        raw_id = st.get("id")
        if raw_id is not None and not (isinstance(raw_id, str) and raw_id.strip()):
            errors.append(
                "Step #%d ('%s'): id must be a non-empty string, got %r — omit the "
                "key to default to the step name" % (idx + 1, name, raw_id))
            continue
        # The step's record key in context.json `steps`: explicit id, else the name.
        sid = effective_step_id(st, name)
        cdir = os.path.join(root, "components", name)
        if not os.path.isdir(cdir):
            errors.append("Step '%s' not found in components/" % name)
            continue
        if not os.path.exists(os.path.join(cdir, "step.yaml")):
            errors.append("Step '%s' missing step.yaml" % name)
            continue
        # The `steps` map in context.json is keyed on the effective id, so two steps
        # resolving to the same id would silently OVERWRITE each other's verification
        # record while the run reports success (issue #22) — the lying-success this
        # engine exists to refuse. Fail closed. Disabled steps count too: the ambiguity
        # is in the file, not in whether the step ran.
        if sid in seen_ids:
            errors.append(
                "Step #%d ('%s'): id '%s' duplicates step #%d — context.json keys "
                "`steps` on the step id, so the second record would overwrite the "
                "first's verification. Give one of them a distinct `id:`."
                % (idx + 1, name, sid, seen_ids[sid]))
        else:
            seen_ids[sid] = idx + 1
        if not os.path.exists(os.path.join(cdir, "run.sh")):
            errors.append("Step '%s' missing run.sh" % name)
        try:
            resolved, schema = resolve_params(root, name, st.get("params") or {}, g)
        except Exception as e:
            errors.append("Step '%s': cannot load schema: %s" % (name, e))
            continue
        if strict:
            known = {p["name"]: p for p in schema["params"]}
            for k, v in (st.get("params") or {}).items():
                if k not in known:
                    errors.append("Step '%s': unknown param '%s' (known: %s)"
                                  % (name, k, ", ".join(known.keys()) or "none"))
                else:
                    errors.extend(_check_param(name, k, v, known[k]))
            # Environment fact, not an authoring error — see the docstring.
            for cmd in (schema.get("requirements") or {}).get("commands", []) or []:
                if shutil.which(cmd) is None:
                    msg = "Step '%s': required command not found on PATH: %s" % (name, cmd)
                    if require_commands:
                        errors.append(msg)
                    else:
                        environment.append(msg)
        resolved_steps.append({"name": name, "id": sid,
                              "enabled": st.get("enabled", True), "params": resolved})

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "environment": environment,
        "name": data.get("name"),
        "version": data.get("version"),
        "globals": g,
        "steps": resolved_steps,
    }


def resolve_steps(root, chain_file):
    data = load_file(chain_file) or {}
    g = data.get("globals") or {}
    out = []
    for st in (data.get("steps") or []):
        if not isinstance(st, dict) or "name" not in st:
            continue
        sid = effective_step_id(st, st["name"])
        if st.get("enabled", True) is False:
            out.append({"name": st["name"], "id": sid, "enabled": False, "params": {}})
            continue
        try:
            resolved, _ = resolve_params(root, st["name"], st.get("params") or {}, g, include_defaults=False)
        except Exception:
            resolved = st.get("params") or {}
        out.append({"name": st["name"], "id": sid, "enabled": True, "params": resolved})
    return out


def list_components(root):
    cdir = os.path.join(root, "components")
    out = []
    if not os.path.isdir(cdir):
        return out
    for name in sorted(os.listdir(cdir)):
        d = os.path.join(cdir, name)
        if not os.path.isdir(d) or name.startswith("_"):
            continue
        sy = os.path.join(d, "step.yaml")
        if not os.path.exists(sy):
            continue
        try:
            data = load_file(sy) or {}
            out.append({
                "name": data.get("name", name),
                "description": data.get("description", ""),
                "version": data.get("version", "1.0"),
                "type": data.get("type", "unknown"),
                "param_count": len(data.get("params_schema") or {}),
            })
        except Exception as e:
            out.append({"name": name, "error": str(e)})
    return out


def list_chains(root):
    chains = []
    cdir = os.path.join(root, "chains")
    for base, dirs, files in os.walk(cdir):
        # chains/**/fixtures/ holds deliberately-INVALID repro chains (they exist to
        # FAIL validation — e.g. the issue #22 duplicate-id probe). `validate all` and
        # the chains listing must not treat them as registered chains, or every gate
        # would go red on a file that is doing its job by being invalid.
        dirs[:] = [d for d in dirs if d != "fixtures"]
        for fn in files:
            if not (fn.endswith(".yaml") or fn.endswith(".yml")):
                continue
            path = os.path.join(base, fn)
            rel = os.path.relpath(path, cdir)
            name = rel[:-5] if rel.endswith(".yaml") else rel[:-4]
            try:
                data = load_file(path) or {}
                steps = [s.get("name") for s in (data.get("steps") or []) if isinstance(s, dict)]
                chains.append({
                    "name": name,
                    "description": data.get("description", ""),
                    "version": data.get("version"),
                    "steps": len(steps),
                    "components": steps,
                    "path": path,
                })
            except Exception as e:
                chains.append({"name": name, "error": str(e), "path": path})
    chains.sort(key=lambda c: c["name"])
    return chains


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _out(obj):
    print(json.dumps(obj, indent=2))


def main(argv):
    if not argv:
        _out({"error": "no subcommand"})
        return 2
    cmd = argv[0]
    try:
        if cmd == "parse":
            _out(load_file(argv[1]))
        elif cmd == "component-schema":
            _out(component_schema(argv[1], argv[2]))
        elif cmd == "resolve-steps":
            _out(resolve_steps(argv[1], argv[2]))
        elif cmd == "list-chains":
            _out(list_chains(argv[1]))
        elif cmd == "list-components":
            _out(list_components(argv[1]))
        elif cmd == "resolve-params":
            params = json.loads(argv[3]) if len(argv) > 3 and argv[3] else {}
            gl = json.loads(argv[4]) if len(argv) > 4 and argv[4] else {}
            resolved, _schema = resolve_params(argv[1], argv[2], params, gl)
            _out(resolved)
        elif cmd == "step-config":
            # resolve-params → STEP_CONFIG block (for run-component)
            params = json.loads(argv[3]) if len(argv) > 3 and argv[3] else {}
            gl = json.loads(argv[4]) if len(argv) > 4 and argv[4] else {}
            resolved, _schema = resolve_params(argv[1], argv[2], params, gl, include_defaults=False)
            sys.stdout.write(build_step_config(resolved))
        elif cmd == "engine-plan":
            # one line per step:
            #   "STEP\t<name>\t<b64 step_config>\t<b64 params_json>"  or  "SKIP\t<name>"
            # The 4th field is the resolved params serialized as JSON by THIS resolver
            # (the single source of truth). The engine persists it verbatim into
            # context.json so the verifier sees the exact target the step ran with —
            # it never re-parses the STEP_CONFIG YAML itself (no second param parser).
            # Line format: TAG\t<component name>\t<effective id>\t<b64 config>\t<b64
            # params>. `name` is the component to execute; `id` is the key its record
            # lives under in context.json `steps` (defaults to the name). The engine
            # keys __WC_STEP on `id`.
            for st in resolve_steps(argv[1], argv[2]):
                if not st["enabled"]:
                    sys.stdout.write("SKIP\t%s\t%s\n" % (st["name"], st["id"]))
                    continue
                cfg = build_step_config(st["params"])
                b64 = base64.b64encode(cfg.encode("utf-8")).decode("ascii")
                pj = base64.b64encode(
                    json.dumps(st["params"], sort_keys=True).encode("utf-8")
                ).decode("ascii")
                sys.stdout.write("STEP\t%s\t%s\t%s\t%s\n" % (st["name"], st["id"], b64, pj))
        elif cmd == "validate":
            flags = argv[3:]
            strict = "--strict" in flags
            res = validate_chain(argv[1], argv[2], strict=strict,
                                 require_commands="--require-commands" in flags)
            _out(res)
            return 0 if res["valid"] else 1
        else:
            _out({"error": "unknown subcommand: %s" % cmd})
            return 2
    except Exception as e:
        _out({"error": str(e)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
