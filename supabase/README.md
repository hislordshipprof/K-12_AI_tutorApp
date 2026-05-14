# Supabase — K-12 AI Tutor

Local Postgres + Auth + Storage + Realtime stack for the K-12 AI tutor app.

## Prerequisites

- [Supabase CLI](https://supabase.com/docs/guides/local-development) (`brew install supabase/tap/supabase` or equivalent)
- Docker Desktop running

## Run it locally

```bash
# Start the full local stack (Postgres, Auth, Studio, Storage, Realtime).
supabase start

# Apply all migrations and run seed.sql on a fresh database.
# Run this any time you add a new migration or want a clean slate.
supabase db reset
```

After `supabase start` the CLI prints the local URLs and keys. Defaults:

| Service       | URL                              |
| ------------- | -------------------------------- |
| API           | http://127.0.0.1:54321           |
| DB            | postgresql://...@127.0.0.1:54322 |
| Studio        | http://127.0.0.1:54323           |
| Inbucket mail | http://127.0.0.1:54324           |

The CLI also prints the `anon` key, `service_role` key, and JWT secret. Copy
the `anon` key into `apps/web/.env.local` as `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
and `service_role` only into server-side env (never the browser).

## Layout

```
supabase/
├── config.toml                              # local stack config (ports, auth, etc.)
├── seed.sql                                 # curriculum seed (runs after migrations on db reset)
└── migrations/
    ├── 20260514000000_init.sql              # tables, extensions, indexes
    ├── 20260514000100_rls.sql               # row-level security policies
    └── 20260514000200_functions.sql         # triggers + compute_streak()
```

## Schema highlights

- **profiles** is 1-1 with `auth.users` via a trigger (`handle_new_user`).
- **courses → units → topics** is the public-readable curriculum tree.
  Lesson steps live in `topics.content` as a JSON array of
  `{tts, html, dur}` entries.
- **lesson_sessions** is the "Aria teaches" envelope. **qa_questions**
  and **sketches** hang off it (scoped via session, not directly via user).
- **flashcards** carries SM-2 state (`ease`, `interval_days`, `due_at`) for
  spaced repetition.
- **lesson_embeddings** uses `pgvector(768)` for semantic curriculum lookup.
- **agent_traces** is service-role only — observability for the AI runtime.

## RLS

Every user-owned table has RLS enabled. The auth model:

- `profiles`: each user can read/insert/update **only** their own row.
- Curriculum (`courses`, `units`, `topics`, `lesson_embeddings`): authenticated
  read for all; writes go through service role (e.g. content pipeline).
- All user-owned tables: `auth.uid() = user_id` for select/insert/update/delete.
- `qa_questions` and `sketches`: scoped through `lesson_sessions.user_id`.
- `agent_traces`: RLS enabled with **no** policies — only `service_role`
  (which bypasses RLS) can read or write.

## Useful commands

```bash
supabase status              # show running services & keys
supabase db reset            # drop + recreate + migrate + seed
supabase db diff -f my_name  # generate a new migration from local changes
supabase db lint             # run pg-lint over migrations
supabase stop                # tear down local stack
```
