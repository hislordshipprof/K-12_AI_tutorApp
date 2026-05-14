# Build Progress

Updated continuously during the autonomous overnight build.

## Phase 0 — Foundation ✅

- [x] Repo cloned (empty start)
- [x] `.gitignore` protecting all secret paths
- [x] `.env.example` documented; live `.env` files written and confirmed gitignored
- [x] pnpm workspace + Turborepo configured
- [x] README + docs scaffold
- [x] Latest model names confirmed via web search (Apr 2026)
  - `gemini-2.5-flash` (text + vision)
  - `gemini-2.5-flash-native-audio-latest` (voice)
  - `gemini-2.5-pro` (reasoning)
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

### ✅ Agent S2 — In-app screens (Dashboard, Planner, Notes, History) — DONE
- (app)/layout.tsx + app-chrome client wrapper (Server Component → Client wrapper pattern for usePathname)
- Dashboard: hero with stats, 3 course cards, expandable curriculum (Unit 4 default open), today's schedule (4 rows), streak card
- Planner: 7-day grid (Tue 13 = today), color-coded blocks (mint/indigo/amber/coral/lavender), sidebar with goals/Aria note/weekly stats
- Notes: Tab between Notes (9-card grid, sticky-note styling) and Flashcards (6 decks with mastery %)
- History: 9 rows with chalk-thumb SVG, score color-coding, replay button
- 8 dashboard sub-components extracted (app-chrome, curriculum-unit, today-row, streak-card, week-day-column, note-card, deck-row, history-row)
- pnpm typecheck/build/start all clean; all 4 routes return HTTP 200
- Dashboard uses TanStack Query for /v1/courses with fallback to local data

### ✅ Agent S3 — Classroom + Q&A + Quiz + Complete + sketch/voice/reactions — DONE
- 14 components: whiteboard-svg (8-step chalk SVG), qa-answer-svg, sketch-layer (perfect-freehand), sketch-toolbar, reactions-cluster, reply-bar, peer-presence, voice-mode, voice-bar, waveform, qa-overlay (streaming), quiz-me-pop, caption-bar, classroom-shell (572 LoC orchestrator)
- 5 hooks: use-speak, use-listen, use-socratic-aria, use-sketch-recognition, use-session
- 3 routes: classroom/[topicId], classroom/quiz/[topicId], classroom/complete/[sessionId] (split into Server Component thin wrappers + Client islands)
- lib/sse.ts — POST-based SSE helper w/ Supabase bearer injection
- Q&A SSE end-to-end wired (token stream → caption append in real time)
- Sketch upload wired (fire-and-forget for A2 to complete)
- Voice mode → Q&A integration wired
- pnpm typecheck/lint/build all clean

## ✅ Phase 2 fully verified end-to-end
All 9 routes return HTTP 200 in `pnpm start` smoke:
- `/` (Landing), `/onboarding`, `/dashboard`, `/planner`, `/notes`, `/history`
- `/classroom/wave-properties-anatomy`
- `/classroom/quiz/wave-properties-anatomy`
- `/classroom/complete/test-session`

Verifier fixes applied during this phase:
- Build memory: `NODE_OPTIONS='--max-old-space-size=4096'` baked into `pnpm build`
- Fonts: switched from `next/font/google` (build-time fetch) to runtime `<link>` (sandbox-friendly, same UX in real browsers)
- Embedding dim: explicit `output_dimensionality=768` to match `vector(768)` DB column
- Model names: switched from web-search guesses (`gemini-3.1-flash` 404'd) to verified stable GA via real `models.list()`:
  - `gemini-2.5-flash` (text + vision)
  - `gemini-2.5-flash-native-audio-latest` (voice bidi)
  - `gemini-2.5-pro` (reasoning)

Committed as `9086ddb`.

## Phase 3 — AI agent layer (in progress)

Three parallel agents dispatched:
- 🟡 A1 — TutorAgent + SocraticAgent + state + reply/reaction routes
- 🟡 A2 — VisionAgent + real sketch route (Gemini Vision)
- 🟡 A3 — VoiceAgent + ws/voice bridge (Gemini Live API)

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
