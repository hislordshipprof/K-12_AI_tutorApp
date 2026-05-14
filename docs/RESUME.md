# Resume — pick up this build in a new Claude Code session

> One-stop doc for continuing work on this repo in a fresh Claude Code session (e.g. moving from a cloud sandbox to your local machine, or starting a new session weeks later).

## 1. Get the repo running locally

```bash
# Clone
git clone https://github.com/hislordshipprof/K-12_AI_tutorApp.git
cd K-12_AI_tutorApp

# Install web deps
pnpm install

# Install api deps in a venv
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cd ../..

# Create env files (see "Env vars" section below)
# Then start both servers:
pnpm dev
```

→ http://localhost:3000 should load. Aria Q&A works against real Gemini.

## 2. Env vars (paste these into the right files)

These are gitignored on purpose. **Replace the Gemini key with yours** — don't reuse a key that's been shared via copy/paste.

### `apps/api/.env`
```bash
GEMINI_API_KEY=<your_gemini_key>
GEMINI_MODEL_TEXT=gemini-2.5-flash
GEMINI_MODEL_VISION=gemini-2.5-flash
GEMINI_MODEL_LIVE=gemini-2.5-flash-native-audio-latest
GEMINI_MODEL_PRO=gemini-2.5-pro
GEMINI_MODEL_EMBED=gemini-embedding-001

# Use local Supabase for now (Docker via `supabase start`), OR plug in your cloud project:
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_ANON_KEY=local-anon-placeholder
SUPABASE_SERVICE_ROLE_KEY=local-service-placeholder
SUPABASE_JWT_SECRET=super-secret-jwt-token-with-at-least-32-characters-long

API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
DEV_MODE=true
```

### `apps/web/.env.local`
```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321
NEXT_PUBLIC_SUPABASE_ANON_KEY=local-anon-placeholder
GEMINI_API_KEY=<your_gemini_key>
```

## 3. Bootstrap prompt for the new Claude session

Paste this verbatim as your first message to the new Claude Code session:

```
We're picking up an in-progress K-12 AI tutor app. Phases 0-3 are
complete and committed (foundation, all 9 prototype screens, AI agents
on real Gemini). Before doing anything else, read these in order:

1. docs/HANDOFF.md        — current state, what works vs stubbed
2. docs/PROGRESS.md       — phase-by-phase log
3. docs/phase-4-briefs.md — ready-to-dispatch agent prompts for next work
4. docs/production-checklist.md — feature matrix

Then verify the local build:
- pnpm install
- cd apps/api && python3 -m venv .venv && source .venv/bin/activate && pip install -e . && pytest -q
- cd .. && pnpm typecheck && pnpm build
- pnpm dev (in repo root)
- Smoke: curl localhost:3000 and visit each of the 9 routes

After verification, here's what's left to do (highest priority first):

(1) Hook up cloud Supabase via the Supabase MCP server:
    - Apply migrations: supabase/migrations/*.sql
    - Apply seed: supabase/seed.sql
    - Update apps/api/.env + apps/web/.env.local with real keys

(2) Replace sample-data stubs in app/api/v1/{courses,sessions,notes,quiz,
    planner,flashcards}.py with real supabase queries (schema is ready).

(3) Build /login + /auth/callback pages using @supabase/ssr magic link.
    Add middleware.ts to gate /dashboard, /classroom/*.

(4) Write the Playwright E2E suite per docs/phase-4-briefs.md (Agent T1).

(5) Deploy: Vercel for web, Fly.io for api (configs in apps/{web,api} ready).

Dispatch parallel agents for (1)+(2), (3), (4) — they own non-overlapping
paths. Verify each before moving on.

The Gemini key is in apps/api/.env (gitignored, never commit).
```

## 4. Quick verification commands

```bash
# All-in-one sanity check
bash scripts/verify-all.sh

# Just the API
cd apps/api && .venv/bin/pytest -q             # → 75 passed

# Smoke a real Gemini call
SID=00000000-0000-0000-0000-000000000001
curl -sN -X POST http://localhost:8000/v1/sessions/$SID/qa \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User-Id: demo' \
  -d '{"question":"what is wave amplitude?","source":"text"}'
# → should stream a Socratic response (not a definition)
```

## 5. Key facts the new session needs to know

- **Models**: `gemini-2.5-flash` (text+vision), `gemini-2.5-flash-native-audio-latest` (Live voice), `gemini-2.5-pro` (reasoning), `gemini-embedding-001` (768-dim to match `vector(768)` DB)
- **Web search results lie** about Gemini model names — always verify via `models.list()`
- **Embedding default is 3072-dim**; we set `output_dimensionality=768` explicitly to match the DB column
- **Build memory**: `NODE_OPTIONS='--max-old-space-size=4096'` is baked into `pnpm build` (default heap too small for the classroom shell)
- **Fonts**: loaded via runtime `<link>` (not `next/font/google`) so the build doesn't need internet at compile time
- **Auth in dev**: `DEV_MODE=true` + `X-Dev-User-Id` header bypasses JWT verification. Flip to `false` before deploying.
- **Voice config**: `GeminiService.get_live_client(system_instruction=..., response_modalities=["AUDIO"])` — empty config returns "Cannot extract voices from a non-audio request"
- **Service role key never in browser** — only `apps/api/.env`
- **Sketch endpoint expects multipart** with PNG; client serializes a stroke as SVG Blob (works but `apps/web/src/components/classroom/sketch-layer.tsx` should rasterize to PNG for better Vision results)

## 6. Files most likely to need surgery

| Need | File(s) |
|---|---|
| Real Supabase queries | `apps/api/app/api/v1/courses.py`, `sessions.py`, `notes.py`, `quiz.py`, `planner.py`, `flashcards.py` |
| Aria's persona/tone | `apps/api/app/agents/prompts.py` |
| Lesson content (8 steps) | `supabase/seed.sql` (jsonb in `topics.content`) + `apps/web/src/components/classroom/classroom-shell.tsx` (LESSON_STEPS) |
| Design tokens | `apps/web/tailwind.config.ts` + `apps/web/src/app/globals.css` |
| Add a new screen | new `apps/web/src/app/.../page.tsx` + matching component in `apps/web/src/components/` |
| Add an API endpoint | new file in `apps/api/app/api/v1/`, then register in `router.py` |

## 7. Sandbox quirks NOT to re-fix on local

These were workarounds for the air-gapped build sandbox; **on a normal machine they're non-issues**, but if you see something weird, check here first:

- `pnpm dev` Turbopack ENOENT race → use `pnpm start` (after `pnpm build`) for verification. Real dev mode works fine on a normal machine.
- Google Fonts not loading → already switched to runtime `<link>`. Works in any browser with internet.
- Commit signing fails → only happens in the sandbox's broken signing infra. Don't disable signing on your local; let your normal config handle it.

## 8. Conversation transcript (optional, for the curious)

The previous Claude Code session's full JSONL transcript was 880 messages over ~1.5 hours of autonomous building. Not needed for resumption — every important decision is in commit messages, `docs/HANDOFF.md`, and `docs/PROGRESS.md`.

---

**TL;DR**: clone repo, paste 2 env files, paste the bootstrap prompt, and you're back where we left off in 5 minutes.
