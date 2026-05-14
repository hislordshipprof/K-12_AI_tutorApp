/**
 * Hydration-aware interaction helpers for Playwright + Next.js dev server.
 *
 * Next 15 + React 19 + Turbopack dev mode occasionally takes a few hundred
 * milliseconds after `networkidle` before button onClick handlers are
 * actually wired up. A click sent during that window is silently lost
 * (the event fires on a not-yet-hydrated DOM node) and the test wedges
 * waiting for state that never arrives.
 *
 * `clickAndWait` retries the click + assertion together via
 * `expect(...).toPass`, which is the canonical Playwright pattern for
 * tolerating eventually-consistent UI. The first click that lands after
 * hydration triggers the assertion to pass and the loop exits.
 *
 * The click target's onClick handler must be idempotent enough that
 * repeated invocations don't break state (most React click handlers
 * guarded by an existing-state check qualify — e.g. the quiz screen's
 * `if (showFb) return;`).
 */
import { expect, type Locator, type Page } from '@playwright/test';

interface ClickAndWaitOptions {
  /** Total budget for the retry loop. Default 10s. */
  timeout?: number;
  /** Time the click+assert pair gets per attempt. Default 1.5s. */
  attemptTimeout?: number;
}

/**
 * Click a locator and wait for an assertion to pass, retrying the pair
 * until either succeeds or the outer timeout elapses.
 */
export async function clickAndWait(
  click: Locator,
  assert: () => Promise<void>,
  opts: ClickAndWaitOptions = {},
): Promise<void> {
  const { timeout = 10_000, attemptTimeout = 1_500 } = opts;
  await expect(async () => {
    await click.click({ timeout: attemptTimeout }).catch(() => undefined);
    await assert();
  }).toPass({ timeout, intervals: [250, 500, 1000] });
}

/**
 * Convenience wrapper: click a locator and wait until the page URL
 * matches a regexp. Same retry semantics as `clickAndWait`.
 */
export async function clickAndNavigate(
  page: Page,
  click: Locator,
  urlPattern: RegExp,
  opts: ClickAndWaitOptions = {},
): Promise<void> {
  await clickAndWait(
    click,
    async () => {
      await expect(page).toHaveURL(urlPattern, { timeout: opts.attemptTimeout ?? 1_500 });
    },
    opts,
  );
}

/**
 * Convenience wrapper: click a locator and wait until a target locator
 * becomes visible. Same retry semantics as `clickAndWait`.
 */
export async function clickAndReveal(
  click: Locator,
  reveal: Locator,
  opts: ClickAndWaitOptions = {},
): Promise<void> {
  await clickAndWait(
    click,
    async () => {
      await expect(reveal).toBeVisible({ timeout: opts.attemptTimeout ?? 1_500 });
    },
    opts,
  );
}
