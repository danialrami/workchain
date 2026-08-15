# LUFS Workchain MCP Server

FastMCP server exposing the LUFS Workchain engine through the [Model Context Protocol](https://modelcontextprotocol.io). The deep reference (signatures, return shapes, worked examples) lives at [`docs/reference/interfaces/mcp.md`](../docs/reference/interfaces/mcp.md).

## Features

- **list_components()** — List all available processing components
- **get_step_schema(component)** — Get parameter schema for a specific component
- **validate_chain(chain_file, strict)** — Validate chain YAML before execution
- **run_chain(chain_file, input_file, output_dir)** — Execute a processing chain on an audio file
- **run_component(component, input_file, output_dir, params_json)** — Run a single component standalone
- **create_component(name, description, type, params_json, commands)** — Scaffold a new component

## Setup

```bash
# Create virtual environment
cd mcp-server
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install fastmcp pyyaml
```

## Running

```bash
# STDIO mode (for local testing and agent integration)
python server.py

# Streamable HTTP mode (for MCP Gateway / remote agents)
python server.py --transport streamable-http --port 9000
```

## Tools

All six tools return JSON strings. See [`docs/reference/interfaces/mcp.md`](../docs/reference/interfaces/mcp.md) for full signatures, return shapes, and worked examples with real component data.

| Tool | Description |
|---|---|
| `list_components()` | List every component (name, type, version, param_count) |
| `get_step_schema(component)` | Full spec params/outputs/requirements/verify for one component |
| `validate_chain(chain_file, strict)` | Validate chain structure; `strict=True` checks param ranges |
| `run_chain(chain_file, input_file, output_dir)` | Execute a processing chain |
| `run_component(component, input_file, output_dir, params_json)` | Run a component standalone |
| `create_component(name, description, type, params_json, commands)` | Scaffold a component (sentinel blocks until implemented) |

## Integration with MCP Gateway

```yaml
registry:
  workchain:
    description: "LUFS audio processing workchain — chains, components, validation"
    title: "LUFS Workchain"
    type: "server"
    image: your-registry.example/workchain-mcp:latest
    source: https://github.com/lufs-audio/workchain
    tools:
      - name: list_components
      - name: get_step_schema
      - name: validate_chain
      - name: run_chain
      - name: run_component
      - name: create_component
```