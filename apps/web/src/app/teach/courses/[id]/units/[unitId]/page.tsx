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

interface UnitDetail {
  id: string;
  name: string;
  course_id: string;
  course_title: string;
  materials: Material[];
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
