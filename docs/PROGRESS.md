# Build Progress

Updated continuously during the autonomous overnight build.

## Phase 0 — Foundation ✅

- [x] Repo cloned (empty start)
- [x] `.gitignore` protecting all secret paths
- [x] `.env.example` documented; live `.env` files written and confirmed gitignored
- [x] pnpm workspace + Turborepo configured
- [x] README + docs scaffold
- [x] Latest model names confirmed via web search (Apr 2026)
  - `gemini-3.1-flash` (text + vision)
  - `gemini-3.1-flash-live-preview` (voice)
  - `gemini-3.1-pro` (reasoning)
  - `gemini-embedding-001`
- [x] `google-genai` Python SDK v2.2.0 chosen (replaces deprecated `google-generativeai`)

## Phase 1 — Parallel backbone

### ✅ DB agent — done
- 3 migrations (init 259 + RLS 308 + functions 108 = 675 lines)
- Seed (128 lines, AP Physics 1 + Calc BC + Bio courses with units/topics)
- 16 tables with RLS, pgvector extension, triggers, helper functions
- Verified end-to-end against real Postgres 16 + pgvector (idempotent reset confirmed)
- Per-table policy counts: 4 CRUD owner-scoped for user tables, 1 public-read for course catalog, 0 for service-only `agent_traces`

### ✅ Web agent — done
- Next.js 15.5.18 + React 19.2.6 + Tailwind 3.4.19 + framer-motion + Zustand + TanStack Query + Vercel AI SDK + perfect-freehand + Supabase SSR + shadcn-compatible
- All design tokens in `tailwind.config.ts` + `globals.css` (paper/ink/indigo/coral/amber/mint/board + chalk colors, 3 fonts via next/font, custom keyframes)
- 5 shared components: AriaMascot, Icon (27 paths), TopNav, Rail, CourseCard
- lib/api.ts (typed fetch + Bearer injection), lib/supabase/{client,server}.ts
- Vitest + Playwright wired
- `pnpm typecheck && pnpm lint && pnpm build` all clean
- Placeholder home page

### ✅ API agent — done
- 11 route files (courses, sessions, qa, sketch, quiz, notes, planner, flashcards, health) + ws/voice.py
- gemini.py service module: stream_text (SSE), analyze_image (vision), embed, get_live_client (Live API context manager)
- Lazy client init (imports safe without API key)
- Tenacity retry policy (5xx, 429, deadline) with exponential backoff
- 18 pytest tests passing (Q&A SSE shape, retry behavior, JSON coercion, lazy-init guard, etc.)
- SecretStr for all secrets — won't leak in logs
- Structured request logging with X-Request-ID
- 3-layer exception handler (HTTPException, validation, unhandled)
- Dev-mode JWT bypass via X-Dev-User-Id header
- Docker + fly.toml ready for Fly.io deploy
- google-genai 2.2.0 confirmed working

### ✅ Phase 1 fully verified
- `/health` returns 200 with all model names
- `/v1/courses` returns proper JSON
- `/docs` renders Swagger UI
- 18 tests passing
- Web build clean, no type errors
- No secrets in tracked files; .env files confirmed gitignored

## Phase 2 — Screens (in progress)

### 🟡 Agent S1 — Marketing screens
- ✅ Landing page (page.tsx)
- ✅ Onboarding 4-step flow ((marketing)/onboarding/page.tsx)
- ✅ Marketing layout
- ✅ Components: floating-chip, live-board (chalkboard mock)
- Running final typecheck/build/lint

### 🟡 Agent S2 — In-app screens (Dashboard, Planner, Notes, History)
- ✅ (app)/layout.tsx + app-chrome client wrapper
- ✅ Dashboard with hero, course cards, curriculum, today's schedule
- ✅ Planner with 7-day grid
- ✅ Notes with tabs (Notes / Flashcards)
- ✅ History with chalk thumbnails
- ✅ 8 dashboard sub-components extracted
- Running final typecheck/build/lint

### 🟡 Agent S3 — Classroom + Q&A + Quiz + Complete + sketch/voice/reactions
- Heaviest scope — still ramping up
- Will produce ~14 components + 3 routes + 5 hooks

## Phase 3 — AI agent layer (queued)
## Phase 4 — Polish + ship (queued)

## Phase 2 — Screens (queued)

Five parallel agents will build:
- Landing + Onboarding
- Dashboard
- Planner + Notes + History
- Classroom + Q&A + Quiz + Complete
- Tutor features (sketch, voice UI, reactions, reply bar, peer presence)

## Phase 3 — AI agent layer (queued)

- TutorAgent + SocraticAgent (LangGraph state machine)
- VisionAgent (sketch analysis)
- VoiceAgent (Gemini Live WebSocket bridge)

## Phase 4 — Polish + ship (queued)

- E2E + integration tests
- Deployment configs (Vercel, Fly.io)
- Observability (Sentry, agent_traces)

## Verification checkpoints

After each phase, the build is verified by:
1. `pnpm typecheck && pnpm build` (web)
2. `pytest -q && uvicorn app.main:app` smoke (api)
3. `supabase db reset` (db)
4. `pnpm test:e2e` (full stack, after phase 3)
