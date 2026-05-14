import { expect, test } from '@playwright/test';

import { installMockApi } from '../helpers/mock-api';

test.describe('Marketing → onboarding → dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page);
  });

  test('landing page shows hero copy', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('private tutor', { exact: false })).toBeVisible();
  });

  test('"Start free" navigates to onboarding', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /start free/i }).click();
    await expect(page).toHaveURL(/\/onboarding$/);
    // Step 0 of onboarding is Aria's intro.
    await expect(page.getByText(/Meet your tutor/i)).toBeVisible();
  });

  test('completing all 4 onboarding steps lands on /dashboard', async ({ page }) => {
    await page.goto('/onboarding', { waitUntil: 'networkidle' });

    // Helper: click then poll until the expected next-step element appears.
    // Next dev + React 19 hydration occasionally drops the first click; we
    // retry up to 5 times before failing.
    async function clickUntil(
      buttonName: RegExp,
      nextStepLocator: () => Promise<unknown>,
    ): Promise<void> {
      const btn = page.getByRole('button', { name: buttonName });
      await expect(btn).toBeVisible();
      for (let attempt = 0; attempt < 5; attempt++) {
        await btn.click({ trial: false }).catch(() => undefined);
        try {
          await nextStepLocator();
          return;
        } catch {
          await page.waitForTimeout(500);
        }
      }
      // Final await to surface the real assertion error.
      await nextStepLocator();
    }

    await clickUntil(/let.?s go/i, async () => {
      await expect(page.getByText(/Step 1 of 3/i)).toBeVisible({ timeout: 2000 });
    });

    // Step 1 — pick a grade, then Continue
    const gradeBtn = page.getByRole('button', { name: /11th grade/i });
    await expect(gradeBtn).toBeVisible();
    await gradeBtn.click();
    await page.getByRole('button', { name: /^continue$/i }).click();

    // Step 2 — pick at least one course, then Continue
    const courseBtn = page.getByRole('button', { name: /AP Physics 1/i });
    await expect(courseBtn).toBeVisible();
    await courseBtn.click();
    await page.getByRole('button', { name: /continue with 1/i }).click();

    // Step 3 — pick a goal, then "Open my classroom"
    const goalBtn = page.getByRole('button', { name: /score a 5/i });
    await expect(goalBtn).toBeVisible();
    await goalBtn.click();
    await page.getByRole('button', { name: /open my classroom/i }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText(/Good morning,\s*Alex/i)).toBeVisible();
  });
});
