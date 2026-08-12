#!/usr/bin/env python3
"""
workchain_runlog.py — per-run log files with bounded retention.

ONE implementation, reachable from all three interfaces exactly like the parser, the
verifier, and the preflight: the bash engine calls it once per run, the CLI can call it.
A second copy of retention logic in a second repo is how two log directories quietly grow different rules.

WHAT IT IS FOR: "what happened to which file, when." An engine run streams its log_* lines
into one file per run; `open` creates that file and prunes the directory to the newest N
(default 25) so the log dir cannot grow without bound and nobody has to remember to clean it.

WHY APPENDING IS NOT DONE HERE: this module creates and prunes; it does NOT write log lines.
Appending happens in bash with a bare `printf >>` (see lib/common-utils.sh). An ingest of
259k files emits millions of lines, and a Python subprocess per line would cost
more than the work being logged.

PRUNING IS DELIBERATELY PARANOID. It is the only destructive thing in this repo, it is
driven by an environment variable, and a mis-set WORKCHAIN_RUNLOG_DIR pointing at a real
directory must never be able to delete a user's files. So it:
  · never recurses (os.listdir, not os.walk);
  · only considers regular files, never symlinks or directories;
  · only unlinks names matching a STRICT pattern this module itself generates;
  · never unlinks the run that was just opened.
Anything it does not recognise, it leaves alone. A stray file in the log dir survives
forever, which is the correct failure direction.

CLI:
  workchain_runlog.py open  [--label L] [--dir D] [--keep N] [--json]   # -> path on stdout
  workchain_runlog.py list  [--dir D] [--json]
  workchain_runlog.py prune [--dir D] [--keep N] [--json]
  workchain_runlog.py tail  [--dir D] [-n LINES]                        # newest run
  workchain_runlog.py path  [--dir D]                                   # newest run's path

Env:
  WORKCHAIN_RUNLOG_DIR   default ~/.workchain/runs
  WORKCHAIN_RUNLOG_KEEP  default 25

Exit codes: 0 ok · 1 nothing found (tail/path) · 2 usage/internal error.
"""

import datetime
import json
import os
import platform
import re
import sys
import uuid

DEFAULT_KEEP = 25
LATEST = "latest.log"

# The one pattern this module generates and the ONLY one it will ever delete.
#   20260731T061203.481902Z-deliverable-voice-a1b2c3.log
# Microseconds are load-bearing, not decoration: several runs can start inside the same
# second, and with only second precision the sort tiebreak fell to the random hex suffix —
# which is not chronological, so "keep the newest 25" could delete a NEWER log than it kept.
_NAME_RE = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-[A-Za-z0-9][A-Za-z0-9._+-]{0,48}-[0-9a-f]{6}\.log$")
_LABEL_SANE = re.compile(r"[^A-Za-z0-9._+-]+")


def default_dir():
    d = os.environ.get("WORKCHAIN_RUNLOG_DIR")
    if d:
        return os.path.abspath(os.path.expanduser(d))
    return os.path.expanduser("~/.workchain/runs")


def default_keep():
    raw = os.environ.get("WORKCHAIN_RUNLOG_KEEP")
    if not raw:
        return DEFAULT_KEEP
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_KEEP
    # 0 or negative would mean "delete everything including the run in progress".
    # Refuse; retention must always keep at least the current run.
    return n if n >= 1 else DEFAULT_KEEP


def sanitize_label(label):
    lab = _LABEL_SANE.sub("-", (label or "run").strip()).strip("-.")
    lab = lab[:48] or "run"
    if not lab[0].isalnum():
        lab = "r" + lab[1:]
    return lab


def run_logs(d):
    """Recognised run logs in `d`, newest first. Ignores everything unrecognised."""
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for n in names:
        if not _NAME_RE.match(n):
            continue
        p = os.path.join(d, n)
        if os.path.islink(p) or not os.path.isfile(p):
            continue
        out.append(p)
    # The name starts with a sortable UTC stamp, so lexical sort == chronological.
    # Filenames, not mtimes: mtime changes as a run appends, and sorting by it would
    # make "newest" mean "most recently written to" rather than "most recently started".
    out.sort(key=os.path.basename, reverse=True)
    return out


def prune(d, keep=None, protect=None):
    """Keep the newest `keep` recognised run logs; delete the rest. Returns deleted paths."""
    keep = default_keep() if keep is None else max(1, int(keep))
    protect = os.path.abspath(protect) if protect else None
    logs = run_logs(d)
    deleted = []
    for p in logs[keep:]:
        if protect and os.path.abspath(p) == protect:
            continue
        try:
            os.unlink(p)
            deleted.append(p)
        except OSError:
            pass
    return deleted


