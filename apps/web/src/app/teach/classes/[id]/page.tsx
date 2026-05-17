'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Class detail (`/teach/classes/[id]`) — roster + join approvals (task 3.2).
 *
 * Loads `GET /v1/teacher/classes/{id}` and drives the approve / decline /
 * remove `class_members` mutations. Approving a pending request is the §14
 * consent checkpoint — the backend records `approved_by` / `approved_at`.
 */

interface RosterMember {
  student_id: string;
  name: string | null;
  email: string | null;
  joined_at: string | null;
}

interface PendingMember {
  student_id: string;
  name: string | null;
  email: string | null;
  requested_at: string | null;
}

interface ClassDetail {
  id: string;
  name: string;
  subject: string | null;
  join_code: string;
  roster: RosterMember[];
  pending: PendingMember[];
  courses: { id: string; title: string }[];
}

/** A teacher course as listed by `GET /v1/teacher/courses` — picker pool. */
interface TeacherCourseLite {
  id: string;
  title: string;
}

const AVATAR_COLORS = ['#5B5BE5', '#FF7A59', '#34C97A', '#A78BFA', '#5FB7F4'];

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? '')
      .join('') || '?'
  );
}

function colorFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i += 1) h = (h * 31 + name.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length] ?? '#5B5BE5';
}

