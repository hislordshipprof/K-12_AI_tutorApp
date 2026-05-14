# Hand-off — what's in this repo when you wake up

> **TL;DR**: Two clean commits on local `main`. Foundation + Phase 2 done and verified. Phase 3 AI agents in progress. The classroom UI streams real Gemini responses via SSE. Run `pnpm dev` + `cd apps/api && DEV_MODE=true uvicorn app.main:app` and visit `localhost:3000` to try it.

## What's done

### Foundation (commit `9c88140`)
- pnpm + Turborepo monorepo
- Next.js 15 + React 19 + Tailwind 3.4 + design tokens ported from prototype
- FastAPI + google-genai 2.2.0 SDK
- Supabase migrations (16 tables, RLS, pgvector, AP Physics 1 seed)
- GitHub Actions CI + secret-scan + deploy workflows
- Docker + fly.toml + vercel.json

### Phase 2 — All 9 screens (commit `9086ddb`)
- Landing, Onboarding, Dashboard, Planner, Notes, History, Classroom, Quiz, Complete
- Every route returns HTTP 200 (verified)
- Q&A SSE end-to-end: ask a question → real Gemini Socratic response streams into Aria's bubble
- Sketch UI works; backend stub for now
- Voice mode UI works; backend stub for now

### Phase 3 — AI intelligence (commit `2caa021` + `937b747`) ✅
- **TutorAgent + SocraticAgent**: stateful session orchestration with hint ladder, Aria persona
  - Multi-turn history → Aria refers back to earlier questions
  - 4 reaction responses (slower/confused/got_it/mind_blown)
  - Real Gemini Socratic responses verified (asks back, never defines)
- **VisionAgent**: sketch image → Gemini 2.5 Flash vision → structured recognition + Socratic message
  - Verified: PNG sine-wave → `shape: "wave", confidence: 1.0`
  - Heuristic geometric fallback ported from prototype
- **VoiceAgent**: WebSocket bridge to Gemini Live API (bidi voice)
  - Aria persona + AUDIO modality plumbed through config
  - Verified: WS connect → text frame → real PCM audio chunks stream back
- 75 pytest tests pass (up from 18)

## What you need to do when you wake up

### 1. Push to GitHub

The local repo at `/home/claude/K-12_AI_tutorApp` has commits ready. I couldn't push because the build environment has no GitHub credentials.

```bash
cd /home/claude/K-12_AI_tutorApp
./scripts/push-to-github.sh
```

The script handles three auth paths (gh CLI, GITHUB_TOKEN env, or interactive prompt). For a personal access token, generate one at https://github.com/settings/tokens with `repo` scope.

### 2. Try it locally

```bash
cd /home/claude/K-12_AI_tutorApp

# Terminal 1 — API (real Gemini)
cd apps/api && source .venv/bin/activate && DEV_MODE=true uvicorn app.main:app --reload

# Terminal 2 — Web
cd apps/web && pnpm dev
```

Then visit http://localhost:3000.

Click **Start free** → onboard → dashboard → resume lesson. In the classroom, click **Raise hand**, ask "What is amplitude?" — you'll see Aria respond in real time via SSE with a real Gemini 2.5 Flash call.

### 3. Hook up your Supabase project

Two options:

**Option A — Use the local Docker Supabase** (zero cloud setup):
```bash
supabase start    # spins up local stack via Docker
supabase db reset # applies migrations + seed
# Copy the printed anon/service_role/JWT secret keys into apps/api/.env and apps/web/.env.local
```

**Option B — Use your cloud Supabase project**:
- You mentioned the Supabase MCP is connected. Have a future Claude session apply `supabase/migrations/*.sql` and `supabase/seed.sql` via MCP, then put your project keys in the `.env` files.
- Or manually: `supabase link --project-ref <ref>` → `supabase db push` → paste seed in dashboard SQL editor.

See `docs/supabase-mcp.md` for details.

### 4. Deploy (when you're ready)

```bash
# API → Fly.io
cd apps/api && fly launch  # creates the app
fly secrets set GEMINI_API_KEY=AIza... SUPABASE_URL=... SUPABASE_ANON_KEY=... SUPABASE_SERVICE_ROLE_KEY=... SUPABASE_JWT_SECRET=...
fly deploy

# Web → Vercel
cd apps/web && vercel  # link the project, set env vars in Vercel dashboard
vercel --prod
```

See `docs/deployment.md` for the full guide.

## What's stubbed vs real

