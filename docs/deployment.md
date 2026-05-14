# Deployment

## Production targets

| Component | Platform | Notes |
|---|---|---|
| Web (Next.js) | Vercel | Auto-deploy on push to `main`, preview on every PR |
| API (FastAPI) | Fly.io | WebSocket-friendly, low cold-start, `min_machines_running=1` for voice |
| DB | Supabase managed | Free tier OK for MVP, upgrade to Pro for production |
| Storage | Supabase Storage | Avatar + sketch image archives |

## Environment variables

| Var | Where set | Notes |
|---|---|---|
| `GEMINI_API_KEY` | Fly.io secrets | `fly secrets set GEMINI_API_KEY=...` |
| `SUPABASE_URL` | Fly.io + Vercel | Same value in both |
| `SUPABASE_ANON_KEY` | Vercel (`NEXT_PUBLIC_`) + Fly.io | Safe to expose in browser |
| `SUPABASE_SERVICE_ROLE_KEY` | Fly.io only | NEVER in browser env |
| `SUPABASE_JWT_SECRET` | Fly.io only | Used to verify tokens |
| `NEXT_PUBLIC_API_BASE` | Vercel | `https://api.k12tutor.app` in prod |

## Deploy steps (first time)

### 1. Supabase
1. Create project at https://app.supabase.com
2. Get project ref, anon key, service role key, JWT secret (Settings → API)
3. `supabase link --project-ref <ref>`
4. `supabase db push` to apply migrations
5. Open SQL editor, paste `supabase/seed.sql` to load demo content

### 2. Fly.io (API)
```bash
cd apps/api
fly launch  # creates app + fly.toml; use python builder, port 8000
fly secrets set GEMINI_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... SUPABASE_JWT_SECRET=...
fly deploy
```

### 3. Vercel (Web)
```bash
cd apps/web
vercel
# In the Vercel dashboard:
# - Set Framework: Next.js
# - Root Directory: apps/web
# - Build Command: (default)
# - Add env vars: NEXT_PUBLIC_API_BASE, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY
vercel --prod
```

### 4. CORS
Update FastAPI `CORS_ORIGINS` env on Fly to include your Vercel domain.

## CI/CD (GitHub Actions)

`.github/workflows/ci.yml` runs on every push:
- Web: typecheck, lint, build, Playwright smoke
- API: ruff, mypy, pytest

`.github/workflows/deploy.yml` runs on push to `main`:
- Vercel deploys via Git integration (no action needed)
- Fly deploys via `flyctl deploy --remote-only` with `FLY_API_TOKEN` GH secret

## Monitoring

- Sentry (frontend + backend)
- Supabase dashboard for DB metrics
- Fly.io built-in metrics + `fly logs`
- `agent_traces` table for AI debugging

## Cost estimates (per 100 active students/month)

| Item | Est. cost |
|---|---|
| Gemini 3.1 Flash (text) | ~$5-15 |
| Gemini 3.1 Flash (vision) | ~$5-10 |
| Gemini 3.1 Flash Live | ~$20-40 (voice is the priciest) |
| Vercel Pro | $20 |
| Fly.io shared CPU | $10-20 |
| Supabase Pro | $25 |
| **Total** | **~$85-130/mo** |

For pre-launch / dev: free tier works, daily limits sufficient.
