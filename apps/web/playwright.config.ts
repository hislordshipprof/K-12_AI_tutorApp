import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.PORT ?? 3000);
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`;

/**
 * Playwright config for the EduMind web E2E suite.
 *
 * - chromium-only (CI-friendly)
 * - auto-starts `pnpm dev` on port 3000 unless one's already running
 * - all `/v1/*` backend calls are intercepted in tests via `installMockApi`
 */
export default defineConfig({
  testDir: './tests/e2e',
  // Next.js dev server compiles routes on-demand, so first-hit can be slow.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // Run files sequentially so the dev server isn't slammed with parallel
  // first-compile requests (which surfaces as "Application error" flakes).
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'pnpm dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