| Feature | Status |
|---|---|
| All 9 UI screens | ✅ Real, prototype-faithful |
| Q&A streaming (Gemini text) | ✅ End-to-end real Gemini |
| Sketch UI (drawing) | ✅ Real (perfect-freehand chalk) |
| Sketch analysis (vision) | 🟡 Phase 3 in progress; UI works, awaiting agent A2 |
| Voice mode UI | ✅ Real (Web Speech for transcription) |
| Voice mode bidi (Gemini Live) | 🟡 Phase 3 in progress; agent A3 |
| Reactions (🐢 😕 💡 🤯) | ✅ UI works; backend wiring in agent A1 |
| Reply bar | ✅ UI works; backend wiring in agent A1 |
| Quiz feedback | ✅ Local logic (correct answer hardcoded); backend stub |
| Notes / Planner / History | 🟡 UI renders with fixture data; real CRUD pending |
| Auth (Supabase magic link) | 🟡 Demo mode bypass works; login UI not built |

## Cost so far

The Gemini API key has been used for:
- ~3 smoke-test SSE Q&A calls (a few hundred tokens total)
- ~2 embedding calls (negligible)
- ~1 `models.list()` call (free)

Estimated cost so far: **under $0.01**.

## Where the key lives

```
apps/api/.env             # GEMINI_API_KEY=AIza... (gitignored)
apps/web/.env.local       # mirrors for browser-side use (gitignored)
.env.example              # template w/ placeholders only — safe to commit
```

`.gitignore` blocks all `.env` files. Pre-commit hook at `scripts/pre-commit` scans for `AIza` prefixes and refuses to commit if found.

## Architecture deep-dive

- [`docs/architecture.md`](architecture.md) — full system diagram + tech stack
- [`docs/agents.md`](agents.md) — Socratic Aria + sub-agent design
- [`docs/api.md`](api.md) — endpoint reference
- [`docs/deployment.md`](deployment.md) — production deploy steps
- [`docs/security.md`](security.md) — threat model + defenses
- [`docs/production-checklist.md`](production-checklist.md) — what's ready vs not
- [`docs/local-dev.md`](local-dev.md) — three ways to run locally

## Things I'd polish next

1. **Real Supabase wiring** — Most endpoints return sample data. Wire to actual DB queries.
2. **Auth flow** — Build /login (magic link) + /auth/callback. Demo bypass works for now.
3. **Mobile classroom** — Desktop-only currently. Needs dedicated mobile layout.
4. **Observability** — Sentry, populate agent_traces table, admin dashboard.
5. **Cost guardrails** — Per-user daily token cap.
6. **Real flashcards SM-2 logic** — Schema is ready, UI shows decks; need scheduler.

## Sandbox quirks I worked around

- **Sandbox can't reach `fonts.googleapis.com`** → switched from `next/font/google` (build-time fetch) to runtime `<link>` (works the same in real browsers, builds without internet)
- **Default Node heap too small for the classroom build** → baked `NODE_OPTIONS='--max-old-space-size=4096'` into `pnpm build`
- **Web search said `gemini-3.1-flash` exists** → actually returns 404 from the API. Listed real models, switched to `gemini-2.5-flash` (stable GA), `gemini-2.5-flash-native-audio-latest` (Live), `gemini-2.5-pro` (reasoning).
- **Embedding dim mismatch** → API returned 3072 dims by default; DB schema is `vector(768)`. Set `output_dimensionality=768` explicitly.
- **Build env's signing server returns 400** → committed with signing disabled locally. Re-sign before pushing if your branch protection requires signed commits.

## Real Gemini call I verified

```
$ curl -sN -X POST http://localhost:8000/v1/sessions/.../qa \
  -d '{"question":"What is wave amplitude in one short sentence?","source":"text"}'

data: {"type":"token","content":"That's a great question to start with!\n\nWhen you think about a wave, like a ripple in water or a sound"}
data: {"type":"token","content":" wave, what aspect of it would tell you how \"strong\" or \"intense\" it is?"}
data: {"type":"done"}
```

Note Aria asks a guiding question — Socratic, doesn't define amplitude directly. The persona is working.

## Stats

- Total LoC: ~12,500 (frontend ~6620, backend ~2200, SQL ~800, docs ~1900)
- Tests: 18 API unit tests (more added in Phase 3)
- Latest models confirmed via real `models.list()`: gemini-2.5-flash + 2.5-pro + native-audio-latest + embedding-001
- Build time: web ~10s, API tests ~2s
