import { loadConfig, getConfig, setConfig, deleteConfig, resetConfig, getConfigPath } from '../lib/config.js';
import { formatError } from '../lib/formatter.js';
import { CliError } from '../lib/utils.js';

const VALID_KEYS = ['workchainRoot', 'server', 'defaultChain', 'outputDir', 'concurrency'];

export async function configCommand(subcommand, key, value, options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || false;

  try {
    switch (subcommand) {
      case 'set':
        if (!key || value === undefined) {
          throw new CliError(2, 'Usage: workchain config set <key> <value>');
        }
        if (!VALID_KEYS.includes(key)) {
          throw new CliError(2, `Invalid config key: "${key}". Valid keys: ${VALID_KEYS.join(', ')}`);
        }
        setConfig(key, value);
        if (json) {
          console.log(JSON.stringify({ status: 'completed', key, value: getConfig(key) }, null, 2));
        } else {
          console.log(`Set ${key} = ${getConfig(key)}`);
        }
        break;

      case 'get':
        if (!key) {
          throw new CliError(2, 'Usage: workchain config get <key>');
        }
        const val = getConfig(key);
        if (json) {
          console.log(JSON.stringify({ [key]: val }, null, 2));
        } else {
          console.log(val);
        }
        break;

      case 'list':
        const config = loadConfig();
        if (json) {
          console.log(JSON.stringify(config, null, 2));
        } else {
          for (const [k, v] of Object.entries(config)) {
            if (k.startsWith('_')) continue;
            console.log(`${k}: ${v}`);
          }
          console.log(`---`);
          console.log(`Config file: ${config._configPath}`);
          if (config._envOverrides.length > 0) {
            console.log(`Env overrides: ${config._envOverrides.join(', ')}`);
          }
        }
        break;

      case 'delete':
        if (!key) {
          throw new CliError(2, 'Usage: workchain config delete <key>');
        }
        deleteConfig(key);
        if (!json) console.log(`Deleted config key: ${key}`);
        break;

      case 'reset':
        resetConfig();
        if (!json) console.log('Configuration reset to defaults.');
        break;

      default:
        console.log('Usage: workchain config <subcommand> [key] [value]');
        console.log('');
        console.log('Subcommands:');
        console.log('  set <key> <value>    Set a config value');
        console.log('  get <key>            Get a config value');
        console.log('  list                 List all config values');
        console.log('  delete <key>         Delete a config key');
        console.log('  reset                Reset all config to defaults');
        console.log('');
        console.log('Valid keys:');
        for (const k of VALID_KEYS) {
          console.log(`  ${k}`);
        }
    }
  } catch (err) {
    if (err instanceof CliError) {
      console.error(formatError(err, { json }));
      process.exit(err.code);
    }
    console.error(formatError(err, { json }));
    process.exit(1);
  }
}
