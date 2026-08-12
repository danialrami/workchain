import { readFile, writeFile, readdir, stat } from 'fs/promises';
import { join, relative, extname } from 'path';
import { existsSync } from 'fs';

/**
 * Generate an HTML report from context.json, styled in the LUFS design language
 * (Host Grotesk / Public Sans / Space Mono; brand palette on near-black).
 * Renders component outputs flexibly by type: audio, image, video, text/json, directories.
 */
export async function generateReport(contextPath, outputDir, inputName) {
  const raw = await readFile(contextPath, 'utf-8');
  const context = JSON.parse(raw);
  const reportInputName = inputName || context.input_name || 'output';
  const reportFile = join(outputDir, `${reportInputName}_report.html`);
  const html = await buildHtmlReport(context, outputDir, reportInputName);
  await writeFile(reportFile, html, 'utf-8');
  return reportFile;
}

async function buildHtmlReport(context, outputDir, reportInputName) {
  const steps = context.steps || {};
  const stepsHtml = await buildStepsHtml(steps, outputDir);
  const timestamp = new Date().toISOString();
  const chainName = context.chain_name || 'chain';
  const chainStatus = context.status || (Object.values(steps).every(s => s.status === 'completed') ? 'completed' : 'unknown');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LUFS Workchain — ${escapeHtml(reportInputName)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Host+Grotesk:wght@400;500;600;700&family=Public+Sans:wght@400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:#111111; --panel:#181a19; --panel2:#1f2220; --line:#2c302e;
      --ink:#E2E3D8; --muted:#9aa39c; --faint:#6b746d;
      --teal:#78BEBA; --yellow:#E7B225; --blue:#2069AF; --red:#D35233;
    }
    * { box-sizing:border-box; margin:0; padding:0; }
    body {
      font-family:"Public Sans",system-ui,sans-serif; background:var(--bg); color:var(--ink);
      line-height:1.6; padding:48px 24px; max-width:1080px; margin:0 auto;
      -webkit-font-smoothing:antialiased;
    }
    h1,h2,h3 { font-family:"Host Grotesk","Public Sans",sans-serif; letter-spacing:-.01em; }
    .eyebrow { font-family:"Space Mono",monospace; font-size:12px; letter-spacing:.28em; text-transform:uppercase; color:var(--teal); margin-bottom:14px; }
    h1 { font-size:2.4rem; font-weight:700; margin-bottom:6px; }
    h1 .accent { color:var(--teal); }
    h2 { font-size:1.4rem; font-weight:600; margin:36px 0 16px; padding-bottom:8px; border-bottom:1px solid var(--line); }
    .meta { font-family:"Space Mono",monospace; font-size:12.5px; color:var(--faint); display:flex; flex-wrap:wrap; gap:6px 24px; margin:10px 0 8px; }
    .meta b { color:var(--ink); font-weight:400; }

    .summary { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:22px; margin:24px 0; }
    .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:16px; }
    .summary-item { text-align:center; }
    .summary-value { font-family:"Host Grotesk"; font-size:2.2rem; font-weight:700; line-height:1; }
    .summary-label { font-size:.82rem; color:var(--muted); margin-top:6px; }

    .step { background:var(--panel); border:1px solid var(--line); border-left-width:4px; border-radius:12px; padding:20px 22px; margin-bottom:18px; }
    .step.s-completed { border-left-color:var(--teal); }
    .step.s-completed_with_errors { border-left-color:var(--yellow); }
    .step.s-skipped { border-left-color:var(--faint); }
    .step.s-failed { border-left-color:var(--red); }
    .step.s-not_implemented { border-left-color:var(--blue); }
    .step.s-unknown { border-left-color:var(--faint); }
    .step-header { display:flex; align-items:center; gap:12px; }
    .step-name { font-family:"Host Grotesk"; font-weight:600; font-size:1.15rem; }
    .badge { font-family:"Space Mono",monospace; font-size:10.5px; letter-spacing:.06em; text-transform:uppercase; padding:3px 10px; border-radius:20px; border:1px solid var(--line); }
    .b-completed { color:var(--teal); border-color:rgba(120,190,186,.45); background:rgba(120,190,186,.12); }
    .b-completed_with_errors { color:var(--yellow); border-color:rgba(231,178,37,.4); background:rgba(231,178,37,.12); }
    .b-skipped { color:var(--muted); }
    .b-failed { color:var(--red); border-color:rgba(211,82,51,.45); background:rgba(211,82,51,.12); }
    .b-not_implemented { color:#7fb2e6; border-color:rgba(32,105,175,.5); background:rgba(32,105,175,.16); }
    .b-unknown { color:var(--muted); }

    .output-item { margin-top:16px; padding-left:16px; border-left:2px solid var(--line); }
    .output-label { font-family:"Space Mono",monospace; font-weight:700; color:var(--teal); font-size:.92rem; }
    .output-meta { font-size:.82rem; color:var(--muted); margin:4px 0 8px; word-break:break-word; }
    .output-missing { font-family:"Space Mono",monospace; font-size:.8rem; color:var(--red); }
    audio, video, img { max-width:100%; border-radius:8px; margin:8px 0; }
    audio { width:100%; }
    .image-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:14px; margin:10px 0; }
    .image-grid img { width:100%; height:auto; }
    pre { background:#0c0e0d; border:1px solid var(--line); padding:14px 16px; border-radius:8px; overflow-x:auto; font-family:"Space Mono",monospace; font-size:12.5px; color:#cdd3cb; margin:8px 0; max-height:420px; }
    a.file-link { color:var(--teal); text-decoration:none; border-bottom:1px solid rgba(120,190,186,.3); word-break:break-all; }
    a.file-link:hover { border-color:var(--teal); }
    .dir-listing { background:#0c0e0d; border:1px solid var(--line); padding:12px 16px; border-radius:8px; }
    .dir-listing ul { list-style:none; }
    .dir-listing li { margin:4px 0; font-family:"Space Mono",monospace; font-size:.85rem; }
    .kv { font-family:"Space Mono",monospace; font-size:.8rem; color:var(--muted); }
    .kv b { color:var(--ink); font-weight:400; }
    footer { margin-top:40px; padding-top:16px; border-top:1px solid var(--line); font-family:"Space Mono",monospace; font-size:11px; color:var(--faint); }
  </style>
</head>
<body>
  <div class="eyebrow">LUFS Workchain · Run Report</div>
  <h1><span class="accent">${escapeHtml(chainName)}</span></h1>
  <div class="meta">
    <div>INPUT&nbsp; <b>${escapeHtml(reportInputName)}</b></div>
    <div>STATUS&nbsp; <b>${escapeHtml(chainStatus)}</b></div>
    <div>GENERATED&nbsp; <b>${timestamp}</b></div>
  </div>

  ${buildSummaryHtml(steps)}

  <h2>Processing steps</h2>
  ${stepsHtml}

  <footer>Generated by LUFS Workchain · ${escapeHtml(chainName)}</footer>
</body>
</html>`;
}

function buildSummaryHtml(steps) {
  const entries = Object.entries(steps || {});
  const total = entries.length;
  const count = (st) => entries.filter(([, s]) => s.status === st).length;
  const completed = count('completed');
  const failed = count('failed') + count('not_implemented');
  const warned = count('completed_with_errors');
  const skipped = count('skipped');

  const cell = (value, label, color) =>
    `<div class="summary-item"><div class="summary-value" style="color:${color}">${value}</div><div class="summary-label">${label}</div></div>`;

  return `<div class="summary"><div class="summary-grid">
    ${cell(total, 'Steps', 'var(--ink)')}
    ${cell(completed, 'Completed', 'var(--teal)')}
    ${warned ? cell(warned, 'With warnings', 'var(--yellow)') : ''}
    ${cell(skipped, 'Skipped', 'var(--muted)')}
    ${cell(failed, 'Failed', failed ? 'var(--red)' : 'var(--muted)')}
  </div></div>`;
}

async function buildStepsHtml(steps, outputDir) {
  const entries = Object.entries(steps || {});
  if (entries.length === 0) return '<p class="output-meta">No steps recorded in context.</p>';
  const results = await Promise.all(entries.map(([n, d]) => buildStepHtml(n, d, outputDir)));
  return results.join('\n');
}

async function buildStepHtml(stepName, stepData, outputDir) {
  const status = stepData.status || 'unknown';
  const outputsHtml = stepData.outputs
    ? await buildOutputsHtml(stepData.outputs, outputDir)
    : '';
  const reason = stepData.error || stepData.reason
    ? `<div class="output-meta">${escapeHtml(stepData.error || stepData.reason)}</div>`
    : '';
  return `<div class="step s-${escapeHtml(status)}">
    <div class="step-header">
      <span class="step-name">${escapeHtml(stepName)}</span>
      <span class="badge b-${escapeHtml(status)}">${escapeHtml(status)}</span>
    </div>
    ${reason}
    ${outputsHtml}
  </div>`;
}

async function buildOutputsHtml(outputs, outputDir) {
  const entries = Object.entries(outputs);
  const results = await Promise.all(entries.map(([n, d]) => buildOutputHtml(n, d, outputDir)));
  return results.join('\n');
}

async function buildOutputHtml(outputName, outputData, outputDir) {
  if (!outputData) return '';
  const outputPath = outputData.path;
  const relPath = outputPath ? relative(outputDir, outputPath) : '';
  const present = outputPath && existsSync(outputPath);

  let contentHtml = '';
  if (present) {
    const ext = extname(outputPath).toLowerCase();
    let isDir = outputData.type === 'directory';
    if (!isDir) {
      try { isDir = (await stat(outputPath)).isDirectory(); } catch {}
    }
    if (isDir) {
      contentHtml = await buildDirectoryHtml(outputPath, outputDir);
    } else if (['.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aiff', '.aif', '.opus'].includes(ext)) {
      contentHtml = `<audio controls src="${escapeHtml(relPath)}">Audio playback unsupported.</audio>`;
    } else if (['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'].includes(ext)) {
      contentHtml = `<img src="${escapeHtml(relPath)}" alt="${escapeHtml(outputName)}" />`;
    } else if (['.mp4', '.webm', '.mov'].includes(ext)) {
      contentHtml = `<video controls src="${escapeHtml(relPath)}">Video playback unsupported.</video>`;
    } else if (['.txt', '.log', '.md', '.json', '.yaml', '.yml', '.csv'].includes(ext) || outputData.type === 'json') {
      contentHtml = await buildTextFileHtml(outputPath);
    }
  } else if (outputData.status && outputData.status !== 'completed') {
    contentHtml = `<div class="output-missing">not produced (status: ${escapeHtml(outputData.status)})</div>`;
  }

  const pathHtml = relPath
    ? `Path: <a href="${escapeHtml(relPath)}" class="file-link">${escapeHtml(relPath)}</a>${outputData.description ? ` · ${escapeHtml(outputData.description)}` : ''}`
    : (outputData.description ? escapeHtml(outputData.description) : '');

  return `<div class="output-item">
    <div class="output-label">${escapeHtml(outputName)}</div>
    ${pathHtml ? `<div class="output-meta">${pathHtml}</div>` : ''}
    ${contentHtml}
    ${buildMetadataHtml(outputData)}
  </div>`;
}

async function buildDirectoryHtml(dirPath, outputDir) {
  try {
    const files = await readdir(dirPath);
    const imageFiles = files.filter(f => ['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(extname(f).toLowerCase()));
    if (imageFiles.length > 0) {
      const imagesHtml = imageFiles
        .map(f => `<img src="${escapeHtml(relative(outputDir, join(dirPath, f)))}" alt="${escapeHtml(f)}" />`)
        .join('\n');
      return `<div class="image-grid">${imagesHtml}</div>`;
    }
    const filesHtml = files
      .map(f => `<li><a href="${escapeHtml(relative(outputDir, join(dirPath, f)))}" class="file-link">${escapeHtml(f)}</a></li>`)
      .join('\n');
    return `<div class="dir-listing"><ul>${filesHtml}</ul></div>`;
  } catch {
    return '<p class="output-missing">Error reading directory.</p>';
  }
}

async function buildTextFileHtml(filePath) {
  try {
    const content = await readFile(filePath, 'utf-8');
    return `<pre>${escapeHtml(content)}</pre>`;
  } catch {
    return '<p class="output-missing">Error reading file.</p>';
  }
}

function buildMetadataHtml(outputData) {
  const metadata = { ...outputData };
  for (const k of ['path', 'status', 'type', 'exists', 'description', 'path_template']) delete metadata[k];
  const entries = Object.entries(metadata);
  if (entries.length === 0) return '';
  const rows = entries
    .map(([key, value]) => {
      const v = typeof value === 'object' ? JSON.stringify(value) : String(value);
      return `<div class="kv"><b>${escapeHtml(key)}:</b> ${escapeHtml(v)}</div>`;
    })
    .join('\n');
  return `<div style="margin-top:8px">${rows}</div>`;
}

function escapeHtml(str) {
  if (typeof str !== 'string') return str;
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
