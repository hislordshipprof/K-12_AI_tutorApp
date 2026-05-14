# Supabase MCP hand-off

The user has the Supabase MCP server connected at the Claude Code level. The current build agent's tool session does **not** expose `mcp__supabase__*` tools directly. The migrations and seed have been written as standard Postgres SQL, so they run identically against:

1. **Local Supabase** (Docker, via `supabase start && supabase db reset`)
2. **Your cloud Supabase project** (via MCP, `supabase db push`, or the dashboard SQL editor)

## When MCP tools are available

You (or a future Claude Code session) can:

```
# Apply all migrations to the live cloud project
mcp__supabase__apply_migration  ← runs each file in supabase/migrations/

# Run the seed
mcp__supabase__execute_sql  ← contents of supabase/seed.sql

# Inspect
mcp__supabase__list_tables
mcp__supabase__inspect_schema
```

## Manual path (if you'd rather use the CLI)

1. Get your project ref from `https://app.supabase.com/project/_/settings/general`.
2. `supabase login`
3. `supabase link --project-ref <ref>`
4. `supabase db push` — pushes `supabase/migrations/*.sql` to remote
5. Paste `supabase/seed.sql` into the dashboard SQL editor.

## After applying

Grab your real keys from `https://app.supabase.com/project/<ref>/settings/api`:
- `Project URL` → `SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_URL`
- `anon public` → `SUPABASE_ANON_KEY` + `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `service_role secret` → `SUPABASE_SERVICE_ROLE_KEY`
- `JWT Secret` (Settings → API → JWT Settings) → `SUPABASE_JWT_SECRET`

Update `apps/api/.env` and `apps/web/.env.local` and restart both dev servers.
