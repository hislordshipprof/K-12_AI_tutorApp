'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useRef, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { api, ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Unit detail (`/teach/courses/[id]/units/[unitId]`) — material upload (3.3).
 *
 * Loads `GET /v1/teacher/units/{id}` and drives the `POST .../materials`
 * upload, which runs the §6 ingest → normalize-to-PDF pipeline. The
 * segment job + the confirm-breakdown screen that follow are task 3.4.
 */

type ConversionStatus = 'pending' | 'converting' | 'converted' | 'failed';

interface Material {
  id: string;
  filename: string;
  kind: string | null;
  status: ConversionStatus;
}

interface SegmentJob {
  id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  stage: string | null;
}

interface TopicLite {
  id: string;
  n: number;
  name: string;
  status: 'draft' | 'published';
}

interface UnitDetail {
  id: string;
  name: string;
  course_id: string;
  course_title: string;
  materials: Material[];
  segment_job: SegmentJob | null;
  topics: TopicLite[];
}

interface StagedFile {
  id: string;
  file: File;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UnitDetailPage() {
  const params = useParams();
  const unitId = String(params.unitId ?? '');
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<UnitDetail>({
    queryKey: ['teacher-unit', unitId],
    queryFn: () => api<UnitDetail>(`/v1/teacher/units/${unitId}`),
    enabled: unitId.length > 0,
    // While a segment job is in flight, poll so the breakdown panel
    // advances converting → comprehending → done without a manual refresh.
    refetchInterval: (query) => {
      const s = query.state.data?.segment_job?.status;
      return s === 'queued' || s === 'running' ? 2500 : false;
    },
  });

  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadMut = useMutation({
    mutationFn: (files: StagedFile[]) => {
      const fd = new FormData();
      for (const f of files) fd.append('files', f.file);
      return api<Material[]>(`/v1/teacher/units/${unitId}/materials`, {
        method: 'POST',
        body: fd,
      });
    },
    onSuccess: () => {
      setStaged([]);
      queryClient.invalidateQueries({ queryKey: ['teacher-unit', unitId] });
    },
  });

  const stage = (files: FileList | null) => {
    if (!files) return;
    const next = Array.from(files).map((file) => ({
      id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 8)}`,
      file,
    }));
    setStaged((s) => [...s, ...next]);
  };

  const unstage = (id: string) =>
    setStaged((s) => s.filter((f) => f.id !== id));

  const upload = () => {
    if (staged.length === 0 || uploadMut.isPending) return;
    uploadMut.mutate(staged);
  };

  if (isLoading) return <LoadingScreen />;
  if (isError || !data) return <NotFoundScreen />;

  const materials = data.materials;
  const uploadError =
    uploadMut.error instanceof ApiError
      ? uploadMut.error.message
      : uploadMut.isError
        ? 'Upload failed — please try again.'
        : null;

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
            href={`/teach/courses/${data.course_id}`}
            className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/55 transition-colors hover:text-white"
          >
            <Icon name="prev" size={14} /> {data.course_title}
          </Link>
          <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
            {data.name}
          </h1>
          <div className="mt-1 text-sm text-white/55">
            Upload this unit&apos;s material — notes, slide decks, worksheets.
          </div>
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-12 px-8 pb-16 pt-9">
        {/* UPLOAD */}
        <section>
          <SectHd
            title="Add material"
            sub="Drop in one or more files, review the list, then upload."
          />

          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              stage(e.dataTransfer.files);
            }}
            className={cn(
              'flex w-full flex-col items-center rounded-[20px] border-2 border-dashed px-6 py-10 text-center transition-colors',
              dragging
                ? 'border-indigo bg-indigo-soft'
                : 'border-border-2 bg-white/60 hover:border-indigo hover:bg-white',
            )}
          >
            <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-indigo-soft text-indigo">
              <Icon name="download" size={24} />
            </div>
            <div className="font-display text-[15px] font-bold text-ink">
              Drop files here, or click to browse
            </div>
            <div className="mt-1 text-[12px] text-ink-3">
              PDF, PowerPoint, or Word — one or many.
            </div>
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.ppt,.pptx,.doc,.docx"
            className="hidden"
            onChange={(e) => {
              stage(e.target.files);
              e.target.value = '';
            }}
          />

          {/* Staged files — not yet uploaded */}
          {staged.length > 0 && (
            <div className="mt-3.5 rounded-[20px] border border-border bg-white p-4 shadow-sm">
              <div className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-ink-3">
                Ready to upload ({staged.length})
              </div>
              {staged.map((f) => (
                <div
                  key={f.id}
                  className="flex items-center gap-3 border-b border-border py-2.5 last:border-b-0"
                >
                  <Icon name="notes" size={16} className="text-ink-3" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink">
                      {f.file.name}
                    </div>
                    <div className="text-xs text-ink-3">
                      {fmtSize(f.file.size)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => unstage(f.id)}
                    disabled={uploadMut.isPending}
                    aria-label={`Remove ${f.file.name}`}
                    className="grid h-7 w-7 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
              ))}
              {uploadError && (
                <div className="mt-3 rounded-xl bg-coral-soft px-3.5 py-2.5 text-[12px] font-medium text-coral">
                  {uploadError}
                </div>
              )}
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={upload}
                  disabled={uploadMut.isPending}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
                >
                  <Icon name="download" size={15} />
                  {uploadMut.isPending
                    ? 'Uploading…'
                    : `Upload ${staged.length} ${staged.length === 1 ? 'file' : 'files'}`}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* MATERIALS */}
        <section>
          <SectHd
            title="Materials"
            sub={`${materials.length} ${materials.length === 1 ? 'file' : 'files'} in this unit`}
          />
          {materials.length > 0 ? (
            <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
              {materials.map((m) => (
                <div
                  key={m.id}
                  className="flex items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0"
                >
                  <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
                    <Icon name="notes" size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-ink">
                      {m.filename}
                    </div>
                    {m.kind && (
                      <div className="text-xs capitalize text-ink-3">
                        {m.kind}
                      </div>
                    )}
                  </div>
                  <StatusBadge status={m.status} />
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-[20px] border border-dashed border-border-2 bg-white/60 px-5 py-6 text-[13px] text-ink-3">
              <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
                <Icon name="notes" size={18} />
              </div>
              No material yet — upload this unit&apos;s files above.
            </div>
          )}
        </section>

        {/* TOPIC BREAKDOWN */}
        <section>
          <SectHd
            title="Topic breakdown"
            sub="The model reads your material and proposes a set of topics — you review and confirm them."
          />
          <BreakdownPanel
            courseId={data.course_id}
            unitId={unitId}
            materialCount={materials.length}
            segmentJob={data.segment_job}
          />
        </section>

        {/* TOPICS */}
        {(data.topics ?? []).length > 0 && (
          <section>
            <SectHd
              title="Topics"
              sub={`${(data.topics ?? []).length} ${(data.topics ?? []).length === 1 ? 'topic' : 'topics'} — generate and publish each one's lesson.`}
            />
            <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
              {(data.topics ?? []).map((t) => (
                <Link
                  key={t.id}
                  href={`/teach/courses/${data.course_id}/topics/${t.id}`}
                  className="flex items-center gap-4 border-b border-border px-5 py-4 transition-colors last:border-b-0 hover:bg-paper-2"
                >
                  <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft font-display text-sm font-bold text-indigo">
                    {t.n}
                  </div>
                  <div className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">
                    {t.name}
                  </div>
                  <span
                    className={cn(
                      'rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em]',
                      t.status === 'published'
                        ? 'bg-mint-soft text-[#1C7A47]'
                        : 'bg-paper-2 text-ink-3',
                    )}
                  >
                    {t.status}
                  </span>
                  <Icon name="chev" size={16} className="text-ink-3" />
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/* ─── topic-breakdown panel (task 3.4) ──────────────────────────────────────── */

function BreakdownPanel({
  courseId,
  unitId,
  materialCount,
  segmentJob,
}: {
  courseId: string;
  unitId: string;
  materialCount: number;
  segmentJob: SegmentJob | null;
}) {
  const queryClient = useQueryClient();

  const startMut = useMutation({
    mutationFn: () =>
      api(`/v1/teacher/units/${unitId}/segment`, { method: 'POST' }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['teacher-unit', unitId] }),
  });

  if (materialCount === 0) {
    return (
      <div className="flex items-center gap-3 rounded-[20px] border border-dashed border-border-2 bg-white/60 px-5 py-6 text-[13px] text-ink-3">
        <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
          <Icon name="course" size={18} />
        </div>
        Upload this unit&apos;s material first — then generate the breakdown.
      </div>
    );
  }

  const status = segmentJob?.status ?? null;

  if (status === 'queued' || status === 'running') {
    const activeStage =
      segmentJob?.stage === 'comprehending' ? 'comprehending' : 'converting';
    return <SegmentProgress activeStage={activeStage} />;
  }

  if (status === 'succeeded') {
    return (
      <div className="flex flex-wrap items-center gap-4 rounded-[20px] border border-border bg-white p-5 shadow-sm">
        <div className="grid h-12 w-12 flex-shrink-0 place-items-center rounded-2xl bg-mint-soft text-[#1C7A47]">
          <Icon name="check" size={24} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-display text-[15px] font-bold text-ink">
            Breakdown ready
          </div>
          <div className="mt-0.5 text-[13px] text-ink-3">
            The model proposed a set of topics from your material. Review,
            edit, and confirm them to create the lessons.
          </div>
        </div>
        <Link
          href={`/teach/courses/${courseId}/units/${unitId}/breakdown`}
          className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
        >
          Review breakdown <Icon name="chev" size={15} />
        </Link>
      </div>
    );
  }

  if (status === 'failed') {
    return (
      <div className="rounded-[20px] border border-coral/30 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <div className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl bg-coral-soft text-coral">
            <Icon name="close" size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-ink">
              Segmentation didn&apos;t finish
            </div>
            <div className="text-[13px] text-ink-3">
              Something went wrong reading the material. Try again.
            </div>
          </div>
          <button
            type="button"
            onClick={() => startMut.mutate()}
            disabled={startMut.isPending}
            className="rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
          >
            {startMut.isPending ? 'Starting…' : 'Try again'}
          </button>
        </div>
      </div>
    );
  }

  // idle — material uploaded, no segment job yet.
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-[20px] border border-border bg-white p-5 shadow-sm">
      <div className="grid h-12 w-12 flex-shrink-0 place-items-center rounded-2xl bg-indigo-soft text-indigo">
        <Icon name="course" size={24} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-display text-[15px] font-bold text-ink">
          Generate the topic breakdown
        </div>
        <div className="mt-0.5 text-[13px] text-ink-3">
          When you&apos;ve added every file for this unit, the model reads
          them and proposes the topics. This takes a couple of minutes.
        </div>
        {startMut.isError && (
          <div className="mt-1.5 text-[12px] font-medium text-coral">
            Couldn&apos;t start segmentation — please try again.
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => startMut.mutate()}
        disabled={startMut.isPending}
        className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:opacity-50"
      >
        <Icon name="plus" size={15} />
        {startMut.isPending ? 'Starting…' : 'Generate breakdown'}
      </button>
    </div>
  );
}

function SegmentProgress({
  activeStage,
}: {
  activeStage: 'converting' | 'comprehending';
}) {
  const steps: { key: 'converting' | 'comprehending'; label: string }[] = [
    { key: 'converting', label: 'Preparing material' },
    { key: 'comprehending', label: 'Reading & proposing topics' },
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
            Generating the topic breakdown…
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

/* ─── helpers ──────────────────────────────────────────────────────────────── */

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

function StatusBadge({ status }: { status: ConversionStatus }) {
  const map: Record<ConversionStatus, { label: string; cls: string }> = {
    pending: { label: 'Pending', cls: 'bg-paper-2 text-ink-3' },
    converting: { label: 'Converting…', cls: 'bg-amber-soft text-[#8A6800]' },
    converted: { label: 'Ready', cls: 'bg-mint-soft text-[#1C7A47]' },
    failed: { label: 'Failed', cls: 'bg-coral-soft text-coral' },
  };
  const { label, cls } = map[status];
  return (
    <span
      className={cn(
        'rounded-full px-2.5 py-1 text-[11px] font-bold',
        cls,
      )}
    >
      {label}
    </span>
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
          <Icon name="notes" size={24} />
        </div>
        <div className="font-display text-[18px] font-bold">Unit not found</div>
        <div className="mt-1 text-[13px] text-ink-3">
          This unit doesn&apos;t exist, or it isn&apos;t one of yours.
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
