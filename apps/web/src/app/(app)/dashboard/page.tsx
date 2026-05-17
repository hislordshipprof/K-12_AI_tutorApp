'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { CourseCard } from '@/components/aria/course-card';
import { CurriculumUnit } from '@/components/dashboard/curriculum-unit';
import { StreakCard } from '@/components/dashboard/streak-card';
import { TodayRow } from '@/components/dashboard/today-row';
import { displayName, useMe } from '@/hooks/use-me';
import { api, resolveClassroomTopicPath } from '@/lib/api';

// Shape returned by GET /v1/me/courses — the dashboard course list, each
// item tagged `group` ('recommended' | 'teacher').
interface MyCourseRow {
  id: string;
  slug: string;
  title: string;
  exam: string | null;
  subject: string | null;
  color_gradient: string | null;
  icon_emoji: string | null;
  group: 'recommended' | 'teacher';
  published_topic_count: number | null;
}

interface CourseDto {
  id: string;
  slug: string;
  name: string;
  meta: string;
  pct: number | null;     // null when we don't know yet — render as "—"
  icon: string;
  color: string;
  group: 'recommended' | 'teacher';
  /** A teacher course with no published topic yet — shown, not enterable. */
  comingSoon: boolean;
  active?: boolean;
}

const DEFAULT_COURSE_COLOR = 'linear-gradient(135deg,#1F4E7A 0%,#5B5BE5 100%)';

interface UnitRow {
  id: string;
  n: number;
  name: string;
  topics: { id: string; n: number; name: string; duration_min: number | null }[];
}

interface PlannerBlock {
  date: string;
  start_time?: string | null;
  duration_min?: number | null;
  kind: string;
  payload?: Record<string, unknown> | null;
  status?: string;
}

interface PlannerWeek {
  week_start: string;
  blocks: PlannerBlock[];
}

function fmtDur(min: number | null): string {
  return min ? `${min}m` : '';
}

function todayISODate(): string {
  return new Date().toISOString().slice(0, 10);
}