function shortDate(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function relTime(iso: string | null): string {
  if (!iso) return 'recently';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'recently';
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return `on ${shortDate(iso)}`;
}

export default function ClassDetailPage() {
  const params = useParams();
  const classId = String(params.id ?? '');
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);

  const { data, isLoading, isError } = useQuery<ClassDetail>({
    queryKey: ['teacher-class', classId],
    queryFn: () => api<ClassDetail>(`/v1/teacher/classes/${classId}`),
    enabled: classId.length > 0,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['teacher-class', classId] });

  const approveMut = useMutation({
    mutationFn: (studentId: string) =>
      api(`/v1/teacher/classes/${classId}/members/${studentId}/approve`, {
        method: 'POST',
      }),
    onSuccess: invalidate,
  });

  const removeMut = useMutation({
    mutationFn: (studentId: string) =>
      api(`/v1/teacher/classes/${classId}/members/${studentId}`, {
        method: 'DELETE',
      }),
    onSuccess: invalidate,
  });

  // The teacher's courses — the pool the "Assign a course" picker draws from.
  const { data: teacherCourses = [] } = useQuery<TeacherCourseLite[]>({
    queryKey: ['teacher-courses'],
    queryFn: () => api<TeacherCourseLite[]>('/v1/teacher/courses'),
    staleTime: 30_000,
  });
  const [coursePick, setCoursePick] = useState('');

  const assignMut = useMutation({
    mutationFn: (courseId: string) =>
      api(`/v1/teacher/classes/${classId}/courses`, {
        method: 'POST',
        json: { course_id: courseId },
      }),
    onSuccess: () => {
      setCoursePick('');
      invalidate();
    },
  });

  const unassignMut = useMutation({
    mutationFn: (courseId: string) =>
      api(`/v1/teacher/classes/${classId}/courses/${courseId}`, {
        method: 'DELETE',
      }),
    onSuccess: invalidate,
  });

  const copyCode = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.join_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable — no-op */
    }
  };

  if (isLoading) return <LoadingScreen />;
  if (isError || !data) return <NotFoundScreen />;

  const pending = data.pending;
  const roster = data.roster;

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
            href="/teach"
            className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/55 transition-colors hover:text-white"
          >
            <Icon name="prev" size={14} /> All classes
          </Link>
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
                {data.name}
              </h1>
              {data.subject && (
                <div className="mt-1 text-sm text-white/55">{data.subject}</div>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-2.5">
                <StatChip n={roster.length} label="Students" />
                <StatChip
                  n={pending.length}
                  label="Pending"
                  tone={pending.length > 0 ? 'amber' : 'plain'}
                />
                <Link
                  href={`/teach/classes/${classId}/analytics`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-white/12 bg-white/[0.06] px-3.5 py-1.5 text-xs font-semibold text-white/80 transition-colors hover:bg-white/15 hover:text-white"
                >
                  <Icon name="history" size={13} /> Class progress
                </Link>
              </div>
            </div>

            {/* JOIN CODE panel */}
            <div className="rounded-2xl border border-white/12 bg-white/[0.06] p-4">
              <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-white/45">
                Join code
              </div>
              <div className="flex items-center gap-3">
                <span className="font-mono text-2xl font-bold tracking-[0.08em] text-white">
                  {data.join_code}
                </span>
                <button
                  type="button"
                  onClick={copyCode}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-white/20"
                >
                  <Icon name={copied ? 'check' : 'notes'} size={13} />
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <div className="mt-1.5 text-[11px] text-white/40">
                Students enter this to request a spot.
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-12 px-8 pb-16 pt-9">
        {/* PENDING REQUESTS — the consent gate */}
        <section>
          <SectHd
            title="Pending requests"
            sub={
              pending.length > 0
                ? `${pending.length} ${pending.length === 1 ? 'student is' : 'students are'} waiting for your approval`
                : 'Students who enter the join code appear here for approval'
            }
          />
          {pending.length > 0 ? (
            <div className="overflow-hidden rounded-[20px] border border-coral/30 bg-white shadow-sm">
              <div className="flex items-center gap-2 border-b border-border bg-coral-soft px-5 py-2.5 text-[12px] font-semibold text-coral">
                <Icon name="bell" size={14} />
                Approving a student is the consent record for letting them in.
              </div>
              {pending.map((m) => (
                <PendingRow
                  key={m.student_id}
                  name={m.name ?? 'Unnamed student'}
                  email={m.email}
                  when={`requested ${relTime(m.requested_at)}`}
                  busy={
                    (approveMut.isPending &&
                      approveMut.variables === m.student_id) ||
                    (removeMut.isPending && removeMut.variables === m.student_id)
                  }
                  onApprove={() => approveMut.mutate(m.student_id)}
                  onDecline={() => removeMut.mutate(m.student_id)}
                />
              ))}
            </div>
          ) : (
            <EmptyRow icon="check" text="No pending requests right now." />
          )}
        </section>

        {/* ROSTER */}
        <section>
          <SectHd
            title="Roster"
            sub={`${roster.length} active ${roster.length === 1 ? 'student' : 'students'}`}
          />
          {roster.length > 0 ? (
            <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
              {roster.map((m) => (
                <RosterRow
                  key={m.student_id}
                  name={m.name ?? 'Unnamed student'}
                  email={m.email}
                  when={`joined ${shortDate(m.joined_at) || 'recently'}`}
                  busy={
                    removeMut.isPending && removeMut.variables === m.student_id
                  }
                  onRemove={() => removeMut.mutate(m.student_id)}
                />
              ))}
            </div>
          ) : (
            <EmptyRow
              icon="users"
              text="No students yet — share the join code to get your class started."
            />
          )}
        </section>

        {/* ASSIGNED COURSES */}
        <section>
          <SectHd
            title="Assigned courses"
            sub="Courses this class's students can see on their dashboard"
          />
          {(() => {
            const assignable = teacherCourses.filter(
              (tc) => !data.courses.some((ac) => ac.id === tc.id),
            );
            return (
              <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
                {data.courses.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0"
                  >
                    <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
                      <Icon name="course" size={18} />
                    </div>
                    <div className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">
                      {c.title}
                    </div>
                    <button
                      type="button"
                      onClick={() => unassignMut.mutate(c.id)}
                      disabled={unassignMut.isPending}
                      aria-label={`Unassign ${c.title}`}
                      className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-coral-soft hover:text-coral disabled:opacity-40"
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </div>
                ))}
                {data.courses.length === 0 && (
                  <div className="px-5 py-4 text-[13px] text-ink-3">
                    No courses assigned yet.
                  </div>
                )}

                {/* assign control */}
                <div className="border-t border-border bg-paper-2/50 px-5 py-3">
                  {assignable.length > 0 ? (
                    <form
                      className="flex items-center gap-2.5"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (coursePick && !assignMut.isPending) {
                          assignMut.mutate(coursePick);
                        }
                      }}
                    >
                      <select
                        value={coursePick}
                        onChange={(e) => setCoursePick(e.target.value)}
                        aria-label="Course to assign"
                        className="min-w-0 flex-1 rounded-lg border border-border-2 bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-indigo"
                      >
                        <option value="">Assign a course…</option>
                        {assignable.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.title}
                          </option>
                        ))}
                      </select>
                      <button
                        type="submit"
                        disabled={!coursePick || assignMut.isPending}
                        className="rounded-lg bg-indigo px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-40"
                      >
                        {assignMut.isPending ? 'Assigning…' : 'Assign'}
                      </button>
                    </form>
                  ) : (
                    <span className="text-[13px] text-ink-3">
                      {teacherCourses.length === 0
                        ? 'Create a course first, then assign it to this class.'
                        : 'All your courses are assigned to this class.'}
                    </span>
                  )}
                </div>
              </div>
            );
          })()}
        </section>
      </div>
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

