---
title: MCP Reference
description: Complete reference for the FastMCP server — 6 tools, transports, invocation, and return shapes.
type: reference
---

# MCP Server Reference

The Workchain MCP server (`mcp-server/server.py`) exposes the engine's capabilities through the [Model Context Protocol](https://modelcontextprotocol.io). An AI agent can discover components, read schemas, validate chains, run processing, and even scaffold new components — all without touching a terminal.

**Transport:** stdio (default), `--transport streamable-http --port 9000` (HTTP).

**Entry point:**

```bash
# stdio (default, for local agent integration)
python mcp-server/server.py

# HTTP (for MCP Gateway / remote agents)
python mcp-server/server.py --transport streamable-http --port 9000
```

**Implementation:** FastMCP (`mcp[fastmcp]`). Install with:

```bash
uv pip install fastmcp
```

## Tools

The server exposes exactly six tools. All return JSON strings.

### `list_components`

List every available processing component.

```python
list_components() -> str  # JSON string
```

**Returns:** `{"status", "count", "components": [{name, description, type, version, param_count}]}`

Use this first to discover what the workchain can do, then call `get_step_schema(component)` for details.

```json
{
  "status": "completed",
  "count": 6,
  "components": [
    {"name": "audio_benchmark", "description": "Audio quality analysis benchmark suite", "version": "1.0", "type": "text", "param_count": 2},
    {"name": "normalization", "description": "LUFS audio normalization using FFmpeg", "version": "1.1", "type": "audio", "param_count": 5},
    {"name": "stem_separation", "description": "Source separation via python-audio-separator", "version": "2.0", "type": "audio", "param_count": 6}
  ]
}
```

### `get_step_schema`

Get the full schema for one component before using it in a chain.

```python
get_step_schema(component: str = "") -> str  # JSON string. component is required.
```

**Parameters:**
- `component` (string) — directory name in `components/`, e.g. `"normalization"`.

**Returns:** `{"status", "component", "schema": {params: [...], outputs: {...}, requirements: {...}, ...}}`

The schema includes parameters with `type`, `default`, and numeric `range` bounds; declared outputs with `path_template`; input types; and required commands.

### `validate_chain`

Validate a chain **before** running it — cheap insurance against a bad run.

```python
validate_chain(chain_file: str = "", strict: bool = True) -> str  # JSON string
```

**Parameters:**
- `chain_file` (string) — chain name (`"astro-catalog"`), relative path under `chains/`, or absolute path.
- `strict` (boolean, default `True`) — check params against component schemas (types, ranges, unknown keys) and preflight required commands.

**Returns:** `{"status": "completed"|"invalid", "valid": bool, "errors": [...], "steps": [...]}`

With `strict=True` (default), this catches type errors, out-of-range values, and missing commands before execution.

### `run_chain`

Run a processing chain on an audio file.

```python
run_chain(chain_file: str = "", input_file: str = "", output_dir: str = "") -> str  # JSON string
```

**Parameters:**
- `chain_file` (string) — chain name or path to chain YAML.
- `input_file` (string) — path to input audio file.
- `output_dir` (string, optional) — output directory. Auto-generated if empty.

**Returns:** `{"status", "exit_code", "output_dir", "stdout", "stderr"}`

The server delegates to the Node CLI (`cli/bin/workchain.js`) and captures its output. Timeout: 10 minutes.

### `run_component`

Run a component standalone (outside of a chain).

```python
run_component(component: str = "", input_file: str = "", output_dir: str = "", params_json: str = "{}") -> str  # JSON string
```

**Parameters:**
- `component` (string) — component directory name.
- `input_file` (string) — path to input audio file.
- `output_dir` (string, optional) — output directory.
- `params_json` (string, optional, default `"{}"`) — component parameters as JSON, e.g. `'{"target_lufs":-14}'`.

**Returns:** Parsed JSON from the CLI's `--json` output, or `{status, exit_code, raw_output, stderr}` on parse failure.

Timeout: 5 minutes.

### `create_component`

Scaffold a new component so an agent can extend the workchain itself. This tool is the fix for a known repo-wide gap where the MCP server originally omitted it (the stale 5-tools README).

```python
create_component(name: str = "", description: str = "", type: str = "audio", params_json: str = "", commands: str = "") -> str  # JSON string
```

**Parameters:**
- `name` (string) — component name in snake_case (required).
- `description` (string) — component description (required).
- `type` (string, default `"audio"`) — component type: `audio`, `image`, `video`, `data`, `text`.
- `params_json` (string, optional) — JSON array of parameter definitions, e.g. `[{"name":"gain_db","type":"number","default":3}]`.
- `commands` (string, optional) — comma-separated required CLI tools.

**Returns:** `{"status", "component_name", "component_path", "files_created": [...]}`

Creates `components/<name>/{step.yaml, run.sh, README.md, provision.sh, test-chain.yaml}`. The generated `run.sh` fails until implemented via the `WORKCHAIN_NOT_IMPLEMENTED=1` sentinel — a fresh scaffold never reports false success. After creating it, edit `run.sh` to add real processing and remove the sentinel line.

## Invocation examples

### Stdio mode (local MCP client)

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_components","arguments":{}}}' \
  | python mcp-server/server.py
```

### Streamable HTTP mode

```bash
python mcp-server/server.py --transport streamable-http --port 9000 &
curl -X POST http://127.0.0.1:9000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_components","arguments":{}}}'
```

## Relationship to other docs

This page is the canonical MCP reference. The `mcp-server/README.md` in the repository currently lists only 5 tools (omitting `create_component`) — it is **stale** and will be corrected in a subsequent update. The source of truth is `mcp-server/server.py` and this reference page.