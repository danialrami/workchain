import { existsSync } from 'fs';
import { join } from 'path';
import { resolveWorkchainRoot } from '../lib/workchain.js';
import { generateComponent } from '../lib/component-generator.js';
import { formatResult } from '../lib/formatter.js';
import { CliError } from '../lib/utils.js';

export async function generateCommand(type, options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || false;

  try {
    if (type !== 'component') {
      throw new CliError(2, `Unsupported generation type: "${type}". Use "component".`);
    }

    if (!options.name) throw new CliError(2, '--name is required for generate component');
    if (!options.description) throw new CliError(2, '--description is required for generate component');
    if (!options.type) throw new CliError(2, '--type is required for generate component');

    const workchainRoot = resolveWorkchainRoot();

    // Parse params from options
    const params = [];
    if (options.params) {
      const paramsArray = JSON.parse(options.params);
      if (Array.isArray(paramsArray)) {
        for (const p of paramsArray) {
          params.push({
            name: p.name,
            type: p.type || 'string',
            default: p.default,
            description: p.description,
            min: p.min,
            max: p.max,
          });
        }
      }
    }

    // Generate the component
    const result = await generateComponent({
      name: options.name,
      description: options.description,
      type: options.type,
      params,
      commands: options.commands || '',
      pythonPackages: options.pythonPackages || '',
      nodePackages: options.nodePackages || '',
      dependencies: options.dependency ? (Array.isArray(options.dependency) ? options.dependency : [options.dependency]) : [],
      outputSubdir: options.outputSubdir || '',
      kind: options.kind || '',
    }, workchainRoot);

    if (json) {
      console.log(formatResult(result, { json }));
    } else {
      console.log(`Component '${result.component_name}' created successfully!`);
      console.log(`Path: ${result.component_path}`);
      console.log(`Files created:`);
      for (const file of result.files_created) {
        console.log(`  - ${file}`);
      }
    }

  } catch (err) {
    if (err instanceof CliError) {
      const result = { status: 'error', command: 'generate', code: err.code, message: err.message, details: err.details };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    const result = { status: 'error', command: 'generate', code: 1, message: `Unexpected error: ${err.message}`, details: {} };
    console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
    process.exit(1);
  }
}