function prettyDate(): string {
  return new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

const ONBOARDING_KEY = 'edumind.onboarding';

export default function DashboardPage() {
  const router = useRouter();
  const [openUnit, setOpenUnit] = useState<string | null>('u4');

  // Active course = clicked card OR onboarding's primary OR first course.
  // Initialised lazily from localStorage so a returning user sees their
  // onboarding choice respected even before they tap a card.
  const [activeSlugState, setActiveSlugState] = useState<string | null>(null);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(ONBOARDING_KEY);
      if (!raw) return;
      const prefs = JSON.parse(raw) as { primarySlug?: string };
      if (prefs.primarySlug) setActiveSlugState(prefs.primarySlug);
    } catch {
      // ignored — falls through to first-course default below.
    }
  }, []);

  // Real user profile + dashboard stats.
  const { data: me } = useMe();

  // Real curriculum tree from Supabase. The course cards are course rows;
  // per-course progress requires a topic_progress aggregation we don't ship
  // a dedicated endpoint for yet — we render `pct = null` ("—") rather than
  // inventing a fake percentage.
  const { data: courses = [] } = useQuery<CourseDto[]>({
    queryKey: ['dashboard-courses'],
    queryFn: async () => {
      const remote = await api<MyCourseRow[]>('/v1/me/courses');
      return remote.map(
        (c): CourseDto => ({
          id: c.id,
          slug: c.slug,
          name: c.title,
          meta:
            c.group === 'teacher'
              ? (c.subject ?? 'Teacher course')
              : c.exam
                ? `${c.exam} course`
                : '—',
          pct: null,
          icon: c.icon_emoji ?? '📚',
          color: c.color_gradient ?? DEFAULT_COURSE_COLOR,
          group: c.group,
          comingSoon:
            c.group === 'teacher' && (c.published_topic_count ?? 0) === 0,
        }),
      );
    },
    staleTime: 60_000,
  });

  // Curriculum tree — driven by the active card (which itself respects
  // onboarding's primarySlug when no card has been clicked).
  const firstCourseSlug = courses[0]?.slug;
  const activeSlug =
    activeSlugState ?? firstCourseSlug ?? 'ap-physics-1';
  // Recompute `active` from state instead of the static i===0 default.
  const coursesWithActive = courses.map((c) => ({
    ...c,
    active: c.slug === activeSlug,
  }));
  const recommendedCards = coursesWithActive.filter(
    (c) => c.group === 'recommended',
  );
  const teacherCards = coursesWithActive.filter((c) => c.group === 'teacher');
  const { data: units = [] } = useQuery<UnitRow[]>({
    queryKey: ['course-units', activeSlug],
    queryFn: async () => {
      try {
        return await api<UnitRow[]>(`/v1/courses/${activeSlug}/units`);
      } catch {
        return [];
      }
    },
    enabled: Boolean(activeSlug),
    staleTime: 60_000,
  });

  const totalTopics = units.reduce((acc, u) => acc + u.topics.length, 0);

  // Today's plan — fetch the week, filter to today's blocks.
  const { data: planner } = useQuery<PlannerWeek | null>({
    queryKey: ['planner-week'],
    queryFn: async () => {
      try {
        return await api<PlannerWeek>('/v1/planner/week');
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });
  const today = todayISODate();
  const todayBlocks = (planner?.blocks ?? []).filter((b) => b.date === today);

  // "Pick up where you left off" — routes to the user's most-recent topic
  // when we have one. Pre-first-session we resolve the first real topic of
  // the curriculum (its UUID) rather than the old prototype slug, which has
  // no `topics` row and would fail the session FK.
  const resumeTopic = me?.last_topic ?? null;
  const goClassroom = async () => {
    if (resumeTopic?.id) {
      router.push(`/classroom/${resumeTopic.id}`);
      return;
    }
    // Prefer the first topic of the active course's loaded curriculum.
    const firstTopicId = units.find((u) => u.topics.length > 0)?.topics[0]?.id;
    if (firstTopicId) {
      router.push(`/classroom/${firstTopicId}`);
      return;
    }
    const resolved = await resolveClassroomTopicPath();
    if (resolved) router.push(resolved);
  };

  return (
    <div className="bg-paper">
      {/* HERO */}
      <div
        className="relative -mb-[50px] overflow-hidden rounded-b-[32px] px-8 pb-20 pt-9"
        style={{
          background: 'linear-gradient(135deg, #1B1F2E 0%, #2A2E47 100%)',
        }}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse 60% 80% at 90% 50%, rgba(91,91,229,.25), transparent 60%), radial-gradient(ellipse 50% 70% at 10% 100%, rgba(255,200,87,.10), transparent 60%)',
          }}
        />
        <div className="relative mx-auto grid max-w-[1180px] grid-cols-1 items-center gap-8 md:grid-cols-[1.4fr_1fr]">
          <div>
            <div className="mb-2 text-[13px] font-medium tracking-[-0.005em] text-white/65">
              <span className="inline-block">👋</span> &nbsp;Welcome back
            </div>
            <h1 className="mb-2.5 font-display text-[44px] font-bold leading-[1.05] tracking-[-0.03em] text-white">
              Good morning, <em className="not-italic text-amber italic">{displayName(me)}</em>
            </h1>
            <p className="mb-[22px] max-w-[520px] text-base leading-[1.5] text-white/70">
              {me && me.streak_days > 0 ? (
                <>
                  You&apos;re on a{' '}
                  <b className="font-semibold text-white">{me.streak_days}-day streak</b> 🔥{' '}
                </>
              ) : (
                <>Welcome in. </>
              )}
              Aria&apos;s ready when you are — pick a course below to begin.
            </p>
            <div className="flex gap-8">
              <Stat
                num={me ? String(me.stats.topics_done) : '—'}
                lbl="Topics done"
              />
              <Stat
                num={
                  me ? (
                    <>
                      {(me.stats.time_spent_min / 60).toFixed(1)}
                      <span className="text-[0.6em]">h</span>
                    </>
                  ) : (
                    '—'
                  )
                }
                lbl="Time learned"
              />
              <Stat
                num={
                  me?.stats.quiz_avg_pct != null ? (
                    <>
                      {me.stats.quiz_avg_pct}
                      <span className="text-[0.6em]">%</span>
                    </>
                  ) : (
                    '—'
                  )
                }
                lbl="Quiz avg"
              />
              <Stat
                num={
                  <>
                    <em className="mr-1 text-[0.85em] not-italic text-amber">🔥</em>
                    {me?.streak_days ?? 0}
                  </>
                }
                lbl="Day streak"
              />
            </div>
          </div>

          {/* RESUME CARD */}
          <button
            type="button"
            onClick={goClassroom}
            className="relative overflow-hidden rounded-[20px] p-[22px] text-left text-white shadow-[0_12px_32px_rgba(91,91,229,0.4)]"
            style={{
              background:
                'linear-gradient(135deg, #5B5BE5 0%, #A78BFA 100%)',
            }}
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -right-[20%] -top-[20%] h-[140%] w-[70%]"
              style={{
                background:
                  'radial-gradient(circle, rgba(255,255,255,.18), transparent 60%)',
              }}
            />
            <div className="relative mb-1.5 text-[11px] font-bold uppercase tracking-[0.12em] opacity-85">
              Pick up where you left off
            </div>
            <div className="relative mb-1 font-display text-[22px] font-bold leading-[1.15] tracking-[-0.015em]">
              {resumeTopic?.name ?? 'Start your first lesson'}
            </div>
            <div className="relative mb-4 text-[13px] opacity-85">
              {resumeTopic
                ? [
                    resumeTopic.course_slug
                      ?.replace(/^ap-/, 'AP ')
                      .replace(/-/g, ' ')
                      .replace(/\b\w/g, (c) => c.toUpperCase())
                      .replace('Bc', 'BC'),
                    resumeTopic.unit_n ? `Unit ${resumeTopic.unit_n}` : null,
                    resumeTopic.duration_min ? `${resumeTopic.duration_min} min` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')
                : 'Pick any topic below to begin'}
            </div>
            <div className="relative mb-4 h-1 overflow-hidden rounded-[2px] bg-white/[0.18]">
              <div
                className="h-full rounded-[2px] bg-amber"
                style={{
                  width: '44%',
                  boxShadow: '0 0 8px rgba(255,200,87,.6)',
                }}
              />
            </div>
            <div className="relative inline-flex items-center gap-2 rounded-[11px] bg-white px-[18px] py-2.5 text-sm font-bold text-indigo-deep shadow-[0_4px_14px_rgba(0,0,0,0.18)]">
              <Icon name="play" size={14} /> Resume lesson
            </div>
          </button>
        </div>
      </div>

      {/* BODY */}
      <div className="relative mx-auto max-w-[1180px] px-8 pb-12 pt-[50px]">
        {/* RECOMMENDED COURSES */}
        <SectHd
          title="Recommended"
          sub="Built-in AP courses · pick one to study"
        />
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
          {recommendedCards.map((c) => (
            <CourseCard
              key={c.id}
              name={c.name}
              meta={c.meta}
              pct={c.pct}
              icon={c.icon}
              color={c.color}
              active={c.active}
              onClick={() => {
                // First click on a non-active card selects it (updates
                // the curriculum tree below). Re-clicking the active card
                // starts a lesson — either resumes the user's most-recent
                // session OR jumps to the first topic of that course.
                if (!c.active) {
                  setActiveSlugState(c.slug);
                  return;
                }
                goClassroom();
              }}
            />
          ))}
        </div>

        {/* FROM YOUR TEACHER */}
        {teacherCards.length > 0 && (
          <>
            <SectHd
              title="From your teacher"
              sub="Courses your teacher published to a class you joined"
            />
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
              {teacherCards.map((c) => (
                <CourseCard
                  key={c.id}
                  name={c.name}
                  meta={c.meta}
                  pct={c.pct}
                  icon={c.icon}
                  color={c.color}
                  active={c.active}
                  tag={c.comingSoon ? 'Coming soon' : 'Course'}
                  onClick={() => {
                    // A course with no published topic yet isn't enterable.
                    if (c.comingSoon) return;
                    if (!c.active) {
                      setActiveSlugState(c.slug);
                      return;
                    }
                    goClassroom();
                  }}
                />
              ))}
            </div>
          </>
        )}

        {/* CURRICULUM */}
        <SectHd
          title={`${courses.find((c) => c.slug === activeSlug)?.name ?? 'Curriculum'} — Units`}
          sub="College Board aligned · 2024 CED"
        />
        <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-border px-[22px] py-5">
            <div>
              <div className="font-display text-lg font-bold tracking-[-0.015em]">
                {courses.find((c) => c.slug === activeSlug)?.name ?? 'Curriculum'}
              </div>
              <div className="mt-0.5 text-xs text-ink-3">
                {me ? `${me.stats.topics_done} of ${totalTopics} topics complete` : `${totalTopics} topics in this course`}
              </div>
            </div>
          </div>
          {units.length === 0 && (
            <div className="px-[22px] py-6 text-sm text-ink-3">
              Curriculum loading… or this course doesn&apos;t have content yet.
            </div>
          )}
          {units.map((u) => (
            <CurriculumUnit
              key={u.id}
              unit={{
                id: u.id,
                n: u.n,
                name: u.name,
                count: u.topics.length,
                done: 0,
                topics: u.topics.map((t) => ({
                  id: t.id,
                  name: t.name,
                  dur: fmtDur(t.duration_min),
                })),
              }}
              open={openUnit === u.id}
              onToggle={() => setOpenUnit(openUnit === u.id ? null : u.id)}
            />
          ))}
        </div>

        {/* TODAY + STREAK */}
        <SectHd
          title={`Today, ${prettyDate()}`}
          sub={
            todayBlocks.length > 0
              ? 'Aria scheduled this for you'
              : 'No plan scheduled for today yet — start a lesson when you’re ready.'
          }
        />
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-[1.4fr_1fr]">
          <div className="rounded-[18px] border border-border bg-white px-5 py-[18px] shadow-sm">
            {todayBlocks.length === 0 && (
              <div className="px-1 py-6 text-sm text-ink-3">
                Nothing scheduled today.
              </div>
            )}
            {todayBlocks.map((b, i) => {
              const tagFor = (status?: string): { tag: string; tagClass: string } => {
                if (status === 'done')
                  return { tag: 'Done', tagClass: 'bg-mint-soft text-[#1C7A47]' };
                if (status === 'skipped')
                  return { tag: 'Skipped', tagClass: 'bg-paper-2 text-ink-3' };
                return { tag: 'Up next', tagClass: 'bg-indigo-soft text-indigo-deep' };
              };
              const { tag, tagClass } = tagFor(b.status);
              const title = (b.payload?.title as string | undefined) ?? b.kind;
              const meta = [b.kind, b.duration_min ? `${b.duration_min} min` : null]
                .filter(Boolean)
                .join(' · ');
              return (
                <TodayRow
                  key={i}
                  time={b.start_time ?? '—'}
                  dot={b.status === 'done' ? 'done' : undefined}
                  title={title}
                  meta={meta}
                  tag={tag}
                  tagClass={tagClass}
                />
              );
            })}
          </div>
          <StreakCard days={me?.streak_days ?? 0} />
        </div>
      </div>
    </div>
  );
}

/* ─── helpers ─── */

function Stat({ num, lbl }: { num: React.ReactNode; lbl: string }) {
  return (
    <div className="flex flex-col">
      <div className="font-display text-3xl font-bold tracking-[-0.02em] text-white">
        {num}
      </div>
      <div className="mt-[3px] text-[11px] font-medium uppercase tracking-[0.04em] text-white/55">
        {lbl}
      </div>
    </div>
  );
}

function SectHd({
  title,
  sub,
  action,
}: {
  title: string;
  sub?: React.ReactNode;
  action?: string;
}) {
  return (
    <div className="mb-[18px] mt-12 flex flex-wrap items-end justify-between gap-4 first:mt-0">
      <div>
        <div className="font-display text-[22px] font-bold tracking-[-0.02em]">
          {title}
        </div>
        {sub && <div className="text-[13px] text-ink-3">{sub}</div>}
      </div>
      {action && (
        <div className="cursor-pointer text-[13px] font-semibold text-indigo">
          {action}
        </div>
      )}
    </div>
  );
}

