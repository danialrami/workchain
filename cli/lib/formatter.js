import chalk from 'chalk';

// The run banner is a fixed-width box. The border and the rows are derived from ONE
// number so they cannot drift apart: previously each row appended a hard-coded run of
// spaces, so the right-hand border only lined up if the chain name happened to be
// exactly the length the author's test case had. `tests/content_hash_test` measured 51
// columns against a 41-column border. Chain and input names are caller data of unbounded
// length, so the width has to be computed, and over-long text truncated rather than
// allowed to blow the box open.
const BOX_INNER = 37;
const BOX_TOP = '  ╭' + '─'.repeat(BOX_INNER) + '╮';
const BOX_BOTTOM = '  ╰' + '─'.repeat(BOX_INNER) + '╯';

function boxRow(text) {
  const field = BOX_INNER - 2; // two spaces of inset inside the left border
  const chars = [...String(text)];
  const t = chars.length > field ? chars.slice(0, field - 1).join('') + '…' : chars.join('');
  const padded = t + ' '.repeat(field - [...t].length);
  return chalk.bold(`  │  ${padded}│`);
}

export function formatResult(result, options = {}) {
  if (options.json) {
    return JSON.stringify(result, null, 2);
  }
  return formatHuman(result);
}

function formatHuman(result) {
  const lines = [];

  if (result.status === 'dry_run') {
    lines.push('');
    lines.push(`  Chain: ${result.chain}`);
    lines.push(`  ${result.description}`);
    lines.push(`  Version: ${result.version}`);
    lines.push(`  Input: ${result.input_name}.${result.input_ext}`);
    lines.push(`  Steps (${result.step_count}):`);
    for (const step of result.steps) {
      lines.push(`    ${step.name} — ${step.description}`);
      if (step.outputs.length > 0) {
        lines.push(`      outputs: ${step.outputs.join(', ')}`);
      }
    }
    lines.push('');
    lines.push(chalk.yellow('  ── Dry Run ──'));
    lines.push('  No files were processed.');
    lines.push('');
    return lines.join('\n');
  }

  if (result.status === 'error') {
    lines.push(chalk.red(`\n  ✖ ${result.message}`));
    // Surface the failed checks — the measured facts that stopped the run. These are
    // previously only reachable via --verbose or by digging into context.json, which
    // made the default failure output near-silent for the exact event the tool exists
    // to expose.
    if (result.failures && result.failures.length) {
      for (const f of result.failures) {
        const n = f.failed_checks.length;
        lines.push(`    ${chalk.bold(f.step)} — ${f.tier} (${n} of ${f.total_checks || n} checks failed)`);
        for (const c of f.failed_checks) {
          lines.push(chalk.red(`      ✗ ${c.name}: ${c.detail}`));
        }
      }
    }
    if (result.details) {
      for (const [key, value] of Object.entries(result.details)) {
        if (typeof value === 'object') continue;
        lines.push(`    ${key}: ${value}`);
      }
    }
    return lines.join('\n');
  }

  lines.push('');
  lines.push(chalk.bold(BOX_TOP));
  lines.push(boxRow('LUFS Workchain'));
  lines.push(boxRow(`Chain: ${result.chain || 'unknown'}`));
  lines.push(boxRow(`Input: ${result.input_name || ''}.${result.input_ext || ''}`));
  lines.push(chalk.bold(BOX_BOTTOM));
  lines.push('');
  lines.push(chalk.bold('  Executing steps...'));

  if (result.steps) {
    for (const [name, step] of Object.entries(result.steps)) {
      const icon = step.status === 'completed' ? chalk.green('✔') : step.status === 'failed' ? chalk.red('✖') : chalk.cyan('…');
      const dots = '.'.repeat(Math.max(1, 44 - name.length));
      const time = step.status === 'completed' ? chalk.white(` ${formatDurationSimple(step.duration_ms)}`) : '';
      lines.push(`  ${icon} ${name} ${chalk.dim(dots)}${time}`);
    }
  }

  lines.push('');
  lines.push(chalk.bold('  ── Complete ──'));
  if (result.output_dir) lines.push(`  Output: ${result.output_dir}`);
  if (result.duration_ms) lines.push(`  Duration: ${(result.duration_ms / 1000).toFixed(1)}s`);
  lines.push(chalk.green(`  Status: ${result.status}`));
  lines.push('');

  return lines.join('\n');
}

function formatDurationSimple(ms) {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatList(items, title, options = {}) {
  if (options.json) {
    return JSON.stringify(items, null, 2);
  }

  const lines = [];
  lines.push(chalk.bold(`\n  ${title}:`));
  lines.push('');

  for (const item of items) {
    if (item.name && item.description) {
      const paddedName = item.name.padEnd(22);
      lines.push(`  ${chalk.cyan(paddedName)} ${item.description}`);
    } else {
      lines.push(`  ${chalk.cyan(item.name || item)}`);
    }
  }

  lines.push('');
  return lines.join('\n');
}

export function emitProgress(data) {
  process.stderr.write(JSON.stringify({ progress: data }) + '\n');
}

export function formatError(error, options = {}) {
  if (options.json) {
    return JSON.stringify({
      status: 'error',
      command: error.command || 'unknown',
      code: error.code || 1,
      message: error.message,
      details: error.details || {},
    }, null, 2);
  }

  if (error.code === 2) {
    return chalk.yellow(`Warning: ${error.message}`);
  }
  return chalk.red(`Error: ${error.message}`);
}
