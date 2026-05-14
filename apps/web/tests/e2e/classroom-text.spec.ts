import { expect, test } from '@playwright/test';

import { installMockApi } from '../helpers/mock-api';

test.describe('Classroom — text Q&A + sketch', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page, {
      qaAnswerChunks: ['Amplitude ', 'is the wave ', 'height ', 'from rest.'],
    });
    await page.goto('/classroom/wave-properties-anatomy');
  });

  test('whiteboard renders and "Raise hand" opens Q&A overlay', async ({ page }) => {
    // Whiteboard SVG is the only visible chalk surface.
    const board = page.locator('.cr-board svg').first();
    await expect(board).toBeVisible();

    await page.getByRole('button', { name: /raise hand/i }).click();

    const textarea = page.getByPlaceholder(/ask prof\. aria anything/i);
    await expect(textarea).toBeVisible();
  });

  test('typing a question streams an answer back', async ({ page }) => {
    await page.getByRole('button', { name: /raise hand/i }).click();

    const textarea = page.getByPlaceholder(/ask prof\. aria anything/i);
    await expect(textarea).toBeVisible();
    // Use pressSequentially so React's controlled-input onChange fires for
    // every character — `fill` sometimes lands before hydration in dev.
    await textarea.click();
    await textarea.pressSequentially("What's amplitude?", { delay: 10 });

    const send = page.locator('button.qa-send').first();
    await expect(send).toBeEnabled();
    await send.click();

    // The mocked SSE stream concatenates to the full sentence.
    await expect(
      page.getByText(/Amplitude is the wave height from rest\./i),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('"Resume" closes the overlay', async ({ page }) => {
    await page.getByRole('button', { name: /raise hand/i }).click();
    const overlay = page.locator('.qa-ov.active');
    await expect(overlay).toBeVisible();

    await page.locator('.qa-bar button.qa-resume').click();

    await expect(overlay).toHaveCount(0);
  });

  test('clicking the sketch (✏️) tool reveals the sketch toolbar', async ({ page }) => {
    await page.getByTitle('Sketch on the board').click();

    // The toolbar exposes the Chalk label when open.
    await expect(page.locator('.sketch-toolbar.open')).toBeVisible();
    await expect(page.getByText(/^Chalk$/)).toBeVisible();
  });
});
