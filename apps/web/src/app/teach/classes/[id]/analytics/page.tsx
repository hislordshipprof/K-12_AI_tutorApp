'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';

/**
 * Class analytics (`/teach/classes/[id]/analytics`) — aggregate per-topic
 * progress for a class (task 5.3).
 *
 * Loads `GET /v1/teacher/classes/{id}/analytics`: for every published topic
 * of every course assigned to the class, how many of the class's active
 * students have started it, how many have completed it, and their average
 * score — grouped course -> unit -> topic.
 */

interface TopicStat {
  topic_id: string;
  name: string | null;
  n: number | null;
  started: number;
  completed: number;
  avg_score: number | null;
}

interface UnitStat {
  unit_id: string;
  name: string | null;
  n: number | null;
  topics: TopicStat[];
}

interface CourseStat {
  course_id: string;
  title: string | null;
  units: UnitStat[];
}

interface ClassAnalytics {
  class_id: string;
  class_name: string | null;
  student_count: number;
  courses: CourseStat[];
}

export default function ClassAnalyticsPage() {
  const params = useParams();
  const classId = String(params.id ?? '');

  const { data, isLoading, isError } = useQuery<ClassAnalytics>({
    queryKey: ['class-analytics', classId],
    queryFn: () =>
      api<ClassAnalytics>(`/v1/teacher/classes/${classId}/analytics`),
    enabled: classId.length > 0,
  });

  if (isLoading) return <LoadingScreen />;
  if (isError || !data) return <NotFoundScreen />;

  const students = data.student_count;

  return (
    <div className="min-h-full bg-paper">
      {/* ─── HEADER ──────────────────────────────────────────────────────── */}
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
          <Link
            href={`/teach/classes/${classId}`}
            className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/55 transition-colors hover:text-white"
          >
            <Icon name="prev" size={14} /> {data.class_name ?? 'Class'}
          </Link>
          <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
            Class progress
          </h1>
          <div className="mt-1 text-sm text-white/55">
            How far {data.class_name ?? 'this class'} has gotten, topic by
            topic.
          </div>
          <div className="mt-4 flex flex-wrap gap-2.5">
            <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3.5 py-1.5">
              <span className="font-display text-[15px] font-bold tabular-nums text-white">
                {students}
              </span>
              <span className="text-xs font-medium text-white/55">
                {students === 1 ? 'Student' : 'Students'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-8 px-8 pb-16 pt-9">
        {students === 0 && (
          <EmptyState
            text="No students yet — once students join this class and start lessons, their progress shows up here."
          />
        )}
        {students > 0 && data.courses.length === 0 && (
          <EmptyState
            text="No published topics yet. Assign a course and publish its topics to start tracking class progress."
          />
        )}

        {data.courses.map((course) => (
          <section key={course.course_id}>
            <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
              <div className="flex items-center gap-3 border-b border-border px-5 py-4">
                <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft text-indigo">
                  <Icon name="course" size={18} />
                </div>
                <div className="font-display text-lg font-bold tracking-[-0.015em]">
                  {course.title ?? 'Untitled course'}
                </div>
              </div>
              {course.units.map((unit) => (
                <div key={unit.unit_id}>
                  <div className="border-b border-border bg-paper px-5 py-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                    {unit.n != null ? `Unit ${unit.n} · ` : ''}
                    {unit.name ?? 'Unit'}
                  </div>
                  {unit.topics.map((t) => (
                    <TopicRow
                      key={t.topic_id}
                      topic={t}
                      students={students}
                    />
                  ))}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

/* ─── helpers ──────────────────────────────────────────────────────────── */

function TopicRow({
  topic,
  students,
}: {
  topic: TopicStat;
  students: number;
}) {
  const pct =
    students > 0 ? Math.round((topic.completed / students) * 100) : 0;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border px-5 py-3.5 last:border-b-0">
      <div className="min-w-[180px] flex-1 text-sm font-semibold text-ink">
        {topic.n != null ? (
          <span className="text-ink-3">Topic {topic.n} · </span>
        ) : null}
        {topic.name ?? 'Untitled topic'}
      </div>

      {/* completion */}
      <div className="flex items-center gap-2.5">
        <div className="h-[6px] w-[120px] overflow-hidden rounded-[3px] bg-paper-2">
          <div
            className="h-full rounded-[3px] bg-indigo transition-[width]"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-[64px] text-[12px] font-semibold tabular-nums text-ink-2">
          {topic.completed}/{students} done
        </span>
      </div>

      {/* started */}
      <span className="w-[78px] text-[12px] text-ink-3">
        {topic.started} started
      </span>

      {/* average score */}
      <span
        className={
          'rounded-full px-2.5 py-1 text-[11px] font-bold ' +
          (topic.avg_score == null
            ? 'bg-paper-2 text-ink-3'
            : topic.avg_score >= 70
              ? 'bg-mint-soft text-[#1C7A47]'
              : 'bg-amber-soft text-[#8A6800]')
        }
      >
        {topic.avg_score == null ? 'no scores' : `avg ${topic.avg_score}%`}
      </span>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 rounded-[20px] border border-dashed border-border-2 bg-white/60 px-5 py-6 text-[13px] text-ink-3">
      <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
        <Icon name="history" size={18} />
      </div>
      {text}
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="min-h-full bg-paper">
      <div className="h-[180px] rounded-b-[28px] bg-[linear-gradient(135deg,#1B1F2E_0%,#2A2E47_100%)]" />
      <div className="mx-auto max-w-[1180px] space-y-4 px-8 pt-9">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-20 animate-soft-pulse rounded-[20px] border border-border bg-white shadow-sm"
          />
        ))}
      </div>
    </div>
  );
}

function NotFoundScreen() {
  return (
    <div className="grid min-h-full place-items-center bg-paper px-8">
      <div className="flex flex-col items-center text-center">
        <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-paper-2 text-ink-3">
          <Icon name="history" size={24} />
        </div>
        <div className="font-display text-[18px] font-bold">
          Class not found
        </div>
        <div className="mt-1 text-[13px] text-ink-3">
          This class doesn&apos;t exist, or it isn&apos;t one of yours.
        </div>
        <Link
          href="/teach"
          className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
        >
          <Icon name="prev" size={15} /> Back to your classes
        </Link>
      </div>
    </div>
  );
}
