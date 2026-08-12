import split2 from 'split2';

const ANSI_RE = /\x1b\[[0-9;]*m/g;

// Engine progress markers (running/completed) are written to STDOUT by log_step/log_info.
const STEP_START = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*STEP:\s*Executing step:\s*(\S+)/;
const STEP_RUNNING = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*(?:Running|STEP:\s*Running):\s*(\S+)/;
const STEP_COMPLETED = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*Step completed:\s*(\S+)/;
const WORKCHAIN_DONE = /completed successfully/;

// Engine failure diagnostics are written to STDERR by log_error. The step-runner emits
// `Step failed: <name>` for a run error and `Step failed verification: <name>` for a
// contract failure.
const STEP_FAILED = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*ERROR:\s*Step failed(?:\s+verification)?:\s*(\S+)/;
// The verifier's summary line is re-logged through log_error, so it carries the ERROR
// prefix: `ERROR: ✗ <comp> — verification FAILED (N of M checks)`. It opens a failure
// block; the indented check lines that follow belong to it.
const VERIFY_FAILED = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*ERROR:\s*✗\s*(\S+)\s*—\s*verification FAILED\s*\((\d+) of (\d+) checks\)/;
// Indented (2+ spaces after ERROR:) `    <check>: <detail>` lines belong to the open
// failure block. "Step failed verification:" uses a single space and is NOT a detail.
const VERIFY_DETAIL = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*ERROR:\s{2,}(\S[^:]*?):\s+(.*)$/;
const WORKCHAIN_HALTED = /^\s*\[?\d{2}:\d{2}:\d{2}\]?\s*ERROR:\s*Chain halted:\s*step\s+'([^']+)'\s*failed/;

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
    const reason = /Step failed verification:/.test(text) ? 'verification' : 'run';
    return JSON.stringify({ progress: { step: match[1], status: 'failed', error: reason } });
  }
  if (text.match(WORKCHAIN_DONE)) {
    return JSON.stringify({ progress: { status: 'workchain_completed' } });
  }

  return null;
}

/**
 * Build an NDJSON progress parser to attach to an engine stream.
 *
 * Engine stdout carries the running/completed markers; engine stderr carries the
 * failure diagnostics. Both are parsed and re-emitted as newline-delimited JSON on
 * the CLI's stderr, so the agent-facing progress stream reports step *failure* — not
 * just a `running` event followed by dead air.
 *
 * `quiet` (default for the stderr stream) drops unrecognized raw lines so the stream
 * stays valid NDJSON; set `quiet:false` to also forward raw lines (human verbose mode).
 */
export function createProgressParser(options = {}) {
  const quiet = options.quiet ?? false;
  const seenRunning = new Set();
  let pendingFailure = null; // { step, reason, checks:[] } accumulated from stderr

  return split2(line => {
    const raw = typeof line === 'string' ? line : line.toString();
    const cleaned = raw.replace(ANSI_RE, '').trim();

    if (!cleaned) return;

    // A verifier "verification FAILED" summary opens a failure block on stderr.
    const vf = cleaned.match(VERIFY_FAILED);
    if (vf) {
      pendingFailure = {
        step: vf[1],
        reason: 'verification',
        checks: [],
        total: Number(vf[3]),
      };
      // NOTE: must return undefined, not null — split2's mapper runs through
      // `push(this, val)` which calls `self.push(val)` whenever `val !== undefined`.
      // `self.push(null)` ends the readable stream, so null would break every
      // subsequent line. Return nothing (undefined) to consume without emitting.
      return undefined;
    }

    // Indented check-detail lines accumulate into the open failure block.
    if (pendingFailure) {
      const vd = cleaned.match(VERIFY_DETAIL);
      if (vd) {
        pendingFailure.checks.push(`${vd[1]}: ${vd[2]}`);
        return undefined; // split2 push(undefined) is skipped; null would end the stream
      }
    }

    const event = parseLine(cleaned);
    if (event) {
      const parsed = JSON.parse(event);
      const p = parsed.progress;

      if (p.status === 'failed' && pendingFailure && p.step === pendingFailure.step) {
        if (pendingFailure.checks.length) p.checks = pendingFailure.checks;
        if (pendingFailure.reason) p.error = pendingFailure.reason;
        pendingFailure = null;
        return JSON.stringify(parsed) + '\n';
      }

      if (p.status === 'running') {
        if (seenRunning.has(p.step)) return;
        seenRunning.add(p.step);
      }

      // Newline-delimit so the progress stream is valid NDJSON (one object per line).
      return event + '\n';
    }

    const halted = cleaned.match(WORKCHAIN_HALTED);
    if (halted) {
      return JSON.stringify({ progress: { status: 'chain_halted', step: halted[1] } }) + '\n';
    }

    if (!quiet) {
      return raw + '\n';
    }
  });
}
