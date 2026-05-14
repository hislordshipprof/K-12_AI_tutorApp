# Production readiness checklist

Status tracked here: ✓ = done, ◐ = partial, ◯ = not started.
Last updated: 2026-05-14 (after security + curriculum + real-data refactor).

## Functional

| Item | Status |
|---|---|
| All 9 prototype screens render | ✓ (Playwright 15/15 passing) |
| Auth (Supabase magic link + Google) | ✓ (`/login`, `/auth/callback`, middleware gating, DEMO_MODE bypass for previews) |
| Q&A streaming with real Gemini | ✓ (SSE, Socratic, multi-turn — live-verified on `gemini-3.1-flash-lite`) |
| Sketch analysis with Gemini Vision | ✓ (multipart upload, 8MB cap, magic-byte sniff; sample Socratic reply streams back) |
| Voice mode with Gemini Live | ✓ (WS bridge to `gemini-2.5-flash-native-audio-latest`; bidi audio; concurrency-gated 1/user) |
| Quiz generation + scoring | ◐ (attempts recorded to `quiz_attempts`; questions still a single hardcoded sample — needs content pipeline) |
| Notes CRUD (manual + auto) | ✓ (real Supabase round-trip; UI fetches `/v1/notes`) |
| Planner with weekly schedule | ✓ (real Supabase `/v1/planner/week`; UI buckets by day; auto-generation deferred) |
| Flashcards (SM-2 spaced repetition) | ◐ (SM-2 algorithm + `/v1/flashcards/due` ship; no deck-builder UI yet) |
| History replay | ◐ (list page hits real `/v1/history`; click-to-replay not built — needs lesson playback state archival) |
| Real student state on dashboard | ✓ (name, streak, stats from `/v1/me`; curriculum tree from `/v1/courses/{slug}/units`; no hardcoded fixtures) |

## Curriculum & content

| Item | Status |
|---|---|
| AP Physics 1 unit tree aligned to 2024 CED | ✓ (migration `20260514001000_curriculum_v2_ced_2024`) |
| AP Calc BC unit tree aligned to 2024 CED | ✓ (10 units) |
| AP Biology unit tree aligned to 2024 CED | ✓ (8 units — already matched) |
| Real lesson content for ≥1 topic | ✓ (one — Oscillations: Amplitude, Period & Frequency, hand-authored) |
| Real lesson content for the other ~25 topics | ◯ (needs content pipeline) |
| Quiz questions per topic | ◯ (one hardcoded sample shared across all quiz routes) |
| OpenStax / external content ingest pipeline | ◯ (designed; see `docs/content-pipeline.md`) |

## Non-functional

| Item | Status |
|---|---|
| TypeScript strict mode | ✓ |
| All Tailwind tokens centralized | ✓ |
| RLS on every user-owned table | ✓ |
| Server-side Gemini calls only (key never in browser) | ✓ (verified — bundle scan clean) |
| SecretStr wrapping in API | ✓ |
| Structured logs (JSON in prod) | ✓ |
| X-Request-ID per request | ✓ |
| Retry on transient Gemini errors | ✓ |
| Pre-commit secret scan hook | ✓ |
| GitHub Actions CI (typecheck/lint/test/build) | ✓ |
| GitHub Actions secret scan | ✓ |
| GitHub Actions deploy workflow | ✓ |
| Dockerfile for API | ✓ |
| fly.toml | ✓ |
| vercel.json | ✓ |
| OpenAPI auto-gen | ✓ |
| Health check endpoint | ✓ (`/health` reports configured models) |
| CORS configured | ✓ (env-driven; lifespan refuses `*` in prod) |
| Rate limiting | ✓ (slowapi: 30/min qa+reply, 10/min sketch; voice WS 1 concurrent/user) |
| Sentry / observability | ◯ |
| `agent_traces` table populated | ◯ (schema ready) |

## Security (hardened in 2026-05-14 audit + fixes)

