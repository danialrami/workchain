import { resolveWorkchainRoot } from '../lib/workchain.js';
import { wy } from '../lib/wyaml.js';
import { formatList } from '../lib/formatter.js';
import { CliError } from '../lib/utils.js';

/**
 * List available components. Enumeration + parsing delegated to the single parser
 * (lib/workchain_yaml.py list-components) so the CLI/engine/MCP agree (review Bug 7).
 */
export async function componentsCommand(options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || false;

  try {
    const workchainRoot = resolveWorkchainRoot();
    let components = wy(workchainRoot, ['list-components', workchainRoot]) || [];

    if (options.filter) {
      const pattern = options.filter.toLowerCase();
      components = components.filter(c => c.name.toLowerCase().includes(pattern));
    }
    components.sort((a, b) => a.name.localeCompare(b.name));

    console.log(formatList(components, 'Available components', { json }));
  } catch (err) {
    if (err instanceof CliError) {
      const result = { status: 'error', command: 'components', code: err.code, message: err.message, details: err.details };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    console.error(json ? JSON.stringify({ status: 'error', command: 'components', code: 1, message: err.message }, null, 2) : `Error: ${err.message}`);
    process.exit(1);
  }
}
