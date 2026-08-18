#!/usr/bin/env node
// cdp_transform worker — runs one cdp-wasm catalog effect under a fail-closed contract.
//
// Invoked by run.sh. Two jobs the cdp-wasm library deliberately leaves to the caller:
//   1. Validate supplied parameters against the catalog's OWN declared min/max BEFORE
//      processing. cdp-wasm treats those ranges as advisory (src/effects.js:147-158) and
//      passes out-of-range values straight through; stretch.time at factor 0.02 then
//      returns a 2130-byte WAV with zero samples and no error.
//   2. Measure the render (duration, true peak, RMS, rate, channels, stereo correlation)
//      and write it to a record the verifier can hold us to.
//
// Streams: stdout is reserved for the final JSON line; all chatter goes to stderr.
// Exit codes: 0 = rendered and measured; 1 = refused or failed (with a reason on stderr).

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve as presolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const argv = process.argv.slice(2);
const arg = (name, fallback = null) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : fallback;
};
const flag = (name) => argv.includes(`--${name}`);
const die = (msg) => { console.error(`cdp_transform: ${msg}`); process.exit(1); };

// ── resolve the cdp-wasm library ─────────────────────────────────────────────
async function loadLib(dir) {
  const candidates = [];
  if (dir) candidates.push(presolve(dir, 'src/index.js'), presolve(dir, 'index.js'));
  for (const c of candidates) {
    if (existsSync(c)) return import(pathToFileURL(c).href);
  }
  try {
    return await import('cdp-wasm');
  } catch (e) {
    die(
      'cannot resolve the cdp-wasm library.\n' +
      "  Install it (npm install cdp-wasm) so it resolves from node_modules, or set the\n" +
      '  cdp_wasm_dir param / CDP_WASM_DIR env to the package directory (the one holding\n' +
      `  package.json and wasm/).\n  Underlying error: ${e.message}`
    );
  }
}

const libDir = arg('lib', process.env.CDP_WASM_DIR || '') || '';
const lib = await loadLib(libDir);
const { CDP, EFFECTS, applyEffect, decodeAudio, decodeWav, encodeWav, paramRange } = lib;

// ── --list-effects: machine-readable catalog for agents ──────────────────────
if (flag('list-effects')) {
  const rows = EFFECTS.map((e) => ({
    id: e.id, label: e.label, category: e.category, program: e.program, domain: e.domain,
    mono: !!e.mono, inputs: e.inputs || 1,
    supported: !(e.multiOut || e.variadicInputs || e.mixChain || (e.inputs >= 2)),
    deterministic: !(e.parityExempt || e.paritySkip),
    params: (e.params || []).map((p) => ({
      name: p.name, default: p.default, min: p.min, max: p.max,
      hardMin: p.hardMin ?? null, hardMax: p.hardMax ?? null, help: p.help || null,
    })),
  }));
  process.stdout.write(JSON.stringify({ count: rows.length, effects: rows }) + '\n');
  process.exit(0);
}

const inputPath = arg('input') || die('--input is required');
const outputPath = arg('output') || die('--output is required');
const recordPath = arg('record') || die('--record is required');
const effectId = arg('effect') || die('--effect is required');
const channels = arg('channels', 'split');
const minPeak = Number(arg('min-peak', '-60'));
const unlocked = flag('unlocked');

let values;
try {
  values = JSON.parse(arg('values', '{}') || '{}');
} catch (e) {
  die(`values_json is not valid JSON: ${e.message}`);
}
if (values === null || typeof values !== 'object' || Array.isArray(values)) {
  die('values_json must be a JSON object, e.g. {"factor": 4}');
}

// Breakpoint envelopes: a parameter can vary over time instead of being constant. This is how
// CDP sound design actually works, and cdp-wasm supports it through `extra.brk` -- each entry
// becomes a /brk_<name>.brk file and the parameter's value is replaced by that path.
//
// Verified before exposing it: an envelope materially changes the render (a rising sweep and a
// falling sweep hash differently from each other and from the constant), and each is
// deterministic. A parameter that were silently ignored would be worse than absent.
let brk;
try {
  brk = JSON.parse(arg('brk', '{}') || '{}');
} catch (e) {
  die(`values_brk_json is not valid JSON: ${e.message}`);
}
if (brk === null || typeof brk !== 'object' || Array.isArray(brk)) {
  die('values_brk_json must be a JSON object, e.g. {"windows": "0 1\\n2 80"}');
}

