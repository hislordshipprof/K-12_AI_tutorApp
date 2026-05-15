-- ============================================================================
-- K-12 AI Tutor — Content Pipeline Foundation (B1)
-- ----------------------------------------------------------------------------
-- 1. Rework `lesson_embeddings` from per-topic to per-chunk (breaking change;
--    table is empty in practice — no data loss).
-- 2. HNSW index on the new embedding column (cosine distance).
-- 3. `content_provenance jsonb` on `topics`.
-- 4. `content_history` archive table.
-- 5. `content_review` human-in-the-loop queue table.
-- 6. RLS: all three new/redesigned tables are service_role only.
-- ============================================================================

-- ── 1. lesson_embeddings — per-chunk redesign ───────────────────────────────
--
-- The original table keyed on topic_id (one row per topic, summary text + one
-- vector). RAG needs one row per chunk so we drop and recreate. Any policies
-- on the old table go with it on drop. CASCADE picks up the read policy that
-- was created in the RLS migration.
drop table if exists public.lesson_embeddings cascade;

create table public.lesson_embeddings (
  chunk_id    uuid primary key default gen_random_uuid(),
  topic_id    uuid not null references public.topics(id) on delete cascade,
  ordinal     int  not null,
  text        text not null,
  source_url  text,
  embedding   vector(768),
  created_at  timestamptz not null default now(),
  unique (topic_id, ordinal)
);

create index if not exists idx_lesson_embeddings_topic
  on public.lesson_embeddings(topic_id);

-- HNSW index for cosine similarity — matches the embedder's gemini-embedding-2
-- 768-d output. Built on the empty table so no `concurrently` needed.
create index if not exists idx_lesson_embeddings_hnsw
  on public.lesson_embeddings
  using hnsw (embedding vector_cosine_ops);

-- Service-role only (no policies) — the runtime RPC `match_lesson_chunks`
-- (added in B3) will run as security definer to expose read access.
alter table public.lesson_embeddings enable row level security;


-- ── 2. topics.content_provenance ────────────────────────────────────────────
alter table public.topics
  add column if not exists content_provenance jsonb;


-- ── 3. content_history (archive prior topics.content) ───────────────────────
create table if not exists public.content_history (
  id           uuid primary key default gen_random_uuid(),
  topic_id     uuid not null references public.topics(id) on delete cascade,
  content      jsonb,
  provenance   jsonb,
  archived_at  timestamptz not null default now()
);

create index if not exists idx_content_history_topic
  on public.content_history(topic_id);

alter table public.content_history enable row level security;
-- (no policies — service_role only)


-- ── 4. content_review (human-in-the-loop queue) ────────────────────────────
do $$ begin
  create type public.content_review_status as enum
    ('pending', 'approved', 'edit_needed');
exception when duplicate_object then null;
end $$;

create table if not exists public.content_review (
  topic_id     uuid primary key references public.topics(id) on delete cascade,
  status       public.content_review_status not null default 'pending',
  notes        text,
  reviewer_id  uuid references public.profiles(id) on delete set null,
  decided_at   timestamptz
);

alter table public.content_review enable row level security;
-- (no policies — service_role only)
