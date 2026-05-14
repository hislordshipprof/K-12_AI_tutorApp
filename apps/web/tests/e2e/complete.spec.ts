import { expect, test } from '@playwright/test';

import { clickAndWait } from '../helpers/hydration';
import { installMockApi } from '../helpers/mock-api';

test.describe('Lesson-complete celebration', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page);
    await page.goto('/classroom/complete/wave-properties-anatomy');
  });

  test('renders trophy + confetti + completion copy', async ({ page }) => {
    await expect(page.getByText('🏆')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Lesson\s*complete!/i })).toBeVisible();
    // Confetti container is `aria-hidden` and may have no own bounding box,
    // so we assert it's attached + the pieces rendered, not "visible".
    const confetti = page.locator('.complete-confetti');
    await expect(confetti).toBeAttached();
    expect(await confetti.locator('div').count()).toBeGreaterThan(0);
  });

  test('"Back to dashboard" returns to the landing/dashboard route', async ({ page }) => {
    await clickAndWait(
      page.getByRole('button', { name: /back to dashboard/i }),
      async () => {
        await expect(page).not.toHaveURL(/\/classroom\/complete\//, { timeout: 1_500 });
      },
    );
  });
});