| Item | Status |
|---|---|
| IDOR: every session-id route owner-checked | ✓ (`require_session_owner` dep; `assert_session_owner_ws` for WS) |
| Service-role bypass blocked at app layer | ✓ (tutor.py queries scoped by `user_id`) |
| JWT-bypass header (`X-Dev-User-Id`) blocked in prod | ✓ (`is_dev` returns False when `ENVIRONMENT=production`) |
| Lifespan startup guard against unsafe envs | ✓ (refuses prod + DEV_MODE=true OR prod + CORS_ORIGINS=*) |
| Web build refuses `NEXT_PUBLIC_DEMO_MODE=true` on Vercel prod | ✓ (next.config.ts throw) |
| `service_role` rotated before deploy | ◐ (one-time visible in chat log; rotation pending user) |
| Web bundle has no server secrets | ✓ (verified via grep `AIza` / `sb_secret_` in `.next/`) |
| Voice WS authenticated + session-owner-checked | ✓ (close 4401 / 4403 / 4429 codes) |
| Sketch upload bounded (8 MB) + magic-byte sniffed | ✓ |
| `agent_traces` is service-role-only | ✓ (RLS on, zero policies) |

## Models (live-verified via `models.list()` 2026-05-14)

| Role | Model | Status |
|---|---|---|
| TEXT | `gemini-3.1-flash-lite` | ✓ GA |
| VISION | `gemini-3.1-flash-lite` | ✓ GA |
| LIVE | `gemini-2.5-flash-native-audio-latest` | ✓ (hold — 3.1 live still Preview) |
| PRO | `gemini-pro-latest` (alias) | ✓ |
| EMBED | `gemini-embedding-2` | ✓ GA |

Gemini 2.5 family deprecates 2026-06-17 — TEXT/VISION/EMBED already off it.

## Testing

| Item | Status |
|---|---|
| Unit tests (API) | ✓ 110 passing (was 18 → 75 in Phase 3 → 110 in Phase 4) |
| Unit tests (Web) | ◯ (vitest wired, no tests yet) |
| E2E tests (Playwright) | ✓ 15/15 passing in ~54s against prod build |
| Manual smoke checklist | ✓ end-to-end against real Supabase + real Gemini |

## Deployment

| Item | Status |
|---|---|
| Supabase project live | ✓ (`molsszjunoffjkzfgiyw`, us-east-1, free tier; all migrations applied) |
| Vercel project linked | ◯ (needs user — `vercel link` from `apps/web`) |
| Fly.io app launched | ◯ (needs user — `fly launch` from `apps/api`) |
| Custom domain | ◯ (optional) |
| HTTPS | Auto via Vercel + Fly |
| Cron for nightly PlannerAgent | ◯ |

## Cost & monitoring

| Item | Status |
|---|---|
| Per-user rate limit on Gemini-burning routes | ✓ (slowapi 30/min qa+reply, 10/min sketch) |
| Voice WS concurrency cap | ✓ (1/user) |
| Per-user daily token quota | ◯ |
| Cost dashboard | Use Google Cloud Console + Supabase + Fly + Vercel dashboards |
| Error tracking | ◯ (Sentry) |

## Compliance / safety

| Item | Status |
|---|---|
| COPPA — students under 13 excluded by grade | ✓ |
| Privacy: no PII beyond name + grade | ✓ |
| Voice audio not persisted by default | ✓ |
| Aria persona is age-appropriate, supportive | ✓ |
| Gemini safety filters not disabled | ✓ |
| Terms / Privacy pages | ◯ (need legal review) |

## What's left to ship the MVP

In priority order:

1. **Content pipeline** — populate the ~25 empty topics. Design lives at `docs/content-pipeline.md`. Pulls OpenStax (CC BY 4.0) chapters per topic, has Gemini Pro plan + Gemini Flash-Lite write 8 Aria-voice steps, validates required equations survived, writes to `topics.content`. Effort: ~1 engineer-week.
2. **Interruptible turn-taking** — student can talk over Aria, cancel a streaming Q&A, raise a hand mid-lesson. Design at `docs/interruption-architecture.md`. Effort: ~3–4 days.
3. **Quiz content from DB** — depends on the content pipeline writing `quiz_questions` rows per topic. Effort: ~1 day after the pipeline lands.
4. **Observability** — `agent_traces` table writer + Sentry. Effort: ~1 day.
5. **Rotate `service_role` + deploy** — Vercel for web, Fly.io for api. Effort: ~half a day, mostly user-driven.
