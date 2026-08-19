"""Small HTTP origin for the first Workchain x402 demo.

This is intentionally boring infrastructure: it owns the audio execution boundary, while the
Cloudflare Worker owns public MCP + payment policy. The origin never sees a wallet or a private
key. It accepts one allow-listed demo request, runs the real Bash engine, and refuses to return a
successful result unless every step's verifier record is true.

Run from the repository root:
    python3 demo/x402-mcp/origin/src/server.py

Environment:
    WORKCHAIN_ROOT          repository root (defaults to this checkout)
    ORIGIN_HOST             bind host (default 127.0.0.1)
    ORIGIN_PORT             bind port (default 8788)
    PUBLIC_BASE_URL         URL placed in artifact links (default http://127.0.0.1:8788)
    WORKCHAIN_BACKEND_TOKEN optional bearer token required by POST /v1/render
    WORKCHAIN_RENDER_TTL_S  artifact retention window in seconds (default 3600)
"""

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

HERE = Path(__file__).resolve()
DEFAULT_ROOT = HERE.parents[4]
ROOT = Path(os.environ.get("WORKCHAIN_ROOT", str(DEFAULT_ROOT))).resolve()
CHAIN = "base-demo-normalization"
HOST = os.environ.get("ORIGIN_HOST", "127.0.0.1")
PORT = int(os.environ.get("ORIGIN_PORT", "8788"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8788").rstrip("/")
BACKEND_TOKEN = os.environ.get("WORKCHAIN_BACKEND_TOKEN", "")
RENDER_TTL_S = int(os.environ.get("WORKCHAIN_RENDER_TTL_S", "3600"))
ARTIFACT_ROOT = Path(os.environ.get("WORKCHAIN_ARTIFACT_ROOT", tempfile.gettempdir())) / "workchain-x402-demo"
ENGINE = ROOT / "engine" / "workchain-engine.sh"
CHAIN_FILE = ROOT / "chains" / (CHAIN + ".yaml")

_LOCK = threading.Lock()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode("utf-8")


def response_payload(status: str, **fields: Any) -> Dict[str, Any]:
    payload = {"status": status}
    payload.update(fields)
    return payload


def within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def verification_summary(context: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Return (verified, diagnostics), failing closed on missing records."""
    steps = context.get("steps")
    if not isinstance(steps, dict) or not steps:
        return False, [{"reason": "missing_steps"}]

    failures = []
    for step_id, step in steps.items():
        if not isinstance(step, dict):
            failures.append({"step": step_id, "reason": "step_record_not_object"})
            continue
        if step.get("status") != "completed":
            failures.append({"step": step_id, "reason": "step_not_completed", "status": step.get("status")})
        verification = step.get("verification")
        if not isinstance(verification, dict) or verification.get("verified") is not True:
            failures.append({
                "step": step_id,
                "reason": "step_not_verified",
                "verified": verification.get("verified") if isinstance(verification, dict) else None,
                "verification_failures": verification.get("failures", []) if isinstance(verification, dict) else [],
            })

    return not failures and context.get("status") == "completed", failures


def artifact_records(run_id: str, output_dir: Path, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expose only files recorded by the engine, never an arbitrary directory listing."""
    records = []
    seen = set()
    for step in (context.get("steps") or {}).values():
        if not isinstance(step, dict):
            continue
        for output in (step.get("outputs") or {}).values():
            if not isinstance(output, dict):
                continue
            raw_path = output.get("path")
            if not raw_path:
                continue
            path = Path(raw_path).resolve()
            if not within(path, output_dir) or not path.is_file():
                continue
            relative = path.relative_to(output_dir).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            records.append({
                "name": output.get("type") or path.name,
                "path": relative,
                "url": "%s/artifacts/%s/%s" % (PUBLIC_BASE_URL, run_id, quote(relative, safe="/")),
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "bytes": path.stat().st_size,
            })
    return sorted(records, key=lambda record: record["path"])


def generate_fixture(path: Path) -> None:
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
        "-ac", "2", "-c:a", "pcm_s16le", str(path),
    ]
    result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("fixture generation failed: %s" % (result.stderr[-800:] or "ffmpeg exited non-zero"))


def run_verified_render(run_id: str) -> Dict[str, Any]:
    if not ENGINE.is_file() or not CHAIN_FILE.is_file():
        raise RuntimeError("demo chain or engine is missing")

    run_dir = ARTIFACT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_file = run_dir / "input.wav"
    output_dir = run_dir / "output"
    generate_fixture(input_file)

    command = [
        "bash", str(ENGINE),
        "-c", str(CHAIN_FILE),
        "-o", str(output_dir),
        str(input_file),
    ]
    result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    context_path = output_dir / "context.json"
    context: Dict[str, Any] = {}
    if context_path.is_file():
        try:
            context = json.loads(context_path.read_text())
        except Exception as exc:
            return response_payload("error", verified=False, run_id=run_id, error="context.json is unreadable: %s" % exc)

    verified, failures = verification_summary(context)
    if result.returncode != 0 or not verified:
        return response_payload(
            "error",
            verified=False,
            run_id=run_id,
            engine_exit_code=result.returncode,
            failures=failures,
            stderr=result.stderr[-2000:],
            stdout=result.stdout[-2000:],
        )

    return response_payload(
        "completed",
        verified=True,
        run_id=run_id,
        chain=CHAIN,
        engine_exit_code=0,
        artifacts=artifact_records(run_id, output_dir, context),
        verification={"steps": len(context.get("steps", {})), "failures": []},
    )


def cleanup_old_artifacts() -> None:
    cutoff = time.time() - RENDER_TTL_S
    if not ARTIFACT_ROOT.is_dir():
        return
    for child in ARTIFACT_ROOT.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child)
        except FileNotFoundError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "workchain-x402-origin/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep one-line access logs on stderr; never mix them into JSON responses.
        print("origin: " + (fmt % args), file=sys.stderr, flush=True)

    def _send(self, code: int, payload: Any, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json_bytes(payload)
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            # A client may close after reading a large audio artifact; the render is still valid.
            pass

    def _authorized(self) -> bool:
        if not BACKEND_TOKEN:
            return True
        return self.headers.get("Authorization", "") == "Bearer " + BACKEND_TOKEN

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send(HTTPStatus.OK, response_payload("ok", service="workchain-x402-origin", chain=CHAIN))
            return
        if parsed.path.startswith("/artifacts/"):
            self._serve_artifact(parsed.path)
            return
        self._send(HTTPStatus.NOT_FOUND, response_payload("error", error="not_found"))

    def _serve_artifact(self, path: str) -> None:
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) < 3 or parts[0] != "artifacts":
            self._send(HTTPStatus.NOT_FOUND, response_payload("error", error="not_found"))
            return
        run_id = parts[1]
        if not run_id or any(ch not in "0123456789abcdef-" for ch in run_id):
            self._send(HTTPStatus.NOT_FOUND, response_payload("error", error="invalid_run_id"))
            return
        run_root = (ARTIFACT_ROOT / run_id).resolve()
        output_root = (run_root / "output").resolve()
        candidate = (output_root / Path(*parts[2:])).resolve()
        if not within(candidate, output_root) or not candidate.is_file():
            self._send(HTTPStatus.NOT_FOUND, response_payload("error", error="artifact_not_found"))
            return
        try:
            self._send(HTTPStatus.OK, candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        except OSError:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, response_payload("error", error="artifact_read_failed"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/render":
            self._send(HTTPStatus.NOT_FOUND, response_payload("error", error="not_found"))
            return
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, response_payload("error", error="unauthorized"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16 * 1024:
                raise ValueError("request too large")
            body = self.rfile.read(length) if length else b"{}"
            request = json.loads(body.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request body must be a JSON object")
            if request.get("chain", CHAIN) != CHAIN:
                raise ValueError("only the allow-listed demo chain is available")
            if request.get("fixture", "tone") != "tone":
                raise ValueError("only the deterministic tone fixture is available")
            run_id = str(uuid.uuid4())
            with _LOCK:
                cleanup_old_artifacts()
                result = run_verified_render(run_id)
            self._send(HTTPStatus.OK if result.get("verified") else HTTPStatus.BAD_GATEWAY, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, response_payload("error", error=str(exc)))
        except subprocess.TimeoutExpired:
            self._send(HTTPStatus.GATEWAY_TIMEOUT, response_payload("error", error="render timed out"))
        except Exception as exc:  # the outer boundary must still return JSON
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, response_payload("error", error=str(exc)))


def main() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("workchain x402 origin listening on %s:%d" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
