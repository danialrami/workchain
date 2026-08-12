#!/usr/bin/env python3
"""
LUFS Workchain MCP Server - Minimal V1
Provides tools for interacting with the LUFS Workchain system.
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger('lufs-workchain-mcp')

try:
    from fastmcp import FastMCP
except ImportError:
    print("Error: fastmcp not installed. Install with: uv pip install fastmcp", file=sys.stderr)
    sys.exit(1)

# Single source-of-truth parser/resolver/validator. No PyYAML dependency required —
# the module falls back to a stdlib parser — so the MCP runs on a bare system and parses
# YAML identically to the engine and the CLI (review Bug 7).
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
import workchain_yaml as wy

# Initialize MCP server
mcp = FastMCP("lufs-workchain")

# Resolve workchain root (parent directory of mcp-server/)
WORKCHAIN_ROOT = Path(__file__).parent.parent
COMPONENTS_DIR = WORKCHAIN_ROOT / "components"
CHAINS_DIR = WORKCHAIN_ROOT / "chains"
CLI_PATH = WORKCHAIN_ROOT / "cli" / "bin" / "lufs-workchain.js"


def _resolve_chain_path(chain_file: str):
    """Resolve a chain name / relative path / absolute path to a chains/ file."""
    p = Path(chain_file)
    if p.is_absolute() and p.exists():
        return p
    for cand in (CHAINS_DIR / chain_file, CHAINS_DIR / f"{chain_file}.yaml", CHAINS_DIR / f"{chain_file}.yml"):
        if cand.exists():
            return cand
    return None


@mcp.tool()
def list_components() -> str:
    """List every available processing component (name, description, type, param count).

    Start here to discover what the workchain can do. Then call get_step_schema(component)
    for the full parameter + output schema of one you want to use. Returns JSON:
    {status, count, components:[{name, description, type, version, param_count}]}.
    """
    try:
        components = wy.list_components(str(WORKCHAIN_ROOT))
        return json.dumps({"status": "completed", "count": len(components), "components": components}, indent=2)
    except Exception as e:
        logger.error(f"Error listing components: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def get_step_schema(component: str = "") -> str:
    """Get the full schema for one component before using it in a chain.

    Returns parameters (with type, default, and numeric `range` bounds), declared outputs,
    accepted input types, and required commands — everything needed to pass valid params.
    `component` is the directory name in components/ (e.g. "normalization").
    Returns JSON: {status, component, schema:{params:[...], outputs:{...}, requirements:{...}, ...}}.
    """
    if not component.strip():
        return json.dumps({"status": "error", "message": "Component name is required"})
    try:
        schema = wy.component_schema(str(WORKCHAIN_ROOT), component)
        return json.dumps({"status": "completed", "component": component, "schema": schema}, indent=2)
    except FileNotFoundError:
        return json.dumps({"status": "error", "message": f"Component '{component}' not found"})
    except Exception as e:
        logger.error(f"Error getting schema for {component}: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def run_chain(chain_file: str = "", input_file: str = "", output_dir: str = "") -> str:
    """Run a processing chain on an audio file."""
    if not chain_file.strip():
        return json.dumps({"status": "error", "message": "chain_file is required"})
    if not input_file.strip():
        return json.dumps({"status": "error", "message": "input_file is required"})
    
    try:
        # Resolve paths
        if not Path(chain_file).is_absolute():
            chain_path = CHAINS_DIR / chain_file
            if not chain_path.exists() and not chain_path.suffix:
                chain_path = CHAINS_DIR / f"{chain_file}.yaml"
                if not chain_path.exists():
                    chain_path = CHAINS_DIR / f"{chain_file}.yml"
        else:
            chain_path = Path(chain_file)
        
        input_path = Path(input_file).expanduser().absolute()
        output_path = Path(output_dir).expanduser().absolute() if output_dir.strip() else Path.cwd() / f"output_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Validate inputs
        if not chain_path.exists():
            return json.dumps({"status": "error", "message": f"Chain file not found: {chain_path}"})
        if not input_path.exists():
            return json.dumps({"status": "error", "message": f"Input file not found: {input_path}"})
        
        # Create output directory
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Run chain using CLI
        cmd = ["node", str(CLI_PATH), "run", str(chain_path), str(input_path), "-o", str(output_path)]
        logger.info(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(WORKCHAIN_ROOT)
        )
        
        return json.dumps({
            "status": "completed" if result.returncode == 0 else "error",
            "exit_code": result.returncode,
            "output_dir": str(output_path),
            "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
            "stderr": result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr,
        }, indent=2)
    
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "message": "Chain execution timed out after 10 minutes"})
    except Exception as e:
        logger.error(f"Error running chain: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def validate_chain(chain_file: str = "", strict: bool = True) -> str:
    """Validate a chain BEFORE running it — cheap insurance against a bad run.

    With strict=True (default) this checks every step's params against the component schema
    (unknown keys, wrong type, out-of-range numbers) and preflights that required commands
    exist. `chain_file` may be a chain name ("astro-catalog"), a relative path under chains/,
    or an absolute path. Returns JSON: {status: completed|invalid, valid, errors:[...], steps:[...]}.
    """
    if not chain_file.strip():
        return json.dumps({"status": "error", "message": "chain_file is required"})
    try:
        chain_path = _resolve_chain_path(chain_file)
        if not chain_path:
            return json.dumps({"status": "error", "message": f"Chain not found: {chain_file}"})
        res = wy.validate_chain(str(WORKCHAIN_ROOT), str(chain_path), strict=strict)
        res["status"] = "completed" if res.get("valid") else "invalid"
        return json.dumps(res, indent=2)
    except Exception as e:
        logger.error(f"Error validating chain: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def run_component(component: str = "", input_file: str = "", output_dir: str = "", params_json: str = "{}") -> str:
    """Run a component standalone (outside of a chain)."""
    if not component.strip():
        return json.dumps({"status": "error", "message": "component is required"})
    if not input_file.strip():
        return json.dumps({"status": "error", "message": "input_file is required"})
    
    try:
        input_path = Path(input_file).expanduser().absolute()
        
        if not input_path.exists():
            return json.dumps({"status": "error", "message": f"Input file not found: {input_path}"})
        
        # Build command
        cmd = ["node", str(CLI_PATH), "run-component", component, str(input_path), "--json"]
        
        # Parse params_json
        try:
            params = json.loads(params_json)
            if params and isinstance(params, dict):
                cmd.extend(["--params-json", params_json])
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in params_json: {params_json}")
        
        if output_dir.strip():
            cmd.extend(["-o", output_dir])
        
        logger.info(f"Running component: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(WORKCHAIN_ROOT)
        )
        
        # Parse JSON output
        try:
            run_result = json.loads(result.stdout)
            return json.dumps(run_result, indent=2)
        except json.JSONDecodeError:
            return json.dumps({
                "status": "completed" if result.returncode == 0 else "error",
                "exit_code": result.returncode,
                "raw_output": result.stdout[:1000],
                "stderr": result.stderr[:500],
            }, indent=2)
    
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "message": "Component execution timed out after 5 minutes"})
    except Exception as e:
        logger.error(f"Error running component: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def create_component(name: str = "", description: str = "", type: str = "audio",
                     params_json: str = "", commands: str = "") -> str:
    """Scaffold a NEW component so an agent can extend the workchain itself.

    Creates components/<name>/{step.yaml, run.sh, README.md}. The generated run.sh FAILS
    until implemented (a safety sentinel), so a fresh scaffold never reports false success —
    after creating it, edit components/<name>/run.sh to add real processing and remove the
    `WORKCHAIN_NOT_IMPLEMENTED=1` line. `name` must be snake_case. `params_json` is a JSON
    array like [{"name":"gain_db","type":"number","default":3,"min":-30,"max":30}].
    `commands` is a comma-separated list of required CLI tools (e.g. "ffmpeg").
    Returns JSON: {status, component_name, component_path, files_created}.
    """
    if not name.strip() or not description.strip():
        return json.dumps({"status": "error", "message": "name and description are required"})
    cmd = ["node", str(CLI_PATH), "generate", "component",
           "--name", name, "--description", description, "--type", type, "--json"]
    if params_json.strip():
        cmd += ["--params", params_json]
    if commands.strip():
        cmd += ["--commands", commands]
    logger.info(f"Creating component: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(WORKCHAIN_ROOT))
        try:
            return json.dumps(json.loads(result.stdout), indent=2)
        except json.JSONDecodeError:
            return json.dumps({
                "status": "completed" if result.returncode == 0 else "error",
                "exit_code": result.returncode,
                "raw_output": result.stdout[:1000],
                "stderr": result.stderr[:500],
            }, indent=2)
    except Exception as e:
        logger.error(f"Error creating component: {e}")
        return json.dumps({"status": "error", "message": str(e)})


if __name__ == "__main__":
    # Get transport from command line args
    transport = "stdio"
    port = 9000
    
    if len(sys.argv) > 1:
        if "--transport" in sys.argv:
            idx = sys.argv.index("--transport")
            if idx + 1 < len(sys.argv):
                transport = sys.argv[idx + 1]
        
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            if idx + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[idx + 1])
                except ValueError:
                    pass
    
    logger.info(f"Starting LUFS Workchain MCP Server on transport={transport}, port={port}")
    logger.info(f"Workchain root: {WORKCHAIN_ROOT}")
    
    # Only pass port for HTTP-based transports
    if transport in ["streamable-http", "sse"]:
        mcp.run(transport=transport, port=port)
    else:
        mcp.run(transport=transport)
