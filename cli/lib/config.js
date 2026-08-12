import Conf from 'conf';
import os from 'os';

const schema = {
  workchainRoot: {
    type: 'string',
    default: '',
    description: 'Path to lufs-workchain repository root.',
  },
  server: {
    type: 'string',
    default: 'local',
    description: 'Backend server URL. "local" for local execution.',
  },
  defaultChain: {
    type: 'string',
    default: 'deliverable-voice',
    description: 'Default chain name for run.',
  },
  outputDir: {
    type: 'string',
    default: './output',
    description: 'Default output directory.',
  },
  concurrency: {
    type: 'number',
    default: Math.max(1, os.cpus().length - 1),
    minimum: 1,
    description: 'Max parallel chains (reserved for future use).',
  },
};

const ENV_MAP = {
  LUFS_WORKCHAIN_ROOT: 'workchainRoot',
  LUFS_WORKCHAIN_SERVER: 'server',
  LUFS_WORKCHAIN_DEFAULT_CHAIN: 'defaultChain',
  LUFS_WORKCHAIN_CONCURRENCY: 'concurrency',
};

function createStore() {
  return new Conf({ projectName: 'lufs-workchain', schema });
}

export function loadConfig() {
  const store = createStore();
  const config = { ...store.store };

  for (const [envVar, configKey] of Object.entries(ENV_MAP)) {
    if (process.env[envVar]) {
      const value = process.env[envVar];
      config[configKey] = configKey === 'concurrency' ? parseInt(value, 10) : value;
    }
  }

  config._configPath = store.path;
  config._envOverrides = Object.keys(ENV_MAP).filter(k => process.env[k]);

  return config;
}

export function getConfig(key) {
  const config = loadConfig();
  return config[key];
}

export function setConfig(key, value) {
  const store = createStore();
  store.set(key, value);
}

export function deleteConfig(key) {
  const store = createStore();
  store.delete(key);
}

export function resetConfig() {
  const store = createStore();
  store.clear();
}

export function getConfigPath() {
  const store = createStore();
  return store.path;
}
