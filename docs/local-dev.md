# Local development

Three ways to run the app locally, ordered easiest → most complete.

## A. Demo mode (no Supabase needed)

Fastest way to see the UI working with real Gemini calls but no auth, no DB persistence.

```bash
# In one terminal — API
cd apps/api
source .venv/bin/activate
DEV_MODE=true uvicorn app.main:app --reload

# In another — web
cd apps/web
pnpm dev
```

- API endpoints accept `X-Dev-User-Id: demo-user` header (or work without auth in DEV_MODE).
- Course/topic/session data is in-memory or seeded fixtures.
- Q&A and sketch endpoints make real Gemini calls — you'll see actual streaming responses.
- Voice mode connects to the FastAPI WS, which connects to Gemini Live API — works fully.

This is the path I recommend for a first look.

## B. Local Supabase (full stack on your machine)

Spin up the entire DB locally via Docker.

```bash
# Start Supabase (Docker required)
supabase start

# Apply migrations + seed
supabase db reset

# Copy the printed anon/service_role keys + JWT secret into apps/api/.env and apps/web/.env.local
# The default local URL is http://127.0.0.1:54321

# Run dev
pnpm dev
```

The Studio UI is at http://127.0.0.1:54323.

## C. Cloud Supabase

Use your real Supabase project. See [`supabase-mcp.md`](supabase-mcp.md) for instructions on:
- Applying migrations via Supabase MCP (one command)
- Or manually via `supabase db push`
- Where to find your project keys

Then update `apps/api/.env` and `apps/web/.env.local` and restart the dev servers.

## Frequently asked

**Q: I see "GEMINI_API_KEY is not set" on startup.**
A: Check that `apps/api/.env` has `GEMINI_API_KEY=AIza...`. The file should NOT be checked into git.

**Q: The Q&A response is slow / hangs.**
A: Gemini sometimes returns slower than expected. Check `/tmp/api.log` for errors. The default timeout is reasonable; if you hit rate limits, the tenacity retry kicks in.

**Q: Voice mode says "permission denied".**
A: Click the mic icon in the browser address bar to allow microphone access.

**Q: How do I see what Aria is "thinking"?**
A: Set `LOG_LEVEL=DEBUG` in `apps/api/.env`. You'll get verbose structlog output showing each Gemini call, token counts, and agent state transitions.

**Q: Where does the chalk effect come from?**
A: SVG `<feTurbulence>` + `<feDisplacementMap>` filter. Defined inline in `whiteboard-svg.tsx` and `sketch-layer.tsx`. Pure browser SVG — no canvas, no library.
