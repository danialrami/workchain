import { resolveWorkchainRoot, resolveComponentDir } from '../lib/workchain.js';
import { wy } from '../lib/wyaml.js';
import { CliError } from '../lib/utils.js';

/**
 * Show a component's schema. Parsing is delegated to lib/workchain_yaml.py (the single
 * source-of-truth parser), so the JSON includes everything — including param `range`
 * bounds that the old hand-rolled CLI regex silently dropped (review Bug 7).
 */
export async function componentCommand(name, options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || options.json || false;

  try {
    const workchainRoot = resolveWorkchainRoot();
    resolveComponentDir(name, workchainRoot); // throws CliError(2) if not found

    const component = wy(workchainRoot, ['component-schema', workchainRoot, name]);

    const output = json ? JSON.stringify(component, null, 2) : formatComponentHuman(component);
    console.log(output);
  } catch (err) {
    if (err instanceof CliError) {
      const result = { status: 'error', command: 'component', code: err.code, message: err.message, details: err.details };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    console.error(json ? JSON.stringify({ status: 'error', command: 'component', code: 1, message: err.message }, null, 2) : `Error: ${err.message}`);
    process.exit(1);
  }
}

function formatComponentHuman(comp) {
  const lines = [];
  lines.push(`\n  ${comp.name}`);
  lines.push(`  ${'─'.repeat(comp.name.length)}`);
  lines.push(`  ${comp.description}`);
  lines.push(`  Type: ${comp.type} | Version: ${comp.version}`);
  lines.push('');

  if (comp.params && comp.params.length > 0) {
    lines.push('  Parameters:');
    for (const p of comp.params) {
      const def = p.default !== null && p.default !== undefined ? ` = ${p.default}` : '';
      const r = p.range && (p.range.min !== undefined || p.range.max !== undefined)
        ? ` [${p.range.min ?? '-∞'}..${p.range.max ?? '∞'}]`
        : '';
      lines.push(`    ${p.name} (${p.type})${def}${r} — ${p.description || ''}`);
    }
    lines.push('');
  }

  if (comp.outputs && comp.outputs.items && comp.outputs.items.length > 0) {
    lines.push('  Outputs:');
    for (const item of comp.outputs.items) {
      lines.push(`    ${item.name} (${item.type})${item.path_template ? ` → ${item.path_template}` : ''}`);
    }
    lines.push('');
  }

  const reqs = comp.requirements || {};
  const reqKeys = Object.keys(reqs);
  if (reqKeys.length > 0) {
    lines.push('  Requirements:');
    for (const [key, values] of Object.entries(reqs)) {
      if (Array.isArray(values) && values.length > 0) {
        lines.push(`    ${key}: ${values.join(', ')}`);
      }
    }
    lines.push('');
  }

  return lines.join('\n');
}
