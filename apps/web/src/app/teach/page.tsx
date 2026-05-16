'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Icon, type IconName } from '@/components/aria/icon';
import { CreateClassModal } from '@/components/teach/create-class-modal';
import { displayName, useMe } from '@/hooks/use-me';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Teacher home (`/teach`) — the classes + courses overview (task 3.1).
 *
 * Lists the signed-in teacher's classes and courses from
 * `GET /v1/teacher/classes` and `GET /v1/teacher/courses`. The teacher
 * role gate lives in `layout.tsx`; a student never reaches this screen.
 */

interface TeacherClass {
  id: string;
  name: string;
  join_code: string;
  subject: string | null;
  student_count: number;
  pending_count: number;
}

interface TeacherCourse {
  id: string;
  title: string;
  subject: string | null;
  grade_band: string | null;
  unit_count: number;
  topic_count: number;
  published_count: number;
  draft_count: number;
  icon_emoji: string | null;
  color_gradient: string | null;
}

const DEFAULT_COURSE_COLOR =
  'linear-gradient(135deg,#1F4E7A 0%,#5B5BE5 100%)';

export default function TeachHomePage() {
  const { data: me } = useMe();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const {
    data: classes = [],
    isLoading: classesLoading,
    isError: classesError,
  } = useQuery<TeacherClass[]>({
    queryKey: ['teacher-classes'],
    queryFn: () => api<TeacherClass[]>('/v1/teacher/classes'),
    staleTime: 30_000,
  });

  const {
    data: courses = [],
    isLoading: coursesLoading,
    isError: coursesError,
  } = useQuery<TeacherCourse[]>({
    queryKey: ['teacher-courses'],
    queryFn: () => api<TeacherCourse[]>('/v1/teacher/courses'),
    staleTime: 30_000,
  });

  const studentTotal = classes.reduce((n, c) => n + c.student_count, 0);
  const pendingTotal = classes.reduce((n, c) => n + c.pending_count, 0);

  return (
    <div className="min-h-full bg-paper">
      {/* ─── COMMAND BAR ─────────────────────────────────────────────────── */}
      <header className="relative overflow-hidden rounded-b-[28px] bg-[linear-gradient(135deg,#1B1F2E_0%,#2A2E47_100%)]">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse 50% 90% at 88% 30%, rgba(91,91,229,.28), transparent 62%), radial-gradient(ellipse 44% 80% at 8% 110%, rgba(255,200,87,.10), transparent 60%)',
          }}
        />
        <div className="relative mx-auto max-w-[1180px] px-8 py-7">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-white/45">
                Teaching workspace
              </div>
              <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
                Good morning,{' '}
                <em className="not-italic text-amber">{displayName(me)}</em>
              </h1>
            </div>
            <div className="flex flex-wrap gap-2.5">
              <button
                type="button"
                onClick={() => setCreateOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/[0.18]"
              >
                <Icon name="plus" size={15} /> New class
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white shadow-[0_6px_18px_rgba(91,91,229,0.45)] transition-colors hover:bg-indigo-deep"
              >
                <Icon name="plus" size={15} /> New course
              </button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2.5">
            <StatChip n={classes.length} label={classes.length === 1 ? 'Class' : 'Classes'} />
            <StatChip n={courses.length} label={courses.length === 1 ? 'Course' : 'Courses'} />
            <StatChip n={studentTotal} label="Students" />
            <StatChip
              n={pendingTotal}
              label="Awaiting approval"
              tone={pendingTotal > 0 ? 'amber' : 'plain'}
            />
          </div>
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-14 px-8 pb-16 pt-9">
        {/* CLASSES */}
        <section id="classes" className="scroll-mt-6">
          <SectHd
            title="Your classes"
            sub={
              classes.length > 0
                ? `${classes.length} ${classes.length === 1 ? 'class' : 'classes'} · ${studentTotal} students`
                : 'Classes you teach'
            }
            action="+ New class"
            onAction={() => setCreateOpen(true)}
          />
          {classesError ? (
            <LoadError what="classes" />
          ) : classesLoading ? (
            <SkeletonGrid />
          ) : classes.length > 0 ? (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
              {classes.map((c) => (
                <ClassCard key={c.id} cls={c} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon="users"
              title="No classes yet"
              body="Create a class and share its join code so students can enrol."
              cta="New class"
              onCta={() => setCreateOpen(true)}
            />
          )}
        </section>

        {/* COURSES */}
        <section id="courses" className="scroll-mt-6">
          <SectHd
            title="Your courses"
            sub={
              courses.length > 0
                ? `${courses.length} ${courses.length === 1 ? 'course' : 'courses'}`
                : 'Courses you author'
            }
            action="+ New course"
          />
          {coursesError ? (
            <LoadError what="courses" />
          ) : coursesLoading ? (
            <SkeletonGrid />
          ) : courses.length > 0 ? (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
              {courses.map((k) => (
                <CourseCard key={k.id} course={k} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon="course"
              title="No courses yet"
              body="Create a course, add a unit, and upload your material to get started."
              cta="New course"
            />
          )}
        </section>
      </div>

      <CreateClassModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(cls) => {
          setCreateOpen(false);
          queryClient.invalidateQueries({ queryKey: ['teacher-classes'] });
          router.push(`/teach/classes/${cls.id}`);
        }}
      />
    </div>
  );
}

/* ─── helpers ──────────────────────────────────────────────────────────────── */

function StatChip({
  n,
  label,
  tone = 'plain',
}: {
  n: number;
  label: string;
  tone?: 'plain' | 'amber';
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-full border px-3.5 py-1.5',
        tone === 'amber'
          ? 'border-amber/25 bg-amber/[0.12]'
          : 'border-white/10 bg-white/[0.06]',
      )}
    >
      <span
        className={cn(
          'font-display text-[15px] font-bold tabular-nums',
          tone === 'amber' ? 'text-amber' : 'text-white',
        )}
      >
        {n}
      </span>
      <span
        className={cn(
          'text-xs font-medium',
          tone === 'amber' ? 'text-amber/85' : 'text-white/55',
        )}
      >
        {label}
      </span>
    </div>
  );
}

function SectHd({
  title,
  sub,
  action,
  onAction,
}: {
  title: string;
  sub?: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="mb-[18px] flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="font-display text-[22px] font-bold tracking-[-0.02em]">
          {title}
        </div>
        {sub && <div className="text-[13px] text-ink-3">{sub}</div>}
      </div>
      {action && (
        <button
          type="button"
          onClick={onAction}
          className="text-[13px] font-semibold text-indigo transition-colors hover:text-indigo-deep"
        >
          {action}
        </button>
      )}
    </div>
  );
}

function ClassCard({ cls }: { cls: TeacherClass }) {
  return (
    <Link
      href={`/teach/classes/${cls.id}`}
      className="flex flex-col rounded-[20px] border border-border bg-white p-5 shadow-sm transition-all duration-200 hover:-translate-y-[2px] hover:shadow-md"
    >
      <div className="flex items-center gap-3">
        <div className="grid h-11 w-11 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft text-indigo">
          <Icon name="users" size={22} />
        </div>
        <div className="min-w-0">
          <div className="truncate font-display text-[16px] font-bold tracking-[-0.015em]">
            {cls.name}
          </div>
          <div className="text-xs text-ink-3">
            {cls.student_count} {cls.student_count === 1 ? 'student' : 'students'}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between rounded-xl bg-paper-2 px-3.5 py-2.5">
        <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink-3">
          Join code
        </span>
        <span className="font-mono text-sm font-semibold tracking-wide text-ink">
          {cls.join_code}
        </span>
      </div>

      {cls.pending_count > 0 ? (
        <div className="mt-2.5 flex items-center gap-2 rounded-xl bg-coral-soft px-3.5 py-2.5 text-[12px] font-semibold text-coral">
          <Icon name="bell" size={14} />
          {cls.pending_count} {cls.pending_count === 1 ? 'student' : 'students'}{' '}
          awaiting approval
        </div>
      ) : (
        <div className="mt-2.5 flex items-center gap-2 rounded-xl bg-paper-2 px-3.5 py-2.5 text-[12px] font-medium text-ink-3">
          <Icon name="check" size={14} />
          No pending requests
        </div>
      )}
    </Link>
  );
}

function CourseCard({ course }: { course: TeacherCourse }) {
  const allDraft = course.published_count === 0;
  const allPublished = course.draft_count === 0 && course.published_count > 0;
  const statusLabel = allDraft
    ? 'Draft'
    : allPublished
      ? 'Published'
      : 'In progress';
  const meta = [course.subject, course.grade_band].filter(Boolean).join(' · ');

  return (
    <div className="flex flex-col overflow-hidden rounded-[20px] border border-border bg-white shadow-sm transition-all duration-200 hover:-translate-y-[2px] hover:shadow-md">
      <div
        className="relative flex h-[84px] items-end p-4"
        style={{ background: course.color_gradient ?? DEFAULT_COURSE_COLOR }}
      >
        <div className="absolute right-3.5 top-3.5 grid h-[38px] w-[38px] place-items-center rounded-xl border border-white/20 bg-white/[0.18] text-[20px] backdrop-blur-md">
          {course.icon_emoji ?? '📚'}
        </div>
        <div className="rounded-md bg-black/25 px-2.5 py-[3px] text-[10px] font-bold uppercase tracking-[0.1em] text-white backdrop-blur-sm">
          {statusLabel}
        </div>
      </div>

      <div className="flex flex-1 flex-col p-4">
        <div className="font-display text-[17px] font-bold tracking-[-0.015em]">
          {course.title}
        </div>
        <div className="mt-0.5 text-xs text-ink-3">{meta || 'Course'}</div>

        <div className="mt-3 flex items-center gap-1.5 text-xs text-ink-2">
          <span className="font-semibold">{course.unit_count}</span> units
          <span className="text-border-2">·</span>
          <span className="font-semibold">{course.topic_count}</span> topics
        </div>

        <div className="mt-3 flex items-center gap-3.5 border-t border-border pt-3 text-[12px]">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-mint" />
            <span className="font-semibold text-ink">{course.published_count}</span>
            <span className="text-ink-3">published</span>
          </span>
          {course.draft_count > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-amber" />
              <span className="font-semibold text-ink">{course.draft_count}</span>
              <span className="text-ink-3">draft</span>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState({
  icon,
  title,
  body,
  cta,
  onCta,
}: {
  icon: IconName;
  title: string;
  body: string;
  cta: string;
  onCta?: () => void;
}) {
  return (
    <div className="flex flex-col items-center rounded-[20px] border border-dashed border-border-2 bg-white/60 px-6 py-12 text-center">
      <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-indigo-soft text-indigo">
        <Icon name={icon} size={24} />
      </div>
      <div className="font-display text-[17px] font-bold tracking-[-0.015em]">
        {title}
      </div>
      <div className="mt-1 max-w-[340px] text-[13px] text-ink-3">{body}</div>
      <button
        type="button"
        onClick={onCta}
        className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
      >
        <Icon name="plus" size={15} /> {cta}
      </button>
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[150px] animate-soft-pulse rounded-[20px] border border-border bg-white shadow-sm"
        />
      ))}
    </div>
  );
}

function LoadError({ what }: { what: string }) {
  return (
    <div className="rounded-[20px] border border-dashed border-border-2 bg-white/60 px-6 py-8 text-center text-[13px] text-ink-3">
      Couldn&apos;t load your {what} right now. Refresh to try again.
    </div>
  );
}
