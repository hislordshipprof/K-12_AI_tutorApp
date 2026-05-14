'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { CourseCard } from '@/components/aria/course-card';
import { CurriculumUnit, type Unit } from '@/components/dashboard/curriculum-unit';
import { StreakCard } from '@/components/dashboard/streak-card';
import { TodayRow } from '@/components/dashboard/today-row';
import { api } from '@/lib/api';

interface CourseDto {
  id: string;
  name: string;
  meta: string;
  pct: number;
  icon: string;
  color: string;
  active?: boolean;
}

const FALLBACK_COURSES: CourseDto[] = [
  {
    id: 'ap-physics-1',
    name: 'AP Physics 1',
    meta: '8 units · 48 topics',
    pct: 28,
    icon: '⚛️',
    color: 'linear-gradient(135deg,#1F4E7A 0%,#5B5BE5 100%)',
    active: true,
  },
  {
    id: 'ap-calc-bc',
    name: 'AP Calculus BC',
    meta: '10 units · 60 topics',
    pct: 12,
    icon: '∫',
    color: 'linear-gradient(135deg,#7C2D80 0%,#A78BFA 100%)',
  },
  {
    id: 'ap-biology',
    name: 'AP Biology',
    meta: '8 units · 52 topics',
    pct: 0,
    icon: '🧬',
    color: 'linear-gradient(135deg,#15693E 0%,#34C97A 100%)',
  },
];

const UNITS: Unit[] = [
  { id: 'u1', n: 1, name: 'Kinematics', count: 6, done: 6, status: 'done' },
  { id: 'u2', n: 2, name: "Forces & Newton's Laws", count: 7, done: 4 },
  { id: 'u3', n: 3, name: 'Energy & Momentum', count: 6, done: 1 },
  {
    id: 'u4',
    n: 4,
    name: 'Waves & Sound',
    count: 7,
    done: 1,
    topics: [
      { name: 'Introduction to Waves', dur: '12m', state: 'done' },
      { name: 'Wave Properties & Anatomy', dur: '18m', state: 'current' },
      { name: 'Wave Speed & Medium', dur: '14m' },
      { name: 'Superposition & Interference', dur: '20m' },
      { name: 'Standing Waves', dur: '16m' },
      { name: 'Sound Waves & Doppler', dur: '22m' },
      { name: 'Unit 4 Practice Exam', dur: '45m' },
    ],
  },
  { id: 'u5', n: 5, name: 'Electric Charge & Force', count: 5, done: 0 },
  { id: 'u6', n: 6, name: 'Circuits', count: 5, done: 0 },
];

export default function DashboardPage() {
  const router = useRouter();
  const [openUnit, setOpenUnit] = useState<string | null>('u4');

  // Sample remote fetch; falls back silently to local data so the page renders
  // standalone before the FastAPI backend exists.
  const { data: courses } = useQuery<CourseDto[]>({
    queryKey: ['courses'],
    queryFn: async () => {
      try {
        const remote = await api<CourseDto[]>('/v1/courses');
        return remote.length > 0 ? remote : FALLBACK_COURSES;
      } catch {
        return FALLBACK_COURSES;
      }
    },
    initialData: FALLBACK_COURSES,
  });

  const goClassroom = () => router.push('/classroom/wave-properties-anatomy');

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
              Good morning, <em className="not-italic text-amber italic">Alex</em>
            </h1>
            <p className="mb-[22px] max-w-[520px] text-base leading-[1.5] text-white/70">
              You&apos;re on a <b className="font-semibold text-white">5-day streak</b> 🔥
              Last time we covered crests & troughs —{' '}
              <b className="font-semibold text-white">amplitude is next.</b> Aria&apos;s ready when
              you are.
            </p>
            <div className="flex gap-8">
              <Stat num="12" lbl="Topics done" />
              <Stat
                num={
                  <>
                    3.5<span className="text-[0.6em]">h</span>
                  </>
                }
                lbl="Time learned"
              />
              <Stat
                num={
                  <>
                    87<span className="text-[0.6em]">%</span>
                  </>
                }
                lbl="Quiz avg"
              />
              <Stat
                num={
                  <>
                    <em className="mr-1 text-[0.85em] not-italic text-amber">🔥</em>5
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
              Wave Properties & Anatomy
            </div>
            <div className="relative mb-4 text-[13px] opacity-85">
              Unit 4 · 8 of 18 min · Aria paused at &quot;amplitude&quot;
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
        {/* COURSE CARDS */}
        <SectHd
          title="Your courses"
          sub="3 active · pick one to study"
          action="+ Add a course"
        />
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((c) => (
            <CourseCard
              key={c.id}
              name={c.name}
              meta={c.meta}
              pct={c.pct}
              icon={c.icon}
              color={c.color}
              active={c.active}
              onClick={c.active ? goClassroom : undefined}
            />
          ))}
        </div>

        {/* CURRICULUM */}
        <SectHd
          title="AP Physics 1 — Curriculum"
          sub="College Board aligned · 2024–2025"
          action="View full syllabus →"
        />
        <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-border px-[22px] py-5">
            <div>
              <div className="font-display text-lg font-bold tracking-[-0.015em]">
                AP Physics 1: Algebra-Based
              </div>
              <div className="mt-0.5 text-xs text-ink-3">
                12 of 48 topics complete · est. 27 hrs remaining
              </div>
            </div>
            <div className="flex gap-[18px]">
              <CurrStat v="28%" l="Complete" />
              <CurrStat v="87%" l="Quiz avg" />
            </div>
          </div>
          {UNITS.map((u) => (
            <CurriculumUnit
              key={u.id}
              unit={u}
              open={openUnit === u.id}
              onToggle={() => setOpenUnit(openUnit === u.id ? null : u.id)}
            />
          ))}
        </div>

        {/* TODAY + STREAK */}
        <SectHd
          title="Today, May 13"
          sub={
            <>
              Aria scheduled this for you ·{' '}
              <span className="cursor-pointer text-indigo">edit plan →</span>
            </>
          }
        />
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-[1.4fr_1fr]">
          <div className="rounded-[18px] border border-border bg-white px-5 py-[18px] shadow-sm">
            <TodayRow
              time="9:00"
              dot="done"
              title="Wave Properties & Anatomy"
              meta="Lesson · AP Physics 1 · 18 min"
              tag="Done"
              tagClass="bg-mint-soft text-[#1C7A47]"
            />
            <TodayRow
              time="10:30"
              title="Wave Equation Practice"
              meta="Quiz · 10 problems · 15 min"
              tag="Up next"
              tagClass="bg-indigo-soft text-indigo-deep"
            />
            <TodayRow
              time="2:00"
              dot="coral"
              title="Office hours with Aria"
              meta="Review FRQ #2 from last week's mock exam"
              tag="Aria"
              tagClass="bg-coral-soft text-[#A1452B]"
            />
            <TodayRow
              time="7:00"
              dot="amber"
              title="Flashcard review · Wave terms"
              meta="22 cards · spaced repetition · 8 min"
              tag="Cards"
              tagClass="bg-amber-soft text-[#8A6800]"
            />
          </div>
          <StreakCard days={5} />
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

function CurrStat({ v, l }: { v: string; l: string }) {
  return (
    <div className="text-right">
      <div className="font-display text-lg font-bold text-indigo">{v}</div>
      <div className="text-[10px] uppercase tracking-[0.08em] text-ink-3">{l}</div>
    </div>
  );
}
