import { resolveWorkchainRoot } from '../lib/workchain.js';
import { wy } from '../lib/wyaml.js';
import { formatList } from '../lib/formatter.js';
import { CliError } from '../lib/utils.js';

/**
 * List available chains. Enumeration + parsing delegated to the single parser
 * (lib/workchain_yaml.py list-chains) so the CLI/engine/MCP agree (review Bug 7).
 */
export async function chainsCommand(options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || false;

  try {
    const workchainRoot = resolveWorkchainRoot();
    let chains = wy(workchainRoot, ['list-chains', workchainRoot]) || [];

    if (options.filter) {
      const pattern = options.filter.toLowerCase();
      chains = chains.filter(c => c.name.toLowerCase().includes(pattern));
    }
    chains.sort((a, b) => a.name.localeCompare(b.name));

    console.log(formatList(chains, 'Available chains', { json }));
  } catch (err) {
    if (err instanceof CliError) {
      const result = { status: 'error', command: 'chains', code: err.code, message: err.message, details: err.details };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    console.error(json ? JSON.stringify({ status: 'error', command: 'chains', code: 1, message: err.message }, null, 2) : `Error: ${err.message}`);
    process.exit(1);
  }
}
