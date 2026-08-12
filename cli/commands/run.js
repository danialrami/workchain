import { execa } from 'execa';
import { readFile, mkdir } from 'fs/promises';
import { existsSync, readFileSync } from 'fs';
import { resolve, join } from 'path';
import { resolveWorkchainRoot, resolveChainFile } from '../lib/workchain.js';
import { spawnEngineChain } from '../lib/engine.js';
import { wy } from '../lib/wyaml.js';
import { createProgressParser } from '../lib/progress.js';
import { formatResult } from '../lib/formatter.js';
import { validateInputFile, CliError, formatTimestamp, countSteps, parseYamlField } from '../lib/utils.js';
import { generateReport } from '../lib/report-generator.js';

export async function runCommand(chain, input, options, command) {
  const startTime = Date.now();
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || options.json || false;
  const verbose = globalOpts.verbose || false;

  try {
    const inputPath = resolve(input);

    const workchainRoot = resolveWorkchainRoot();
    const chainFile = resolveChainFile(chain, workchainRoot);

    if (options.dryRun) {
      // A dry run is a plan preview — it never touches the input, so it is valid even
      // before the input file exists. An agent can preview the plan first and check
      // the steps, and only a real `run` demands a real file (validated below).
      const plan = buildDryRunPlan(chainFile, inputPath, workchainRoot);
      console.log(formatResult(plan, { json }));
      return;
    }

    // Real runs require a real, supported input file.
    validateInputFile(inputPath);

    const outputDir = options.output
      ? resolve(options.output)
      : resolve(`./output_${formatTimestamp()}`);

    await mkdir(outputDir, { recursive: true });

    const { subprocess } = spawnEngineChain({
      workchainRoot,
      chainFile,
      inputPath,
      outputDir,
      timeout: options.timeout,
    });

    const progressParser = createProgressParser({ quiet: !verbose });
    // Engine progress markers (running/completed) live on stdout; failure diagnostics
    // live on stderr. Parse stdout for the happy path and stderr for failures.
    subprocess.stdout.pipe(progressParser).pipe(process.stderr, { end: false });
    if (verbose) {
      // Human mode: forward raw engine stderr so a person can read the full log.
      subprocess.stderr.pipe(process.stderr, { end: false });
    } else {
      // Agent mode: keep stderr a clean NDJSON stream, but still parse it so a step
      // FAILURE gets a structured `failed` event (previously stderr was dropped
      // entirely — a failure read as a `running` event then dead air). Consuming
      // stderr also stops a full pipe buffer from ever blocking the child.
      const errorParser = createProgressParser({ quiet: true });
      subprocess.stderr.pipe(errorParser).pipe(process.stderr, { end: false });
      // The progress stream is best-effort; the authoritative failure detail always
      // comes from context.json via buildResult. A parser hiccup must never crash the
      // run — swallow stream errors so the exit code and summary still surface.
      errorParser.on('error', () => {});
    }
    progressParser.on('error', () => {});

    const { exitCode } = await subprocess;

    const contextPath = resolve(outputDir, 'context.json');
    let contextData = null;
    let reportPath = null;

    if (existsSync(contextPath)) {
      const raw = await readFile(contextPath, 'utf-8');
      contextData = JSON.parse(raw);
    }

    // Generate HTML report if --report flag is set
    if (options.report && contextData && exitCode === 0) {
      try {
        // Calculate inputName for report filename
        const inputParts = inputPath.split(/[/\\]/).pop() || inputPath;
        const lastDot = inputParts.lastIndexOf('.');
        const inputName = lastDot > 0 ? inputParts.slice(0, lastDot) : inputParts;

        reportPath = await generateReport(contextPath, outputDir, inputName);
      } catch (err) {
        console.error(`Warning: Failed to generate report: ${err.message}`);
      }
    }

    const durationMs = Date.now() - startTime;
    const result = buildResult(contextData, exitCode, inputPath, chain, outputDir, durationMs, reportPath);

    const output = formatResult(result, { json });
    console.log(output);

    if (result.status === 'error') {
      process.exit(result.code || 1);
    }
  } catch (err) {
    handleError(err, 'run', json);
  }
}

