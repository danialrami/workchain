#!/usr/bin/env node

import { Command } from 'commander';
import { runCommand } from '../commands/run.js';
import { runComponentCommand } from '../commands/run-component.js';
import { chainsCommand } from '../commands/chains.js';
import { chainCommand } from '../commands/chain.js';
import { componentsCommand } from '../commands/components.js';
import { componentCommand } from '../commands/component.js';
import { configCommand } from '../commands/config.js';
import { generateCommand } from '../commands/generate.js';
import { validateCommand } from '../commands/validate.js';
import { doctorCommand } from '../commands/doctor.js';
import { registryCommand } from '../commands/registry.js';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(join(__dirname, '..', 'package.json'), 'utf-8'));

const program = new Command();

program
  .name('workchain')
  .description('LUFS audio processing workchain — agent-first CLI')
  .version(pkg.version)
  .option('--json', 'Output raw JSON (machine mode)')
  .option('--no-color', 'Disable colored output')
  .option('--verbose', 'Verbose logging to stderr (raw engine output)');

program.addHelpText('after', `
Examples:
  $ workchain run deliverable-voice song.wav -o ./output
  $ workchain chains --json
  $ workchain component normalization --json
  $ workchain config set workchainRoot /path/to/repo

Exit Codes:
  0  Success
  1  Execution error
  2  Input error (file not found, bad chain name)
  3  Configuration error (workchain root not found)
`);

const runCmd = program
  .command('run')
  .description('Execute a processing chain on an audio file')
  .argument('<chain>', 'Chain name or path to chain YAML')
  .argument('<input>', 'Input audio file')
  .option('-o, --output <dir>', 'Output directory (default: ./output_YYYYMMDD_HHMMSS)')
  .option('--timeout <seconds>', 'Max execution time in seconds (default: 3600)', parseInt)
  .option('--dry-run', 'Preview chain execution without running it')
  .option('--report', 'Generate HTML report after chain completes')
  .action(runCommand);

runCmd.addHelpText('after', `
Examples:
  $ workchain run deliverable-voice song.wav -o ./output
  $ workchain run deliverable-voice song.wav --dry-run
  $ workchain run deliverable-voice song.wav --dry-run --json
  $ workchain run deliverable-voice song.wav -o ./output --json
  $ workchain run ./my-chain.yaml /path/to/input.mp3 -o /tmp/out
  $ workchain run deliverable-voice long_song.wav --timeout 7200
  $ workchain run deliverable-voice song.wav --report

Exit Codes:
  0  Chain completed successfully (or dry-run plan generated)
  1  Chain execution failed (component error, FFmpeg missing)
  2  Input validation failed (file not found, unsupported format)
  3  Workchain root not found
`);

const runComponentCmd = program
  .command('run-component')
  .description('Run a component standalone (outside of a chain)')
  .argument('<component>', 'Component name (directory in components/)')
  .argument('<input>', 'Input audio file or directory')
  .option('-o, --output <dir>', 'Output directory (default: ./output_YYYYMMDD_HHMMSS)')
  .option('--timeout <seconds>', 'Max execution time in seconds (default: 3600)', parseInt)
  .option('--params-json <json>', 'Component parameters as JSON string (e.g., \'{"target_lufs":-14}\')')
  .option('-r, --recursive', 'Recursively scan directories for audio files (batch mode)')
  .option('-e, --extensions <list>', 'Comma-separated list of extensions (default: mp3,wav,flac,etc)')
  .action(runComponentCommand);

runComponentCmd.addHelpText('after', `
Examples:
  $ workchain run-component normalization input.wav -o ./output
  $ workchain run-component normalization input.wav --params-json '{"target_lufs":-14}'
  $ workchain run-component audio_benchmark input.wav --json
  $ workchain run-component canvas_01 input.wav --output ./assets

Batch mode (process directory of audio files):
  $ workchain run-component audio_benchmark /path/to/audio/folder --json
  $ workchain run-component normalization /path/to/audio/folder -r --extensions mp3,wav

Exit Codes:
  0  Component completed successfully
  1  Component execution failed (batch: some files failed)
  2  Input error (file not found, component not found)
  3  Workchain root not found
`);

const chainsCmd = program
  .command('chains')
  .description('List available processing chains')
  .option('--filter <pattern>', 'Filter by name (case-insensitive substring)')
  .action(chainsCommand);

chainsCmd.addHelpText('after', `
Examples:
  $ workchain chains
  $ workchain chains --json
  $ workchain chains --filter astro

Exit Codes:
  0  Success (may return empty array)
  2  Chains directory not found
  3  Workchain root not found
`);

const chainCmd = program
  .command('chain')
  .description('Show chain definition and parameters')
  .argument('<name>', 'Chain name')
  .action(chainCommand);