def open_run(label="run", d=None, keep=None, meta=None):
    """Create a new run log, write its header, prune the directory. Returns (path, deleted)."""
    d = d or default_dir()
    keep = default_keep() if keep is None else max(1, int(keep))
    os.makedirs(d, exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
    name = "%s-%s-%s.log" % (stamp, sanitize_label(label), uuid.uuid4().hex[:6])
    path = os.path.join(d, name)
    assert _NAME_RE.match(name), "generated a name our own pruner would not recognise: %s" % name

    local = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    hdr = [
        "# LUFS Workchain run log",
        "# label     : %s" % label,
        "# started   : %s (%s UTC)" % (local, stamp),
        "# host      : %s (%s %s)" % (platform.node(), platform.system(), platform.machine()),
        "# pid       : %d" % os.getpid(),
        "# cwd       : %s" % os.getcwd(),
        "# retention : newest %d run logs in %s" % (keep, d),
    ]
    for k in sorted((meta or {}).keys()):
        hdr.append("# %-10s: %s" % (k, meta[k]))
    hdr.append("#" + "-" * 78)
    with open(path, "w") as f:
        f.write("\n".join(hdr) + "\n")
        f.flush()
        os.fsync(f.fileno())

    # Prune AFTER creating, protecting the file we just made, so retention is measured
    # including the current run and the current run can never be the thing deleted.
    deleted = prune(d, keep=keep, protect=path)

    # Convenience pointer for `tail -f`. Best-effort: a filesystem without symlinks is
    # not a reason to fail a run.
    try:
        link = os.path.join(d, LATEST)
        if os.path.islink(link):
            os.unlink(link)                     # ours; safe to replace
            os.symlink(os.path.basename(path), link)
        elif not os.path.exists(link):
            os.symlink(os.path.basename(path), link)
        # else: a REGULAR FILE named latest.log already exists. It is not ours and it may be
        # somebody's data (this directory comes from an env var). Leave it and skip the
        # convenience link — losing a symlink is nothing, deleting a file is forever.
    except OSError:
        pass
    return path, deleted


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _arg(argv, flag, default=None):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def main(argv):
    if not argv:
        sys.stderr.write(__doc__.split("CLI:", 1)[1].strip() + "\n")
        return 2
    cmd = argv[0]
    want_json = "--json" in argv
    d = _arg(argv, "--dir") or default_dir()
    d = os.path.abspath(os.path.expanduser(d))
    keep_raw = _arg(argv, "--keep")
    keep = int(keep_raw) if keep_raw else default_keep()

    try:
        if cmd == "open":
            label = _arg(argv, "--label", "run")
            meta = {}
            m = _arg(argv, "--meta")
            if m:
                try:
                    meta = json.loads(m)
                except ValueError:
                    meta = {"meta": m}
            path, deleted = open_run(label, d, keep, meta)
            if want_json:
                print(json.dumps({"path": path, "dir": d, "keep": keep,
                                  "pruned": deleted, "n_pruned": len(deleted)}, indent=2))
            else:
                print(path)          # stdout is JUST the path, so bash can capture it
            if deleted:
                sys.stderr.write("runlog: autoclean removed %d old run log(s), keeping newest %d\n"
                                 % (len(deleted), keep))
            return 0

        if cmd == "list":
            logs = run_logs(d)
            if want_json:
                print(json.dumps({"dir": d, "keep": keep, "n": len(logs),
                                  "logs": [{"path": p, "bytes": os.path.getsize(p)} for p in logs]},
                                 indent=2))
            else:
                for p in logs:
                    print("%9d  %s" % (os.path.getsize(p), os.path.basename(p)))
                sys.stderr.write("%d run log(s) in %s (retention: newest %d)\n" % (len(logs), d, keep))
            return 0

        if cmd == "prune":
            deleted = prune(d, keep=keep)
            if want_json:
                print(json.dumps({"dir": d, "keep": keep, "pruned": deleted,
                                  "n_pruned": len(deleted)}, indent=2))
            else:
                sys.stderr.write("pruned %d, keeping newest %d in %s\n" % (len(deleted), keep, d))
            return 0

        if cmd in ("tail", "path"):
            logs = run_logs(d)
            if not logs:
                sys.stderr.write("no run logs in %s\n" % d)
                return 1
            newest = logs[0]
            if cmd == "path":
                print(newest)
                return 0
            n_raw = _arg(argv, "-n", "40")
            n = int(n_raw)
            with open(newest) as f:
                lines = f.readlines()
            sys.stderr.write("── %s ──\n" % os.path.basename(newest))
            sys.stdout.write("".join(lines[-n:]))
            return 0

        sys.stderr.write("unknown subcommand: %s\n" % cmd)
        return 2
    except Exception as e:
        sys.stderr.write("runlog error: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
