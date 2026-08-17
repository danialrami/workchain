// cli/lib/cdp-catalog.js — resolution + formatting helpers for
// `workchain run-component <component> --list-effects` (issue #24).
//
// The listing is only worth anything if it sees the SAME catalog a real run would use,
// so resolveCdpLibrary mirrors components/cdp_transform/transform.mjs loadLib() exactly:
//
//   1. cdp_wasm_dir param  (--params-json '{"cdp_wasm_dir": "..."}') — wins over env
//   2. CDP_WASM_DIR environment variable
//   3. normal node_modules resolution (import 'cdp-wasm')
//
// and, like loadLib, a directory that does not hold the package falls through to normal
// resolution rather than erroring. Unit 02 owns transform.mjs; this module only reads its
// logic and mirrors it, so a listing and a run can never disagree about which ids exist.

import { existsSync, readFileSync } from 'fs';
import { dirname, resolve as presolve } from 'path';
import { createRequire } from 'module';
import { pathToFileURL } from 'url';

const require = createRequire(import.meta.url);

export class CdpCatalogError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CdpCatalogError';
  }
}

/** Load the package entry from an explicit directory (mirrors loadLib's candidate order). */
async function loadFromDir(dir) {
  for (const candidate of [presolve(dir, 'src/index.js'), presolve(dir, 'index.js')]) {
    if (existsSync(candidate)) return import(pathToFileURL(candidate).href);
  }
  return null;
}

/**
 * Read the installed cdp-wasm version. Informative only, never fatal: a version we
 * cannot locate resolves to null rather than failing the listing.
 */
function readVersion(repoDir) {
  try {
    if (repoDir) {
      const pkgPath = presolve(repoDir, 'package.json');
      if (!existsSync(pkgPath)) return null;
      return JSON.parse(readFileSync(pkgPath, 'utf-8')).version || null;
    }
    // Resolved via node_modules: walk up from the resolved main entry until we hit the
    // package.json that names cdp-wasm. The resolved path can point inside a symlinked
    // package whose main lives in src/ (e.g. .../node_modules/cdp-wasm/src/index.js), so
    // dirname() with no verification is wrong — the package root is the nearest ancestor
    // whose package.json declares the cdp-wasm name.
    let dir = dirname(require.resolve('cdp-wasm'));
    for (let i = 0; i < 6; i++) {
      const pkgPath = presolve(dir, 'package.json');
      if (existsSync(pkgPath)) {
        const meta = JSON.parse(readFileSync(pkgPath, 'utf-8'));
        if (meta.name === 'cdp-wasm') return meta.version || null;
      }
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Resolve the cdp-wasm library exactly as a cdp_transform run would.
 *
 * @param {object} [opts]
 * @param {string|null} [opts.cdpWasmDir]  the cdp_wasm_dir step param (highest precedence)
 * @param {Function} [opts.loadNormal]     normal node_modules resolution; injectable for tests
 * @returns {Promise<{lib: object, source: 'param'|'env'|'node_modules', dir: string|null, version: string|null}>}
 */
export async function resolveCdpLibrary({ cdpWasmDir = null, loadNormal } = {}) {
  const explicitDir = cdpWasmDir || null;
  const envDir = process.env.CDP_WASM_DIR || null;
  let source = explicitDir ? 'param' : envDir ? 'env' : 'node_modules';
  let dir = explicitDir || envDir || null;

  let lib = dir ? await loadFromDir(dir) : null;
  if (!lib) {
    // A dir that does not hold the package falls through to normal resolution —
    // the same fallthrough loadLib performs, so the listing never disagrees with a run.
    source = 'node_modules';
    dir = null;
    try {
      lib = loadNormal ? await loadNormal() : await import('cdp-wasm');
    } catch (err) {
      throw new CdpCatalogError(
        'cannot resolve the cdp-wasm library.\n' +
        '  Install it (npm install cdp-wasm) so it resolves from node_modules, or set the\n' +
        '  cdp_wasm_dir param / CDP_WASM_DIR env to the package directory (the one holding\n' +
        `  package.json and wasm/).\n  Underlying error: ${err.message}`
      );
    }
  }

  return { lib, source, dir, version: readVersion(dir) };
}

/**
 * Map raw EFFECTS entries to the listing shape: id, group (the id's program prefix —
 * catalog ids are `program.mode`, so the prefix is the CDP program family), output
 * count (1, or null for multiOut effects whose output count is only knowable at
 * runtime — e.g. housekeep.split emits one file per input channel), and each
 * parameter's min/max/default.
 */
export function formatEffects(effects) {
  return effects.map((e) => ({
    id: e.id,
    group: String(e.id).split('.')[0] || null,
    outputs: e.multiOut ? null : 1,
    params: (e.params || []).map((p) => ({
      name: p.name,
      min: typeof p.min === 'number' ? p.min : null,
      max: typeof p.max === 'number' ? p.max : null,
      default: p.default ?? null,
    })),
  }));
}

/**
 * Build the JSON-safe catalog document. Counts are derived from the actual EFFECTS
 * array — never hardcoded — so they track the installed catalog version.
 */
export function buildCatalog(resolved, { component }) {
  const effects = formatEffects(resolved.lib.EFFECTS || []);
  return {
    component,
    library: {
      name: 'cdp-wasm',
      version: resolved.version,
      resolved_from: resolved.source,
      dir: resolved.dir,
    },
    effect_count: effects.length,
    group_count: new Set(effects.map((e) => e.group)).size,
    effects,
  };
}

function paramText(p) {
  if (p.min === null && p.max === null) {
    return `${p.name}=${JSON.stringify(p.default)} (choices)`;
  }
  return `${p.name}=${JSON.stringify(p.default)} (${p.min ?? '?'}..${p.max ?? '?'})`;
}

/** Human form — same content as the JSON form, one line per effect. */
export function formatCatalogHuman(catalog) {
  const lines = [];
  lines.push(
    `${catalog.component} — cdp-wasm catalog: ${catalog.effect_count} effects across ${catalog.group_count} groups`
  );
  lines.push(
    `library: ${catalog.library.name} ${catalog.library.version ?? '?'} — resolved from ${catalog.library.resolved_from}` +
      (catalog.library.dir ? ` (${catalog.library.dir})` : '')
  );
  lines.push('');
  for (const e of catalog.effects) {
    const outputs = e.outputs === null ? 'multi' : String(e.outputs);
    const params = e.params.length
      ? e.params.map(paramText).join(', ')
      : '(no parameters)';
    lines.push(`${e.id.padEnd(30)} group=${String(e.group).padEnd(14)} outputs=${outputs.padEnd(5)} ${params}`.trimEnd());
  }
  lines.push('');
  return lines.join('\n');
}