chainCmd.addHelpText('after', `
Examples:
  $ workchain chain deliverable-voice
  $ workchain chain deliverable-voice --json

Exit Codes:
  0  Success
  2  Chain not found
  3  Workchain root not found
`);

const componentsCmd = program
  .command('components')
  .description('List available processing components')
  .option('--filter <pattern>', 'Filter by name (case-insensitive substring)')
  .action(componentsCommand);

componentsCmd.addHelpText('after', `
Examples:
  $ workchain components
  $ workchain components --json
  $ workchain components --filter norm

Exit Codes:
  0  Success (may return empty array)
  2  Components directory not found
  3  Workchain root not found
`);

const componentCmd = program
  .command('component')
  .description('Show component schema and parameters')
  .argument('<name>', 'Component name (directory in components/)')
  .action(componentCommand);

componentCmd.addHelpText('after', `
Examples:
  $ workchain component normalization
  $ workchain component normalization --json
  $ workchain component artwork_01 --json

Exit Codes:
  0  Success
  2  Component not found
  3  Workchain root not found
`);

const configCmd = program
  .command('config')
  .description('Manage configuration')
  .argument('[subcommand]', 'Subcommand: set, get, list, delete, reset')
  .argument('[key]', 'Config key')
  .argument('[value]', 'Config value')
  .action(configCommand);

configCmd.addHelpText('after', `
Subcommands:
  set <key> <value>    Set a config value
  get <key>            Get a config value
  list                 List all config values
  delete <key>         Delete a config key
  reset                Reset all config to defaults

Valid Keys:
  workchainRoot        Path to workchain repository
  server               Backend (default: local)
  defaultChain         Default chain name (default: deliverable-voice)
  outputDir            Default output directory (default: ./output)
  concurrency          Max parallel chains (default: CPU-1)

Examples:
  $ workchain config set workchainRoot /path/to/workchain
  $ workchain config get workchainRoot
  $ workchain config list
  $ workchain config list --json

Exit Codes:
  0  Success
  1  Config operation failed
  2  Invalid key or missing argument
`);

const generateCmd = program
  .command('generate')
  .description('Generate scaffolding (component)')
  .argument('<type>', 'Type of thing to generate (component)')
  .option('--name <name>', 'Component name (snake_case, lowercase)')
  .option('--description <text>', 'Component description')
  .option('--type <type>', 'Component type (audio/image/video/data/text)')
  .option('--kind <kind>', 'Component kind: light | heavy | api (default: inferred from deps)')
  .option('--params <json>', 'Parameter definitions as JSON array')
  .option('--commands <list>', 'Required system commands (comma-separated)')
  .option('--python-packages <list>', 'Required Python packages (comma-separated) — implies heavy')
  .option('--node-packages <list>', 'Required Node packages (comma-separated)')
  .option('--dependency <name>', 'Previous step component name')
  .option('--output-subdir <path>', 'Output subdirectory')
  .action(generateCommand);

generateCmd.addHelpText('after', `
Examples:
  # Minimal component
  $ workchain generate component \\
      --name my_filter \\
      --description "A simple audio filter" \\
      --type audio

  # Heavy (Python venv) component with parameters
  $ workchain generate component \\
      --name spectral_gate \\
      --description "Spectral noise gate" \\
      --type audio --kind heavy \\
      --params '[{"name":"threshold_db","type":"number","default":-60}]' \\
      --python-packages numpy,scipy

  # API component (delegates to an external service)
  $ workchain generate component \\
      --name cloud_master \\
      --description "Cloud mastering via an external API" \\
      --type audio --kind api

Every generated component is a COMPLETE PUZZLE PIECE — step.yaml (with requirements +
verify), run.sh (fails until implemented), provision.sh, test-chain.yaml, README —
and declares a real contract from day one.

Exit Codes:
  0  Component created successfully
  1  Generation failed
  2  Invalid input (missing required flag, bad params/kind)
  3  Workchain root not found
`);

const validateCmd = program
  .command('validate')
  .description('Validate chain YAML files')
  .argument('<chain>', 'Chain name (or "all" to validate all chains)')
  .option('--strict', 'Schema-aware checks: param types, numeric ranges, unknown params; reports missing required commands')
  .option('--require-commands', 'Also FAIL when a declared command is missing from this PATH (environment gate; off by default so a static lint stays portable)')
  .action(validateCommand);

validateCmd.addHelpText('after', `
Examples:
  $ workchain validate deliverable-voice
  $ workchain validate all --json
  $ workchain validate my-custom-chain

Exit Codes:
  0  Validation passed
  1  Validation failed (errors found)
  2  Chain not found
`);

program
  .command('doctor')
  .description('Check every component inbound dependency contract (preflight-all)')
  .option('--deep', 'Also verify model content hashes (slow)')
  .action(doctorCommand);

program
  .command('registry')
  .description('The generated component index (generate | check)')
  .argument('[action]', 'generate (default) or check', 'generate')
  .action(registryCommand);

program.parse();
