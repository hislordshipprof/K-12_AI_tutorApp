# Resume — pick up this build in a new session

> Last updated: 2026-05-15. One-stop doc for continuing work in a fresh session.

## 1. Get the repo running locally

```bash
pnpm install                                  # web deps
cd apps/api && python -m venv .venv            # api deps in a venv
.venv/Scripts/pip install -e .                 # (Windows; use .venv/bin on macOS/Linux)
cd ../.. && pnpm dev                           # starts web + api
```

→ http://localhost:3000 loads. Aria Q&A, lessons, and live drawing all work.

## 2. Env vars (gitignored — never commit)

### `apps/api/.env`
```bash
GEMINI_API_KEY=<your_gemini_key>
GEMINI_MODEL_TEXT=gemini-3.1-flash-lite
GEMINI_MODEL_VISION=gemini-3.1-flash-lite
GEMINI_MODEL_LIVE=gemini-2.5-flash-native-audio-latest
GEMINI_MODEL_PRO=gemini-pro-latest
GEMINI_MODEL_EMBED=gemini-embedding-2

# Cloud Supabase project molsszjunoffjkzfgiyw (migrations already applied)
SUPABASE_URL=<project_url>
SUPABASE_ANON_KEY=<anon_key>
SUPABASE_SERVICE_ROLE_KEY=<service_role_key>
SUPABASE_JWT_SECRET=<jwt_secret>

API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
DEV_MODE=true

# Optional — only for the scene-drawing batch script with --provider anthropic
ANTHROPIC_API_KEY=<your_anthropic_key>
```

### `apps/web/.env.local`
```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=<project_url>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon_key>
NEXT_PUBLIC_DEMO_MODE=true
```

## 3. Verify the build

```bash
cd apps/api && .venv/Scripts/pytest -q        # → 169 passed
cd ../web && npx tsc --noEmit && npx next build
```

## 4. Models

| Role | Model |
|---|---|
| TEXT / VISION | `gemini-3.1-flash-lite` |
| LIVE (voice) | `gemini-2.5-flash-native-audio-latest` |
| PRO (lesson generation) | `gemini-pro-latest` |
| EMBED | `gemini-embedding-2` (768-dim, matches `vector(768)`) |
| Scene drawing (offline batch, optional) | Claude Sonnet 4.6 via `--provider anthropic` |

## 5. What's left (highest priority first)

1. **Observability** — build `apps/api/app/core/tracing.py` (`agent_traces` writer) +
   Sentry init. Schema is ready; nothing writes to it yet.
2. **Rotate secrets** — Supabase `service_role` key and the Anthropic key (was pasted
   in a chat) before any deploy.
3. **Deploy** — `vercel link` from `apps/web`, `fly launch` from `apps/api`. Configs ready.
4. **Feature polish** — flashcard deck-builder UI, history click-to-replay, mobile
   classroom layout, web unit tests, per-user daily token quota, Terms/Privacy pages.

## 6. Key facts a new session needs

- **Live drawing**: lesson steps carry a `scene` field. 12 hand-built typed scenes
  (`apps/web/src/components/classroom/scenes/`) chosen by a deterministic tagger
  (`app/content/scene_tagger.py`); everything else is a model-drawn `custom-svg`.
  Re-draw scenes with `python -m scripts.generate_scene_svgs` (`--provider anthropic`
  for Claude, `--force` to redraw existing, `--dry-run` to preview).
- **Demo auth**: `DEV_MODE=true` + `X-Dev-User-Id` header bypasses JWT. The web client
  and `streamSSE` both send it when `NEXT_PUBLIC_DEMO_MODE=true`. Flip off before deploy.
- **Service role key never in browser** — only `apps/api/.env`.
- **Content** is RAG-grounded from OpenStax (CC BY 4.0) — see `docs/content-pipeline.md`.
- **`next build` shares `.next/` with the dev server** — running a build clobbers a
  running `pnpm dev`; restart the dev server afterward.

## 7. Files most likely to need surgery

| Need | File(s) |
|---|---|
| Aria's persona / tone | `apps/api/app/agents/prompts.py` |
| Scene rules / typed scenes | `app/content/scene_tagger.py`, `apps/web/.../classroom/scenes/` |
| Scene generation | `apps/api/scripts/generate_scene_svgs.py` |
| Add an API endpoint | new file in `apps/api/app/api/v1/`, register in `router.py` |
| Add a screen | new `apps/web/src/app/.../page.tsx` + component |
