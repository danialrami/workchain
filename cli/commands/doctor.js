import { execaSync } from 'execa';
import { join } from 'path';
import { resolveWorkchainRoot } from '../lib/workchain.js';

/**
 * `workchain doctor` — run the inbound dependency preflight for every component and
 * report what's provisioned vs missing. The health check for an install; also how heavy
 * component tests self-skip. Delegates to lib/workchain_registry.py (single source of truth).
 */
export async function doctorCommand(options, command) {
  const json = command.parent?.opts()?.json || false;
  const workchainRoot = resolveWorkchainRoot();
  const script = join(workchainRoot, 'lib', 'workchain_registry.py');
  const args = ['doctor', workchainRoot];
  if (json) args.push('--json');
  if (options.deep) args.push('--deep');
  const res = execaSync('python3', [script, ...args], {
    cwd: workchainRoot,
    reject: false,
    stdio: 'inherit',
  });
  process.exit(res.exitCode ?? 0);
}
