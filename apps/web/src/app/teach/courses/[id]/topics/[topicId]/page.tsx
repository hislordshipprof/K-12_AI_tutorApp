'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Topic page (`/teach/courses/[id]/topics/[topicId]`) — generate / review /
 * version / publish (task 3.5).
 *
 * The teacher runs the per-topic generation job, reviews and edits the
 * generated lesson, previews it as a student (the live classroom), manages
 * versions, and publishes — publish is blocked until the active version's
 * lesson validates (teacher-authoring.md §6). Loads
 * `GET /v1/teacher/topics/{id}` and drives the generate job, the
 * content/design-notes `PATCH`es, version activate/delete, and publish.
 */

interface Step {
  tts: string;
  html: string;
  dur: string;
  scene: Record<string, unknown>;
  page: string | null;
}

interface KeyPointGap {
  section: string;
  key_point: string;
  verdict: 'missing' | 'weak';
  detail: string;
}

interface Validation {
  passed: boolean;
  covered: number;
  total: number;
  gaps: KeyPointGap[];
}

interface Version {
  id: string;
  label: string;
  created_at: string;
  active: boolean;
  validation: Validation | null;
}

interface GenJob {
  id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  stage: string | null;
}

interface TopicDetail {
  id: string;
  name: string;
  status: 'draft' | 'published';
  design_notes: string | null;
  content: Step[];
  active_version_id: string | null;
  course_id: string;
  unit_id: string;
  unit_name: string;
  generate_job: GenJob | null;
  versions: Version[];
}

function shortDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export default function TopicPage() {
  const params = useParams();
  const courseId = String(params.id ?? '');
  const topicId = String(params.topicId ?? '');
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<TopicDetail>({
    queryKey: ['teacher-topic', topicId],
    queryFn: () => api<TopicDetail>(`/v1/teacher/topics/${topicId}`),
    enabled: topicId.length > 0,
    refetchInterval: (query) => {
      const s = query.state.data?.generate_job?.status;
      return s === 'queued' || s === 'running' ? 2500 : false;
    },
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['teacher-topic', topicId] });

  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState('');

  const notesMut = useMutation({
    mutationFn: (design_notes: string) =>
      api(`/v1/teacher/topics/${topicId}`, {
        method: 'PATCH',
        json: { design_notes },
      }),
    onSuccess: () => {
      setEditingNotes(false);
      invalidate();
    },
  });

  const contentMut = useMutation({
    mutationFn: (content: Step[]) =>
      api(`/v1/teacher/topics/${topicId}`, {
        method: 'PATCH',
        json: { content },
      }),
    onSuccess: invalidate,
  });

  const generateMut = useMutation({
    mutationFn: () =>
      api(`/v1/teacher/topics/${topicId}/generate`, { method: 'POST' }),
    onSuccess: invalidate,
  });

  const activateMut = useMutation({
    mutationFn: (versionId: string) =>
      api(`/v1/teacher/topics/${topicId}/versions/${versionId}/activate`, {
        method: 'POST',
      }),
    onSuccess: invalidate,
  });

  const deleteMut = useMutation({
    mutationFn: (versionId: string) =>
      api(`/v1/teacher/topics/${topicId}/versions/${versionId}`, {
        method: 'DELETE',
      }),
    onSuccess: invalidate,
  });

  const publishMut = useMutation({
    mutationFn: () =>
      api(`/v1/teacher/topics/${topicId}/publish`, { method: 'POST' }),
    onSuccess: invalidate,
  });

  if (isLoading) return <LoadingScreen />;
  if (isError || !data) return <NotFoundScreen courseId={courseId} />;

  const job = data.generate_job;
  const inFlight = job?.status === 'queued' || job?.status === 'running';
  const stage: 'idle' | 'running' | 'done' | 'failed' = inFlight
    ? 'running'
    : data.versions.length > 0
      ? 'done'
      : job?.status === 'failed'
        ? 'failed'
        : 'idle';

  const steps = data.content ?? [];
  const activeVersion =
    data.versions.find((v) => v.id === data.active_version_id) ?? null;
  const validation = activeVersion?.validation ?? null;
  const validated = validation?.passed === true;

  const saveStep = (i: number, patch: { tts: string; html: string }) => {
    const next = steps.map((s, j) => (j === i ? { ...s, ...patch } : s));
    contentMut.mutate(next);
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
            href={`/teach/courses/${courseId}/units/${data.unit_id}`}
            className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/55 transition-colors hover:text-white"
          >
            <Icon name="prev" size={14} /> {data.unit_name}
          </Link>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
              {data.name}
            </h1>
            <StatusPill status={data.status} />
          </div>
          {stage === 'done' && (
            <div className="mt-4 flex flex-wrap gap-2.5">
              <StatChip n={steps.length} label="Steps" />
              <StatChip n={data.versions.length} label="Versions" />
            </div>
          )}
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-12 px-8 pb-32 pt-9">
        {/* DESIGN NOTES */}
        <section>
          <SectHd
            title="Design notes"
            sub="Per-lesson guidance for the generator — what to emphasise, how to open."
          />
          <div className="rounded-[20px] border border-border bg-white p-5 shadow-sm">
            {editingNotes ? (
              <>
                <textarea
                  autoFocus
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  rows={3}
                  placeholder="e.g. Lead with a concrete example before the equation."
                  className="w-full resize-y rounded-xl border border-border-2 bg-paper px-3.5 py-2.5 text-sm leading-[1.55] text-ink outline-none transition placeholder:text-muted focus:border-indigo focus:bg-white focus:ring-2 focus:ring-indigo/15"
                />
                {notesMut.isError && (
                  <div className="mt-2 text-[12px] font-medium text-coral">
                    Couldn&apos;t save — please try again.
                  </div>
                )}
                <div className="mt-3 flex justify-end gap-2.5">
                  <button
                    type="button"
                    onClick={() => setEditingNotes(false)}
                    disabled={notesMut.isPending}
                    className="rounded-xl px-3.5 py-2 text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => notesMut.mutate(notesDraft.trim())}
                    disabled={notesMut.isPending}
                    className="rounded-xl bg-indigo px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
                  >
                    {notesMut.isPending ? 'Saving…' : 'Save'}
                  </button>
                </div>
              </>
            ) : (
              <div className="flex items-start justify-between gap-4">
                {data.design_notes ? (
                  <p className="text-sm leading-[1.6] text-ink-2">
                    {data.design_notes}
                  </p>
                ) : (
                  <p className="text-sm text-ink-3">
                    No design notes — add guidance to steer the next
                    generation.
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setNotesDraft(data.design_notes ?? '');
                    setEditingNotes(true);
                  }}
                  className="flex-shrink-0 rounded-lg px-3 py-1.5 text-[13px] font-semibold text-indigo transition-colors hover:bg-indigo-soft"
                >
                  {data.design_notes ? 'Edit' : 'Add'}
                </button>
              </div>
            )}
          </div>
        </section>

        {/* LESSON */}
        <section>
          <SectHd
            title="Lesson"
            sub="The generated Aria lesson — review, edit, and preview before publishing."
          />

          {stage === 'idle' && (
            <div className="flex flex-wrap items-center gap-4 rounded-[20px] border border-border bg-white p-5 shadow-sm">
              <div className="grid h-12 w-12 flex-shrink-0 place-items-center rounded-2xl bg-indigo-soft text-indigo">
                <Icon name="course" size={24} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-display text-[15px] font-bold text-ink">
                  Generate the lesson
                </div>
                <div className="mt-0.5 text-[13px] text-ink-3">
                  The model writes Aria&apos;s lesson from this topic&apos;s
                  slides and key points. This takes a couple of minutes.
                </div>
                {generateMut.isError && (
                  <div className="mt-1.5 text-[12px] font-medium text-coral">
                    Couldn&apos;t start generation — please try again.
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => generateMut.mutate()}
                disabled={generateMut.isPending}
                className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
              >
                <Icon name="plus" size={15} />
                {generateMut.isPending ? 'Starting…' : 'Generate lesson'}
              </button>
            </div>
          )}

          {stage === 'running' && (
            <GenerateProgress
              activeStage={
                job?.stage === 'generating' || job?.stage === 'validating'
                  ? job.stage
                  : 'rendering'
              }
            />
          )}

          {stage === 'failed' && (
            <div className="rounded-[20px] border border-coral/30 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <div className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl bg-coral-soft text-coral">
                  <Icon name="close" size={20} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-ink">
                    Generation didn&apos;t finish
                  </div>
                  <div className="text-[13px] text-ink-3">
                    Something went wrong writing the lesson. Try again.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => generateMut.mutate()}
                  disabled={generateMut.isPending}
                  className="rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
                >
                  {generateMut.isPending ? 'Starting…' : 'Try again'}
                </button>
              </div>
            </div>
          )}

          {stage === 'done' && (
            <div className="space-y-4">
              {validation && <ValidationBanner validation={validation} />}

              <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
                {steps.map((s, i) => (
                  <StepCard
                    key={i}
                    index={i}
                    step={s}
                    busy={contentMut.isPending}
                    onSave={(patch) => saveStep(i, patch)}
                  />
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <Link
                  href={`/classroom/${topicId}`}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
                >
                  <Icon name="play" size={15} /> Preview as student
                </Link>
                <button
                  type="button"
                  onClick={() => generateMut.mutate()}
                  disabled={generateMut.isPending}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-border-2 px-4 py-2.5 text-sm font-semibold text-ink-2 transition-colors hover:border-indigo hover:bg-indigo-soft hover:text-indigo disabled:opacity-50"
                >
                  <Icon name="prev" size={15} />
                  {generateMut.isPending ? 'Starting…' : 'Re-generate'}
                </button>
                <span className="text-[12px] text-ink-3">
                  Re-generating writes a new version — your current one is kept.
                </span>
              </div>
            </div>
          )}
        </section>

        {/* VERSIONS */}
        {data.versions.length > 0 && (
          <section>
            <SectHd
              title="Versions"
              sub="Every generation is kept — switch the live one or delete old drafts."
            />
            <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
              {data.versions.map((v) => (
                <VersionRow
                  key={v.id}
                  version={v}
                  busy={activateMut.isPending || deleteMut.isPending}
                  onActivate={() => activateMut.mutate(v.id)}
                  onDelete={() => deleteMut.mutate(v.id)}
                />
              ))}
            </div>
          </section>
        )}
      </div>

      {/* ─── PUBLISH BAR ─────────────────────────────────────────────────── */}
      {stage === 'done' && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-white/95 backdrop-blur-sm">
          <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-4 px-8 py-3.5">
            <div className="flex items-center gap-2 text-[13px]">
              {data.status === 'published' ? (
                <span className="inline-flex items-center gap-1.5 font-semibold text-[#1C7A47]">
                  <Icon name="check" size={15} /> Published — students can see
                  this topic.
                </span>
              ) : publishMut.isError ? (
                <span className="font-medium text-coral">
                  Couldn&apos;t publish — the lesson must validate first.
                </span>
              ) : validated ? (
                <span className="text-ink-3">
                  Lesson validated — ready to publish to your classes.
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 font-medium text-coral">
                  <Icon name="close" size={14} /> Publish is blocked until the
                  lesson validates — re-generate to fix the gaps.
                </span>
              )}
            </div>
            <button
              type="button"
              disabled={
                data.status === 'published' ||
                !validated ||
                publishMut.isPending
              }
              onClick={() => publishMut.mutate()}
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Icon name="check" size={15} />
              {data.status === 'published'
                ? 'Published'
                : publishMut.isPending
                  ? 'Publishing…'
                  : 'Publish topic'}
            </button>
          </div>
        </div>
      )}
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

function StatusPill({ status }: { status: 'draft' | 'published' }) {
  return (
    <span
      className={cn(
        'rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-[0.1em]',
        status === 'published'
          ? 'bg-mint-soft text-[#1C7A47]'
          : 'bg-white/[0.08] text-white/70',
      )}
    >
      {status}
    </span>
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

function GenerateProgress({
  activeStage,
}: {
  activeStage: 'rendering' | 'generating' | 'validating';
}) {
  const steps: { key: 'rendering' | 'generating' | 'validating'; label: string }[] =
    [
      { key: 'rendering', label: 'Rendering the slides' },
      { key: 'generating', label: 'Writing the lesson' },
      { key: 'validating', label: 'Checking coverage' },
    ];
  const activeIdx = steps.findIndex((s) => s.key === activeStage);

  return (
    <div className="rounded-[20px] border border-border bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft text-indigo">
          <span className="block h-4 w-4 animate-spin rounded-full border-2 border-indigo border-t-transparent" />
        </div>
        <div>
          <div className="text-sm font-semibold text-ink">
            Generating the lesson…
          </div>
          <div className="text-[13px] text-ink-3">
            This runs in the background — you can leave this page.
          </div>
        </div>
      </div>
      <div className="mt-4 space-y-2">
        {steps.map((s, i) => {
          const done = i < activeIdx;
          const active = i === activeIdx;
          return (
            <div key={s.key} className="flex items-center gap-2.5">
              <span
                className={cn(
                  'grid h-5 w-5 flex-shrink-0 place-items-center rounded-full text-[10px] font-bold',
                  done && 'bg-mint text-white',
                  active && 'bg-indigo text-white',
                  !done && !active && 'bg-paper-2 text-ink-3',
                )}
              >
                {done ? <Icon name="check" size={11} /> : i + 1}
              </span>
              <span
                className={cn(
                  'text-[13px]',
                  active ? 'font-semibold text-ink' : 'text-ink-3',
                )}
              >
                {s.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ValidationBanner({ validation }: { validation: Validation }) {
  const [open, setOpen] = useState(false);

  if (validation.passed) {
    return (
      <div className="flex items-center gap-3 rounded-[16px] border border-mint/30 bg-mint-soft px-4 py-3">
        <Icon name="check" size={18} className="text-[#1C7A47]" />
        <div className="text-[13px] font-semibold text-[#1C7A47]">
          Lesson validated — all {validation.total} key points are taught.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-[16px] border border-amber/40 bg-amber-soft px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 text-[13px] font-semibold text-[#8A6800]">
          <Icon name="bell" size={16} />
          {validation.covered} of {validation.total} key points are taught —{' '}
          {validation.gaps.length}{' '}
          {validation.gaps.length === 1 ? 'gap' : 'gaps'} to fix.
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex-shrink-0 text-[12px] font-semibold text-[#8A6800] underline-offset-2 hover:underline"
        >
          {open ? 'Hide' : 'Show gaps'}
        </button>
      </div>
      {open && validation.gaps.length > 0 && (
        <ul className="mt-2.5 space-y-2 border-t border-amber/30 pt-2.5">
          {validation.gaps.map((g, i) => (
            <li key={i} className="text-[12px] text-[#7A5C00]">
              <span className="font-bold uppercase tracking-[0.06em]">
                {g.verdict}
              </span>{' '}
              — {g.key_point}
              <div className="text-[#9A7C20]">{g.detail}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StepCard({
  index,
  step,
  busy,
  onSave,
}: {
  index: number;
  step: Step;
  busy: boolean;
  onSave: (patch: { tts: string; html: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [tts, setTts] = useState(step.tts);
  const [html, setHtml] = useState(step.html);

  const save = () => {
    onSave({ tts: tts.trim(), html: html.trim() });
    setEditing(false);
  };

  return (
    <div className="border-b border-border px-5 py-3.5 last:border-b-0">
      <div className="flex items-start gap-3.5">
        <div className="mt-0.5 grid h-7 w-7 flex-shrink-0 place-items-center rounded-lg bg-paper-2 font-display text-[12px] font-bold text-ink-3">
          {index}
        </div>
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="space-y-2">
              <label className="block">
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.1em] text-ink-3">
                  Aria says (spoken)
                </span>
                <textarea
                  value={tts}
                  onChange={(e) => setTts(e.target.value)}
                  rows={2}
                  className="w-full resize-y rounded-lg border border-border-2 bg-paper px-3 py-2 text-[13px] text-ink outline-none transition focus:border-indigo focus:bg-white"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.1em] text-ink-3">
                  On screen (teleprompter HTML)
                </span>
                <textarea
                  value={html}
                  onChange={(e) => setHtml(e.target.value)}
                  rows={2}
                  className="w-full resize-y rounded-lg border border-border-2 bg-paper px-3 py-2 font-mono text-[12px] text-ink outline-none transition focus:border-indigo focus:bg-white"
                />
              </label>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setTts(step.tts);
                    setHtml(step.html);
                    setEditing(false);
                  }}
                  disabled={busy}
                  className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={save}
                  disabled={busy}
                  className="rounded-lg bg-indigo px-3 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
                >
                  {busy ? 'Saving…' : 'Save step'}
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-[13px] leading-[1.5] text-ink">{step.tts}</p>
              <p className="mt-0.5 font-mono text-[11px] leading-[1.5] text-ink-3">
                {step.html}
              </p>
            </>
          )}
        </div>
        {!editing && (
          <div className="flex flex-shrink-0 items-center gap-1.5">
            <span className="rounded-md bg-paper-2 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-ink-3">
              {step.dur}
            </span>
            <span
              className={cn(
                'rounded-md px-1.5 py-0.5 text-[10px] font-semibold',
                step.page
                  ? 'bg-indigo-soft text-indigo'
                  : 'bg-paper-2 text-ink-3',
              )}
            >
              {step.page ? 'slide' : 'board'}
            </span>
            <button
              type="button"
              onClick={() => {
                setTts(step.tts);
                setHtml(step.html);
                setEditing(true);
              }}
              aria-label={`Edit step ${index}`}
              className="rounded-lg px-2.5 py-1 text-[12px] font-semibold text-indigo transition-colors hover:bg-indigo-soft"
            >
              Edit
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function VersionRow({
  version,
  busy,
  onActivate,
  onDelete,
}: {
  version: Version;
  busy: boolean;
  onActivate: () => void;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const v = version;
  const valid = v.validation?.passed === true;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0">
      <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 font-display text-[12px] font-bold text-ink-2">
        {v.label}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink">{v.label}</span>
          {v.active && (
            <span className="rounded-full bg-indigo-soft px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-indigo">
              Live
            </span>
          )}
          {v.validation && (
            <span
              className={cn(
                'rounded-full px-2 py-0.5 text-[10px] font-bold',
                valid
                  ? 'bg-mint-soft text-[#1C7A47]'
                  : 'bg-amber-soft text-[#8A6800]',
              )}
            >
              {valid
                ? 'validated'
                : `${v.validation.covered}/${v.validation.total} covered`}
            </span>
          )}
        </div>
        <div className="text-xs text-ink-3">
          generated {shortDateTime(v.created_at)}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {!v.active && (
          <button
            type="button"
            onClick={onActivate}
            disabled={busy}
            className="rounded-lg border border-border-2 px-3 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:border-indigo hover:bg-indigo-soft hover:text-indigo disabled:opacity-40"
          >
            Make live
          </button>
        )}
        {!v.active &&
          (confirming ? (
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={onDelete}
                disabled={busy}
                className="rounded-lg bg-coral px-3 py-1.5 text-[12px] font-semibold text-white transition-colors hover:brightness-95 disabled:opacity-50"
              >
                Delete
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={busy}
                className="rounded-lg px-2.5 py-1.5 text-[12px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label={`Delete ${v.label}`}
              className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-coral-soft hover:text-coral"
            >
              <Icon name="close" size={14} />
            </button>
          ))}
      </div>
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
            className="h-20 animate-soft-pulse rounded-[20px] border border-border bg-white shadow-sm"
          />
        ))}
      </div>
    </div>
  );
}

function NotFoundScreen({ courseId }: { courseId: string }) {
  return (
    <div className="grid min-h-full place-items-center bg-paper px-8">
      <div className="flex flex-col items-center text-center">
        <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-paper-2 text-ink-3">
          <Icon name="course" size={24} />
        </div>
        <div className="font-display text-[18px] font-bold">
          Topic not found
        </div>
        <div className="mt-1 text-[13px] text-ink-3">
          This topic doesn&apos;t exist, or it isn&apos;t one of yours.
        </div>
        <Link
          href={`/teach/courses/${courseId}`}
          className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
        >
          <Icon name="prev" size={15} /> Back to the course
        </Link>
      </div>
    </div>
  );
}
