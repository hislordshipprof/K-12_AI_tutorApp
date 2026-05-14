import { expect, test } from '@playwright/test';

import { clickAndNavigate, clickAndReveal } from '../helpers/hydration';
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
    await clickAndNavigate(
      page,
      page.getByRole('link', { name: /start free/i }),
      /\/onboarding$/,
    );
    await expect(page.getByText(/Meet your tutor/i)).toBeVisible();
  });

  test('completing all 4 onboarding steps lands on /dashboard', async ({ page }) => {
    await page.goto('/onboarding', { waitUntil: 'networkidle' });

    // Step 0 → Step 1
    await clickAndReveal(
      page.getByRole('button', { name: /let.?s go/i }),
      page.getByText(/Step 1 of 3/i),
    );

    // Step 1 — pick a grade, then Continue
    await clickAndReveal(
      page.getByRole('button', { name: /11th grade/i }),
      page.getByRole('button', { name: /^continue$/i }),
    );
    await clickAndReveal(
      page.getByRole('button', { name: /^continue$/i }),
      page.getByRole('button', { name: /AP Physics 1/i }),
    );

    // Step 2 — pick a course, then Continue
    await clickAndReveal(
      page.getByRole('button', { name: /AP Physics 1/i }),
      page.getByRole('button', { name: /continue with 1/i }),
    );
    await clickAndReveal(
      page.getByRole('button', { name: /continue with 1/i }),
      page.getByRole('button', { name: /score a 5/i }),
    );

    // Step 3 — pick a goal, then "Open my classroom"
    await clickAndReveal(
      page.getByRole('button', { name: /score a 5/i }),
      page.getByRole('button', { name: /open my classroom/i }),
    );
    await clickAndNavigate(
      page,
      page.getByRole('button', { name: /open my classroom/i }),
      /\/dashboard$/,
    );
    await expect(page.getByText(/Good morning,\s*Alex/i)).toBeVisible();
  });
});
