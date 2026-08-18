/**
 * config.js — the CLI's settings store: a JSON file at an OS-appropriate path.
 *
 * Replaces `conf` (issue #7 step 2). conf pulled in ajv (2.4M) plus 16 more packages to
 * validate, store and watch a handful of keys whose writers and readers we control
 * entirely. Node 18 provides everything the CLI actually used from conf:
 *
 *   - OS config-home path rules (XDG / APPDATA / ~/Library/Preferences) — ~20 lines;
 *   - tolerant read (missing or unparsable file → defaults) — JSON.parse in a try;
 *   - atomic replace — write a temp file then renameSync over the target (atomic on the
 *     same filesystem, so a crash mid-write leaves the old file or the new file, never
 *     a torn one);
 *   - defaults for the five known keys — a plain DEFAULTS object, no schema engine.
 *
 * The exported API is unchanged (loadConfig/getConfig/setConfig/deleteConfig/
 * resetConfig/getConfigPath), so no command needed to change.
 *
 * One deliberate move, per the issue's step-2 prescription: the file lives at
 * <config-home>/lufs-workchain/config.json instead of conf's env-paths location
 * (<config-home>/workchain-nodejs/config.json). The CLI has not shipped on npm yet, so
 * nothing was ever persisted under the old path — there is no user config to migrate.
 */

import os from 'os';
import { join, dirname } from 'path';
import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'fs';

const DEFAULTS = {
  workchainRoot: '',
  server: 'local',
  defaultChain: 'deliverable-voice',
  outputDir: './output',
  // Mirrors the old schema default: one worker below CPU count, never below one.
  concurrency: Math.max(1, os.cpus().length - 1),
};

const ENV_MAP = {
  LUFS_WORKCHAIN_ROOT: 'workchainRoot',
  LUFS_WORKCHAIN_SERVER: 'server',
  LUFS_WORKCHAIN_DEFAULT_CHAIN: 'defaultChain',
  LUFS_WORKCHAIN_CONCURRENCY: 'concurrency',
};

/** Resolve the config file path from the OS config-home rules (issue #7 step 2). */
export function getConfigPath() {
  let base;
  if (process.platform === 'darwin') {
    base = join(os.homedir(), 'Library', 'Preferences');
  } else if (process.platform === 'win32') {
    base = process.env.APPDATA || join(os.homedir(), 'AppData', 'Roaming');
  } else {
    base = process.env.XDG_CONFIG_HOME || join(os.homedir(), '.config');
  }
  return join(base, 'lufs-workchain', 'config.json');
}

/** Tolerant read: a missing or unparsable file is an empty store, not an error. */
function readStore() {
  try {
    return JSON.parse(readFileSync(getConfigPath(), 'utf-8'));
  } catch {
    return {};
  }
}

/**
 * Atomic replace: write to a temp file on the same filesystem, then rename over the
 * target. renameSync is atomic on POSIX, so a crash between the write and the rename can
 * only ever leave the previous file intact plus a stray `.tmp` (overwritten by the next
 * write); it can never leave a torn config.json.
 */
function writeStore(obj) {
  const target = getConfigPath();
  mkdirSync(dirname(target), { recursive: true });
  const tmp = `${target}.tmp`;
  writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n');
  renameSync(tmp, target);
}

export function loadConfig() {
  const config = { ...DEFAULTS, ...readStore() };

  for (const [envVar, configKey] of Object.entries(ENV_MAP)) {
    if (process.env[envVar]) {
      const value = process.env[envVar];
      config[configKey] = configKey === 'concurrency' ? parseInt(value, 10) : value;
    }
  }

  config._configPath = getConfigPath();
  config._envOverrides = Object.keys(ENV_MAP).filter(k => process.env[k]);

  return config;
}

export function getConfig(key) {
  const config = loadConfig();
  return config[key];
}

export function setConfig(key, value) {
  writeStore({ ...readStore(), [key]: value });
}

export function deleteConfig(key) {
  const store = readStore();
  delete store[key];
  writeStore(store);
}

export function resetConfig() {
  writeStore({});
}