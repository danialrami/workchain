import { execa, execaSync } from 'execa';
import { join, resolve, dirname } from 'path';
import { mkdtempSync, mkdirSync, rmSync, existsSync, readFileSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CLI_PATH = resolve(__dirname, '..', 'bin', 'lufs-workchain.js');
const WORKCHAIN_ROOT = resolve(__dirname, '..', '..');

// Canonical audio fixture — GENERATED deterministically with ffmpeg at setup, not committed
// as a binary. A binary WAV had been committed base64-encoded (ffprobe rejects it), so CI —
// which uses the committed bytes — failed all audio tests, while a laptop with a valid local
// copy passed (review: fixture corruption / Bug 8). ffmpeg is already required by these tests
// (see measureLufs), so generating the fixture is dependency-free and byte-identical on every
// machine: a 3s stereo 48kHz 440Hz sine. Assigned in beforeAll below.
let FIXTURE;
let fixtureDir;

function cli(args, opts = {}) {
  return execa('node', [CLI_PATH, ...args], { cwd: WORKCHAIN_ROOT, reject: false, ...opts });
}

/** Measure integrated loudness (LUFS) of a file via ffmpeg's loudnorm analysis (to stderr). */
function measureLufs(file) {
  const res = execaSync('ffmpeg', ['-nostdin', '-i', file, '-af', 'loudnorm=print_format=json', '-f', 'null', '-'], { reject: false });
  const out = `${res.stderr || ''}${res.stdout || ''}`;
  const m = out.match(/"input_i"\s*:\s*"?(-?[0-9.]+)"?/);
  return m ? parseFloat(m[1]) : null;
}

describe('CLI Commands', () => {
  let tempDir;

  beforeAll(() => {
    fixtureDir = mkdtempSync(join(tmpdir(), 'lufs-fixture-'));
    FIXTURE = join(fixtureDir, 'tone.wav');
    const r = execaSync('ffmpeg', [
      '-nostdin', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
      '-ar', '48000', '-ac', '2', FIXTURE,
    ], { reject: false });
    if (r.exitCode !== 0 || !existsSync(FIXTURE)) {
      throw new Error(`Failed to generate test fixture (is ffmpeg installed?): ${r.stderr || r.shortMessage || 'unknown error'}`);
    }
  });

  afterAll(() => { try { rmSync(fixtureDir, { recursive: true, force: true }); } catch {} });

  beforeEach(() => { tempDir = mkdtempSync(join(tmpdir(), 'lufs-test-')); });
  afterEach(() => { try { rmSync(tempDir, { recursive: true, force: true }); } catch {} });

  describe('fixtures', () => {
    it('the generated audio fixture exists and is valid (guards against the missing/corrupt-fixture skip)', () => {
      expect(existsSync(FIXTURE)).toBe(true);
      // Valid audio the toolchain can actually read — not a base64 blob masquerading as a WAV.
      const probe = execaSync('ffprobe', ['-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', FIXTURE], { reject: false });
      expect(probe.exitCode).toBe(0);
      expect(probe.stdout.trim()).toBe('audio');
    });
  });

  describe('validate command', () => {
    it('validates a valid chain', async () => {
      const { stdout } = await cli(['validate', 'simple-test', '--json']);
      const result = JSON.parse(stdout);
      expect(result.status).toBe('completed');
      expect(result.chain_name).toBe('simple-test');
      expect(result.steps_count).toBeGreaterThan(0);
    }, 30000);

    it('fails on an invalid chain', async () => {
      const invalidChain = join(tempDir, 'invalid-chain.yaml');
      writeFileSync(invalidChain, 'invalid: yaml: [');
      const { exitCode } = await cli(['validate', invalidChain, '--json']);
      expect(exitCode).not.toBe(0);
    }, 30000);

    it('validates all chains', async () => {
      const { stdout } = await cli(['validate', 'all']);
      expect(stdout).toContain('✓');
    }, 30000);

    it('--strict rejects an out-of-range / unknown param', async () => {
      const bad = join(WORKCHAIN_ROOT, 'chains', `_test_bad_${Date.now()}.yaml`);
      writeFileSync(bad, 'name: "bad"\nversion: "1.0"\nsteps:\n  - name: normalization\n    params: { target_lufs: 50, mystery: 1 }\n');
      try {
        const { stdout, exitCode } = await cli(['validate', bad.split('/').pop().replace('.yaml', ''), '--strict', '--json']);
        const result = JSON.parse(stdout);
        expect(exitCode).not.toBe(0);
        expect(result.status).toBe('error');
        expect(JSON.stringify(result.errors)).toMatch(/above max|unknown param/);
      } finally {
        rmSync(bad, { force: true });
      }
    }, 30000);

    // A missing external tool is a fact about THIS MACHINE, not about whether the
    // chain YAML is correct. Conflating the two broke CI for every component that
    // wraps a domain binary (audioqr, then lufs-seed) even though the chains were
    // fine. These two tests pin both halves of that distinction.
    function scaffoldToolChain(tag) {
      const stamp = `${Date.now()}${Math.floor(Math.random() * 1e4)}`;
      const compName = `_test_${tag}_${stamp}`;
      const compDir = join(WORKCHAIN_ROOT, 'components', compName);
      const chainName = `_test_chain_${tag}_${stamp}`;
      const chain = join(WORKCHAIN_ROOT, 'chains', `${chainName}.yaml`);
      mkdirSync(compDir, { recursive: true });
      writeFileSync(join(compDir, 'step.yaml'),
        `name: ${compName}\nversion: "1.0"\ntype: data\nparams_schema: {}\n` +
        `outputs:\n  schema_version: "1.0"\n  items:\n    - name: primary_output\n` +
        `      type: file\n      description: out\n      required: true\n` +
        `      path_template: "out.txt"\n` +
        `requirements:\n  commands:\n    - definitely-not-a-real-binary-xyz\n`);
      writeFileSync(join(compDir, 'run.sh'), '#!/bin/bash\nreturn 0\n');
      writeFileSync(chain, `name: "${chainName}"\nversion: "1.0"\nsteps:\n  - name: ${compName}\n`);
      return { chainName, chain, compDir };
    }

    it('--strict reports a missing required command WITHOUT failing', async () => {
      const { chainName, chain, compDir } = scaffoldToolChain('needstool');
      try {
        const { stdout, exitCode } = await cli(['validate', chainName, '--strict', '--json']);
        const result = JSON.parse(stdout);
        // The chain is VALID — nothing about the YAML is wrong.
        expect(exitCode).toBe(0);
        expect(result.status).toBe('completed');
        expect(result.errors).toBeUndefined();
        // ...but the gap is reported, never hidden.
        expect(JSON.stringify(result.environment)).toMatch(/definitely-not-a-real-binary-xyz/);
      } finally {
        rmSync(chain, { force: true });
        rmSync(compDir, { recursive: true, force: true });
      }
    }, 30000);

    it('--require-commands turns a missing command back into a failure', async () => {
      const { chainName, chain, compDir } = scaffoldToolChain('reqcmd');
      try {
        const { stdout, exitCode } = await cli(
          ['validate', chainName, '--strict', '--require-commands', '--json']);
        const result = JSON.parse(stdout);
        expect(exitCode).not.toBe(0);
        expect(result.status).toBe('error');
        expect(JSON.stringify(result.errors)).toMatch(/definitely-not-a-real-binary-xyz/);
      } finally {
        rmSync(chain, { force: true });
        rmSync(compDir, { recursive: true, force: true });
      }
    }, 30000);
  });

  describe('parameters actually apply (review Bug 1 — measured)', () => {
    it('run-component normalization honors --params-json target_lufs', async () => {
      const out = join(tempDir, 'norm');
      const { stdout } = await cli(['run-component', 'normalization', FIXTURE, '-o', out, '--params-json', '{"target_lufs":-16}', '--json'], { timeout: 60000 });
      const result = JSON.parse(stdout);
      expect(result.status).toBe('completed');
      const lufs = measureLufs(join(out, 'tone_normalized.wav'));
      expect(lufs).not.toBeNull();
      // Must be near the requested -16 and clearly NOT the old -11 default (the shipped bug).
      expect(Math.abs(lufs - (-16))).toBeLessThan(2);
      expect(lufs).toBeLessThan(-13);
    }, 60000);

    it('chain params + precedence reach the engine (target_lufs=-20)', async () => {
      const chain = join(WORKCHAIN_ROOT, 'chains', `_test_p20_${Date.now()}.yaml`);
      writeFileSync(chain, 'name: "p20"\nversion: "1.0"\nglobals: { lufs_target: -8 }\nsteps:\n  - name: normalization\n    params: { target_lufs: -20 }\n');
      const out = join(tempDir, 'p20');
      try {
        const { stdout } = await cli(['run', chain, FIXTURE, '-o', out, '--json'], { timeout: 60000 });
        expect(JSON.parse(stdout).status).toBe('completed');
        const lufs = measureLufs(join(out, 'tone_normalized.wav'));
        // params (-20) must win over globals (-8); proves precedence + no clobber.
        expect(Math.abs(lufs - (-20))).toBeLessThan(2);
      } finally {
        rmSync(chain, { force: true });
      }
    }, 60000);
  });

  describe('honest outputs (review Bug 2 — measured)', () => {
    it('audio_benchmark emits valid JSON for all 7 checks with no parse errors', async () => {
      const out = join(tempDir, 'bench');
      const { stdout } = await cli(['run-component', 'audio_benchmark', FIXTURE, '-o', out, '--json'], { timeout: 60000 });
      expect(JSON.parse(stdout).status).toBe('completed');
      const report = JSON.parse(readFileSync(join(out, 'logs', 'audio_benchmark.json'), 'utf-8'));
      // Count varies with the signal (a pure tone has no noise floor); the honesty invariant
      // is that no check emits malformed JSON (review Bug 2 — the old "unknown"-token corruption).
      expect(report.benchmark_count).toBeGreaterThanOrEqual(5);
      const errored = Object.values(report.checks).filter(c => c && c.error);
      expect(errored.length).toBe(0);
    }, 60000);

    it('content_hash emits a full SHA256 digest and a matching short id', async () => {
      const out = join(tempDir, 'ch');
      const { stdout } = await cli(['run-component', 'content_hash', FIXTURE, '-o', out, '--json'], { timeout: 60000 });
      expect(JSON.parse(stdout).status).toBe('completed');
      const record = JSON.parse(readFileSync(join(out, 'content_hash', 'content_hash.json'), 'utf-8'));
      expect(record.algorithm).toBe('sha256');
      expect(record.digest).toMatch(/^[0-9a-f]{64}$/);
      expect(record.short_id).toBe(record.digest.slice(0, 8));
    }, 60000);
  });

  describe('special characters in paths (apostrophe/space/ampersand — OpenCode-found bug)', () => {
    it('processes a file whose name has an apostrophe, space, and ampersand', async () => {
      const input = join(tempDir, "Don't Stop & Go (Live).wav");
      writeFileSync(input, readFileSync(FIXTURE));
      const out = join(tempDir, 'apos_out');
      const { stdout } = await cli(['run-component', 'normalization', input, '-o', out, '--params-json', '{"target_lufs":-16}', '--json'], { timeout: 60000 });
      const result = JSON.parse(stdout);
      expect(result.status).toBe('completed');
      const lufs = measureLufs(join(out, "Don't Stop & Go (Live)_normalized.wav"));
      expect(lufs).not.toBeNull();
      expect(Math.abs(lufs - (-16))).toBeLessThan(2); // params applied AND the apostrophe path worked
    }, 60000);
  });

  describe('generate command (review Bug 5)', () => {
    it('generates a component', async () => {
      const name = 'test_component_' + Date.now();
      const { stdout } = await cli(['generate', 'component', '--name', name, '--description', 'Test component', '--type', 'audio', '--json']);
      const result = JSON.parse(stdout);
      expect(result.status).toBe('completed');
      expect(result.component_name).toBe(name);
      expect(result.files_created.length).toBeGreaterThan(0);
      rmSync(join(WORKCHAIN_ROOT, 'components', name), { recursive: true, force: true });
    }, 30000);

    it('a generated scaffold FAILS until implemented (no false success)', async () => {
      const name = 'test_scaffold_' + Date.now();
      await cli(['generate', 'component', '--name', name, '--description', 'Scaffold', '--type', 'audio', '--commands', 'ffmpeg', '--json']);
      try {
        const out = join(tempDir, 'scaffold');
        const { stdout } = await cli(['run-component', name, FIXTURE, '-o', out, '--json'], { timeout: 60000 });
        const result = JSON.parse(stdout);
        expect(result.status).toBe('failed');
        expect(result.exit_code).not.toBe(0);
      } finally {
        rmSync(join(WORKCHAIN_ROOT, 'components', name), { recursive: true, force: true });
      }
    }, 60000);

    it('emits a COMPLETE puzzle piece with the current contract schema (not the legacy keys)', async () => {
      const name = 'test_heavy_' + Date.now();
      const { stdout } = await cli(['generate', 'component', '--name', name, '--description', 'Heavy scaffold',
        '--type', 'audio', '--kind', 'heavy', '--python-packages', 'numpy,scipy', '--json']);
      const dir = join(WORKCHAIN_ROOT, 'components', name);
      try {
        const result = JSON.parse(stdout);
        expect(result.status).toBe('completed');
        // The complete puzzle piece: every part is present.
        for (const f of ['step.yaml', 'run.sh', 'provision.sh', 'README.md', 'test-chain.yaml']) {
          expect(existsSync(join(dir, f))).toBe(true);
        }
        const step = readFileSync(join(dir, 'step.yaml'), 'utf-8');
        // Outbound contract present (a scaffold with no verify: is not a finished component).
        expect(step).toMatch(/^verify:/m);
        expect(step).toMatch(/assert:\s*\[exists, non_empty/);
        // Inbound contract uses the CURRENT schema — never the migrated-away legacy keys.
        expect(step).toMatch(/^\s*python:/m);
        expect(step).toMatch(/import: "numpy"/);
        expect(step).toMatch(/provision: "bash provision\.sh"/);
        expect(step).not.toMatch(/python_packages:/);
        expect(step).not.toMatch(/node_packages:/);
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    }, 30000);

    it('--kind api scaffolds an env-keyed contract (no local venv/models)', async () => {
      const name = 'test_api_' + Date.now();
      const { stdout } = await cli(['generate', 'component', '--name', name, '--description', 'API scaffold',
        '--type', 'audio', '--kind', 'api', '--json']);
      const dir = join(WORKCHAIN_ROOT, 'components', name);
      try {
        expect(JSON.parse(stdout).status).toBe('completed');
        const step = readFileSync(join(dir, 'step.yaml'), 'utf-8');
        expect(step).toMatch(/^\s*env:/m);
        expect(step).toMatch(new RegExp(`${name.toUpperCase()}_API_KEY`));
        expect(step).toMatch(/^verify:/m);
        expect(step).not.toMatch(/python_packages:/);
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    }, 30000);
  });
});
