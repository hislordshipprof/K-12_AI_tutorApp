-- ============================================================================
-- Task 0.4 — Compliance baseline: record terms acceptance at sign-up
-- ----------------------------------------------------------------------------
-- §14 of teacher-authoring.md ("Privacy policy + terms surfaced at sign-up and
-- recorded as accepted") requires an auditable record that each user accepted
-- the Terms of Service + Privacy Policy. This migration adds one column:
--
--   profiles.terms_accepted_at  timestamptz  -- when the user accepted; null
--                                            -- until they do.
--
-- The web sign-up form passes `terms_accepted_at` through `signUp` metadata
-- (`raw_user_meta_data`); the `handle_new_user` trigger (re-defined below)
-- copies it onto the new `public.profiles` row. The column is nullable so
-- pre-existing profiles (and any future server-created row) are valid.
--
-- Every statement is idempotent (`add column if not exists`,
-- `create or replace`) so it is safe to re-run.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. profiles.terms_accepted_at
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column if not exists terms_accepted_at timestamptz;

-- ---------------------------------------------------------------------------
-- 2. handle_new_user() — extend the existing trigger to also seed
--    `terms_accepted_at` from the sign-up metadata.
-- ----------------------------------------------------------------------------
-- This re-defines the function first created in 20260514000200_functions.sql.
-- The only change is the added `terms_accepted_at` column: it is parsed from
-- `raw_user_meta_data->>'terms_accepted_at'` (an ISO-8601 timestamp the web
-- sign-up form sends). If absent or unparseable it falls back to null — the
-- profile row is still created so no sign-up can fail on this.
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, full_name, avatar_color, terms_accepted_at)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data->>'avatar_color', '#5B5BE5'),
    -- `terms_accepted_at` arrives as an ISO-8601 string in the sign-up
    -- metadata; cast it, tolerating absence/garbage by falling back to null.
    (
      select case
        when new.raw_user_meta_data ? 'terms_accepted_at'
          then nullif(new.raw_user_meta_data->>'terms_accepted_at', '')::timestamptz
        else null
      end
    )
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
