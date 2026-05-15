# Hand-off — current state of the repo

> Last updated: 2026-05-15.

## TL;DR

A K-12 AI tutor (AP Physics 1, Calc BC, Biology). All 9 screens, the AI agents
(Socratic Q&A, sketch vision, voice), real RAG-grounded content, quizzes, and the
live-drawing classroom are built and working against real Gemini + cloud Supabase.
What's left is ship infrastructure (observability, deploy) and secondary polish.

Run it: `pnpm dev` → http://localhost:3000. See `docs/RESUME.md` for env setup.

## What works (real, end-to-end)

| Area | Status |
|---|---|
| All 9 screens | ✅ |
| Q&A streaming — Socratic, multi-turn, RAG-grounded | ✅ |
| Sketch analysis (Gemini Vision) | ✅ |
| Voice mode (Gemini Live, bidi audio) | ✅ |
| Lesson playback — natural TTS + word-timed caption reveal | ✅ |
| Live drawing — 12 typed scenes + model-drawn fallback, 100% step coverage | ✅ |
| Follow-up Q&A answers draw scenes | ✅ |
| Quiz — 78 DB-backed questions across 26 topics | ✅ |
| Notes / Planner / History — real Supabase CRUD | ✅ |
| Auth — magic link + Google, middleware gating, demo bypass | ✅ |
| Curriculum — CED-2024 trees + AP Physics 1 sub-topics | ✅ |
| Real content — every topic has an OpenStax-grounded lesson | ✅ |
| Security — IDOR checks, prod env guards, rate limiting, bounded uploads | ✅ |

## What's stubbed / not built

| Item | Status |
|---|---|
| Observability — Sentry + `agent_traces` writer | 🟡 schema ready, writer not built |
| Deploy — Vercel + Fly.io | 🟡 configs ready; needs user `vercel link` / `fly launch` |
| Flashcards | 🟡 SM-2 + `/v1/flashcards/due` work; no deck-builder UI |
| History replay | 🟡 list works; click-to-replay not built |
| Mobile classroom layout | 🟡 desktop-optimized |
| Web unit tests | 🟡 vitest wired, no tests |
| Per-user daily token quota | 🟡 not built |
| Terms / Privacy pages | 🟡 need legal review |

## Before deploying

1. Rotate the Supabase `service_role` key and the Anthropic API key.
2. Set `DEV_MODE=false` and `NEXT_PUBLIC_DEMO_MODE` unset/false in prod env.
3. Build observability so prod failures are visible.

## Tests

- API: 169 pytest passing.
- Web: typecheck / lint / production build clean; 5 Playwright E2E specs.

## Docs map

- `docs/PROGRESS.md` — phase-by-phase build log
- `docs/production-checklist.md` — full feature matrix
- `docs/RESUME.md` — env setup + how to pick the build back up
- `docs/architecture.md` / `docs/agents.md` / `docs/api.md` — system design
- `docs/content-pipeline.md` — how lessons are generated
- `docs/interruption-architecture.md` — turn-taking / barge-in design
- `docs/security.md` — threat model + defenses
- `docs/deployment.md` — production deploy steps
