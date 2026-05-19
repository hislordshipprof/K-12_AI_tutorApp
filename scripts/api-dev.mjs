#!/usr/bin/env node
/**
 * Cross-platform dev launcher for the FastAPI server (`pnpm api:dev`).
 *
 * The repo runs on both Windows and POSIX, where the Python venv layout
 * differs — `.venv\Scripts\` vs `.venv/bin/`. A single bash one-liner in
 * package.json cannot cover both, so this script:
 *   1. creates `apps/api/.venv` on first run,
 *   2. installs the API package editable (a fast no-op when unchanged),
 *   3. starts uvicorn with --reload on port 8000 (DEV_MODE=true).
 *
 * Paths are anchored off this file, so it works regardless of cwd.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const isWin = process.platform === 'win32';
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = join(repoRoot, 'apps', 'api');
const venvDir = join(apiDir, '.venv');
const venvPython = join(
  venvDir,
  isWin ? 'Scripts' : 'bin',
  isWin ? 'python.exe' : 'python',
);

/** Run a blocking step in apps/api; bail out on failure. */
function step(cmd, args, label) {
  const r = spawnSync(cmd, args, { cwd: apiDir, stdio: 'inherit' });
  if (r.status !== 0) {
    console.error(`\n[api:dev] ${label} failed (exit ${r.status ?? r.signal}).`);
    process.exit(r.status ?? 1);
  }
}

// 1. Create the venv on first run.
if (!existsSync(venvDir)) {
  console.log('[api:dev] creating .venv …');
  step(isWin ? 'python' : 'python3', ['-m', 'venv', '.venv'], 'venv create');
}

// 2. Install the API package (editable) — fast no-op when nothing changed.
console.log('[api:dev] installing dependencies …');
step(venvPython, ['-m', 'pip', 'install', '-e', '.', '-q'], 'pip install');

// 3. Start uvicorn with hot-reload.
console.log('[api:dev] starting uvicorn on http://localhost:8000 …');
const server = spawn(
  venvPython,
  [
    '-m',
    'uvicorn',
    'app.main:app',
    '--reload',
    '--host',
    '0.0.0.0',
    '--port',
    '8000',
  ],
  { cwd: apiDir, stdio: 'inherit', env: { ...process.env, DEV_MODE: 'true' } },
);
server.on('exit', (code) => process.exit(code ?? 0));
process.on('SIGINT', () => server.kill('SIGINT'));
process.on('SIGTERM', () => server.kill('SIGTERM'));
