'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Confirm-the-breakdown screen (task 3.4) —
 * `/teach/courses/[id]/units/[unitId]/breakdown`.
 *
 * After the segment job finishes, the teacher reviews the model's PROPOSED
 * topic breakdown: rename / merge / split / reorder / drop topics, and
 * re-include any teaching page the model wrongly excluded (teacher-
 * authoring.md §5.7 — "the model proposes, the teacher disposes"). On
 * Confirm, `POST .../topics` materialises `topics` + `topic_pages` rows.
 *
 * Loads `GET /v1/teacher/units/{id}/segmentation`; the edits are local
 * until Confirm, which posts the final topic list.
 */

interface PageRef {
  material_idx: number;
  page_idx: number;
}

interface ServerTopic {
  title: string;
  summary: string;
  key_points: string[];
  pages: PageRef[];
}

interface Topic extends ServerTopic {
  /** Client-side id — stable across edits, not the DB id. */
  cid: string;
}

interface ExcludedPage {
  material_idx: number;
  page_idx: number;
  reason: string;
}

interface SegMaterial {
  idx: number;
  filename: string;
}

interface SegmentationData {
  status: string;
  topics: ServerTopic[];
  excluded: ExcludedPage[];
  materials: SegMaterial[];
  empty_reason: string | null;
}

/** An existing `topics` row of the unit (from `GET /v1/teacher/units/{id}`). */
interface ExistingTopic {
  id: string;
  n: number;
  name: string;
  status: string;
}

interface UnitDetail {
  topics: ExistingTopic[];
}

/** A proposed topic's mapping decision in the re-segmentation flow. */
interface Decision {
  action: 'add' | 'replace';
  topicId?: string;
}

let _cid = 0;
const cid = () => `t${(_cid += 1)}`;

function pageLabel(p: PageRef, materials: SegMaterial[]): string {
  const m = materials.find((x) => x.idx === p.material_idx);
  const short = (m?.filename ?? `Material ${p.material_idx + 1}`).replace(
    /\.[^.]+$/,
    '',
  );
  return `${short} · p.${p.page_idx + 1}`;
}

