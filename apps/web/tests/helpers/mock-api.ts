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

    // --- Courses (real shape so the dashboard renders the three cards) ---
    if (/\/v1\/courses\/?$/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: '11111111-1111-1111-1111-111111111111',
            slug: 'ap-physics-1',
            title: 'AP Physics 1',
            exam: 'AP',
            color_gradient: 'linear-gradient(135deg,#1F4E7A 0%,#5B5BE5 100%)',
            icon_emoji: '⚛️',
            sort_order: 1,
          },
          {
            id: '22222222-2222-2222-2222-222222222222',
            slug: 'ap-calc-bc',
            title: 'AP Calculus BC',
            exam: 'AP',
            color_gradient: 'linear-gradient(135deg,#7A1F4E 0%,#E55B9C 100%)',
            icon_emoji: '∫',
            sort_order: 2,
          },
          {
            id: '33333333-3333-3333-3333-333333333333',
            slug: 'ap-biology',
            title: 'AP Biology',
            exam: 'AP',
            color_gradient: 'linear-gradient(135deg,#1F7A4E 0%,#5BE59C 100%)',
            icon_emoji: '🧬',
            sort_order: 3,
          },
        ]),
      });
      return;
    }

    // --- Course units tree (curriculum view) ---
    if (/\/v1\/courses\/[^/]+\/units\/?$/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'u1',
            n: 1,
            name: 'Kinematics',
            topics: [
              { id: 't1', n: 1, name: 'Position & Velocity', duration_min: 12 },
            ],
          },
        ]),
      });
      return;
    }

    // --- Planner week ---
    if (/\/v1\/planner\/week\/?$/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ week_start: '2026-05-11', blocks: [] }),
      });
      return;
    }

    // --- /v1/me ---
    if (/\/v1\/me\/?$/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: '00000000-0000-0000-0000-000000000001',
          full_name: 'Alex Johnson',
          avatar_color: '#5B5BE5',
          streak_days: 5,
          stats: { topics_done: 12, time_spent_min: 210, quiz_avg_pct: 87 },
        }),
      });
      return;
    }

    // --- /v1/notes (list) ---
    if (/\/v1\/notes\/?$/.test(path) && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }

    // --- /v1/history ---
    if (/\/v1\/history\/?$/.test(path)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }

    // --- /v1/flashcards/due ---
    if (/\/v1\/flashcards\/due\/?$/.test(path)) {
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
