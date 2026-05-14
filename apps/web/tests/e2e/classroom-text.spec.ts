import { expect, test } from '@playwright/test';

import { clickAndReveal, clickAndWait } from '../helpers/hydration';
import { installMockApi } from '../helpers/mock-api';

test.describe('Classroom — text Q&A + sketch', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page, {
      qaAnswerChunks: ['Amplitude ', 'is the wave ', 'height ', 'from rest.'],
    });
    await page.goto('/classroom/wave-properties-anatomy');
  });

  test('whiteboard renders and "Raise hand" opens Q&A overlay', async ({ page }) => {
    const board = page.locator('.cr-board svg').first();
    await expect(board).toBeVisible();

    await clickAndReveal(
      page.getByRole('button', { name: /raise hand/i }),
      page.getByPlaceholder(/ask prof\. aria anything/i),
    );
  });

  test('typing a question streams an answer back', async ({ page }) => {
    await clickAndReveal(
      page.getByRole('button', { name: /raise hand/i }),
      page.getByPlaceholder(/ask prof\. aria anything/i),
    );

    const textarea = page.getByPlaceholder(/ask prof\. aria anything/i);
    // Use pressSequentially so React's controlled-input onChange fires for
    // every character — `fill` sometimes lands before hydration in dev.
    await textarea.click();
    await textarea.pressSequentially("What's amplitude?", { delay: 10 });

    const send = page.locator('button.qa-send').first();
    await expect(send).toBeEnabled();

    await clickAndReveal(
      send,
      page.getByText(/Amplitude is the wave height from rest\./i),
      { timeout: 20_000, attemptTimeout: 3_000 },
    );
  });

  test('"Resume" closes the overlay', async ({ page }) => {
    await clickAndReveal(
      page.getByRole('button', { name: /raise hand/i }),
      page.locator('.qa-ov.active'),
    );

    await clickAndWait(
      page.locator('.qa-bar button.qa-resume'),
      async () => {
        await expect(page.locator('.qa-ov.active')).toHaveCount(0, { timeout: 1_500 });
      },
    );
  });

  test('clicking the sketch (✏️) tool reveals the sketch toolbar', async ({ page }) => {
    await clickAndReveal(
      page.getByTitle('Sketch on the board'),
      page.locator('.sketch-toolbar.open'),
    );
    await expect(page.getByText(/^Chalk$/)).toBeVisible();
  });
});