function buildDryRunPlan(chainFile, inputPath, workchainRoot) {
  // Parse via the single source-of-truth module (review Bug 7) — no local regex.
  const raw = wy(workchainRoot, ['parse', chainFile]) || {};
  const chainName = raw.name || chainFile.split(/[/\\]/).pop()?.replace('.yaml', '') || 'unknown';
  const description = raw.description || '';
  const version = raw.version || '1.0';
  const stepNames = (raw.steps || [])
    .filter(s => s && typeof s === 'object' && s.enabled !== false)
    .map(s => s.name);

  const inputParts = inputPath.split(/[/\\]/).pop() || inputPath;
  const lastDot = inputParts.lastIndexOf('.');
  const inputName = lastDot > 0 ? inputParts.slice(0, lastDot) : inputParts;
  const inputExt = lastDot > 0 ? inputParts.slice(lastDot + 1) : '';

  const steps = stepNames.map(name => {
    let componentDescription = '';
    let outputTypes = [];
    try {
      const schema = wy(workchainRoot, ['component-schema', workchainRoot, name]);
      componentDescription = schema.description || '';
      outputTypes = ((schema.outputs || {}).items || []).map(i => i.name).filter(Boolean);
    } catch {
      // component missing — validation/run will report it; keep the plan resilient
    }
    return { name, description: componentDescription, outputs: outputTypes };
  });

  const plan = {
    status: 'dry_run',
    command: 'run',
    mode: 'dry-run',
    chain: chainName,
    chain_file: chainFile,
    description,
    version,
    input_file: inputPath,
    input_name: inputName,
    input_ext: inputExt,
    step_count: steps.length,
    steps,
  };

  return plan;
}

/**
 * Extract the verifier's failed checks from context.json for every failed step.
 * These are the measured facts that made the run stop (e.g. "measured -8.85 LUFS vs
 * target -5.0 - off by 3.85 LU") — the whole point of the tool is to surface them.
 */
function collectFailures(contextData) {
  const failures = [];
  const steps = (contextData && contextData.steps) || {};
  for (const [name, step] of Object.entries(steps)) {
    if (step && step.status === 'failed') {
      const v = step.verification || {};
      failures.push({
        step: name,
        tier: v.tier || 'unverified',
        total_checks: Array.isArray(v.checks) ? v.checks.length : 0,
        failed_checks: (v.failures || []).map((f) => ({ name: f.name, detail: f.detail })),
      });
    }
  }
  return failures;
}

function buildResult(contextData, exitCode, inputPath, chain, outputDir, durationMs, reportPath) {
  const inputParts = inputPath.split(/[/\\]/).pop() || inputPath;
  const lastDot = inputParts.lastIndexOf('.');
  const inputName = lastDot > 0 ? inputParts.slice(0, lastDot) : inputParts;
  const inputExt = lastDot > 0 ? inputParts.slice(lastDot + 1) : '';

  if (contextData && exitCode === 0) {
    const result = {
      status: 'completed',
      command: 'run',
      chain,
      input_file: inputPath,
      input_name: inputName,
      input_ext: inputExt,
      output_dir: outputDir,
      duration_ms: durationMs,
      steps: contextData.steps || {},
      warnings: contextData.warnings || [],
    };

    if (reportPath) {
      result.report_file = reportPath;
    }

    return result;
  }

  if (contextData && exitCode !== 0) {
    const failures = collectFailures(contextData);
    const failedStep = failures[0]?.step;
    return {
      status: 'error',
      command: 'run',
      code: 1,
      // Name the lie: say which step failed and why, not just "exit code 1".
      message: failedStep
        ? `Chain halted: step '${failedStep}' failed verification`
        : `Chain execution failed with exit code ${exitCode}`,
      chain,
      input_file: inputPath,
      failures,
      details: {
        chain,
        input_file: inputPath,
        steps: contextData.steps || {},
      },
    };
  }

  return {
    status: 'error',
    command: 'run',
    code: 1,
    message: `Chain execution failed with exit code ${exitCode}`,
    details: {
      chain,
      input_file: inputPath,
      output_dir: outputDir,
      note: 'No context.json was generated. Check engine logs for details.',
    },
  };
}

function handleError(err, command, json) {
  if (err instanceof CliError) {
    const result = {
      status: 'error',
      command,
      code: err.code,
      message: err.message,
      details: err.details,
    };
    console.error(formatResult(result, { json }));
    process.exit(err.code);
  }

  if (err.code === 'ETIMEDOUT') {
    const result = {
      status: 'error',
      command,
      code: 1,
      message: `Chain timed out after ${err.timeout ? Math.round(err.timeout / 1000) : 'unknown'} seconds`,
      details: {},
    };
    console.error(formatResult(result, { json }));
    process.exit(1);
  }

  if (err.code === 'ENOENT' && err.message.includes('uv')) {
    const result = {
      status: 'error',
      command,
      code: 1,
      message: 'uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh',
      details: {},
    };
    console.error(formatResult(result, { json }));
    process.exit(1);
  }

  const result = {
    status: 'error',
    command,
    code: 1,
    message: `Unexpected error: ${err.message}`,
    details: {},
  };
  console.error(formatResult(result, { json }));
  process.exit(1);
}
