import { expect, test } from '@playwright/test';

import { installMockApi } from '../helpers/mock-api';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page);
    await page.goto('/dashboard');
  });

  test('renders hero with "Good morning, Alex"', async ({ page }) => {
    await expect(page.getByText(/Good morning,\s*Alex/i)).toBeVisible();
  });

  test('shows all 3 course cards', async ({ page }) => {
    await expect(page.getByText('AP Physics 1', { exact: true })).toBeVisible();
    await expect(page.getByText('AP Calculus BC', { exact: true })).toBeVisible();
    await expect(page.getByText('AP Biology', { exact: true })).toBeVisible();
  });

  test('"Resume lesson" navigates to the wave-properties classroom', async ({ page }) => {
    // The hero CTA is a <button> whose accessible name starts with the
    // eyebrow label "Pick up where you left off".
    await page
      .getByRole('button', { name: /Pick up where you left off/i })
      .click();
    await expect(page).toHaveURL(/\/classroom\/wave-properties-anatomy$/);
  });

  test('rail nav: dashboard → planner → notes → history', async ({ page }) => {
    await page.getByRole('button', { name: 'Plan' }).click();
    await expect(page).toHaveURL(/\/planner$/);

    await page.getByRole('button', { name: 'Notes' }).click();
    await expect(page).toHaveURL(/\/notes$/);

    await page.getByRole('button', { name: 'History' }).click();
    await expect(page).toHaveURL(/\/history$/);

    await page.getByRole('button', { name: 'Home' }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});
