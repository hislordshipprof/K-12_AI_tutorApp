import { expect, test } from '@playwright/test';

import { clickAndNavigate } from '../helpers/hydration';
import { installMockApi } from '../helpers/mock-api';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page);
    await page.goto('/dashboard');
  });

  test('renders hero with "Good morning, Alex"', async ({ page }) => {
    await expect(page.getByText(/Good morning,/i)).toBeVisible();
  });

  test('shows all 3 course cards', async ({ page }) => {
    // "AP Physics 1" appears twice (course card + curriculum section header
    // for the active course) — assert via the course-card button role.
    await expect(
      page.getByRole('button', { name: /AP Physics 1/ }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: /AP Calculus BC/ }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: /AP Biology/ }).first(),
    ).toBeVisible();
  });

  test('"Resume lesson" navigates to the wave-properties classroom', async ({ page }) => {
    await clickAndNavigate(
      page,
      page.getByRole('button', { name: /Pick up where you left off/i }),
      /\/classroom\/wave-properties-anatomy$/,
    );
  });

  test('rail nav: dashboard → planner → notes → history', async ({ page }) => {
    // `exact: true` because the TopNav "EduMind home" logo button would
    // otherwise also match `name: 'Home'` via substring, and Playwright
    // would click the wrong one (which navigates to '/').
    await clickAndNavigate(
      page,
      page.getByRole('button', { name: 'Plan', exact: true }),
      /\/planner$/,
    );
    await clickAndNavigate(
      page,
      page.getByRole('button', { name: 'Notes', exact: true }),
      /\/notes$/,
    );
    await clickAndNavigate(
      page,
      page.getByRole('button', { name: 'History', exact: true }),
      /\/history$/,
    );
    await clickAndNavigate(
      page,
      page.getByRole('button', { name: 'Home', exact: true }),
      /\/dashboard$/,
    );
  });
});
