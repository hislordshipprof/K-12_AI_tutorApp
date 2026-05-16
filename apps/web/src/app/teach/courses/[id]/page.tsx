'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';

import { Icon } from '@/components/aria/icon';

import { api } from '@/lib/api';

/**
 * Course detail (`/teach/courses/[id]`) — units tree + teaching style (3.3).
 *
 * Loads `GET /v1/teacher/courses/{id}` and drives the teaching-style
 * `PATCH` and the add-unit `POST`. The teaching-style paragraph
 * parameterises Aria's persona for every lesson in the course
 * (teacher-authoring.md §6 "Persona").
 */

interface Unit {
  id: string;
  n: number;
  name: string;
  material_count: number;
}

interface CourseDetail {
  id: string;
  title: string;
  subject: string | null;
  grade_band: string | null;
  teaching_style: string | null;
  units: Unit[];
}

export default function CourseDetailPage() {
  const params = useParams();
  const courseId = String(params.id ?? '');
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<CourseDetail>({
    queryKey: ['teacher-course', courseId],
    queryFn: () => api<CourseDetail>(`/v1/teacher/courses/${courseId}`),
    enabled: courseId.length > 0,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['teacher-course', courseId] });

  const [editingStyle, setEditingStyle] = useState(false);
  const [styleDraft, setStyleDraft] = useState('');
  const [addingUnit, setAddingUnit] = useState(false);
  const [unitDraft, setUnitDraft] = useState('');

  const styleMut = useMutation({
    mutationFn: (teaching_style: string) =>
      api(`/v1/teacher/courses/${courseId}`, {
        method: 'PATCH',
        json: { teaching_style },
      }),
    onSuccess: () => {
      setEditingStyle(false);
      invalidate();
    },
  });

  const unitMut = useMutation({
    mutationFn: (name: string) =>
      api<Unit>(`/v1/teacher/courses/${courseId}/units`, {
        method: 'POST',
        json: { name },
      }),
    onSuccess: () => {
      setUnitDraft('');
      setAddingUnit(false);
      invalidate();
    },
  });

  if (isLoading) return <LoadingScreen />;
  if (isError || !data) return <NotFoundScreen />;

  const style = data.teaching_style ?? '';
  const units = data.units;
  const meta = [data.subject, data.grade_band ? `Grades ${data.grade_band}` : '']
    .filter(Boolean)
    .join(' · ');

  const saveStyle = () => {
    if (styleMut.isPending) return;
    styleMut.mutate(styleDraft.trim());
  };

  const addUnit = () => {
    const name = unitDraft.trim();
    if (!name || unitMut.isPending) return;
    unitMut.mutate(name);
  };

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
            <Icon name="prev" size={14} /> All courses
          </Link>
          <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
            {data.title}
          </h1>
          {meta && <div className="mt-1 text-sm text-white/55">{meta}</div>}
          <div className="mt-4 flex flex-wrap gap-2.5">
            <StatChip n={units.length} label="Units" />
          </div>
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-12 px-8 pb-16 pt-9">
        {/* TEACHING STYLE */}
        <section>
          <SectHd
            title="Teaching style"
            sub="How you teach — this shapes Aria's voice in every lesson of this course."
          />
          <div className="rounded-[20px] border border-border bg-white p-5 shadow-sm">
            {editingStyle ? (
              <>
                <textarea
                  autoFocus
                  value={styleDraft}
                  onChange={(e) => setStyleDraft(e.target.value)}
                  rows={4}
                  placeholder="e.g. I ask a guiding question before each new idea, then build the equation from what students already pictured."
                  className="w-full resize-y rounded-xl border border-border-2 bg-paper px-3.5 py-2.5 text-sm leading-[1.55] text-ink outline-none transition placeholder:text-muted focus:border-indigo focus:bg-white focus:ring-2 focus:ring-indigo/15"
                />
                {styleMut.isError && (
                  <div className="mt-2 text-[12px] font-medium text-coral">
                    Couldn&apos;t save — please try again.
                  </div>
                )}
                <div className="mt-3 flex justify-end gap-2.5">
                  <button
                    type="button"
                    onClick={() => setEditingStyle(false)}
                    disabled={styleMut.isPending}
                    className="rounded-xl px-3.5 py-2 text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={saveStyle}
                    disabled={styleMut.isPending}
                    className="rounded-xl bg-indigo px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
                  >
                    {styleMut.isPending ? 'Saving…' : 'Save'}
                  </button>
                </div>
              </>
            ) : (
              <div className="flex items-start justify-between gap-4">
                {style ? (
                  <p className="text-sm leading-[1.6] text-ink-2">{style}</p>
                ) : (
                  <p className="text-sm text-ink-3">
                    No teaching style set yet — add one so Aria&apos;s lessons
                    sound like you.
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setStyleDraft(style);
                    setEditingStyle(true);
                  }}
                  className="flex-shrink-0 rounded-lg px-3 py-1.5 text-[13px] font-semibold text-indigo transition-colors hover:bg-indigo-soft"
                >
                  {style ? 'Edit' : 'Add'}
                </button>
              </div>
            )}
          </div>
        </section>

        {/* UNITS */}
        <section>
          <SectHd
            title="Units"
            sub={`${units.length} ${units.length === 1 ? 'unit' : 'units'} in this course`}
            action={addingUnit ? undefined : '+ Add unit'}
            onAction={() => setAddingUnit(true)}
          />
          <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
            {units.map((u) => (
              <Link
                key={u.id}
                href={`/teach/courses/${courseId}/units/${u.id}`}
                className="flex items-center gap-4 border-b border-border px-5 py-4 transition-colors last:border-b-0 hover:bg-paper-2"
              >
                <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft font-display text-sm font-bold text-indigo">
                  {u.n}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-ink">
                    {u.name}
                  </div>
                  <div className="text-xs text-ink-3">
                    {u.material_count === 0
                      ? 'No material uploaded'
                      : `${u.material_count} ${u.material_count === 1 ? 'material' : 'materials'}`}
                  </div>
                </div>
                <Icon name="chev" size={16} className="text-ink-3" />
              </Link>
            ))}

            {addingUnit && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  addUnit();
                }}
                className="flex items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0"
              >
                <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 font-display text-sm font-bold text-ink-3">
                  {units.length + 1}
                </div>
                <input
                  autoFocus
                  value={unitDraft}
                  onChange={(e) => setUnitDraft(e.target.value)}
                  placeholder="Unit name — e.g. Energy & Momentum"
                  className="min-w-0 flex-1 rounded-lg border border-border-2 bg-paper px-3 py-2 text-sm text-ink outline-none transition placeholder:text-muted focus:border-indigo focus:bg-white"
                />
                <button
                  type="submit"
                  disabled={!unitDraft.trim() || unitMut.isPending}
                  className="rounded-lg bg-indigo px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-40"
                >
                  {unitMut.isPending ? 'Adding…' : 'Add'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setUnitDraft('');
                    setAddingUnit(false);
                  }}
                  disabled={unitMut.isPending}
                  className="rounded-lg px-3 py-2 text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
                >
                  Cancel
                </button>
              </form>
            )}

            {units.length === 0 && !addingUnit && (
              <div className="px-5 py-6 text-[13px] text-ink-3">
                No units yet — add your first unit to start uploading material.
              </div>
            )}
          </div>
          {unitMut.isError && (
            <div className="mt-2 text-[12px] font-medium text-coral">
              Couldn&apos;t add the unit — please try again.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ─── helpers ──────────────────────────────────────────────────────────────── */

function StatChip({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3.5 py-1.5">
      <span className="font-display text-[15px] font-bold tabular-nums text-white">
        {n}
      </span>
      <span className="text-xs font-medium text-white/55">{label}</span>
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

function LoadingScreen() {
  return (
    <div className="min-h-full bg-paper">
      <div className="h-[150px] rounded-b-[28px] bg-[linear-gradient(135deg,#1B1F2E_0%,#2A2E47_100%)]" />
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
          <Icon name="course" size={24} />
        </div>
        <div className="font-display text-[18px] font-bold">
          Course not found
        </div>
        <div className="mt-1 text-[13px] text-ink-3">
          This course doesn&apos;t exist, or it isn&apos;t one of yours.
        </div>
        <Link
          href="/teach"
          className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
        >
          <Icon name="prev" size={15} /> Back to your courses
        </Link>
      </div>
    </div>
  );
}
