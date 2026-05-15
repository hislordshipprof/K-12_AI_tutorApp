# Production readiness checklist

Status: ✓ = done, ◐ = partial, ◯ = not started.
Last updated: 2026-05-15 (after the live-drawing system + 100% scene coverage).

## Functional

| Item | Status |
|---|---|
| All 9 prototype screens render | ✓ (Playwright specs cover the golden path) |
| Auth (Supabase magic link + Google) | ✓ (`/login`, `/auth/callback`, middleware gating, DEMO_MODE bypass) |
| Q&A streaming with real Gemini | ✓ (SSE, Socratic, multi-turn, RAG-grounded) |
| Sketch analysis with Gemini Vision | ✓ (multipart upload, 8MB cap, magic-byte sniff) |
| Voice mode with Gemini Live | ✓ (WS bridge, bidi audio, 1 concurrent/user) |
| Lesson playback (TTS) | ✓ (Gemini Live natural voice; word-timed caption reveal) |
| Quiz generation + scoring | ✓ (78 questions across 26 topics; DB-backed; attempts recorded) |
| Notes CRUD (manual + auto) | ✓ (real Supabase round-trip) |
| Planner with weekly schedule | ✓ (`/v1/planner/week`; auto-generation deferred) |
| Flashcards (SM-2 spaced repetition) | ◐ (algorithm + `/v1/flashcards/due` ship; no deck-builder UI) |
| History replay | ◐ (list hits real `/v1/history`; click-to-replay not built) |
| Real student state on dashboard | ✓ (name, streak, stats, curriculum tree — no fixtures) |

## Live drawing — "the lesson draws itself"

| Item | Status |
|---|---|
| Word-timed caption + headline reveal (Phase A) | ✓ (`TimedReveal`, synced to TTS clock) |
| 12 typed parametric SVG scenes (Phase B) | ✓ (free-body, projectile, wave, circular-motion, …) |
| Deterministic scene tagger (no LLM) | ✓ (`app/content/scene_tagger.py`) |
| Model-drawn fallback scenes (Phase C) | ✓ (structured primitives, validated, no raw SVG) |
| Scene coverage of all lesson steps | ✓ 100% (224/224 — 83 typed + 141 model-drawn) |
| Follow-up Q&A answers draw scenes | ✓ (SSE `scene` frame → same scene registry) |

## Curriculum & content

| Item | Status |
|---|---|
| AP Physics 1 / Calc BC / Biology unit trees (CED 2024) | ✓ |
| AP Physics 1 sub-topics | ✓ (8 overviews + 16 sub-topics) |
| Real lesson content for all topics | ✓ (RAG-grounded, OpenStax CC BY 4.0) |
| Quiz questions per topic | ✓ (78 across 26 topics) |
| OpenStax ingest pipeline | ✓ (`docs/content-pipeline.md`) |

## Non-functional

| Item | Status |
|---|---|
| TypeScript strict mode | ✓ |
| RLS on every user-owned table | ✓ |
| Server-side Gemini calls only (key never in browser) | ✓ |
| Structured logs, X-Request-ID, retry on transient errors | ✓ |
| GitHub Actions CI (typecheck/lint/test/build) + secret scan | ✓ |
| Dockerfile / fly.toml / vercel.json | ✓ |
| Health check, CORS, rate limiting | ✓ |
| Sentry / observability | ◯ |
| `agent_traces` table populated | ◯ (schema ready, writer not built) |

## Security

| Item | Status |
|---|---|
| IDOR: every session-id route owner-checked | ✓ |
| Service-role bypass blocked at app layer | ✓ |
| `X-Dev-User-Id` JWT bypass blocked in prod | ✓ |
| Lifespan startup guard against unsafe prod envs | ✓ |
| Web bundle has no server secrets | ✓ |
| Voice WS authenticated + session-owner-checked | ✓ |
| Sketch upload bounded + magic-byte sniffed | ✓ |
| Secrets rotated before deploy | ◐ (Supabase `service_role` + Anthropic key — pending user) |

## Testing

| Item | Status |
|---|---|
| Unit tests (API) | ✓ 169 pytest passing |
| Unit tests (Web) | ◯ (vitest wired, no tests yet) |
| E2E tests (Playwright) | ✓ 5 specs (marketing, dashboard, classroom-text, classroom-quiz, complete) |
| Production build | ✓ clean |

## Deployment

| Item | Status |
|---|---|
| Supabase project live | ✓ (`molsszjunoffjkzfgiyw`, all migrations applied) |
| Vercel project linked | ◯ (needs `vercel link` from `apps/web`) |
| Fly.io app launched | ◯ (needs `fly launch` from `apps/api`) |
| Cron for nightly PlannerAgent | ◯ |

## What's left to ship the MVP

In priority order:

1. **Observability** — `agent_traces` writer + Sentry init. Effort: ~1 day.
2. **Rotate secrets** — Supabase `service_role` and the Anthropic API key (pasted in chat).
3. **Deploy** — Vercel for web, Fly.io for api. Effort: ~half a day, user-driven.
4. **Feature polish** — flashcard deck UI, history click-to-replay, mobile classroom
   layout, web unit tests, per-user token quota, Terms/Privacy pages.
