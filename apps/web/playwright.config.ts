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
  // E2E runs against the production build, not `next dev`. Dev mode +
  // React 19 + Turbopack has known hydration-timing flakes where client
  // onClick handlers stay unbound for hundreds of ms after the network
  // settles. `next build && next start` produces a fully-hydrated bundle
  // that behaves like real production traffic. The first run pays the
  // build cost (~30s); subsequent runs reuse the cache.
  webServer: {
    command: 'pnpm build && pnpm start',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