export default function BreakdownPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = String(params.id ?? '');
  const unitId = String(params.unitId ?? '');

  const { data, isLoading, isError } = useQuery<SegmentationData>({
    queryKey: ['unit-segmentation', unitId],
    queryFn: () => api<SegmentationData>(`/v1/teacher/units/${unitId}/segmentation`),
    enabled: unitId.length > 0,
  });

  // The unit's EXISTING topics — if it already has any, confirming the
  // breakdown means a §13 re-segmentation (the teacher maps the new
  // breakdown onto the current topics) rather than a first-time confirm.
  const { data: unitDetail, isLoading: unitLoading } = useQuery<UnitDetail>({
    queryKey: ['teacher-unit', unitId],
    queryFn: () => api<UnitDetail>(`/v1/teacher/units/${unitId}`),
    enabled: unitId.length > 0,
  });

  const [topics, setTopics] = useState<Topic[]>([]);
  const [excluded, setExcluded] = useState<ExcludedPage[]>([]);
  const [ready, setReady] = useState(false);

  // Seed the editable local state once, from the loaded segmentation.
  useEffect(() => {
    if (data && !ready) {
      setTopics(
        (data.topics ?? []).map((t) => ({
          cid: cid(),
          title: t.title,
          summary: t.summary,
          key_points: t.key_points ?? [],
          pages: t.pages ?? [],
        })),
      );
      setExcluded(data.excluded ?? []);
      setReady(true);
    }
  }, [data, ready]);

  const confirmMut = useMutation({
    mutationFn: (ts: Topic[]) =>
      api(`/v1/teacher/units/${unitId}/topics`, {
        method: 'POST',
        json: {
          topics: ts.map((t) => ({
            title: t.title,
            summary: t.summary,
            key_points: t.key_points,
            pages: t.pages,
          })),
        },
      }),
    onSuccess: () =>
      router.push(`/teach/courses/${courseId}/units/${unitId}`),
  });

  const totalPages = useMemo(
    () => topics.reduce((n, t) => n + t.pages.length, 0),
    [topics],
  );

  const rename = (c: string, title: string) =>
    setTopics((ts) => ts.map((t) => (t.cid === c ? { ...t, title } : t)));

  const editSummary = (c: string, summary: string) =>
    setTopics((ts) => ts.map((t) => (t.cid === c ? { ...t, summary } : t)));

  const drop = (c: string) => setTopics((ts) => ts.filter((t) => t.cid !== c));

  const move = (i: number, dir: -1 | 1) =>
    setTopics((ts) => {
      const j = i + dir;
      if (j < 0 || j >= ts.length) return ts;
      const next = [...ts];
      [next[i], next[j]] = [next[j]!, next[i]!];
      return next;
    });

  // Merge topic i into topic i+1's slot — one beat the model over-split.
  const mergeDown = (i: number) =>
    setTopics((ts) => {
      if (i >= ts.length - 1) return ts;
      const a = ts[i]!;
      const b = ts[i + 1]!;
      const merged: Topic = {
        cid: a.cid,
        title: a.title,
        summary: `${a.summary} ${b.summary}`.trim(),
        key_points: [...a.key_points, ...b.key_points],
        pages: [...a.pages, ...b.pages],
      };
      return [...ts.slice(0, i), merged, ...ts.slice(i + 2)];
    });

  // Split topic i in two — the page set + key points halved; teacher renames.
  const split = (i: number) =>
    setTopics((ts) => {
      const t = ts[i]!;
      const pmid = Math.ceil(t.pages.length / 2);
      const kmid = Math.ceil(t.key_points.length / 2);
      const first: Topic = {
        ...t,
        title: `${t.title} (part 1)`,
        key_points: t.key_points.slice(0, kmid),
        pages: t.pages.slice(0, pmid),
      };
      const second: Topic = {
        cid: cid(),
        title: `${t.title} (part 2)`,
        summary: t.summary,
        key_points: t.key_points.slice(kmid),
        pages: t.pages.slice(pmid),
      };
      return [...ts.slice(0, i), first, second, ...ts.slice(i + 1)];
    });

  const reinclude = (page: ExcludedPage, topicCid: string) => {
    setTopics((ts) =>
      ts.map((t) =>
        t.cid === topicCid
          ? {
              ...t,
              pages: [
                ...t.pages,
                { material_idx: page.material_idx, page_idx: page.page_idx },
              ],
            }
          : t,
      ),
    );
    setExcluded((xs) =>
      xs.filter(
        (x) =>
          !(
            x.material_idx === page.material_idx &&
            x.page_idx === page.page_idx
          ),
      ),
    );
  };

  if (isLoading || unitLoading || (data && !ready)) return <LoadingScreen />;
  if (isError || !data) {
    return <NotFoundScreen courseId={courseId} unitId={unitId} />;
  }

  // A unit that already has topics → the §13 re-segmentation mapping flow.
  const existingTopics = unitDetail?.topics ?? [];
  if (existingTopics.length > 0) {
    return (
      <ResegmentView
        courseId={courseId}
        unitId={unitId}
        proposed={data.topics ?? []}
        materials={data.materials ?? []}
        existing={existingTopics}
        emptyReason={data.empty_reason}
      />
    );
  }

  const materials = data.materials ?? [];

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
            href={`/teach/courses/${courseId}/units/${unitId}`}
            className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/55 transition-colors hover:text-white"
          >
            <Icon name="prev" size={14} /> Back to unit
          </Link>
          <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
            Review topic breakdown
          </h1>
          <div className="mt-1 max-w-[640px] text-sm text-white/55">
            The model read your material and proposed these topics. Rename,
            merge, split, reorder, or drop them — and re-include any page it
            set aside by mistake — then confirm.
          </div>
          <div className="mt-4 flex flex-wrap gap-2.5">
            <StatChip n={topics.length} label={topics.length === 1 ? 'Topic' : 'Topics'} />
            <StatChip n={totalPages} label="Slide pages" />
            <StatChip
              n={excluded.length}
              label="Excluded"
              tone={excluded.length > 0 ? 'amber' : 'plain'}
            />
          </div>
        </div>
      </header>

      {/* ─── BODY ────────────────────────────────────────────────────────── */}
      <div className="mx-auto max-w-[1180px] space-y-12 px-8 pb-32 pt-9">
        {/* PROPOSED TOPICS */}
        <section>
          <SectHd
            title="Proposed topics"
            sub="Each becomes one Aria-narrated lesson once you confirm."
          />
          {topics.length > 0 ? (
            <div className="space-y-3">
              {topics.map((t, i) => (
                <TopicCard
                  key={t.cid}
                  topic={t}
                  index={i}
                  isFirst={i === 0}
                  isLast={i === topics.length - 1}
                  materials={materials}
                  onRename={(v) => rename(t.cid, v)}
                  onEditSummary={(v) => editSummary(t.cid, v)}
                  onUp={() => move(i, -1)}
                  onDown={() => move(i, 1)}
                  onMergeDown={() => mergeDown(i)}
                  onSplit={() => split(i)}
                  onDrop={() => drop(t.cid)}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-[20px] border border-dashed border-border-2 bg-white/60 px-6 py-10 text-center text-[13px] text-ink-3">
              {data.empty_reason
                ? `The model found nothing teachable here — ${data.empty_reason}`
                : 'No topics left — every proposed topic was dropped. Add at least one back before confirming.'}
            </div>
          )}
        </section>

        {/* EXCLUDED PAGES */}
        <section>
          <SectHd
            title="Excluded pages"
            sub="The model set these aside as non-teaching. Re-include any it got wrong."
          />
          {excluded.length > 0 ? (
            <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
              {excluded.map((x) => (
                <ExcludedRow
                  key={`${x.material_idx}-${x.page_idx}`}
                  page={x}
                  topics={topics}
                  materials={materials}
                  onReinclude={(topicCid) => reinclude(x, topicCid)}
                />
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-[20px] border border-dashed border-border-2 bg-white/60 px-5 py-6 text-[13px] text-ink-3">
              <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
                <Icon name="check" size={18} />
              </div>
              No pages excluded — every page is in a topic.
            </div>
          )}
        </section>
      </div>

      {/* ─── CONFIRM BAR ─────────────────────────────────────────────────── */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-4 px-8 py-3.5">
          <div className="text-[13px] text-ink-3">
            {confirmMut.isError ? (
              <span className="font-medium text-coral">
                Couldn&apos;t confirm the breakdown — please try again.
              </span>
            ) : topics.length > 0 ? (
              <>
                Confirming creates{' '}
                <span className="font-semibold text-ink">
                  {topics.length} {topics.length === 1 ? 'topic' : 'topics'}
                </span>{' '}
                — each generates its lesson next.
              </>
            ) : (
              'Keep at least one topic to confirm.'
            )}
          </div>
          <div className="flex items-center gap-2.5">
            <Link
              href={`/teach/courses/${courseId}/units/${unitId}`}
              className="rounded-xl px-4 py-2.5 text-sm font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink"
            >
              Cancel
            </Link>
            <button
              type="button"
              disabled={topics.length === 0 || confirmMut.isPending}
              onClick={() => confirmMut.mutate(topics)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Icon name="check" size={15} />
              {confirmMut.isPending ? 'Confirming…' : 'Confirm breakdown'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── re-segmentation mapping view (task 5.4 · §13) ─────────────────────────── */

/**
 * Shown when the breakdown screen opens for a unit that ALREADY has topics:
 * the teacher maps the new proposed breakdown onto the current topics —
 * each proposed topic is added new or replaces an existing one, and any
 * existing topic the new material no longer covers can be retired. Nothing
 * is auto-deleted (`teacher-authoring.md` §13).
 */
function ResegmentView({
  courseId,
  unitId,
  proposed,
  materials,
  existing,
  emptyReason,
}: {
  courseId: string;
  unitId: string;
  proposed: ServerTopic[];
  materials: SegMaterial[];
  existing: ExistingTopic[];
  emptyReason: string | null;
}) {
  const router = useRouter();

  // One decision per proposed topic — default: add as a brand-new topic.
  const [decisions, setDecisions] = useState<Decision[]>(() =>
    proposed.map(() => ({ action: 'add' as const })),
  );
  const [retired, setRetired] = useState<Set<string>>(new Set());

  // existing topic id -> the proposed index replacing it (at most one).
  const replacedBy = new Map<string, number>();
  decisions.forEach((d, i) => {
    if (d.action === 'replace' && d.topicId) replacedBy.set(d.topicId, i);
  });

  const setDecision = (i: number, d: Decision) =>
    setDecisions((ds) => ds.map((x, j) => (j === i ? d : x)));

  const toggleRetire = (topicId: string) =>
    setRetired((s) => {
      const next = new Set(s);
      if (next.has(topicId)) next.delete(topicId);
      else next.add(topicId);
      return next;
    });

  const applyMut = useMutation({
    mutationFn: () =>
      api(`/v1/teacher/units/${unitId}/resegmentation`, {
        method: 'POST',
        json: {
          decisions: decisions.map((d, i) => ({
            index: i,
            action: d.action,
            topic_id: d.action === 'replace' ? (d.topicId ?? null) : null,
          })),
          retire_topic_ids: [...retired],
        },
      }),
    onSuccess: () =>
      router.push(`/teach/courses/${courseId}/units/${unitId}`),
  });

  // Every "replace" decision must name a target topic before applying.
  const ready =
    proposed.length > 0 &&
    decisions.every((d) => d.action === 'add' || Boolean(d.topicId));

  const added = decisions.filter((d) => d.action === 'add').length;
  const replacing = decisions.filter(
    (d) => d.action === 'replace' && d.topicId,
  ).length;

  return (
    <div className="min-h-full bg-paper">
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
            href={`/teach/courses/${courseId}/units/${unitId}`}
            className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/55 transition-colors hover:text-white"
          >
            <Icon name="prev" size={14} /> Back to unit
          </Link>
          <h1 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
            Re-segment this unit
          </h1>
          <div className="mt-1 max-w-[660px] text-sm text-white/55">
            This unit already has topics. Map the model&apos;s new breakdown
            onto them — add a topic, replace one you have, or retire one the
            new material no longer covers. Nothing is deleted.
          </div>
          <div className="mt-4 flex flex-wrap gap-2.5">
            <StatChip n={proposed.length} label="Proposed" />
            <StatChip n={existing.length} label="Current topics" />
            <StatChip
              n={retired.size}
              label="To retire"
              tone={retired.size > 0 ? 'amber' : 'plain'}
            />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1180px] space-y-12 px-8 pb-32 pt-9">
        <section>
          <SectHd
            title="New breakdown"
            sub="Map each proposed topic — add it as new, or replace one you already have."
          />
          {proposed.length > 0 ? (
            <div className="space-y-3">
              {proposed.map((pt, i) => (
                <ProposedMapCard
                  key={i}
                  index={i}
                  topic={pt}
                  existing={existing}
                  decision={decisions[i]!}
                  isTaken={(tid) => {
                    const owner = replacedBy.get(tid);
                    return owner !== undefined && owner !== i;
                  }}
                  retired={retired}
                  onChange={(d) => setDecision(i, d)}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-[20px] border border-dashed border-border-2 bg-white/60 px-6 py-10 text-center text-[13px] text-ink-3">
              {emptyReason
                ? `The model found nothing teachable here — ${emptyReason}`
                : 'The new breakdown has no topics.'}
            </div>
          )}
        </section>

        <section>
          <SectHd
            title="Your current topics"
            sub="Topics not replaced above are kept as-is. Retire any the new material no longer covers — a retired topic disappears for new students but stays for anyone already mid-lesson."
          />
          <div className="overflow-hidden rounded-[20px] border border-border bg-white shadow-sm">
            {existing.map((t) => (
              <ExistingTopicRow
                key={t.id}
                topic={t}
                replacedByIndex={replacedBy.get(t.id)}
                retiring={retired.has(t.id)}
                onToggleRetire={() => toggleRetire(t.id)}
              />
            ))}
          </div>
        </section>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-4 px-8 py-3.5">
          <div className="text-[13px] text-ink-3">
            {applyMut.isError ? (
              <span className="font-medium text-coral">
                Couldn&apos;t apply the re-segmentation — please try again.
              </span>
            ) : !ready ? (
              'Pick a topic to replace for every "Replace" choice.'
            ) : (
              <>
                <span className="font-semibold text-ink">{added}</span> added
                {' · '}
                <span className="font-semibold text-ink">{replacing}</span>{' '}
                replacing
                {' · '}
                <span className="font-semibold text-ink">
                  {retired.size}
                </span>{' '}
                retired
              </>
            )}
          </div>
          <div className="flex items-center gap-2.5">
            <Link
              href={`/teach/courses/${courseId}/units/${unitId}`}
              className="rounded-xl px-4 py-2.5 text-sm font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink"
            >
              Cancel
            </Link>
            <button
              type="button"
              disabled={!ready || applyMut.isPending}
              onClick={() => applyMut.mutate()}
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Icon name="check" size={15} />
              {applyMut.isPending ? 'Applying…' : 'Apply re-segmentation'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProposedMapCard({
  index,
  topic,
  existing,
  decision,
  isTaken,
  retired,
  onChange,
}: {
  index: number;
  topic: ServerTopic;
  existing: ExistingTopic[];
  decision: Decision;
  /** True when another proposed topic already replaces this existing one. */
  isTaken: (topicId: string) => boolean;
  retired: Set<string>;
  onChange: (d: Decision) => void;
}) {
  const value =
    decision.action === 'add' ? 'add' : `replace:${decision.topicId ?? ''}`;

  return (
    <div className="rounded-[20px] border border-border bg-white p-4 shadow-sm">
      <div className="flex items-start gap-3.5">
        <div className="mt-0.5 grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft font-display text-sm font-bold text-indigo">
          {index + 1}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-display text-[16px] font-bold tracking-[-0.015em] text-ink">
            {topic.title}
          </div>
          <p className="mt-0.5 line-clamp-2 text-[13px] leading-[1.5] text-ink-3">
            {topic.summary}
          </p>
          <div className="mt-2">
            <span className="inline-flex items-center gap-1 rounded-md bg-paper-2 px-2 py-1 text-[11px] font-semibold text-ink-3">
              <Icon name="notes" size={11} />
              {topic.pages.length} slide pages
            </span>
          </div>
        </div>
        <div className="flex flex-shrink-0 flex-col items-end gap-1.5">
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-ink-3">
            This topic will
          </span>
          <select
            value={value}
            aria-label={`Mapping for proposed topic ${index + 1}`}
            onChange={(e) => {
              const v = e.target.value;
              onChange(
                v === 'add'
                  ? { action: 'add' }
                  : { action: 'replace', topicId: v.slice('replace:'.length) },
              );
            }}
            className="rounded-lg border border-border-2 bg-paper px-2.5 py-1.5 text-[13px] font-semibold text-ink outline-none transition focus:border-indigo focus:bg-white"
          >
            <option value="add">Be added as a new topic</option>
            {existing.map((t) => (
              <option
                key={t.id}
                value={`replace:${t.id}`}
                disabled={isTaken(t.id) || retired.has(t.id)}
              >
                Replace: {t.n}. {t.name}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

function ExistingTopicRow({
  topic,
  replacedByIndex,
  retiring,
  onToggleRetire,
}: {
  topic: ExistingTopic;
  replacedByIndex: number | undefined;
  retiring: boolean;
  onToggleRetire: () => void;
}) {
  const isReplaced = replacedByIndex !== undefined;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3.5 last:border-b-0">
      <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 font-display text-[12px] font-bold text-ink-2">
        {topic.n}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink">{topic.name}</span>
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em]',
              topic.status === 'published'
                ? 'bg-mint-soft text-[#1C7A47]'
                : topic.status === 'retired'
                  ? 'bg-paper-2 text-ink-3'
                  : 'bg-indigo-soft text-indigo',
            )}
          >
            {topic.status}
          </span>
        </div>
      </div>
      {isReplaced ? (
        <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-indigo">
          <Icon name="check" size={13} /> Replaced by proposed topic{' '}
          {(replacedByIndex ?? 0) + 1}
        </span>
      ) : retiring ? (
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold text-[#8A6800]">
            Will be retired
          </span>
          <button
            type="button"
            onClick={onToggleRetire}
            className="rounded-lg px-2.5 py-1.5 text-[12px] font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink"
          >
            Undo
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-ink-3">Kept as-is</span>
          <button
            type="button"
            onClick={onToggleRetire}
            className="rounded-lg border border-border-2 px-2.5 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:border-coral hover:bg-coral-soft hover:text-coral"
          >
            Retire
          </button>
        </div>
      )}
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

function TopicCard({
  topic,
  index,
  isFirst,
  isLast,
  materials,
  onRename,
  onEditSummary,
  onUp,
  onDown,
  onMergeDown,
  onSplit,
  onDrop,
}: {
  topic: Topic;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  materials: SegMaterial[];
  onRename: (v: string) => void;
  onEditSummary: (v: string) => void;
  onUp: () => void;
  onDown: () => void;
  onMergeDown: () => void;
  onSplit: () => void;
  onDrop: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-[20px] border border-border bg-white p-4 shadow-sm">
      <div className="flex items-start gap-3.5">
        <div className="mt-0.5 grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-indigo-soft font-display text-sm font-bold text-indigo">
          {index + 1}
        </div>
        <div className="min-w-0 flex-1">
          <input
            value={topic.title}
            onChange={(e) => onRename(e.target.value)}
            aria-label={`Topic ${index + 1} title`}
            className="w-full rounded-lg border border-transparent bg-transparent px-1.5 py-1 font-display text-[16px] font-bold tracking-[-0.015em] text-ink outline-none transition hover:border-border-2 focus:border-indigo focus:bg-paper"
          />
          <p className="mt-0.5 line-clamp-2 px-1.5 text-[13px] leading-[1.5] text-ink-3">
            {topic.summary}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 px-1.5">
            <MetaPill icon="notes" text={`${topic.pages.length} slide pages`} />
            <MetaPill
              icon="check"
              text={`${topic.key_points.length} key points`}
            />
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="text-[12px] font-semibold text-indigo transition-colors hover:text-indigo-deep"
            >
              {open ? 'Hide details' : 'Details'}
            </button>
          </div>
        </div>

        {/* reorder + drop */}
        <div className="flex flex-shrink-0 items-center gap-1">
          <IconBtn label="Move up" icon="prev" rotate={90} disabled={isFirst} onClick={onUp} />
          <IconBtn label="Move down" icon="prev" rotate={-90} disabled={isLast} onClick={onDown} />
          <IconBtn label="Drop topic" icon="close" onClick={onDrop} danger />
        </div>
      </div>

      {open && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          <div>
            <div className="mb-1 px-1.5 text-[11px] font-bold uppercase tracking-[0.1em] text-ink-3">
              Summary
            </div>
            <textarea
              value={topic.summary}
              onChange={(e) => onEditSummary(e.target.value)}
              rows={2}
              className="w-full resize-y rounded-lg border border-border-2 bg-paper px-3 py-2 text-[13px] leading-[1.5] text-ink outline-none transition focus:border-indigo focus:bg-white"
            />
          </div>
          <div>
            <div className="mb-1 px-1.5 text-[11px] font-bold uppercase tracking-[0.1em] text-ink-3">
              Key points
            </div>
            <ul className="space-y-1">
              {topic.key_points.map((k, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 px-1.5 text-[13px] text-ink-2"
                >
                  <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-indigo" />
                  {k}
                </li>
              ))}
              {topic.key_points.length === 0 && (
                <li className="px-1.5 text-[13px] text-ink-3">
                  No key points on this topic.
                </li>
              )}
            </ul>
          </div>
          <div>
            <div className="mb-1 px-1.5 text-[11px] font-bold uppercase tracking-[0.1em] text-ink-3">
              Slide pages
            </div>
            <div className="flex flex-wrap gap-1.5 px-1.5">
              {topic.pages.map((p) => (
                <span
                  key={`${p.material_idx}-${p.page_idx}`}
                  className="rounded-md bg-paper-2 px-2 py-1 text-[11px] font-medium text-ink-3"
                >
                  {pageLabel(p, materials)}
                </span>
              ))}
              {topic.pages.length === 0 && (
                <span className="text-[13px] text-ink-3">
                  No slide pages — this topic plays on the chalkboard.
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* merge / split */}
      <div className="mt-3 flex items-center gap-2 border-t border-border pt-3">
        <CardAction
          icon="plus"
          text="Split"
          onClick={onSplit}
          disabled={topic.pages.length < 2 && topic.key_points.length < 2}
        />
        <CardAction
          icon="chev"
          text="Merge with next"
          onClick={onMergeDown}
          disabled={isLast}
        />
      </div>
    </div>
  );
}

function MetaPill({ icon, text }: { icon: 'notes' | 'check'; text: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-paper-2 px-2 py-1 text-[11px] font-semibold text-ink-3">
      <Icon name={icon} size={11} />
      {text}
    </span>
  );
}

function IconBtn({
  label,
  icon,
  rotate = 0,
  disabled = false,
  danger = false,
  onClick,
}: {
  label: string;
  icon: 'prev' | 'close';
  rotate?: number;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors disabled:opacity-25',
        danger
          ? 'hover:bg-coral-soft hover:text-coral'
          : 'hover:bg-paper-2 hover:text-ink',
      )}
    >
      <span style={{ transform: rotate ? `rotate(${rotate}deg)` : undefined }}>
        <Icon name={icon} size={14} />
      </span>
    </button>
  );
}

function CardAction({
  icon,
  text,
  disabled = false,
  onClick,
}: {
  icon: 'plus' | 'chev';
  text: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-lg border border-border-2 px-2.5 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:border-indigo hover:bg-indigo-soft hover:text-indigo disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-border-2 disabled:hover:bg-transparent disabled:hover:text-ink-2"
    >
      <Icon name={icon} size={12} />
      {text}
    </button>
  );
}

function ExcludedRow({
  page,
  topics,
  materials,
  onReinclude,
}: {
  page: ExcludedPage;
  topics: Topic[];
  materials: SegMaterial[];
  onReinclude: (topicCid: string) => void;
}) {
  const [target, setTarget] = useState('');

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3 last:border-b-0">
      <div className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-xl bg-paper-2 text-ink-3">
        <Icon name="notes" size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ink">
          {pageLabel(page, materials)}
        </div>
        <div className="text-xs text-ink-3">{page.reason}</div>
      </div>
      <div className="flex items-center gap-2">
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          aria-label={`Re-include ${pageLabel(page, materials)} into a topic`}
          className="rounded-lg border border-border-2 bg-paper px-2.5 py-1.5 text-[12px] text-ink outline-none transition focus:border-indigo focus:bg-white"
        >
          <option value="">Re-include into…</option>
          {topics.map((t, i) => (
            <option key={t.cid} value={t.cid}>
              {i + 1}. {t.title}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!target}
          onClick={() => target && onReinclude(target)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo px-3 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-indigo-deep disabled:cursor-not-allowed disabled:opacity-30"
        >
          <Icon name="plus" size={12} /> Re-include
        </button>
      </div>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="min-h-full bg-paper">
      <div className="h-[180px] rounded-b-[28px] bg-[linear-gradient(135deg,#1B1F2E_0%,#2A2E47_100%)]" />
      <div className="mx-auto max-w-[1180px] space-y-3 px-8 pt-9">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-24 animate-soft-pulse rounded-[20px] border border-border bg-white shadow-sm"
          />
        ))}
      </div>
    </div>
  );
}

function NotFoundScreen({
  courseId,
  unitId,
}: {
  courseId: string;
  unitId: string;
}) {
  return (
    <div className="grid min-h-full place-items-center bg-paper px-8">
      <div className="flex flex-col items-center text-center">
        <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-paper-2 text-ink-3">
          <Icon name="course" size={24} />
        </div>
        <div className="font-display text-[18px] font-bold">
          No breakdown yet
        </div>
        <div className="mt-1 max-w-[360px] text-[13px] text-ink-3">
          This unit hasn&apos;t been segmented, or it isn&apos;t one of yours.
          Generate the breakdown from the unit page first.
        </div>
        <Link
          href={`/teach/courses/${courseId}/units/${unitId}`}
          className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
        >
          <Icon name="prev" size={15} /> Back to unit
        </Link>
      </div>
    </div>
  );
}
