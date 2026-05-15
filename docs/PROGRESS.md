# Build Progress

> Last updated: 2026-05-15. Living log of what's been built, phase by phase.

## Summary

| Phase | Status | Key deliverables |
|---|---|---|
| 0 — Foundation | ✅ | Monorepo, FastAPI + Next.js scaffolds, Supabase schema, CI/CD |
| 1 — Backbone | ✅ | DB schema (16 tables, RLS, pgvector), design tokens |
| 2 — Screens | ✅ | All 9 prototype screens ported to Next.js |
| 3 — AI agents | ✅ | TutorAgent, VisionAgent, VoiceAgent on real Gemini |
| 4 — Real data | ✅ | Every hardcoded fixture replaced with live `/v1` data |
| 5 — Content pipeline | ✅ | RAG ingest → 26 OpenStax-grounded lessons + 78 quiz questions |
| 6 — Curriculum + security | ✅ | CED-2024 unit trees, AP Physics 1 sub-topics, security audit |
| 7 — Live drawing | ✅ | Word-timed reveal + 12 typed scenes + model-drawn fallback |
| 8 — Ship prep | 🟡 | Observability + deploy + secret rotation still open |

## Phase detail

### Phases 0–3 — foundation, screens, agents
- pnpm + Turborepo monorepo; Next.js 15 / React 19 / Tailwind 3.4; FastAPI + google-genai.
- Supabase: 16 tables, RLS on every user-owned table, pgvector for embeddings.
- All 9 screens: Landing, Onboarding, Dashboard, Planner, Notes, History, Classroom, Quiz, Complete.
- AI agents on real Gemini: stateful Socratic `TutorAgent`, `VisionAgent` (sketch analysis),
  `VoiceAgent` (Gemini Live bidi audio). Hint ladder, reactions, multi-turn session state.

### Phase 4 — real data
- Replaced every hardcoded UI fixture with live backend data (`refactor(web): replace every
  hardcoded fixture with real /v1 data`).
- Added `/v1/me`, `/v1/history`, `/v1/courses/{slug}/units`; dashboard, planner, notes,
  history all round-trip real Supabase rows.

### Phase 5 — content pipeline
- RAG ingestion: OpenStax (CC BY 4.0) chapters → chunk → embed (`lesson_embeddings`,
  pgvector HNSW) → Gemini generates 8-step Aria-voice lessons → 3-gate validator → persist.
- 26 topics now carry real RAG-grounded lesson content; retrieval wired into `TutorAgent`.
- Quiz generation pipeline: 78 questions across 26 topics; quiz endpoints are DB-backed.

### Phase 6 — curriculum + security
- Unit trees aligned to College Board CED 2024 (Physics 1, Calc BC, Biology).
- AP Physics 1 expanded: 8 unit overviews + 16 sub-topics (42 mapping slugs total).
- Security audit + fixes: IDOR ownership checks, service-role scoping, prod env guards,
  rate limiting, bounded uploads.

### Phase 7 — live drawing ("the lesson draws itself")
- **A — word-timed reveal**: caption + chalkboard headline write themselves word-by-word,
  synced to Aria's TTS audio clock (`TimedReveal`).
- **B — typed scenes**: 12 parametric SVG diagram components (free-body, projectile arc,
  wave, circular motion, energy bar chart, …) that draw in sync with audio. A deterministic
  keyword tagger (`app/content/scene_tagger.py`) assigns scenes — no LLM, fully auditable.
- **C — model-drawn fallback**: for steps no typed scene fits, a model emits a structured
  primitive list (line/arrow/rect/circle/path/text…), validated against a whitelist, stored
  as `scene:{type:"custom-svg"}`. Never raw SVG — no injection surface.
- **Coverage: 100%** — all 224 non-intro lesson steps have a scene (83 typed + 141
  model-drawn by Claude Sonnet 4.6).
- Follow-up Q&A answers draw scenes too (same engine, via an SSE `scene` frame).

## Current state

- **API tests**: 169 pytest passing.
- **Web**: typecheck / lint / production build clean; 5 Playwright E2E specs.
- **Models**: see `docs/RESUME.md` § Models.
- **Content**: every topic has a generated lesson; 100% scene coverage; 78 quiz questions.
- **Supabase**: cloud project `molsszjunoffjkzfgiyw`, all migrations applied.

## What's left (see `docs/production-checklist.md` for the full matrix)

1. **Observability** — `agent_traces` writer + Sentry. Not built.
2. **Deploy** — Vercel (web) + Fly.io (api). Configs ready; needs user-driven link/launch.
3. **Secret rotation** — Supabase `service_role` + the Anthropic key before any deploy.
4. **Feature polish** — flashcard deck-builder UI, history click-to-replay, mobile
   classroom layout, web unit tests, per-user token quota, Terms/Privacy pages.
