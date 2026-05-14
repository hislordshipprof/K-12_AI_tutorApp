import { expect, test } from '@playwright/test';

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

    // Option A = "4 seconds" (wrong). Use the locator chain so we don't
    // depend on Playwright's accessible-name flattening between two child
    // divs (letter + text).
    await page.locator('button.q-opt', { hasText: '4 seconds' }).first().click();

    await expect(page.getByText(/close .{0,3}but no/i)).toBeVisible();
  });

  test('correct answer shows the "Nailed it" feedback then advances', async ({ page }) => {
    await page.goto('/classroom/quiz/wave-properties-anatomy', {
      waitUntil: 'networkidle',
    });

    // Option B = "0.25 seconds" (CORRECT).
    await page.locator('button.q-opt', { hasText: '0.25 seconds' }).click();

    await expect(page.getByText(/nailed it/i)).toBeVisible();

    await page.getByRole('button', { name: /next question/i }).click();
    await expect(page).toHaveURL(/\/classroom\/complete\/wave-properties-anatomy$/);
  });
});
