/**
 * engine.js — the single place the CLI spawns the workchain engine.
 *
 * Both `run` (whole chain) and `run-component` (single component) go through here so
 * they behave identically. Previously `run` hard-wrapped the engine in `uv run` and,
 * with uv absent, failed with an opaque "exit code undefined / no context.json" because
 * the ENOENT was swallowed by `reject:false` (review Bug 4). `run-component` used bare
 * `bash`, so the two commands diverged.
 *
 * Policy: use `uv run --project <root>` ONLY when uv is on PATH *and* a project venv
 * exists (so Python components get their dependencies). Otherwise run directly with
 * `bash` — the engine itself only needs system python3 + ffmpeg, so light components work
 * with zero extra tooling. uv is never required for the engine to start.
 */

import { execa } from 'execa';
import { existsSync } from 'fs';
import { join, delimiter } from 'path';

/** Cheap, synchronous PATH lookup — no subprocess, no side effects. */
export function hasCommand(cmd) {
  const paths = (process.env.PATH || '').split(delimiter);
  return paths.some((p) => p && existsSync(join(p, cmd)));
}

/**
 * Decide how to launch the engine.
 * @returns {{ cmd: string, prefix: string[], usesUv: boolean }}
 */
export function detectLauncher(workchainRoot) {
  const venvExists =
    existsSync(join(workchainRoot, '.venv')) ||
    existsSync(join(workchainRoot, 'mcp-server', '.venv'));
  if (hasCommand('uv') && venvExists) {
    return { cmd: 'uv', prefix: ['run', '--project', workchainRoot], usesUv: true };
  }
  return { cmd: 'bash', prefix: [], usesUv: false };
}

/**
 * Spawn the engine for a whole chain.
 * Returns the execa subprocess (so the caller can pipe progress) plus launcher meta.
 */
export function spawnEngineChain({ workchainRoot, chainFile, inputPath, outputDir, timeout }) {
  const enginePath = join(workchainRoot, 'engine', 'workchain-engine.sh');
  const { cmd, prefix, usesUv } = detectLauncher(workchainRoot);
  const args = [...prefix, enginePath, '-c', chainFile, '-o', outputDir, inputPath];

  const subprocess = execa(cmd, args, {
    timeout: (timeout || 3600) * 1000,
    cwd: workchainRoot,
    env: { ...process.env },
    reject: false,
    stdin: 'ignore', // engine/components never read CLI stdin
  });
  return { subprocess, launcher: cmd, usesUv };
}

/**
 * Spawn a single-component bash script (used by run-component).
 * Goes through the same launcher so uv's venv applies when available.
 */
export function spawnComponentScript({ workchainRoot, runScript, timeout, env }) {
  const { prefix, usesUv } = detectLauncher(workchainRoot);
  // The component runs as `bash -c <script>`. When launching through uv, that becomes
  // `uv run --project <root> bash -c <script>`; otherwise just `bash -c <script>`
  // (do NOT double the `bash`).
  const cmd = usesUv ? 'uv' : 'bash';
  const args = usesUv ? [...prefix, 'bash', '-c', runScript] : ['-c', runScript];
  const subprocess = execa(cmd, args, {
    cwd: workchainRoot,
    timeout,
    env: { ...process.env, ...(env || {}) },
    reject: false,
    stdin: 'ignore',
  });
  return { subprocess, launcher: cmd, usesUv };
}
