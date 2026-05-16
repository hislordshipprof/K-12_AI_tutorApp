-- Adds topic_versions.validation: the per-version {passed, covered, total, gaps}
-- lesson-validation result, so the publish gate can check the ACTIVE version.
alter table public.topic_versions add column if not exists validation jsonb;
