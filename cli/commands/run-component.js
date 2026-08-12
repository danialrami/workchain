import { execa } from 'execa';
import { resolve, join, dirname, basename, extname, sep } from 'path';
import { existsSync, mkdirSync, writeFileSync, readdirSync, statSync, readFileSync } from 'fs';
import { resolveWorkchainRoot, resolveComponentDir } from '../lib/workchain.js';
import { spawnComponentScript } from '../lib/engine.js';
import { formatResult } from '../lib/formatter.js';
import { CliError, validateInputFile } from '../lib/utils.js';

const SUPPORTED_AUDIO_EXTENSIONS = ['mp3', 'wav', 'aiff', 'aif', 'flac', 'm4a', 'ogg', 'mp4', 'm4a', 'wma'];

/**
 * Run a component standalone (outside of a chain)
 * Usage: lufs-workchain run-component <component> <input> [options]
 * Batch mode: lufs-workchain run-component <component> <directory> [options]
 */
export async function runComponentCommand(componentName, input, options, command) {
  const globalOpts = command.parent?.opts() || {};
  const json = globalOpts.json || false;
  const verbose = globalOpts.verbose || false;

  try {
    if (!componentName) throw new CliError(2, 'Component name is required');
    if (!input) throw new CliError(2, 'Input file or directory is required');

    const workchainRoot = resolveWorkchainRoot();
    const componentDir = resolveComponentDir(componentName, workchainRoot);

    // Check if input is file or directory
    const inputPath = resolve(input);
    let isDirectory = false;
    try {
      isDirectory = statSync(inputPath).isDirectory();
    } catch (e) {
      // If can't stat, let validateInputFile handle the error
    }

    if (isDirectory) {
      // Batch mode
      const result = await runBatch(componentName, componentDir, inputPath, options, {
        workchainRoot,
        json,
        verbose,
      });
      if (json) {
        console.log(formatResult(result, { json }));
      } else {
        console.log(`Batch processing complete: ${result.summary.completed}/${result.summary.total} files processed successfully`);
      }

      if (result.summary.failed > 0) {
        process.exit(1);
      }
    } else {
      // Single file mode
      const result = await runSingleFile(componentName, componentDir, inputPath, options, {
        workchainRoot,
        json,
        verbose,
      });

      if (json) {
        console.log(formatResult(result, { json }));
      } else {
        console.log(`Component: ${componentName}`);
        console.log(`Status: ${result.status}`);
        console.log(`Output directory: ${result.output_dir}`);
        if (result.outputs) {
          console.log('\nOutputs:');
          for (const [key, value] of Object.entries(result.outputs)) {
            console.log(`  ${key}: ${value.path || value}`);
          }
        }
      }

      if (result.status === 'failed') {
        process.exit(result.exit_code || 1);
      }
    }

  } catch (err) {
    if (err instanceof CliError) {
      const result = {
        status: 'error',
        command: 'run-component',
        code: err.code,
        message: err.message,
      };
      console.error(json ? JSON.stringify(result, null, 2) : `Error: ${err.message}`);
      process.exit(err.code);
    }
    console.error(`Unexpected error: ${err.message}`);
    process.exit(1);
  }
}

/**
 * Run component on a single file
 */
