import { describe, it, expect, afterEach } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import {
  resolveCdpLibrary,
  CdpCatalogError,
  formatEffects,
  buildCatalog,
  formatCatalogHuman,
} from '../lib/cdp-catalog.js';

// A small, hand-checkable catalog standing in for cdp-wasm's EFFECTS: covers a
// plain numeric-param effect, a multiOut effect (output count only knowable at
// runtime), a choices-only param (no numeric min/max), a param whose default
// is 0 (a falsy-but-real value that must survive the mapping), and the two
// stereoUnsafe classes from the installed catalog — setsChannels: true and
// input: 'stereo'.
const FIXTURE = [
  {
    id: 'blur.blur',
    params: [
      { name: 'windows', min: 1, max: 100, default: 10 },
      { name: 'mode', label: 'Mode', choices: [['a', 'mix'], ['b', 'split']], default: 'mix' },
    ],
  },
  { id: 'housekeep.split', multiOut: true, params: [] },
  { id: 'stretch.time', params: [{ name: 'factor', min: 0.25, max: 4, default: 1 }] },
  { id: 'stretch.octave', params: [{ name: 'octaves', min: 0, max: 24, default: 0 }] },
  { id: 'reverb.reverb', setsChannels: true, params: [] },
  { id: 'phase.stereo', input: 'stereo', params: [] },
];

function fakePackage(tag) {
  const dir = mkdtempSync(join(tmpdir(), `cdp-catalog-${tag}-`));
  mkdirSync(join(dir, 'src'), { recursive: true });
  const tagged = FIXTURE.map((e) => ({ ...e, id: `${tag}.${e.id}` }));
  writeFileSync(join(dir, 'src', 'index.js'), `export const EFFECTS = ${JSON.stringify(tagged)};\n`);
  writeFileSync(join(dir, 'package.json'), JSON.stringify({ name: 'cdp-wasm', version: '0.0.0-' + tag }));
  return dir;
}

const envBackup = { has: false, value: undefined };

afterEach(() => {
  if (envBackup.has) process.env.CDP_WASM_DIR = envBackup.value;
  else delete process.env.CDP_WASM_DIR;
  envBackup.has = false;
});

function setEnv(v) {
  envBackup.has = Object.prototype.hasOwnProperty.call(process.env, 'CDP_WASM_DIR');
  envBackup.value = process.env.CDP_WASM_DIR;
  if (v === undefined) delete process.env.CDP_WASM_DIR;
  else process.env.CDP_WASM_DIR = v;
}

describe('formatEffects', () => {
  it('maps id, group (id prefix), output count and per-parameter min/max/default', () => {
    const rows = formatEffects(FIXTURE);
    expect(rows).toEqual([
      {
        id: 'blur.blur',
        group: 'blur',
        outputs: 1,
        stereoUnsafe: false,
        params: [
          { name: 'windows', min: 1, max: 100, default: 10 },
          { name: 'mode', min: null, max: null, default: 'mix' },
        ],
      },
      { id: 'housekeep.split', group: 'housekeep', outputs: null, stereoUnsafe: false, params: [] },
      { id: 'stretch.time', group: 'stretch', outputs: 1, stereoUnsafe: false, params: [{ name: 'factor', min: 0.25, max: 4, default: 1 }] },
      { id: 'stretch.octave', group: 'stretch', outputs: 1, stereoUnsafe: false, params: [{ name: 'octaves', min: 0, max: 24, default: 0 }] },
      { id: 'reverb.reverb', group: 'reverb', outputs: 1, stereoUnsafe: true, params: [] },
      { id: 'phase.stereo', group: 'phase', outputs: 1, stereoUnsafe: true, params: [] },
    ]);
  });

  it('never drops a falsy-but-real default (0 must survive)', () => {
    const [row] = formatEffects([{ id: 'x.y', params: [{ name: 'gain', min: 0, max: 1, default: 0 }] }]);
    expect(row.params[0].default).toBe(0);
  });

  it('derives stereoUnsafe from setsChannels or input:stereo, never from mono:true alone', () => {
    const byId = Object.fromEntries(formatEffects(FIXTURE).map((r) => [r.id, r]));
    expect(byId['reverb.reverb'].stereoUnsafe).toBe(true); // setsChannels: true
    expect(byId['phase.stereo'].stereoUnsafe).toBe(true);  // input: 'stereo'
    expect(byId['blur.blur'].stereoUnsafe).toBe(false);    // channel-preserving control
    // mono-only effects run per channel and preserve the source's channel count.
    // Flagging them would conflate the input contract (mono) with the output
    // contract (stereoUnsafe), so they must stay unflagged.
    const [monoOnly] = formatEffects([{ id: 'splinter.into', mono: true, params: [] }]);
    expect(monoOnly.stereoUnsafe).toBe(false);
  });
});

