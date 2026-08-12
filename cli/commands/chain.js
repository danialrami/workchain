import { resolveWorkchainRoot, resolveChainFile } from '../lib/workchain.js';
import { wy } from '../lib/wyaml.js';
import { CliError } from '../lib/utils.js';

/**
 * Show a chain definition. Parsing delegated to the single parser (lib/workchain_yaml.py)
 * so the CLI, engine and MCP agree on chain structure (review Bug 7).
 */
export async function chainCommand(name, options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || options.json || false;

  try {
    const workchainRoot = resolveWorkchainRoot();
    const chainFile = resolveChainFile(name, workchainRoot);
    const raw = wy(workchainRoot, ['parse', chainFile]) || {};

    const chain = {
      name: raw.name || 'unknown',
      description: raw.description || '',
      version: raw.version || '1.0',
      engineVersion: raw.engine_version || '',
      globals: raw.globals || {},
      steps: (raw.steps || [])
        .filter(s => s && typeof s === 'object')
        .map(s => ({ name: s.name, enabled: s.enabled !== false, params: s.params || {} })),
    };

    const output = json ? JSON.stringify(chain, null, 2) : formatChainHuman(chain);
    console.log(output);
  } catch (err) {
    if (err instanceof CliError) {
      const result = { status: 'error', command: 'chain', code: err.code, message: err.message, details: err.details };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    console.error(json ? JSON.stringify({ status: 'error', command: 'chain', code: 1, message: err.message }, null, 2) : `Error: ${err.message}`);
    process.exit(1);
  }
}

function formatChainHuman(chain) {
  const lines = [];
  lines.push(`\n  ${chain.name}`);
  lines.push(`  ${'─'.repeat(chain.name.length)}`);
  lines.push(`  ${chain.description}`);
  lines.push(`  Version: ${chain.version}${chain.engineVersion ? ` | Engine: ${chain.engineVersion}` : ''}`);
  lines.push('');

  if (chain.globals && Object.keys(chain.globals).length > 0) {
    lines.push('  Globals:');
    for (const [key, val] of Object.entries(chain.globals)) {
      lines.push(`    ${key}: ${val}`);
    }
    lines.push('');
  }

  if (chain.steps.length > 0) {
    lines.push('  Steps:');
    for (const step of chain.steps) {
      const status = step.enabled ? '' : ' [disabled]';
      const params = Object.entries(step.params).map(([k, v]) => `${k}=${v}`).join(', ');
      lines.push(`    ${step.name}${status}${params ? ` (${params})` : ''}`);
    }
    lines.push('');
  }

  return lines.join('\n');
}
