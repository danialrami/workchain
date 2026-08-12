# LUFS Workchain MCP Server

Minimal V1 implementation of the Model Context Protocol server for LUFS Workchain.

## Features

- **list_components()** - List all available processing components
- **get_step_schema(component)** - Get parameter schema for a component
- **run_chain(chain_file, input_file)** - Execute a processing chain
- **validate_chain(chain_file)** - Validate chain YAML before execution
- **run_component(component, input_file)** - Run a component standalone

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
# STDIO mode (for local testing)
python server.py

# Streamable HTTP mode (for MCP Gateway)
python server.py --transport streamable-http --port 9000
```

## Tools

### list_components()
Returns JSON array of all components with their metadata.

### get_step_schema(component: str)
Returns the step.yaml schema for a specific component.

### run_chain(chain_file: str, input_file: str, output_dir: str = "")
Executes a processing chain on an audio file.

### validate_chain(chain_file: str)
Validates a chain YAML file structure.

### run_component(component: str, input_file: str, output_dir: str = "", params_json: str = "{}")
Runs a component standalone (outside of a chain).

## Integration with MCP Gateway

Add to `mcp-data/docker-mcp.yaml`:
```yaml
registry:
  workchain:
    description: "LUFS audio processing workchain - chains, components, validation"
    title: "LUFS Workchain"
    type: "server"
    image: your-registry.example/workchain-mcp:latest
    source: https://github.com/lufs-audio/workchain
    tools:
      - name: list_components
      - name: get_step_schema
      - name: run_chain
      - name: validate_chain
      - name: run_component
```

## Status
