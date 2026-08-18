/**
 * import-audit.test.js — the F1 tripwire (issue #7 step 5).
 *
 * globby sat in both manifests for 24 packages with zero call sites. The check that
 * catches that class of drift is an import audit: every bare `import`/`require` in the
 * published CLI must resolve to a package the manifests declare. This test fails the
 * moment production code references a package that is not declared — the day globby's
 * last call site was deleted, this test would have gone red.
 *
 * The dependency list must also live in EXACTLY ONE place (the root package.json, the
 * only manifest npm consults when installing the published package), so this test
 * additionally asserts cli/package.json declares no dependencies of its own.
 *
 * Scope: every .js/.mjs file under cli/bin, cli/commands, cli/lib and cli/test, plus
 * cli/vitest.config.js. Node builtins ('node:*') and relative imports are inherently
 * fine. Allowed packages come from one source of truth:
 *   - root package.json `dependencies`            (production)
 *   - root package.json `optionalDependencies`    (cdp-wasm — heavy, opt-in, correct)
 *   - cli/package.json `devDependencies`          (vitest — test tooling only)
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join, resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { builtinModules } from 'module';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CLI_ROOT = resolve(__dirname, '..');
const REPO_ROOT = resolve(CLI_ROOT, '..');

const SCAN_DIRS = ['bin', 'commands', 'lib', 'test'];

function collectJsFiles() {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      const st = statSync(full);
      if (st.isDirectory()) walk(full);
      else if (/\.(c|m)?js$/.test(entry)) files.push(full);
    }
  };
  for (const d of SCAN_DIRS) walk(join(CLI_ROOT, d));
  files.push(join(CLI_ROOT, 'vitest.config.js'));
  return files;
}

/**
 * Strip line and block comments so prose cannot trip the audit (cdp-catalog.js's header
 * mentions `import 'cdp-wasm'` inside a comment — comments are not imports).
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
}

/** Pull every string literal used as a module specifier: static, dynamic, require. */
function extractSpecifiers(src) {
  const clean = stripComments(src);
  const specifiers = [];
  const patterns = [
    // import x from '…'  /  import '…'
    /import\s+(?:[^'"]+?\s+from\s+)?['"]([^'"]+)['"]/g,
    // import('…')
    /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
    // require('…') / require.resolve('…')
    /require\s*(?:\.resolve)?\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(clean)) !== null) specifiers.push(m[1]);
  }
  return specifiers;
}

/** Bare specifier → package name: '@scope/pkg/sub' → '@scope/pkg', 'pkg/sub' → 'pkg'. */
function packageName(spec) {
  const parts = spec.split('/');
  return spec.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0];
}

// Node builtins, both spellings: the modern 'node:fs' and the legacy bare 'fs'/'fs/promises'.
const BUILTINS = new Set(['node:', ...builtinModules]);

const isBare = (spec) =>
  !BUILTINS.has(spec) &&
  !spec.startsWith('node:') &&
  !spec.startsWith('.') && !spec.startsWith('/') &&
  !spec.startsWith('file:') && !spec.startsWith('data:');

/** The one source of truth: root dependencies + optionalDependencies + cli devDeps. */
function declaredPackages() {
  const root = JSON.parse(readFileSync(join(REPO_ROOT, 'package.json'), 'utf-8'));
  const cli = JSON.parse(readFileSync(join(CLI_ROOT, 'package.json'), 'utf-8'));
  return new Set([
    ...Object.keys(root.dependencies || {}),
    ...Object.keys(root.optionalDependencies || {}),
    ...Object.keys(cli.devDependencies || {}),
  ]);
}

describe('cli dependency audit (issue #7 step 5)', () => {
  it('declares dependencies in exactly one place: the root manifest', () => {
    const root = JSON.parse(readFileSync(join(REPO_ROOT, 'package.json'), 'utf-8'));
    const cli = JSON.parse(readFileSync(join(CLI_ROOT, 'package.json'), 'utf-8'));
    expect(root.dependencies).toBeDefined();
    // cdp-wasm stays an optional dependency — heavy capability, opt-in (issue non-goal).
    expect(root.optionalDependencies && root.optionalDependencies['cdp-wasm']).toBeTruthy();
    // cli/package.json is shipped as data; it must not carry a second copy of the list.
    expect(cli.dependencies).toBeUndefined();
    expect(cli.optionalDependencies).toBeUndefined();
  });

  it('every import/require in cli/ resolves to a declared dependency', () => {
    const declared = declaredPackages();
    const offenders = [];
    for (const file of collectJsFiles()) {
      const src = readFileSync(file, 'utf-8');
      for (const spec of extractSpecifiers(src)) {
        if (!isBare(spec)) continue;
        const pkg = packageName(spec);
        if (!declared.has(pkg)) {
          offenders.push(`${file}: "${spec}" (package "${pkg}" is not declared anywhere)`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});