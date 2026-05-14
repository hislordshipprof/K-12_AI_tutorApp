# Production readiness checklist

Status tracked here: ✓ = done, ◐ = partial, ◯ = not started.

## Functional

| Item | Status |
|---|---|
| All 9 prototype screens render | ◐ (Phase 2 mid-flight) |
| Auth (Supabase magic link + Google) | ◯ (demo mode bypass for MVP) |
| Q&A streaming with real Gemini | ✓ (route wired, SSE working) |
| Sketch analysis with Gemini Vision | ◯ (Phase 3) |
| Voice mode with Gemini Live | ◯ (Phase 3) |
| Quiz generation + scoring | ◐ (UI ready, AI agent pending) |
| Notes CRUD (manual + auto) | ◐ (stubs return sample data) |
| Planner with weekly schedule | ◐ (UI ready, agent pending) |
| Flashcards (SM-2 spaced repetition) | ◐ (schema ready, no UI logic) |
| History replay | ◐ (UI ready, no replay storage) |

## Non-functional

| Item | Status |
|---|---|
| TypeScript strict mode | ✓ |
| All Tailwind tokens centralized | ✓ |
| RLS on every user-owned table | ✓ |
| Server-side Gemini calls only (key never in browser) | ✓ |
| SecretStr wrapping in API | ✓ |
| Structured logs (JSON in prod) | ✓ |
| X-Request-ID per request | ✓ |
| Retry on transient Gemini errors | ✓ |
| Pre-commit secret scan hook | ✓ (script provided; user installs) |
| GitHub Actions CI (typecheck/lint/test/build) | ✓ |
| GitHub Actions secret scan | ✓ |
| GitHub Actions deploy workflow | ✓ |
| Dockerfile for API | ✓ |
| fly.toml | ✓ |
| vercel.json | ✓ |
| OpenAPI auto-gen | ✓ (FastAPI built-in) |
| Health check endpoint | ✓ |
| CORS configured | ✓ |
| Rate limiting | ◯ (not implemented; Fly.io can do edge rate limiting) |
| Sentry / observability | ◯ (Phase 4) |
| agent_traces table populated | ◯ (Phase 4 — schema ready) |

## Testing

| Item | Status |
|---|---|
| Unit tests (API) | ✓ 18 passing |
| Unit tests (Web) | ◯ (vitest wired, no tests yet) |
| E2E tests (Playwright) | ◯ (Phase 4) |
| Manual smoke checklist | ◐ (see HANDOFF.md) |

## Deployment

| Item | Status |
|---|---|
| Vercel project ready | Needs user — `vercel` CLI link |
| Fly.io app ready | Needs user — `fly launch` |
| Supabase project ready | Needs user — keys + migrations |
| Custom domain | Optional, deferred |
| HTTPS | Auto via Vercel + Fly |
| Cron for nightly PlannerAgent | ◯ (deferred) |

## Cost & monitoring

| Item | Status |
|---|---|
| Per-user token quota | ◯ (deferred) |
| Daily soft/hard cap | ◯ (deferred) |
| Cost dashboard | Use Google Cloud Console + Supabase + Fly + Vercel dashboards |
| Error tracking | ◯ (Sentry — Phase 4) |

## Compliance / safety

| Item | Status |
|---|---|
| COPPA — students under 13 excluded by grade | ✓ |
| Privacy: no PII beyond name + grade | ✓ |
| Voice audio not persisted by default | ✓ (by design — pass-through) |
| Aria persona is age-appropriate, supportive | ✓ (in prompts) |
| Gemini safety filters not disabled | ✓ (defaults retained) |
| Terms / Privacy pages | ◯ (need legal review) |
