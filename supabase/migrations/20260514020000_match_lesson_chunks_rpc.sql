-- ============================================================================
-- K-12 AI Tutor — match_lesson_chunks RPC (B3 runtime RAG)
-- ----------------------------------------------------------------------------
-- pgvector cosine search wrapper over `lesson_embeddings`. Exposing this as a
-- `security definer` function lets the runtime API call it with a thin REST
-- payload (no need to push the 768-d vector through the public REST surface),
-- and keeps RLS on the underlying table service-role-only.
-- ============================================================================

create or replace function public.match_lesson_chunks(
  p_topic_id        uuid,
  p_query_embedding vector(768),
  p_match_count     int default 3,
  p_threshold       float default 0.6
)
returns table (
  chunk_id   uuid,
  ordinal    int,
  text       text,
  source_url text,
  similarity float
)
language sql
stable
security definer
set search_path = public
as $$
  select
    le.chunk_id,
    le.ordinal,
    le.text,
    le.source_url,
    1 - (le.embedding <=> p_query_embedding) as similarity
  from public.lesson_embeddings le
  where le.topic_id = p_topic_id
    and le.embedding is not null
    and 1 - (le.embedding <=> p_query_embedding) >= p_threshold
  order by le.embedding <=> p_query_embedding
  limit greatest(p_match_count, 1);
$$;

-- Allow the API (anon/authenticated/service_role) to invoke the function;
-- the function's `security definer` clause grants it the read it needs.
grant execute on function public.match_lesson_chunks(uuid, vector(768), int, float)
  to anon, authenticated, service_role;

comment on function public.match_lesson_chunks(uuid, vector(768), int, float) is
  'B3 runtime RAG: cosine search over lesson_embeddings within one topic.';
