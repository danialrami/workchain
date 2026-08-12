import split2 from 'split2';

const ANSI_RE = /\x1b\[[0-9;]*m/g;

const STEP_START = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*STEP:\s*Executing step:\s*(\S+)/;
const STEP_RUNNING = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*(?:Running|STEP:\s*Running):\s*(\S+)/;
const STEP_COMPLETED = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*Step completed:\s*(\S+)/;
const STEP_FAILED = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*ERROR:\s*Step failed:\s*(\S+)/;
const WORKCHAIN_DONE = /completed successfully/;

function parseLine(text) {
  let match;

  if ((match = text.match(STEP_START))) {
    return JSON.stringify({ progress: { step: match[1], status: 'running' } });
  }
  if ((match = text.match(STEP_RUNNING))) {
    return JSON.stringify({ progress: { step: match[1], status: 'running' } });
  }
  if ((match = text.match(STEP_COMPLETED))) {
    return JSON.stringify({ progress: { step: match[1], status: 'completed' } });
  }
  if ((match = text.match(STEP_FAILED))) {
    return JSON.stringify({ progress: { step: match[1], status: 'failed', error: 'Step failed' } });
  }
  if (text.match(WORKCHAIN_DONE)) {
    return JSON.stringify({ progress: { status: 'workchain_completed' } });
  }

  return null;
}

export function createProgressParser(options = {}) {
  const quiet = options.quiet ?? false;
  const seenRunning = new Set();

  return split2(line => {
    const raw = typeof line === 'string' ? line : line.toString();
    const cleaned = raw.replace(ANSI_RE, '').trim();

    if (!cleaned) return;

    const event = parseLine(cleaned);
    if (event) {
      const parsed = JSON.parse(event);
      if (parsed.progress?.status === 'running') {
        if (seenRunning.has(parsed.progress.step)) return;
        seenRunning.add(parsed.progress.step);
      }
      // Newline-delimit so the progress stream is valid NDJSON (one object per line).
      return event + '\n';
    }

    if (!quiet) {
      return raw + '\n';
    }
  });
}