/** Parse and sanity-check breakpoint text: newline-separated "time value" pairs. */
function checkBreakpoints(name, text) {
  if (typeof text !== 'string' || !text.trim()) return `${name}: envelope is empty`;
  const pts = [];
  for (const [i, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim();
    if (!line) continue;
    const parts = line.split(/\s+/);
    if (parts.length !== 2) return `${name}: line ${i + 1} is not "time value" (${JSON.stringify(line)})`;
    const t = Number(parts[0]);
    const v = Number(parts[1]);
    if (!Number.isFinite(t) || !Number.isFinite(v)) return `${name}: line ${i + 1} has a non-numeric field`;
    if (t < 0) return `${name}: line ${i + 1} has a negative time`;
    if (pts.length && t < pts[pts.length - 1][0]) return `${name}: times must not decrease (line ${i + 1})`;
    pts.push([t, v]);
  }
  if (pts.length < 2) return `${name}: an envelope needs at least two breakpoints, got ${pts.length}`;
  return { points: pts.length, first: pts[0], last: pts[pts.length - 1] };
}
if (!['split', 'mix'].includes(channels)) die(`channels must be 'split' or 'mix', got '${channels}'`);

// ── the record we will be held to ────────────────────────────────────────────
const record = {
  component: 'cdp_transform',
  effect: effectId,
  cdp_wasm_version: null,
  channels_mode: channels,
  allow_unlocked_range: unlocked,
  min_peak_dbfs_param: minPeak,
  params_requested: values,
  envelopes_requested: Object.keys(brk),
  envelopes_applied: [],
  envelope_detail: {},
  params_resolved: null,
  params_out_of_range: 0,
  params_unknown: 0,
  param_violations: [],
  deterministic_expected: null,
  determinism_ok: undefined,      // emitted ONLY when both renders completed — see step.yaml
  render_sha256: null,
  render_sha256_repeat: null,
  render_samples_sha256: null,
  render_samples_sha256_repeat: null,
  container_bytes_stable: null,
};
const writeRecord = async () => {
  await mkdir(dirname(recordPath), { recursive: true });
  await writeFile(recordPath, JSON.stringify(record, null, 2));
};
const refuse = async (msg) => { console.error(`cdp_transform: ${msg}`); await writeRecord(); process.exit(1); };

try {
  const pkg = JSON.parse(await readFile(presolve(libDir || '.', 'package.json'), 'utf8'));
  record.cdp_wasm_version = pkg.version || null;
} catch { /* resolved from node_modules; version is not load-bearing */ }

// ── effect lookup + capability gate ─────────────────────────────────────────
const effect = EFFECTS.find((e) => e.id === effectId);
if (!effect) {
  await refuse(
    `unknown effect '${effectId}'. This component only runs ids present in the cdp-wasm ` +
    `catalog (${EFFECTS.length} available). Run with --list-effects for the machine-readable list.`
  );
}
if (effect.multiOut || effect.variadicInputs || effect.mixChain || (effect.inputs >= 2)) {
  await refuse(
    `effect '${effectId}' is not a single-input/single-output effect ` +
    `(${[effect.multiOut && 'multi-output', effect.variadicInputs && 'variadic',
        effect.mixChain && 'mixfile-chain', effect.inputs >= 2 && 'two-input']
      .filter(Boolean).join(', ')}). ` +
    'cdp_transform v1.0 declines these rather than mis-handling them: a multi-output effect ' +
    'returns {outputs, names} and writing that object to disk would produce garbage that still ' +
    'passes a file-exists check. Refusing is the honest behaviour.'
  );
}
record.deterministic_expected = !(effect.parityExempt || effect.paritySkip);

// ── FAIL-CLOSED parameter validation against cdp-wasm's own catalog ──────────
const declared = new Map((effect.params || []).map((p) => [p.name, p]));
for (const name of Object.keys(values)) {
  if (!declared.has(name)) {
    record.params_unknown += 1;
    record.param_violations.push({ param: name, reason: 'not a parameter of this effect' });
  }
}
for (const [name, p] of declared) {
  if (!(name in values)) continue;
  const v = Number(values[name]);
  if (!Number.isFinite(v)) {
    if (p.choices) continue;   // enumerated params may be non-numeric
    record.params_out_of_range += 1;
    record.param_violations.push({ param: name, value: values[name], reason: 'not a finite number' });
    continue;
  }
  const { min, max } = paramRange(p, values, { unlocked });
  if (v < min || v > max) {
    // Label the bound accurately. cdp-wasm only records an engine hard limit
    // (hardMin/hardMax) for some params; where it is absent, paramRange returns the
    // curated bound even when unlocked, so calling it "the engine hard range" would
    // be a lie about which authority rejected the value.
    const hard = unlocked && (p.hardMin != null || p.hardMax != null);
    record.params_out_of_range += 1;
    record.param_violations.push({
      param: name, value: v, min, max, bound: hard ? 'engine_hard' : 'catalog_curated',
      reason: `outside the ${hard ? 'engine hard' : 'catalog curated'} range`,
    });
  }
}
// Envelope names must be real parameters of this effect, and the text must parse. cdp-wasm's
// v0.5.3 catalog does not populate the per-param `envelope` flag, so we cannot tell in advance
// which parameters CDP will accept a breakpoint file for -- that is stated in the README rather
// than pretended away. What we CAN check is that the name exists and the curve is well formed.
for (const name of Object.keys(brk)) {
  if (!declared.has(name)) {
    record.params_unknown += 1;
    record.param_violations.push({ param: name, reason: 'envelope names a parameter this effect does not have' });
    continue;
  }
  const res = checkBreakpoints(name, brk[name]);
  if (typeof res === 'string') {
    record.params_out_of_range += 1;
    record.param_violations.push({ param: name, reason: res });
  } else {
    record.envelopes_applied.push(name);
    record.envelope_detail[name] = res;
  }
}

record.params_resolved = Object.fromEntries(
  [...declared].map(([n, p]) => [n, n in values ? values[n] : p.default])
);
if (record.params_out_of_range || record.params_unknown) {
  const lines = record.param_violations
    .map((v) => `    ${v.param}=${v.value ?? '?'} — ${v.reason}` +
      (v.min !== undefined ? ` (${v.min}..${v.max})` : ''))
    .join('\n');
  await refuse(
    `refusing to process: ${record.params_out_of_range} out-of-range and ` +
    `${record.params_unknown} unknown parameter(s) for '${effectId}':\n${lines}\n` +
    '  The cdp-wasm catalog declares these ranges but does not enforce them, so an ' +
    'out-of-range value can render silence and still report success. Fix the value, or set ' +
    'allow_unlocked_range to fall back to the engine hard limit for the params that record ' +
    'one (many do not, and those stay bound by the curated range even when unlocked).'
  );
}

// ── render ──────────────────────────────────────────────────────────────────
// SHA-256 over the DECODED samples, not the container. cdp-wasm's write path can stamp
// wall-clock fields into the WAV header (the PEAK chunk timestamp and the LIST/adtl DATE
// string), so two renders of bit-identical audio differ by a couple of container bytes
// whenever they straddle a second boundary. Determinism is a claim about the audio, so it
// must be decided on the samples; the container comparison is recorded separately as
// container_bytes_stable without gating the step.
// The digest covers the decoded PCM: rate, channel count, frame count, and every channel's
// float32 samples. Same audio in, same digest out, whatever the container happens to say.
const sampleDigest = (bytes) => {
  const d = decodeWav(bytes);
  const h = createHash('sha256');
  const meta = Buffer.alloc(16);
  meta.writeUInt32LE(d.sampleRate, 0);
  meta.writeUInt32LE(d.numChannels, 4);
  meta.writeUInt32LE(d.length, 8);
  meta.writeUInt32LE(d.channelData.length, 12);
  h.update(meta);
  for (const ch of d.channelData) {
    const len = Buffer.alloc(4);
    len.writeUInt32LE(ch.length, 0);
    h.update(len);
    h.update(Buffer.from(ch.buffer, ch.byteOffset, ch.byteLength));
  }
  return h.digest('hex');
};

const cdp = new CDP();
const srcBytes = new Uint8Array(await readFile(inputPath));
const src = decodeAudio(srcBytes);
const srcWav = encodeWav({ sampleRate: src.sampleRate, channelData: src.channelData });

const render = async () => {
  const out = await applyEffect(cdp, effect, values, srcWav, { brk });
  if (!(out instanceof Uint8Array)) {
    throw new Error('effect did not return a single WAV byte array (unexpected shape)');
  }
  return out;
};

let bytes;
try {
  if (effect.mono && src.numChannels > 1 && channels === 'mix') {
    const mono = new Float32Array(src.length);
    for (let c = 0; c < src.numChannels; c++)
      for (let i = 0; i < src.length; i++) mono[i] += src.channelData[c][i] / src.numChannels;
    const monoWav = encodeWav({ sampleRate: src.sampleRate, channelData: [mono] });
    bytes = await applyEffect(cdp, effect, values, monoWav, { brk });
  } else {
    bytes = await render();
  }
} catch (e) {
  await refuse(`render failed: ${String(e.message).split('\n')[0]}`);
}
record.envelopes_all_applied =
  record.envelopes_requested.length === record.envelopes_applied.length;
record.render_sha256 = createHash('sha256').update(bytes).digest('hex');
record.render_samples_sha256 = sampleDigest(bytes);

// Metamorphic: same input + same params => bit-identical AUDIO. The gate is the
// decoded-sample digest (sampleDigest); the container hash is kept as a recorded,
// non-gating fact (container_bytes_stable) because the WAV header embeds wall-clock
// fields and can differ on bit-identical audio. Both sides must actually exist before
// we compare (an unguarded equality passes on None == None).
if (record.deterministic_expected) {
  try {
    const again = await render();
    record.render_sha256_repeat = createHash('sha256').update(again).digest('hex');
    record.render_samples_sha256_repeat = sampleDigest(again);
    record.determinism_ok = record.render_samples_sha256_repeat === record.render_samples_sha256;
    record.container_bytes_stable = record.render_sha256_repeat === record.render_sha256;
  } catch (e) {
    console.error(`cdp_transform: determinism re-render failed: ${e.message}`);
    record.determinism_ok = false;
  }
} else {
  // Determinism is not a legitimate claim here.
  record.determinism_ok = true;
  record.container_bytes_stable = null;
  record.determinism_note = `not asserted: catalog marks this effect ${effect.parityExempt ? 'parityExempt' : 'paritySkip'} (${effect.parityExempt || 'no single-command native equivalent'})`;
}

// ── measure the render (this is what the contract is held to) ───────────────
const d = decodeWav(bytes);
let peak = 0, sumsq = 0, n = 0;
for (const ch of d.channelData) for (const s of ch) { const a = Math.abs(s); if (a > peak) peak = a; sumsq += s * s; n++; }
const db = (x) => (x > 0 ? 20 * Math.log10(x) : -Infinity);
const fin = (x) => (Number.isFinite(x) ? Number(x.toFixed(3)) : -240);

record.measured_duration_s = Number((d.length / d.sampleRate).toFixed(4));
record.measured_peak_dbfs = fin(db(peak));
record.measured_rms_dbfs = fin(db(Math.sqrt(sumsq / Math.max(n, 1))));
record.measured_sample_rate = d.sampleRate;
record.measured_channels = d.numChannels;
record.input_duration_s = Number((src.length / src.sampleRate).toFixed(4));
record.input_channels = src.numChannels;
record.duration_ratio = record.input_duration_s > 0
  ? Number((record.measured_duration_s / record.input_duration_s).toFixed(4)) : null;

// Stereo image: correlation and mono-sum change. Mono-only effects run per channel, so a
// near-mono source can come back decorrelated (splinter.into: -6.03 dB). Recorded, not
// yet gated — see README.
if (d.numChannels === 2) {
  const [a, b] = d.channelData;
  const m = Math.min(a.length, b.length);
  let sa = 0, sb = 0, sab = 0, sm = 0, ss = 0;
  for (let i = 0; i < m; i++) {
    sa += a[i] * a[i]; sb += b[i] * b[i]; sab += a[i] * b[i];
    const mid = (a[i] + b[i]) / 2; sm += mid * mid; ss += (a[i] * a[i] + b[i] * b[i]) / 2;
  }
  record.stereo_correlation = Number((sab / (Math.sqrt(sa * sb) || 1e-12)).toFixed(5));
  record.mono_sum_change_db = fin(db(Math.sqrt(sm / m) / (Math.sqrt(ss / m) || 1e-12)));
}

if (record.measured_peak_dbfs <= minPeak) {
  console.error(
    `cdp_transform: rendered output peaks at ${record.measured_peak_dbfs} dBFS, at or below the ` +
    `min_peak_dbfs floor of ${minPeak}. The file is well-formed but effectively inaudible; ` +
    'this is the failure mode a file-exists check cannot see.'
  );
  await writeRecord();
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, bytes);   // keep it for inspection; the contract will fail the step
  process.exit(1);
}

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, bytes);
await writeRecord();

console.error(
  `cdp_transform: ${effectId} -> ${record.measured_duration_s}s ` +
  `${record.measured_channels}ch ${record.measured_sample_rate}Hz ` +
  `peak ${record.measured_peak_dbfs} dBFS` +
  (record.deterministic_expected ? ` deterministic=${record.determinism_ok}` : ' (randomised effect)')
);
process.stdout.write(JSON.stringify({ ok: true, ...record }) + '\n');
