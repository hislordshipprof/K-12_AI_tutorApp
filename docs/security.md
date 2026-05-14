# Security

## Threat model

This app handles:
- Minor user data (high schoolers, ages 15-18)
- Voice recordings (privacy-sensitive)
- Lesson content (proprietary)
- API keys to expensive paid services (Gemini)

## Defenses

### Secrets
- All API keys live in `.env` files; `.gitignore` blocks them from commit
- Pre-commit hook (recommended) scans for AKIA/sk-/AIza patterns
- Gemini key is **server-side only**; never reaches the browser
- Supabase service_role key is **server-side only**
- Use Vercel/Fly.io secret managers in production

### Auth
- Supabase Auth handles signup/login (email magic link + OAuth)
- JWTs use HS256 with `SUPABASE_JWT_SECRET`
- FastAPI verifies signature, expiration, and audience on every request
- Anon key safe to expose; RLS handles row-level access

### Row-Level Security (RLS)
Every user-owned table has policies enforcing `auth.uid() = user_id`:
- `profiles`, `enrollments`, `topic_progress`, `lesson_sessions`, `qa_questions`, `sketches`, `quiz_attempts`, `notes`, `decks`, `flashcards`, `schedule_blocks`

Public-readable tables (no write):
- `courses`, `units`, `topics`, `lesson_embeddings`

Service-role only:
- `agent_traces`

### Transport
- All endpoints HTTPS in production
- WebSocket uses WSS
- CORS restricted to known frontend origins

### Input validation
- Pydantic schemas at every API entry point
- Image uploads: max 8MB, mime-type check, image-magic-byte check
- Text inputs: length cap (1024 chars for questions)
- Rate limiting (per user, by Supabase user_id): 60 req/min on Q&A, 20 req/min on voice WS

### Output safety
- Aria's system prompt includes safety instructions: no harmful content, age-appropriate language
- Gemini's built-in safety filters are not disabled

### Privacy
- Voice audio is NOT stored by default (passed through, not persisted)
- Sketch images stored in `sketches.png_data_url` but TTL-deletable
- No PII beyond name + grade is required
- COPPA: students under 13 are out of scope; we collect grade level (which excludes elementary)

### Logging
- Structured JSON logs, no PII in log lines
- `agent_traces` redacts long text bodies; keeps metadata

### Dependency security
- Renovate (or Dependabot) for monthly bumps
- `pip-audit` and `pnpm audit` in CI

## Pre-commit hook (recommended)

```bash
# .git/hooks/pre-commit
#!/bin/sh
if git diff --cached --name-only | xargs grep -lE "AIza[0-9A-Za-z_-]{35}|sk-[0-9A-Za-z]{20,}|AKIA[0-9A-Z]{16}" 2>/dev/null; then
  echo "✗ Possible secret in commit. Aborting."
  exit 1
fi
```

## Incident response

If a key leaks to GitHub:
1. Immediately rotate the key in Google AI Studio / Supabase dashboard
2. Update `.env` files locally + Fly/Vercel secrets
3. `git filter-repo` (or BFG) to scrub history if the leak is public
4. Force-push (with permission); notify users if production data exposed
