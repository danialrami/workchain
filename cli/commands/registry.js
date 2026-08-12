import { execaSync } from 'execa';
import { join } from 'path';
import { resolveWorkchainRoot } from '../lib/workchain.js';
import { CliError } from '../lib/utils.js';

/**
 * `workchain registry <generate|check>` — the generated component index.
 *   generate → (re)write components/index.json (manifests + tier + definition hash)
 *   check    → exit 1 if components/index.json is missing or stale (for CI)
 * The index is GENERATED, never hand-edited. Delegates to lib/workchain_registry.py.
 */
export async function registryCommand(action, options, command) {
  const sub = action || 'generate';
  if (!['generate', 'check'].includes(sub)) {
    throw new CliError(2, `Unknown registry action '${sub}' (use: generate | check)`);
  }
  const workchainRoot = resolveWorkchainRoot();
  const script = join(workchainRoot, 'lib', 'workchain_registry.py');
  const res = execaSync('python3', [script, sub, workchainRoot], {
    cwd: workchainRoot,
    reject: false,
    stdio: 'inherit',
  });
  process.exit(res.exitCode ?? 0);
}
