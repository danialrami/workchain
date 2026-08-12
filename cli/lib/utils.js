import { existsSync, statSync } from 'fs';
import { extname } from 'path';

const SUPPORTED_AUDIO_EXTENSIONS = new Set([
  '.wav', '.mp3', '.aiff', '.aif', '.flac', '.m4a', '.ogg',
]);

export class CliError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'CliError';
    this.code = code;
    this.details = details;
  }
}

export function validateInputFile(filePath) {
  if (!filePath) {
    throw new CliError(2, 'No input file specified.');
  }
  if (!existsSync(filePath)) {
    throw new CliError(2, `Input file not found: ${filePath}`);
  }
  const ext = extname(filePath).toLowerCase();
  if (!SUPPORTED_AUDIO_EXTENSIONS.has(ext)) {
    const supported = Array.from(SUPPORTED_AUDIO_EXTENSIONS).join(', ');
    throw new CliError(2, `Unsupported audio format: ${ext}\nSupported formats: ${supported}`);
  }
  if (!statSync(filePath).isFile()) {
    throw new CliError(2, `Not a file: ${filePath}`);
  }
  return filePath;
}

export function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = ((ms % 60000) / 1000).toFixed(1);
  return `${minutes}m ${seconds}s`;
}

export function parseYamlField(yaml, field) {
  const regex = new RegExp(`^${field}:\\s*(.+)$`, 'm');
  const match = yaml.match(regex);
  return match ? match[1].trim().replace(/^["']|["']$/g, '') : null;
}

export function formatTimestamp(date = new Date()) {
  const y = date.getFullYear();
  const M = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const h = String(date.getHours()).padStart(2, '0');
  const m = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${y}${M}${d}_${h}${m}${s}`;
}

export function countSteps(yaml) {
  const stepsMatch = yaml.match(/^steps:\s*$/m);
  if (!stepsMatch) return { count: 0, names: [] };
  const afterSteps = yaml.slice(stepsMatch.index);
  const itemRegex = /^\s+-\s+name:\s*(\w+)/gm;
  const names = [];
  let m;
  while ((m = itemRegex.exec(afterSteps)) !== null) {
    names.push(m[1]);
  }
  return { count: names.length, names };
}
