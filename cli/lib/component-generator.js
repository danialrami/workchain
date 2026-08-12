/**
 * Component Generator (Node.js)
 *
 * Emits a COMPLETE PUZZLE PIECE: a component that already carries the inbound
 * `requirements:` contract, the outbound `verify:` contract, a provision.sh, a
 * test-chain stub, and a README — so an author (human or agent) fills in intent,
 * not plumbing. The schema shape mirrors `components/_template/` (the canonical
 * scaffold); a fresh scaffold FAILS until implemented (honest-failure sentinel in
 * run.sh), so an agent can never mistake an unimplemented piece for a working one.
 *
 * `--kind light|heavy|api` shapes the requirements/provision/verify:
 *   light  — PATH commands only (ffmpeg + stdlib); ships in the lean npm core.
 *   heavy  — a component-local Python venv (numpy/scipy/… via provision.sh).
 *   api    — delegates to an external HTTP API; declares an env-var key.
 *
 * Stdlib-only (no execa) so the generator is trivially testable and carries no
 * runtime deps of its own.
 */

import { writeFileSync, mkdirSync, existsSync, readFileSync, chmodSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const KINDS = ['light', 'heavy', 'api'];

const INPUT_TYPES = {
  audio: ['wav', 'mp3', 'aiff', 'aif', 'flac', 'm4a', 'ogg'],
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp'],
  video: ['mp4', 'mov', 'avi', 'mkv', 'webm'],
};
const MIME = { audio: 'audio/wav', image: 'image/png', video: 'video/mp4', data: 'text/plain', text: 'text/plain' };
const OUT_EXT = { audio: '{input_ext}', image: 'png', video: 'mp4', data: 'txt', text: 'txt' };

/**
 * Generate a new component.
 */
export async function generateComponent(options, workchainRoot) {
  const {
    name,
    description,
    type = 'audio',
    params = [],
    commands = '',
    pythonPackages = '',
    nodePackages = '',
    dependencies = [],
    outputSubdir = '',
    kind = '',
  } = options;

  validateName(name, workchainRoot);

  const resolvedKind = resolveKind(kind, { pythonPackages, nodePackages });

  const componentDir = join(workchainRoot, 'components', name);
  if (existsSync(componentDir)) {
    throw new Error(`Component '${name}' already exists in components/`);
  }
  mkdirSync(componentDir, { recursive: true });

  const ctx = { name, description, type, params, commands, pythonPackages, nodePackages, dependencies, outputSubdir, kind: resolvedKind };

  const files = {
    'step.yaml': generateStepYaml(ctx),
    'run.sh': generateRunSh(ctx),
    'provision.sh': generateProvisionSh(ctx),
    'README.md': generateReadme(ctx),
    'test-chain.yaml': generateTestChain(ctx),
  };

  const createdFiles = [];
  for (const [filename, content] of Object.entries(files)) {
    const filePath = join(componentDir, filename);
    writeFileSync(filePath, content);
    createdFiles.push(filePath);
  }

  // Executable scaffolds — no execa needed.
  chmodSync(join(componentDir, 'run.sh'), 0o755);
  chmodSync(join(componentDir, 'provision.sh'), 0o755);

  return {
    status: 'completed',
    component_name: name,
    component_path: componentDir,
    kind: resolvedKind,
    files_created: createdFiles,
  };
}

function resolveKind(kind, { pythonPackages }) {
  if (kind) {
    if (!KINDS.includes(kind)) {
      throw new Error(`Invalid --kind '${kind}'. Use one of: ${KINDS.join(', ')}`);
    }
    return kind;
  }
  // Infer: python packages ⇒ heavy; otherwise light. `api` is always explicit.
  return pythonPackages && pythonPackages.length > 0 ? 'heavy' : 'light';
}

function validateName(name, workchainRoot) {
  if (!name) throw new Error('Component name is required');
  if (!/^[a-z][a-z0-9_]*$/.test(name)) {
    throw new Error(`Invalid name '${name}'. Use snake_case (lowercase with underscores, starting with a letter)`);
  }
  if (name.startsWith('_')) {
    throw new Error(`Component name '${name}' cannot start with '_' (reserved for templates)`);
  }
  const componentDir = join(workchainRoot, 'components', name);
  if (existsSync(componentDir)) {
    throw new Error(`Component '${name}' already exists in components/`);
  }
}

function splitList(s) {
  return (s || '').split(',').map((x) => x.trim()).filter(Boolean);
}

function outputPathTemplate({ name, type, outputSubdir }) {
  const ext = OUT_EXT[type] || 'out';
  let p = `{input_name}_${name}.${ext}`;
  if (outputSubdir) {
    const sub = outputSubdir.endsWith('/') ? outputSubdir : `${outputSubdir}/`;
    p = `${sub}${p}`;
  }
  return p;
}

/**
 * step.yaml — the two-sided contract. Schema shape mirrors components/_template/step.yaml
 * (new `requirements:` classes + `verify:` block); never the legacy python_packages key.
 */
function generateStepYaml(ctx) {
  const { name, description, type, params, outputSubdir } = ctx;
  const L = [];

  L.push(`name: ${name}`);
  L.push(`description: "${description.replace(/"/g, '\\"')}"`);
  L.push(`version: "1.0"`);
  L.push(``);
  L.push(`type: ${type}`);

  if (INPUT_TYPES[type]) {
    L.push(``);
    L.push(`input_types:`);
    for (const ext of INPUT_TYPES[type]) L.push(`  - ${ext}`);
  }
  if (['audio', 'image', 'video', 'data'].includes(type)) {
    L.push(``);
    L.push(`output_type: ${type}`);
  }

  // params_schema — author-provided, else a commented example the author fills in.
  L.push(``);
  if (params.length > 0) {
    L.push(`params_schema:`);
    for (const p of params) {
      L.push(`  ${p.name}:`);
      L.push(`    type: ${p.type || 'string'}`);
      if (p.default !== undefined) L.push(`    default: ${formatScalar(p.default)}`);
      if (p.description) L.push(`    description: "${String(p.description).replace(/"/g, '\\"')}"`);
      if ((p.type === 'number') && p.min !== undefined && p.max !== undefined) {
        L.push(`    range:`);
        L.push(`      min: ${p.min}`);
        L.push(`      max: ${p.max}`);
      }
    }
  } else {
    L.push(`# params_schema:                # declare tunable params here (see components/_template)`);
    L.push(`#   strength:`);
    L.push(`#     type: number`);
    L.push(`#     default: 1.0`);
    L.push(`#     description: "Example parameter"`);
    L.push(`#     range: { min: 0.0, max: 2.0 }`);
  }

  // outputs — a scaffold declares exactly one primary_output (add more when you implement).
  const mime = MIME[type];
  L.push(``);
  L.push(`# Outputs Schema (version 1.0) — what this component produces (see lib/common-utils.sh register_output).`);
  L.push(`outputs:`);
  L.push(`  schema_version: "1.0"`);
  L.push(`  description: "${description.replace(/"/g, '\\"')} outputs"`);
  L.push(`  items:`);
  L.push(`    - name: primary_output`);
  L.push(`      type: file`);
  L.push(`      description: "Primary output of ${name}"`);
  L.push(`      required: true`);
  if (mime) L.push(`      mime_type: "${mime}"`);
  L.push(`      path_template: "${outputPathTemplate({ name, type, outputSubdir })}"`);

  // Inbound contract — kind-shaped, new schema. Guidance mirrors components/_template.
  L.push(``);
  L.push(`# ── Inbound contract (verified IN) ─────────────────────────────────────────────`);
  L.push(`# What this component NEEDS. Enforced BEFORE run.sh by lib/workchain_preflight.py — a`);
  L.push(`# missing dependency fails honestly. Full spec: docs/product/workchain/03-component-contract (KB).`);
  for (const line of requirementsBlock(ctx)) L.push(line);

  // Outbound contract — always present (a scaffold with no verify: is not a finished component).
  L.push(``);
  L.push(`# ── Outbound contract (verified OUT) ────────────────────────────────────────────`);
  L.push(`# What this component GUARANTEES. Enforced AFTER run.sh by lib/workchain_verify.py.`);
  L.push(`# For creative ops assert metamorphic invariants (duration/loudness preserved), not exact bytes.`);
  L.push(`verify:`);
  L.push(`  schema_version: "1.0"`);
  L.push(`  outputs:`);
  L.push(`    - name: primary_output`);
  L.push(`      assert: [${type === 'audio' ? 'exists, non_empty, audio_valid' : 'exists, non_empty'}]`);
  L.push(`  # post_conditions:                # component-level, numeric/relational (uncomment + adapt)`);
  if (type === 'audio') {
    L.push(`  #   - id: duration_preserved`);
    L.push(`  #     check: audio_duration_matches`);
    L.push(`  #     outputs: [primary_output]`);
    L.push(`  #     tolerance_s: 0.2`);
  } else {
    L.push(`  #   - id: your_invariant`);
    L.push(`  #     check: <check_name>`);
    L.push(`  #     outputs: [primary_output]`);
  }

  return L.join('\n') + '\n';
}

function requirementsBlock(ctx) {
  const { kind, type, commands, pythonPackages, nodePackages, name } = ctx;
  const L = [`requirements:`];
  const cmds = splitList(commands);

  if (kind === 'heavy') {
    if (cmds.length === 0) cmds.push('python3');
    else if (!cmds.includes('python3')) cmds.unshift('python3');
    L.push(`  commands:`);
    for (const c of cmds) L.push(`    - ${c}`);
    L.push(`  python:`);
    L.push(`    venv: ".venv"                 # component-local venv (heavy tier)`);
    L.push(`    python_version: ">=3.10"`);
    L.push(`    packages:`);
    const pkgs = splitList(pythonPackages);
    if (pkgs.length === 0) pkgs.push('numpy');
    for (const p of pkgs) L.push(`      - { import: "${p}" }`);
    L.push(`    provision: "bash provision.sh"`);
    const npkgs = splitList(nodePackages);
    if (npkgs.length > 0) {
      L.push(`  node:`);
      L.push(`    packages:`);
      for (const p of npkgs) L.push(`      - { require: "${p}" }`);
    } else {
      L.push(`  # node: { packages: [ { require: "some-pkg" } ] }`);
    }
    L.push(`  # models:                       # heavy weights (exists+size every run; sha256 only --deep)`);
    L.push(`  #   - { name: "weights", path: "models/weights.bin", bytes: 0, sha256: "" }`);
  } else if (kind === 'api') {
    if (cmds.length === 0) cmds.push('curl');
    L.push(`  commands:`);
    for (const c of cmds) L.push(`    - ${c}`);
    L.push(`  env:                            # presence checked, never the value`);
    L.push(`    - ${name.toUpperCase()}_API_KEY`);
    L.push(`  # python: { venv: ".venv", packages: [ "requests" ], provision: "bash provision.sh" }`);
  } else {
    // light
    if (cmds.length === 0 && type === 'audio') cmds.push('ffmpeg');
    if (cmds.length > 0) {
      L.push(`  commands:`);
      for (const c of cmds) L.push(`    - ${c}`);
    } else {
      L.push(`  commands: []                  # PATH binaries this component needs (e.g. ffmpeg)`);
    }
    L.push(`  # python: { venv: ".venv", python_version: ">=3.10", packages: [ { import: "numpy" } ], provision: "bash provision.sh" }`);
    L.push(`  # node:   { packages: [ { require: "jdenticon" } ] }`);
    L.push(`  # env:    [ SOME_API_KEY ]`);
  }
  return L;
}

function formatScalar(v) {
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (v === null || v === undefined) return '""';
  const s = String(v);
  return /^-?\d+(\.\d+)?$/.test(s) || s === 'true' || s === 'false' ? s : `"${s.replace(/"/g, '\\"')}"`;
}

/**
 * run.sh — rendered from templates/run.sh.template (carries the honest-failure sentinel,
 * ctx_get helpers, param getter). Kind only changes the pre-flight guard block.
 */
function generateRunSh(ctx) {
  const { name, description, type, params, commands, dependencies, outputSubdir, kind } = ctx;
  const templatePath = join(__dirname, 'templates', 'run.sh.template');
  let t = readFileSync(templatePath, 'utf-8');

  t = t.replace(/\{\{COMPONENT_NAME}}/g, name);
  t = t.replace(/\{\{COMPONENT_DESCRIPTION}}/g, description);

  let paramVars = '';
  let paramLog = '';
  for (const p of params) {
    const v = p.name.toUpperCase();
    paramVars += `${v}="$(get_param "${p.name}" "${p.default ?? ''}")"\n`;
    paramLog += `log_info "  ${p.name}: $${v}"\n`;
  }
  t = t.replace(/\{\{PARAMETER_VARS}}/g, paramVars.trim());
  t = t.replace(/\{\{PARAMETER_LOG}}/g, paramLog.trim());

  // Dependency detection via the special-char-safe ctx_get helper (dotted keys supported).
  let dep = '';
  if (dependencies.length > 0) {
    dep += 'SOURCE_INPUT=""\n';
    for (const d of dependencies) {
      dep += `_cand=$(ctx_get_abs "$CONTEXT_FILE" "steps.${d}.output" 2>/dev/null)\n`;
      dep += `[[ -n "$_cand" && -f "$_cand" ]] && SOURCE_INPUT="$_cand"\n`;
    }
    dep += '[[ -n "$SOURCE_INPUT" ]] && INPUT_FILE="$SOURCE_INPUT"\n';
  }
  t = t.replace(/\{\{DEPENDENCY_DETECTION}}/g, dep.trim());

  const sub = outputSubdir ? (outputSubdir.endsWith('/') ? outputSubdir : `${outputSubdir}/`) : '';
  t = t.replace(/\{\{OUTPUT_SUBDIR}}/g, sub);

  const ext = type === 'audio' ? '$INPUT_EXT' : (OUT_EXT[type] || 'out');
  t = t.replace(/\{\{OUTPUT_EXT}}/g, ext);

  // Pre-run guard block — commands for light/heavy, env-var for api.
  let checks = '';
  const cmds = splitList(commands);
  if (kind === 'api') {
    const key = `${name.toUpperCase()}_API_KEY`;
    checks += `if [[ -z "\${${key}:-}" ]]; then\n`;
    checks += `    log_error "${key} is not set"\n`;
    checks += `    ctx_set_status "$CONTEXT_FILE" "${name}" "failed" "missing_env" "${key} not set"\n`;
    checks += `    return 1\n`;
    checks += `fi\n`;
    if (cmds.length === 0) cmds.push('curl');
  }
  for (const c of cmds) {
    checks += `if ! command_exists ${c}; then\n`;
    checks += `    log_error "Command '${c}' not found"\n`;
    checks += `    ctx_set_status "$CONTEXT_FILE" "${name}" "failed" "missing_dependency" "Command ${c} not found"\n`;
    checks += `    return 1\n`;
    checks += `fi\n`;
  }
  t = t.replace(/\{\{COMMAND_CHECKS}}/g, checks.trim());

  return t;
}

/**
 * provision.sh — kind-shaped, idempotent. Light needs nothing; heavy builds a venv; api notes the key.
 */
function generateProvisionSh(ctx) {
  const { name, kind, pythonPackages } = ctx;
  const L = [
    `#!/bin/bash`,
    `# Provision recipe for ${name} — make this component's declared requirements present.`,
    `# Idempotent (safe to re-run). Referenced from step.yaml (requirements.<class>.provision).`,
    `set -euo pipefail`,
    `COMPONENT_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"`,
    ``,
  ];
  if (kind === 'heavy') {
    const pkgs = splitList(pythonPackages);
    const pipList = pkgs.length > 0 ? pkgs.join(' ') : 'numpy';
    L.push(`# Heavy component: create a local venv and install Python deps.`);
    L.push(`python3 -m venv "$COMPONENT_DIR/.venv"`);
    L.push(`"$COMPONENT_DIR/.venv/bin/pip" install --upgrade pip >/dev/null`);
    L.push(`"$COMPONENT_DIR/.venv/bin/pip" install ${pipList}`);
    L.push(`echo "${name}: provisioned .venv"`);
  } else if (kind === 'api') {
    L.push(`# API component: no local install — it calls an external service.`);
    L.push(`if [[ -z "\${${name.toUpperCase()}_API_KEY:-}" ]]; then`);
    L.push(`  echo "${name}: set ${name.toUpperCase()}_API_KEY in your environment before running" >&2`);
    L.push(`fi`);
    L.push(`echo "${name}: nothing to install (API component)"`);
  } else {
    L.push(`# Light component: nothing to provision (PATH binaries + stdlib only).`);
    L.push(`echo "${name}: nothing to provision (light component)"`);
  }
  return L.join('\n') + '\n';
}

/**
 * test-chain.yaml — a minimal single-step chain to exercise the component once implemented.
 * Kept in the component dir (self-contained); not auto-discovered by `validate all`.
 */
function generateTestChain(ctx) {
  const { name, params } = ctx;
  const L = [
    `# Test chain for ${name} — a minimal single-step chain to exercise this component.`,
    `# NOTE: ${name} is a scaffold and FAILS until implemented (remove WORKCHAIN_NOT_IMPLEMENTED in run.sh).`,
    `# Run from the repo root:  lufs-workchain run components/${name}/test-chain.yaml <input> -o ./out`,
    `name: "${name} test"`,
    `version: "1.0"`,
    `steps:`,
    `  - name: ${name}`,
    `    enabled: true`,
  ];
  if (params.length > 0) {
    L.push(`    params:`);
    for (const p of params) L.push(`      ${p.name}: ${formatScalar(p.default ?? '')}`);
  }
  return L.join('\n') + '\n';
}

/**
 * README.md — matches the per-component README template (Purpose / Params / I-O / Verified IN /
 * Verified OUT / Usage / Tier), so a generated component documents its own contract from day one.
 */
function generateReadme(ctx) {
  const { name, description, type, params, commands, pythonPackages, nodePackages, dependencies, kind } = ctx;
  // Registry tier is a runtime-weight label: heavy iff a Python venv / models are declared.
  // An `api` component declares neither, so it registers as light (with an external dependency).
  const tier = kind === 'heavy' ? 'Heavy' : 'Light';
  const L = [];
  L.push(`# ${name}`);
  L.push(``);
  L.push(`${description}`);
  L.push(``);
  L.push(`> **Scaffold.** This component was generated by \`lufs-workchain generate component\` and`);
  L.push(`> **fails until implemented** — \`run.sh\` carries a \`WORKCHAIN_NOT_IMPLEMENTED\` sentinel.`);
  L.push(`> Implement the processing, remove the sentinel, then fill in the real contract below.`);
  L.push(``);
  L.push(`## What it does`);
  L.push(``);
  L.push(`_Describe the transform here._`);
  L.push(``);

  L.push(`## Parameters`);
  L.push(``);
  if (params.length > 0) {
    L.push(`| Parameter | Type | Default | Description |`);
    L.push(`|---|---|---|---|`);
    for (const p of params) {
      L.push(`| \`${p.name}\` | ${p.type || 'string'} | \`${p.default ?? ''}\` | ${p.description || ''} |`);
    }
  } else {
    L.push(`None yet — declare them in \`params_schema\` in \`step.yaml\`.`);
  }
  L.push(``);

  L.push(`## Inputs / Outputs`);
  L.push(``);
  if (INPUT_TYPES[type]) L.push(`- **Input types:** ${INPUT_TYPES[type].map((e) => `\`${e}\``).join(', ')}`);
  L.push(`- **Output type:** \`${type}\``);
  if (dependencies.length > 0) L.push(`- **Depends on:** ${dependencies.map((d) => `\`${d}\``).join(', ')} (uses its output as input)`);
  L.push(``);
  L.push(`| Output | Type | Required | Path |`);
  L.push(`|---|---|---|---|`);
  L.push(`| \`primary_output\` | file | yes | \`{input_name}_${name}.${(OUT_EXT[type] || 'out')}\` |`);
  L.push(``);

  L.push(`## Verified IN (inbound contract)`);
  L.push(``);
  L.push(`Declared in \`step.yaml\` under \`requirements:\` and enforced by \`lib/workchain_preflight.py\` **before** \`run.sh\`. This is a **${tier.toLowerCase()}** component:`);
  L.push(``);
  if (kind === 'heavy') {
    const pkgs = splitList(pythonPackages);
    L.push(`- **commands:** \`python3\`${splitList(commands).length ? ', ' + splitList(commands).join(', ') : ''}`);
    L.push(`- **python:** local \`.venv\` (\`>=3.10\`), packages: ${(pkgs.length ? pkgs : ['numpy']).map((p) => `\`${p}\``).join(', ')} — run \`bash provision.sh\``);
    if (splitList(nodePackages).length) L.push(`- **node:** ${splitList(nodePackages).map((p) => `\`${p}\``).join(', ')}`);
  } else if (kind === 'api') {
    L.push(`- **commands:** ${(splitList(commands).length ? splitList(commands) : ['curl']).map((c) => `\`${c}\``).join(', ')}`);
    L.push(`- **env:** \`${name.toUpperCase()}_API_KEY\` (presence checked; never logged)`);
    L.push(`- Calls an external HTTP API — no local model/venv.`);
  } else {
    const cmds = splitList(commands).length ? splitList(commands) : (type === 'audio' ? ['ffmpeg'] : []);
    L.push(`- **commands:** ${cmds.length ? cmds.map((c) => `\`${c}\``).join(', ') : '_none yet — add the PATH binaries you need_'}`);
    L.push(`- No Python venv or models (ships in the lean npm core).`);
  }
  L.push(``);

  L.push(`## Verified OUT (outbound contract)`);
  L.push(``);
  L.push(`Declared in \`step.yaml\` under \`verify:\` and enforced by \`lib/workchain_verify.py\` **after** a clean run — "proven correct, not exited 0." The scaffold asserts \`primary_output\` is \`[exists, non_empty${type === 'audio' ? ', audio_valid' : ''}]\`; add \`post_conditions\` (metamorphic invariants) as you implement.`);
  L.push(``);

  L.push(`## Usage`);
  L.push(``);
  L.push('```bash');
  const pj = params.length > 0 ? ` --params-json '${JSON.stringify(Object.fromEntries(params.map((p) => [p.name, p.default ?? null])))}'` : '';
  L.push(`lufs-workchain run-component ${name} input.${type === 'audio' ? 'wav' : (OUT_EXT[type] || 'dat')}${pj}`);
  L.push('```');
  L.push(``);
  L.push(`In a chain (see \`test-chain.yaml\`):`);
  L.push(``);
  L.push('```yaml');
  L.push(`steps:`);
  L.push(`  - name: ${name}`);
  L.push(`    enabled: true`);
  L.push('```');
  L.push(``);

  L.push(`## Tier`);
  L.push(``);
  if (kind === 'heavy') {
    L.push(`**Heavy.** Declares a Python venv, so it's provisioned separately from the lean core (\`bash provision.sh\`) and can run server-side via the hosted MCP tier.`);
  } else if (kind === 'api') {
    L.push(`**Light** runtime (no local venv or models, so the registry classifies it light), but it has an **external dependency**: it needs network access and \`${name.toUpperCase()}_API_KEY\`, so it can't run fully offline like the rest of the lean core.`);
  } else {
    L.push(`**Light.** PATH binaries + stdlib only — ships in the lean npm core and runs anywhere the declared commands exist.`);
  }
  return L.join('\n') + '\n';
}
