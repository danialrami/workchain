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
      `Fix with: lufs-workchain config set workchainRoot /path/to/lufs-workchain`
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
    '  Set it with: lufs-workchain config set workchainRoot /path/to/lufs-workchain\n' +
    '  Or set env:   export LUFS_WORKCHAIN_ROOT=/path/to/lufs-workchain'
  );
}

export function resolveChainFile(chainName, workchainRoot) {
  if (chainName.includes('/')) {
    const resolved = resolve(chainName);
    if (existsSync(resolved)) return resolved;
    throw new CliError(2, `Chain file not found: ${resolved}`);
  }

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
    `  Run "lufs-workchain chains" to see available chains.`
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
