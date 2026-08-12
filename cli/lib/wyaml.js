/**
 * wyaml.js — the CLI's bridge to the single parser/resolver (lib/workchain_yaml.py).
 *
 * Every command that needs to read a chain or component schema goes through here, so the
 * CLI, the engine, and the MCP server all parse YAML the exact same way (review Bug 7 —
 * three drifting parsers, e.g. param `range` bounds were dropped only in the CLI's regex).
 */

import { execaSync } from 'execa';
import { join } from 'path';

/**
 * Run a workchain_yaml.py subcommand and return parsed JSON (or raw text).
 * Does not throw on non-zero exit when JSON was still produced (e.g. `validate` on an
 * invalid chain exits 1 but prints a result object).
 */
export function wy(workchainRoot, args, { json = true } = {}) {
  const script = join(workchainRoot, 'lib', 'workchain_yaml.py');
  const res = execaSync('python3', [script, ...args], {
    cwd: workchainRoot,
    reject: false,
    stdin: 'ignore',
  });
  if (!res.stdout) {
    throw new Error(`workchain_yaml ${args[0]} produced no output: ${res.stderr || `exit ${res.exitCode}`}`);
  }
  if (!json) return res.stdout;
  let parsed;
  try {
    parsed = JSON.parse(res.stdout);
  } catch {
    throw new Error(`workchain_yaml ${args[0]} did not return JSON: ${res.stdout.slice(0, 200)}`);
  }
  if (parsed && parsed.error) {
    throw new Error(parsed.error);
  }
  return parsed;
}
