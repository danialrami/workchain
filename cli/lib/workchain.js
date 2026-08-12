import { existsSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { loadConfig } from './config.js';
import { CliError } from './utils.js';

/**
 * Resolve the workchain root directory
 * Looks for engine/workchain-engine.sh marker file
 */
export function resolveWorkchainRoot() {
  const ENGINE_MARKER = 'engine/workchain-engine.sh';
  
  if (process.env.LUFS_WORKCHAIN_ROOT) {
    const root = resolve(process.env.LUFS_WORKCHAIN_ROOT);
    if (existsSync(join(root, ENGINE_MARKER))) {
      return root;
    }
    throw new CliError(3,
      `LUFS_WORKCHAIN_ROOT points to a directory without ${ENGINE_MARKER}: ${root}`
    );
  }

  const config = loadConfig();
  if (config.workchainRoot) {
    const root = resolve(config.workchainRoot);
    if (existsSync(join(root, ENGINE_MARKER))) {
      return root;
    }
    throw new CliError(3,
      `Config workchainRoot points to a directory without ${ENGINE_MARKER}: ${root}\n` +
      `Fix with: workchain config set workchainRoot /path/to/workchain`
    );
  }

  const cliDir = dirname(fileURLToPath(import.meta.url));
  let candidate = resolve(cliDir, '..');
  while (candidate !== resolve(candidate, '..')) {
    if (existsSync(join(candidate, ENGINE_MARKER))) {
      return candidate;
    }
    candidate = resolve(candidate, '..');
  }

  throw new CliError(3,
    'Workchain root not found.\n' +
    '  Set it with: workchain config set workchainRoot /path/to/workchain\n' +
    '  Or set env:   export LUFS_WORKCHAIN_ROOT=/path/to/workchain'
  );
}

export function resolveChainFile(chainName, workchainRoot) {
  // 1. If the name is already a path to an existing file (e.g. ./chain.yaml or an
  //    absolute path), use it as-is.
  const asPath = resolve(chainName);
  if (existsSync(asPath)) return asPath;

  // 2. Otherwise resolve against chains/, including nested subdirectory names such as
  //    `tests/normalization_offtarget` that `chains` lists but that are NOT paths.
  //    Previously any slash was treated as a filesystem path, so the names the tool
  //    printed as available could not be run as written.
  const candidates = [
    join(workchainRoot, 'chains', `${chainName}.yaml`),
    join(workchainRoot, 'chains', 'examples', `${chainName}.yaml`),
    join(workchainRoot, 'chains', 'tests', `${chainName}.yaml`),
  ];

  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }

  throw new CliError(2,
    `Chain not found: "${chainName}"\n` +
    `  Searched in:\n` +
    candidates.map(c => `    - ${c}`).join('\n') + '\n' +
    `  Run "workchain chains" to see available chains.`
  );
}

export function resolveComponentDir(name, workchainRoot) {
  const dir = join(workchainRoot, 'components', name);
  const stepYaml = join(dir, 'step.yaml');
  if (!existsSync(stepYaml)) {
    throw new CliError(2, `Component not found: ${name}`);
  }
  return dir;
}