function SectHd({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-[18px]">
      <div className="font-display text-[22px] font-bold tracking-[-0.02em]">
        {title}
      </div>
      {sub && <div className="text-[13px] text-ink-3">{sub}</div>}
    </div>
  );
}

function Avatar({ name }: { name: string }) {
  return (
    <div
      className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-full text-[12px] font-bold text-white"
      style={{ background: colorFor(name) }}
    >
      {initials(name)}
    </div>
  );
}

function PendingRow({
  name,
  email,
  when,
  busy,
  onApprove,
  onDecline,
}: {
  name: string;
  email: string | null;
  when: string;
  busy: boolean;
  onApprove: () => void;
  onDecline: () => void;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0">
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ink">{name}</div>
        {email && <div className="truncate text-xs text-ink-3">{email}</div>}
      </div>
      <div className="hidden text-xs text-ink-3 sm:block">{when}</div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onDecline}
          disabled={busy}
          className="rounded-lg px-3 py-1.5 text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
        >
          Decline
        </button>
        <button
          type="button"
          onClick={onApprove}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo px-3.5 py-1.5 text-[13px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
        >
          <Icon name="check" size={13} /> Approve
        </button>
      </div>
    </div>
  );
}

function RosterRow({
  name,
  email,
  when,
  busy,
  onRemove,
}: {
  name: string;
  email: string | null;
  when: string;
  busy: boolean;
  onRemove: () => void;
}) {
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="flex items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0">
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ink">{name}</div>
        {email && <div className="truncate text-xs text-ink-3">{email}</div>}
      </div>
      <div className="hidden text-xs text-ink-3 sm:block">{when}</div>
      {confirming ? (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-ink-3">Remove?</span>
          <button
            type="button"
            onClick={onRemove}
            disabled={busy}
            className="rounded-lg bg-coral px-3 py-1.5 text-[13px] font-semibold text-white transition-colors hover:brightness-95 disabled:opacity-50"
          >
            Remove
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            disabled={busy}
            className="rounded-lg px-3 py-1.5 text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="rounded-lg px-3 py-1.5 text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink"
        >
          Remove
        </button>
      )}
    </div>
  );
}

function EmptyRow({
  icon,
  text,
}: {
  icon: 'check' | 'users' | 'course';
  text: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-[20px] border border-dashed border-border-2 bg-white/60 px-5 py-6 text-[13px] text-ink-3">
      <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
        <Icon name={icon} size={18} />
      </div>
      {text}
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="min-h-full bg-paper">
      <div className="h-[168px] rounded-b-[28px] bg-[linear-gradient(135deg,#1B1F2E_0%,#2A2E47_100%)]" />
      <div className="mx-auto max-w-[1180px] space-y-4 px-8 pt-9">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-16 animate-soft-pulse rounded-[20px] border border-border bg-white shadow-sm"
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
          <Icon name="users" size={24} />
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