async function runSingleFile(componentName, componentDir, inputPath, options, context) {
  const { workchainRoot, json, verbose } = context;

  validateInputFile(inputPath);

  const componentStepYaml = join(componentDir, 'step.yaml');
  const componentParams = parseComponentParams(componentStepYaml);
  const stepConfig = buildStepConfig(componentParams, options);

  // Set up output directory
  const outputDir = options.output
    ? resolve(options.output)
    : join(process.cwd(), `output_${getTimestamp()}`);

  // Create output directory
  mkdirSync(outputDir, { recursive: true });

  // Create minimal context.json
  const inputName = basename(inputPath, extname(inputPath));
  const inputExt = extname(inputPath).slice(1); // Remove leading dot

  const contextFile = join(outputDir, 'context.json');
  const ctx = {
    input_file: inputPath,
    input_name: inputName,
    input_ext: inputExt,
    output_dir: outputDir,
    chain_file: 'standalone',
    chain_name: 'standalone',
    start_time: new Date().toISOString(),
    globals: {},
    steps: {},
  };

  // Record the resolved params under steps.<component>.params so the verifier can read
  // the exact target the component ran with. Without this, resolve_target() misses
  // step.params and falls back to the schema default — the direct-path half of Bug 1.
  // (The chain path records params via the engine plan; this mirrors it for run-component.)
  if (options.paramsJson) {
    try {
      const parsed = JSON.parse(options.paramsJson);
      if (parsed && typeof parsed === 'object') {
        ctx.steps[componentName] = { ...(ctx.steps[componentName] || {}), params: parsed };
      }
    } catch {
      // Invalid JSON is surfaced by buildStepConfig(); don't duplicate the error here.
    }
  }

  writeFileSync(contextFile, JSON.stringify(ctx, null, 2));

  if (verbose) {
    console.error(`Context file created: ${contextFile}`);
    console.error(`Component: ${componentName}`);
    console.error(`Input: ${inputPath}`);
    console.error(`Output: ${outputDir}`);
  }

  // Execute the component
  const result = await executeComponent(componentName, componentDir, contextFile, stepConfig, {
    workchainRoot,
    outputDir,
    verbose,
    timeout: (options.timeout || 3600) * 1000,
  });

  return {
    status: result.exitCode === 0 ? 'completed' : 'failed',
    command: 'run-component',
    component: componentName,
    input_file: inputPath,
    output_dir: outputDir,
    exit_code: result.exitCode,
    context: result.contextData,
    outputs: result.contextData?.steps?.[componentName]?.outputs || {},
    verification: result.contextData?.steps?.[componentName]?.verification || null,
  };
}

/**
 * Run component on all audio files in a directory (batch mode)
 */
async function runBatch(componentName, componentDir, inputDir, options, context) {
  const { workchainRoot, json, verbose } = context;

  // Get audio files
  const extensions = options.extensions
    ? options.extensions.split(',').map(e => e.trim().replace(/^\./, ''))
    : SUPPORTED_AUDIO_EXTENSIONS;

  const audioFiles = getAudioFiles(inputDir, extensions, options.recursive || false);

  if (audioFiles.length === 0) {
    throw new CliError(2, `No audio files found in ${inputDir}`);
  }

  if (verbose) {
    console.error(`Found ${audioFiles.length} audio files to process`);
  }

  const results = [];
  let completed = 0;
  let failed = 0;

  // Process files sequentially (to avoid overwhelming the system)
  for (const file of audioFiles) {
    if (verbose) {
      console.error(`Processing: ${file}`);
    }

    try {
      const result = await runSingleFile(componentName, componentDir, file, options, {
        workchainRoot,
        json: false, // Don't output JSON for each file
        verbose,
      });

      results.push({
        input_file: file,
        status: result.status,
        output_dir: result.output_dir,
        outputs: result.outputs,
        exit_code: result.exit_code,
      });

      if (result.status === 'completed') {
        completed++;
      } else {
        failed++;
      }
    } catch (err) {
      failed++;
      results.push({
        input_file: file,
        status: 'error',
        message: err.message,
      });
    }
  }

  return {
    status: failed === 0 ? 'completed' : 'failed',
    command: 'run-component-batch',
    component: componentName,
    input_dir: inputDir,
    total_files: audioFiles.length,
    results,
    summary: {
      total: audioFiles.length,
      completed,
      failed,
    },
  };
}

/**
 * Execute the component using the engine's step-runner
 */
