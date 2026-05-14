# Phase 4 — Polish + ship (dispatch after Phase 3 verifies)

## Agent T1 — E2E Playwright suite

```
Working dir: /home/claude/K-12_AI_tutorApp/apps/web
Owned: apps/web/tests/e2e/*.spec.ts, apps/web/tests/fixtures/*, apps/web/tests/helpers/*
DO NOT TOUCH any other files.

Build a Playwright E2E suite covering the golden path:

1. tests/e2e/marketing.spec.ts
   - Landing page renders, contains "private tutor"
   - "Start free" → /onboarding
   - Onboarding 4 steps complete → /dashboard

2. tests/e2e/dashboard.spec.ts
   - Dashboard renders with "Good morning, Alex"
   - All 3 course cards present
   - "Resume lesson" → /classroom/wave-properties-anatomy
   - Rail navigation: dashboard → planner → notes → history works

3. tests/e2e/classroom-text.spec.ts
   - Classroom renders with WhiteboardSVG visible
   - Click "Raise hand" → QA overlay opens
   - Type a question, send → answer streams in (mock the SSE endpoint)
   - Resume → overlay closes
   - Click ✏️ sketch icon → toolbar appears

4. tests/e2e/classroom-quiz.spec.ts
   - From classroom, navigate to quiz
   - Pick wrong answer → feedback says "Walk it back..." or similar
   - Pick correct → "Nailed it" or similar
   - "Next" → /complete

5. tests/e2e/complete.spec.ts
   - Complete page renders with trophy + confetti
   - "Back to dashboard" → dashboard

Use a mock backend: tests/helpers/mock-api.ts intercepts /v1/* requests and returns deterministic responses (no real Gemini calls in CI).

Acceptance: pnpm test:e2e passes (headless Chrome). Configure playwright.config.ts webServer to auto-start `pnpm dev`.
```

## Agent M1 — Middleware + Supabase auth UX (optional MVP add)

```
Working dir: /home/claude/K-12_AI_tutorApp/apps/web
Owned: apps/web/src/middleware.ts, apps/web/src/app/(marketing)/login/page.tsx, apps/web/src/app/(marketing)/auth/callback/route.ts
DO NOT TOUCH other files.

Build:

1. middleware.ts — Supabase SSR session refresh on every request.
   Use the pattern from @supabase/ssr docs:
     - createServerClient bound to request cookies
     - await supabase.auth.getUser()
     - if no session and path is in /dashboard|/planner|/notes|/history|/classroom — redirect to /login
   
2. /login page — magic-link form using Supabase Auth.
   - Email input → supabase.auth.signInWithOtp({email})
   - Show "Check your email for the magic link" message
   - Also Google OAuth button → supabase.auth.signInWithOAuth({provider:'google'})

3. /auth/callback route — exchange code for session, redirect to /dashboard.

4. DEMO MODE: if NEXT_PUBLIC_DEMO_MODE=true, skip middleware redirects (so the prototype works without auth setup).

Acceptance: pnpm typecheck + pnpm build clean. Hitting /dashboard without auth redirects to /login (in non-demo mode).
```

## Agent O1 — Observability hooks (Sentry + agent_traces emission)

```
Working dir: /home/claude/K-12_AI_tutorApp
Owned: apps/api/app/core/tracing.py, apps/web/src/lib/sentry.ts (stub), update existing routes to emit traces
DO NOT TOUCH unrelated files.

Build:

1. apps/api/app/core/tracing.py — helper `emit_trace(agent, step, input, output, latency_ms, session_id, user_id)` that inserts into agent_traces (via supabase admin client). Background task (don't block the response).

2. Update qa.py, sketch.py, sessions.py, voice.py to emit traces around every Gemini call.

3. apps/web/src/lib/sentry.ts — stub that initializes Sentry IF NEXT_PUBLIC_SENTRY_DSN is set; otherwise no-op. Wrap App with ErrorBoundary.

Acceptance: agent_traces table has rows after a Q&A session (verify with `select count(*) from agent_traces`).
```
