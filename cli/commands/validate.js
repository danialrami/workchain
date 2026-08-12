import { existsSync as exists } from 'fs';
import { join } from 'path';
import { resolveWorkchainRoot } from '../lib/workchain.js';
import { wy } from '../lib/wyaml.js';
import { formatResult } from '../lib/formatter.js';
import { CliError } from '../lib/utils.js';

/**
 * Validate chain YAML files. Delegates to lib/workchain_yaml.py (single parser).
 *
 * With --strict it also checks every step's params against the component's schema
 * (unknown keys, type, numeric range) and REPORTS any declared command missing from
 * this machine's PATH.
 *
 * Missing commands are reported as `environment`, not `errors`, and do not fail the
 * run. Whether `audioqr` or `lufs-seed` happens to be installed here is a fact about
 * THIS MACHINE, not about whether the chain YAML is correct — a CI runner and a Mac
 * disagree about the same unchanged file. Authoring errors travel with the file;
 * environment findings do not. Pass --require-commands to gate on them too, which is
 * what you want immediately before executing a chain on the box that will run it.
 *
 * Runtime safety is unaffected: the engine's preflight still fails closed before any
 * component executes.
 */
export async function validateCommand(chainName, options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || false;
  const strict = !!options.strict;
  const requireCommands = !!options.requireCommands;

  try {
    const workchainRoot = resolveWorkchainRoot();

    if (chainName === 'all') {
      const chains = wy(workchainRoot, ['list-chains', workchainRoot]) || [];
      const results = [];
      let allPassed = true;
      for (const c of chains) {
        const r = validateOne(workchainRoot, c.path, c.name, strict, requireCommands);
        results.push(r);
        if (r.status !== 'completed') allPassed = false;
      }
      const envCount = results.reduce((n, r) => n + (r.environment || []).length, 0);
      if (json) {
        console.log(formatResult({
          status: allPassed ? 'completed' : 'error',
          command: 'validate',
          strict,
          require_commands: requireCommands,
          chains_validated: results.length,
          environment_findings: envCount,
          results,
        }, { json }));
      } else {
        console.log(`Validated ${results.length} chain(s)${strict ? ' (strict)' : ''}`);
        for (const r of results) {
          // '~' = the chain is valid but this machine cannot run it as-is.
          const mark = r.status !== 'completed' ? '✗' : ((r.environment || []).length ? '~' : '✓');
          console.log(`  ${mark} ${r.chain_name}`);
          for (const err of r.errors || []) console.log(`    - ${err}`);
          for (const env of r.environment || []) console.log(`    ~ ${env}`);
        }
        if (envCount && !requireCommands) {
          console.log(`\n${envCount} environment finding(s): the chain(s) are valid, but this ` +
            `machine is missing tools they declare. Not a failure — install the tool where you ` +
            `intend to run it, or use --require-commands to gate on availability.`);
        }
      }
      if (!allPassed) process.exit(1);
      return;
    }

    // Single chain
    let chainFile = join(workchainRoot, 'chains', `${chainName}.yaml`);
    if (!exists(chainFile)) {
      const alt = join(workchainRoot, 'chains', `${chainName}.yml`);
      if (exists(alt)) chainFile = alt;
      else throw new CliError(2, `Chain '${chainName}' not found in chains/`);
    }

    const result = validateOne(workchainRoot, chainFile, chainName, strict, requireCommands);

    if (json) {
      console.log(formatResult(result, { json }));
    } else if (result.status === 'completed') {
      console.log(`✓ Chain '${result.chain_name}' is valid${strict ? ' (strict)' : ''}`);
      for (const env of result.environment || []) console.log(`  ~ ${env}`);
      if ((result.environment || []).length) {
        console.log(`  (valid, but this machine is missing a declared tool — ` +
          `install it where you intend to run, or use --require-commands to gate on it)`);
      }
    } else {
      console.log(`✗ Chain '${result.chain_name}' validation failed`);
      for (const err of result.errors || []) console.log(`  - ${err}`);
      for (const env of result.environment || []) console.log(`  ~ ${env}`);
    }

    if (result.status !== 'completed') process.exit(1);
  } catch (err) {
    if (err instanceof CliError) {
      const result = { status: 'error', command: 'validate', code: err.code, message: err.message };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    const result = { status: 'error', command: 'validate', code: 1, message: `Unexpected error: ${err.message}` };
    console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
    process.exit(1);
  }
}

function validateOne(workchainRoot, chainFile, chainName, strict, requireCommands) {
  const args = ['validate', workchainRoot, chainFile];
  if (strict) args.push('--strict');
  if (requireCommands) args.push('--require-commands');
  const res = wy(workchainRoot, args);
  return {
    status: res.valid ? 'completed' : 'error',
    command: 'validate',
    chain_file: chainFile,
    chain_name: chainName,
    display_name: res.name || undefined,
    steps_count: (res.steps || []).length,
    strict,
    errors: res.errors && res.errors.length ? res.errors : undefined,
    environment: res.environment && res.environment.length ? res.environment : undefined,
  };
}