describe('buildCatalog', () => {
  it('derives effect_count and group_count from the actual catalog (never hardcoded)', () => {
    const catalog = buildCatalog(
      { lib: { EFFECTS: FIXTURE }, source: 'node_modules', dir: null, version: '9.9.9' },
      { component: 'cdp_transform' }
    );
    expect(catalog.effect_count).toBe(6);
    expect(catalog.group_count).toBe(5); // stretch.* appears twice; groups are deduped
    expect(catalog.effects.length).toBe(catalog.effect_count);
  });

  it('has a stable key shape (no timestamps, fixed order)', () => {
    const catalog = buildCatalog(
      { lib: { EFFECTS: FIXTURE }, source: 'env', dir: '/tmp/fake', version: '0.6.0' },
      { component: 'cdp_transform' }
    );
    expect(Object.keys(catalog)).toEqual(['component', 'library', 'effect_count', 'group_count', 'effects']);
    expect(Object.keys(catalog.library)).toEqual(['name', 'version', 'resolved_from', 'dir']);
    expect(catalog.library).toEqual({ name: 'cdp-wasm', version: '0.6.0', resolved_from: 'env', dir: '/tmp/fake' });
    // Two builds of the same catalog are byte-identical.
    const again = buildCatalog(
      { lib: { EFFECTS: FIXTURE }, source: 'env', dir: '/tmp/fake', version: '0.6.0' },
      { component: 'cdp_transform' }
    );
    expect(JSON.stringify(catalog)).toBe(JSON.stringify(again));
  });
});

describe('formatCatalogHuman', () => {
  it('is deterministic and carries the same content as the JSON form', () => {
    const catalog = buildCatalog(
      { lib: { EFFECTS: FIXTURE }, source: 'env', dir: '/tmp/fake', version: '0.6.0' },
      { component: 'cdp_transform' }
    );
    const human = formatCatalogHuman(catalog);
    expect(formatCatalogHuman(catalog)).toBe(human); // deterministic
    expect(human).toContain('6 effects across 5 groups');
    expect(human).toContain('resolved from env (/tmp/fake)');
    for (const row of catalog.effects) expect(human).toContain(row.id); // every effect
    expect(human).toContain('windows=10 (1..100)');     // numeric range
    expect(human).toContain('mode="mix" (choices)');    // choices-only param
    expect(human).toContain('outputs=multi');           // multiOut
    expect(human).toContain('outputs=1');               // single-output
    expect(human).toContain('stereoUnsafe');            // flagged effect marker (setsChannels / input:stereo)
  });
});

describe('resolveCdpLibrary — resolution order mirrors a real run', () => {
  it('uses the cdp_wasm_dir param directory when given', async () => {
    const dir = fakePackage('paramA');
    try {
      const resolved = await resolveCdpLibrary({ cdpWasmDir: dir });
      expect(resolved.source).toBe('param');
      expect(resolved.dir).toBe(dir);
      expect(resolved.version).toBe('0.0.0-paramA');
      expect(resolved.lib.EFFECTS.length).toBe(FIXTURE.length);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('param wins over CDP_WASM_DIR env', async () => {
    const dirA = fakePackage('pA');
    const dirB = fakePackage('pB');
    setEnv(dirB);
    try {
      const resolved = await resolveCdpLibrary({ cdpWasmDir: dirA });
      expect(resolved.source).toBe('param');
      expect(resolved.lib.EFFECTS[0].id.startsWith('pA.')).toBe(true); // param catalog, not env's
      expect(resolved.version).toBe('0.0.0-pA');
    } finally {
      rmSync(dirA, { recursive: true, force: true });
      rmSync(dirB, { recursive: true, force: true });
    }
  });

  it('falls back to CDP_WASM_DIR env when no param is given', async () => {
    const dir = fakePackage('envB');
    setEnv(dir);
    try {
      const resolved = await resolveCdpLibrary({});
      expect(resolved.source).toBe('env');
      expect(resolved.dir).toBe(dir);
      expect(resolved.version).toBe('0.0.0-envB');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('a dir that does not hold the package falls through to normal resolution (like loadLib)', async () => {
    setEnv('/nonexistent/cdp-wasm-dir');
    const normal = { EFFECTS: FIXTURE, from_normal: true };
    const resolved = await resolveCdpLibrary({ loadNormal: async () => normal });
    expect(resolved.source).toBe('node_modules');
    expect(resolved.dir).toBe(null);
    expect(resolved.lib).toBe(normal); // fell through, exactly like transform.mjs loadLib()
  });

  it('fails honestly (CdpCatalogError) when resolution fails everywhere', async () => {
    setEnv('/nonexistent/cdp-wasm-dir');
    await expect(
      resolveCdpLibrary({ loadNormal: async () => { throw new Error('Cannot find package'); } })
    ).rejects.toBeInstanceOf(CdpCatalogError);
    await expect(
      resolveCdpLibrary({ loadNormal: async () => { throw new Error('Cannot find package'); } })
    ).rejects.toThrow(/cannot resolve the cdp-wasm library/);
  });

  it('a bogus param dir falls through past the env to normal resolution (loadLib semantics)', async () => {
    // run.sh: CDP_WASM_DIR=$(get_param "cdp_wasm_dir" "${CDP_WASM_DIR:-}") — once the param is
    // present it wins outright, and loadLib ignores the env entirely; a bogus param dir
    // falls straight through to node_modules. The env must NOT be consulted here.
    const envDir = fakePackage('pB');
    setEnv(envDir);
    try {
      const normal = { EFFECTS: FIXTURE };
      const resolved = await resolveCdpLibrary({ cdpWasmDir: '/nonexistent/param-dir', loadNormal: async () => normal });
      expect(resolved.source).toBe('node_modules');
      expect(resolved.lib).toBe(normal);
    } finally {
      rmSync(envDir, { recursive: true, force: true });
    }
  });
});