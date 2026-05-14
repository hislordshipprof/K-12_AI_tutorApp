import { expect, test } from '@playwright/test';

import { clickAndNavigate, clickAndReveal } from '../helpers/hydration';
import { installMockApi } from '../helpers/mock-api';

/**
 * Quiz screen: pick correct vs wrong answer, then advance to /complete.
 *
 * Question 2 of 3 asks for the period of a 4 Hz wave.
 *   A → 4 seconds   (wrong)
 *   B → 0.25 seconds (CORRECT)
 *   C → 8 seconds   (wrong)
 *   D → 0.5 seconds (wrong)
 */
test.describe('Classroom — quiz flow', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page);
  });

  test('wrong answer shows the "Close — but no" feedback', async ({ page }) => {
    await page.goto('/classroom/quiz/wave-properties-anatomy', {
      waitUntil: 'networkidle',
    });

    // The option button's onClick is guarded by `if (showFb) return;`, so
    // retrying the click is safe — once it lands, repeat clicks are no-ops.
    await clickAndReveal(
      page.locator('button.q-opt', { hasText: '4 seconds' }).first(),
      page.getByText(/close .{0,3}but no/i),
    );
  });

  test('correct answer shows the "Nailed it" feedback then advances', async ({ page }) => {
    await page.goto('/classroom/quiz/wave-properties-anatomy', {
      waitUntil: 'networkidle',
    });

    await clickAndReveal(
      page.locator('button.q-opt', { hasText: '0.25 seconds' }).first(),
      page.getByText(/nailed it/i),
    );

    await clickAndNavigate(
      page,
      page.getByRole('button', { name: /next question/i }),
      /\/classroom\/complete\/wave-properties-anatomy$/,
    );
  });
});
