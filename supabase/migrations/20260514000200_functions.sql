-- ============================================================================
-- K-12 AI Tutor — Helper Functions & Triggers
-- ----------------------------------------------------------------------------
--   - handle_new_user()  : trigger on auth.users to seed public.profiles
--   - bump_updated_at()  : generic updated_at touch
--   - compute_streak()   : consecutive-days-with-completed-session count
-- ============================================================================

-- ---------------------------------------------------------------------------
-- handle_new_user() — auto-create a profiles row for every new auth.users
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, full_name, avatar_color)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data->>'avatar_color', '#5B5BE5')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- bump_updated_at() — generic before-update trigger
-- ---------------------------------------------------------------------------
create or replace function public.bump_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_bump_profiles_updated_at on public.profiles;
create trigger trg_bump_profiles_updated_at
  before update on public.profiles
  for each row execute function public.bump_updated_at();

drop trigger if exists trg_bump_topic_progress_updated_at on public.topic_progress;
create trigger trg_bump_topic_progress_updated_at
  before update on public.topic_progress
  for each row execute function public.bump_updated_at();

drop trigger if exists trg_bump_notes_updated_at on public.notes;
create trigger trg_bump_notes_updated_at
  before update on public.notes
  for each row execute function public.bump_updated_at();

-- ---------------------------------------------------------------------------
-- compute_streak(uuid) — count consecutive days (ending today or yesterday)
-- where the user finished at least one lesson_session.
-- ---------------------------------------------------------------------------
create or replace function public.compute_streak(p_user_id uuid)
returns int
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  v_streak    int := 0;
  v_check_day date := current_date;
  v_has_today boolean;
begin
  -- If no completed session today, start counting from yesterday (so a streak
  -- isn't lost the moment the day rolls over before today's session).
  select exists (
    select 1 from public.lesson_sessions
    where user_id = p_user_id
      and ended_at is not null
      and ended_at::date = v_check_day
  ) into v_has_today;

  if not v_has_today then
    v_check_day := v_check_day - 1;
  end if;

  loop
    if exists (
      select 1 from public.lesson_sessions
      where user_id = p_user_id
        and ended_at is not null
        and ended_at::date = v_check_day
    ) then
      v_streak    := v_streak + 1;
      v_check_day := v_check_day - 1;
    else
      exit;
    end if;
  end loop;

  return v_streak;
end;
$$;