async function executeComponent(componentName, componentDir, contextFile, stepConfig, options) {
  const { workchainRoot, outputDir, verbose, timeout } = options;

  const engineDir = join(workchainRoot, 'engine');
  const libDir = join(workchainRoot, 'lib');
  const componentsDir = join(workchainRoot, 'components');

  // Build a bash script that sources everything properly.
  //
  // After the component exits 0, run the single verifier (lib/workchain_verify.py)
  // against its declared step.yaml `verify:` contract — the same call the engine's
  // process_step makes. This is what turns a standalone "ran" into "proven correct"
  // on the CLI's direct run-component path (which bypasses the chain engine). A
  // component with no contract is reported "unverified" and passes (non-blocking);
  // a declared contract that fails flips the exit code so status becomes "failed".
  const runScript = `
export WORKCHAIN_ROOT="${workchainRoot}"
export LIB_DIR="${libDir}"
export COMPONENTS_DIR="${componentsDir}"
export ENGINE_DIR="${engineDir}"
export CONTEXT_FILE="${contextFile}"
export CURRENT_STEP="${componentName}"

source "${libDir}/constants.sh" 2>/dev/null || true
source "${libDir}/common-utils.sh" 2>/dev/null || true
source "${engineDir}/step-runner.sh"

init_step_runner "${contextFile}"

__wc_rc=0

# Verified IN: enforce the component's declared inbound dependency contract BEFORE running it.
if [ -f "${libDir}/workchain_preflight.py" ]; then
  python3 "${libDir}/workchain_preflight.py" "${workchainRoot}" "${componentName}" "${contextFile}" || __wc_rc=$?
fi

# Only run the component if its dependencies are satisfied.
if [ $__wc_rc -eq 0 ]; then
  source "${componentDir}/run.sh" "${contextFile}" "${stepConfig}"
  __wc_rc=$?
fi

# Verified OUT: enforce the declared output contract after a clean run.
if [ $__wc_rc -eq 0 ] && [ -f "${libDir}/workchain_verify.py" ]; then
  python3 "${libDir}/workchain_verify.py" "${workchainRoot}" "${componentName}" "${contextFile}" || __wc_rc=$?
fi

exit $__wc_rc
`;

  const { subprocess } = spawnComponentScript({
    workchainRoot,
    runScript,
    timeout,
    env: {
      WORKCHAIN_ROOT: workchainRoot,
      LIB_DIR: libDir,
      COMPONENTS_DIR: componentsDir,
      ENGINE_DIR: engineDir,
    },
  });

  // Stream output if verbose
  if (verbose && subprocess.stdout) {
    subprocess.stdout.pipe(process.stderr);
  }
  if (subprocess.stderr) {
    subprocess.stderr.pipe(process.stderr);
  }

  const { exitCode } = await subprocess;

  // Read the updated context
  let contextData = null;
  if (existsSync(contextFile)) {
    contextData = JSON.parse(readFileSync(contextFile, 'utf-8'));
  }

  return { exitCode, contextData };
}

/**
 * Parse component parameters from step.yaml
 */
function parseComponentParams(stepYamlPath) {
  try {
    const yaml = readFileSync(stepYamlPath, 'utf-8');
    const params = {};

    // Simple YAML parsing for params_schema
    const lines = yaml.split('\n');
    let inParamsSchema = false;
    let currentParam = null;

    for (const line of lines) {
      const trimmed = line.trim();

      if (trimmed.startsWith('params_schema:')) {
        inParamsSchema = true;
        continue;
      }

      if (inParamsSchema) {
        if (trimmed.startsWith('  ') && !trimmed.startsWith('    ')) {
          // Top-level param
          const match = trimmed.match(/^(\w+):/);
          if (match) {
            currentParam = match[1];
            params[currentParam] = { type: 'string', default: undefined };
          }
        } else if (trimmed.startsWith('    ') && currentParam) {
          // Param property
          const propMatch = trimmed.match(/^(\w+):\s*(.+)$/);
          if (propMatch) {
            const [, key, value] = propMatch;
            if (key === 'type') params[currentParam].type = value.replace(/['"]/g, '');
            if (key === 'default') params[currentParam].default = value.replace(/['"]/g, '');
          }
        } else if (!trimmed.startsWith('  ')) {
          break;
        }
      }
    }

    return params;
  } catch (e) {
    return {};
  }
}

/**
 * Build step config from CLI options
 * Handles --params-json for component parameters
 */
function buildStepConfig(params, options) {
  const lines = ['  enabled: true'];

  // Handle --params-json option
  if (options.paramsJson) {
    try {
      const paramsObj = JSON.parse(options.paramsJson);
      for (const [key, value] of Object.entries(paramsObj)) {
        if (value !== undefined) {
          lines.push(`  ${key}: ${value}`);
        }
      }
    } catch (e) {
      throw new Error(`Invalid JSON in --params-json: ${e.message}`);
    }
  }

  return lines.join('\n');
}

function getTimestamp() {
  const now = new Date();
  return now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
}

/**
 * Get audio files from directory
 */
function getAudioFiles(dir, extensions, recursive) {
  const files = [];

  try {
    const entries = readdirSync(dir, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = join(dir, entry.name);

      if (entry.isDirectory() && recursive) {
        files.push(...getAudioFiles(fullPath, extensions, recursive));
      } else if (entry.isFile()) {
        const ext = entry.name.split('.').pop()?.toLowerCase();
        if (ext && extensions.includes(ext)) {
          files.push(fullPath);
        }
      }
    }
  } catch (e) {
    // Ignore errors
  }

  return files;
}
