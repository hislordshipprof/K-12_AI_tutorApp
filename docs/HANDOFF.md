# Hand-off — what's in this repo when you wake up

This will be updated continuously as the autonomous build progresses. Final version when all phases complete.

## What works locally right now

(Updated after each phase completes — refer to `PROGRESS.md` for moment-by-moment status.)

## What you need to do when you wake up

1. **Get your Supabase keys** — Either:
   - **MCP path**: Have a Claude Code session apply `supabase/migrations/*.sql` to your cloud project via the Supabase MCP, then paste the anon/service_role keys into `apps/api/.env` and `apps/web/.env.local`
   - **Manual path**: `supabase login` → `supabase link --project-ref <ref>` → `supabase db push`. Then copy keys from the Supabase dashboard.
   - **Skip and use local**: `supabase start` runs a full local stack via Docker. The .env files are already pointed at `http://127.0.0.1:54321` — only the JWT secret + anon key will need to change after `supabase start` prints them.

2. **Verify the Gemini API key works** — `cd apps/api && .venv/bin/python -c "from app.services.gemini import get_gemini; import asyncio; print(asyncio.run(anext(get_gemini().stream_text('hi'))))"`. Should print "Hello" or similar.

3. **Start dev**:
   ```bash
   cd /home/claude/K-12_AI_tutorApp
   pnpm dev   # starts both web + api
   # → http://localhost:3000
   # → http://localhost:8000/docs
   ```

4. **Push to GitHub** — the local repo is at `/home/claude/K-12_AI_tutorApp` with commits ready. Either:
   ```bash
   # Option A (gh CLI auth)
   gh auth login
   git push -u origin main

   # Option B (PAT)
   git push https://<token>@github.com/hislordshipprof/K-12_AI_tutorApp.git main
   ```
   (I couldn't push from my environment without your auth.)

5. **Deploy** — see `docs/deployment.md` for Fly.io + Vercel steps.

## What's stubbed vs real

(Filled in after Phase 3 completes.)

## Cost notes

The Gemini key you provided is being used ONLY in `apps/api/.env` (gitignored). No requests have been billed yet — the build runs against mocked SDK calls in tests. The key takes effect when you run the dev server and ask a question.

Estimated cost for a full test run (one Q&A + one sketch + one voice round-trip): under $0.05 with Gemini 3.1 Flash.

## Where to start poking

| You want to... | Look at... |
|---|---|
| Try the classroom | `/classroom/wave-properties-anatomy` |
| Read the architecture | `docs/architecture.md` |
| Understand the AI agents | `docs/agents.md` |
| See what the AI agents do | `apps/api/app/agents/` |
| Tweak Aria's persona | `apps/api/app/agents/prompts.py` |
| Add a new screen | port from `/home/claude/repo/project/` |
| Fix something on the frontend | `apps/web/src/app/` + `apps/web/src/components/` |

## What I'd build next (if I were continuing)

Top-3 prioritized:

1. **Real Supabase wiring** — currently most endpoints return sample data; wire to actual DB queries via the supabase service module.
2. **Auth flow** — login/signup/magic-link pages. Demo mode bypass works for now.
3. **Mobile classroom** — the classroom is desktop-only; needs a dedicated mobile layout.
