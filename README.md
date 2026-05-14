# K-12 AI Tutor (EduMind)

> An AI tutor for high schoolers powered by Google Gemini's multimodal models (vision + voice + text). Features a live chalkboard classroom with Socratic AI tutor "Aria" that watches your sketches, listens to your voice, and guides without giving away answers.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Next.js 15 (App Router) — Vercel                       │
│  - 9 screens: landing, onboard, dashboard,              │
│    classroom (whiteboard + Socratic Aria), Q&A,         │
│    quiz, complete, planner, notes, history              │
│  - Tailwind + shadcn/ui + Framer Motion                 │
│  - Vercel AI SDK for streaming                          │
└──────────────┬──────────────────────────────────────────┘
               │ HTTPS / SSE / WSS
┌──────────────▼──────────────────────────────────────────┐
│  FastAPI (Python 3.11+) — Fly.io                        │
│  - REST API + Server-Sent Events for AI streaming       │
│  - WebSocket bridge for Gemini Live (voice)             │
│  - LangGraph-based agent orchestration                  │
└──────────────┬──────────────────────────────────────────┘
               │
   ┌───────────┼────────────┐
   ▼           ▼            ▼
Gemini API  Supabase    pgvector
(2.5 Flash, (Postgres, (lesson
 Native      Auth,      embeddings)
 Audio,      Realtime,
 Embed)      Storage)
```

## Models used (April 2026)

| Purpose | Model |
|---|---|
| Text Q&A, lesson narration, Socratic responses | `gemini-2.5-flash` |
| Vision (sketch analysis) | `gemini-2.5-flash` |
| Real-time voice (bidirectional) | `gemini-2.5-flash-native-audio-latest` |
| Heavy reasoning (planner agent) | `gemini-2.5-pro` |
| Embeddings (lesson search) | `gemini-embedding-001` |

## Monorepo layout

```
apps/
  web/        # Next.js 15 frontend
  api/        # FastAPI backend
packages/
  shared-types/  # TS types generated from OpenAPI
supabase/
  migrations/    # SQL schema
  seed.sql       # Demo content (AP Physics 1)
docs/
  architecture.md
  api.md
  agents.md
```

## Quick start (local dev)

### Prerequisites
- Node 22+, pnpm 9+
- Python 3.11+, [Poetry](https://python-poetry.org/) or pip
- Docker (for local Supabase)
- [Supabase CLI](https://supabase.com/docs/guides/cli) `>=2.0`
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/)

### 1. Clone + install
```bash
git clone https://github.com/hislordshipprof/K-12_AI_tutorApp.git
cd K-12_AI_tutorApp
pnpm install
cd apps/api && pip install -e . && cd ../..
```

### 2. Set env
```bash
cp .env.example .env
cp .env.example apps/api/.env
cp .env.example apps/web/.env.local
# Fill in your GEMINI_API_KEY in apps/api/.env and apps/web/.env.local
```

### 3. Start local Supabase
```bash
supabase start
# Copy the printed anon/service_role keys into apps/api/.env and apps/web/.env.local
pnpm db:reset   # applies migrations + seeds AP Physics demo content
```

### 4. Run dev servers
```bash
pnpm dev   # starts both web + api in parallel
# web → http://localhost:3000
# api → http://localhost:8000
# api docs → http://localhost:8000/docs
```

## Project status

See [`docs/PROGRESS.md`](docs/PROGRESS.md) for the current build state and milestone verification.

## Security

- `.env` files are gitignored; **never commit secrets**
- Server-side Gemini calls go through FastAPI; the API key never reaches the browser
- All user tables have Supabase Row-Level Security policies
- See [`docs/security.md`](docs/security.md) for details

## Contributing / Architecture deep-dive

- [Architecture](docs/architecture.md)
- [API reference](docs/api.md)
- [Agent design](docs/agents.md)
- [Deployment](docs/deployment.md)

## License

Proprietary — © 2026 hislordshipprof.
