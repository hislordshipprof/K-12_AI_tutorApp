/**
 * Mock-API helper for Playwright E2E tests.
 *
 * The web app talks to a FastAPI backend at NEXT_PUBLIC_API_BASE (default
 * `http://localhost:8000`). For E2E we intercept every request to that
 * origin via Playwright's `page.route` and return deterministic JSON so
 * the suite never depends on a live backend or real Gemini calls.
 *
 * The two pieces that need special handling:
 *   1. POST /v1/sessions/{id}/qa  — Server-Sent Events stream (token chunks).
 *   2. POST /v1/sessions          — opens a tutor session (returns id).
 *
 * Everything else just resolves to a 200 with an empty/sensible body so
 * fire-and-forget `api(...)` calls in the app don't throw.
 */
import type { Page, Route } from '@playwright/test';

export const MOCK_SESSION_ID = 'sess_test_00000000';

/** Build an SSE body string from a list of token chunks plus a final done frame. */
function buildSSEBody(tokens: string[]): string {
  const frames = tokens.map(
    (t) => `data: ${JSON.stringify({ type: 'token', content: t })}`,
  );
  frames.push(`data: ${JSON.stringify({ type: 'done' })}`);
  // SSE frames end with a blank line — `\n\n` between frames + a trailing one.
  return frames.join('\n\n') + '\n\n';
}

interface InstallOptions {
  /** Override the answer the SSE endpoint streams back. */
  qaAnswerChunks?: string[];
}

/**
 * Install request interceptors on the given page. Call this once per test
 * BEFORE navigating to the page under test.
 *
 * Returns an object exposing the canonical session id so tests can match
 * URLs / routes against it if needed.
 */
export async function installMockApi(
  page: Page,
  opts: InstallOptions = {},
): Promise<{ sessionId: string }> {
  const qaAnswer =
    opts.qaAnswerChunks ?? [
      'Amplitude ',
      'is how far ',
      'the wave swings ',
      'from rest.',
    ];

  // Match every /v1/* call regardless of which host the app points at.
  await page.route('**/v1/**', async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();

    // --- SSE: Q&A streaming ---
    if (/\/v1\/sessions\/[^/]+\/qa$/.test(path) && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
        body: buildSSEBody(qaAnswer),
      });
      return;
    }

    // --- Open a session ---
    if (/\/v1\/sessions\/?$/.test(path) && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: MOCK_SESSION_ID, session_id: MOCK_SESSION_ID }),
      });
      return;
    }

    // --- Misc session sub-resources (reply, sketch, heartbeat, end) ---
    if (/\/v1\/sessions\/[^/]+\/.+/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
      return;
    }

    // --- Quiz attempts ---
    if (/\/v1\/quiz\/.+\/attempt$/.test(path) && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, correct: false }),
      });
      return;
    }

    // --- Courses ---
    if (/\/v1\/courses\/?$/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }

    // Default fall-through — empty JSON so the app's silent catches stay silent.
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    });
  });

  return { sessionId: MOCK_SESSION_ID };
}
