'use client';

import { useMutation } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';

/** Grade bands a teacher course can target (teacher-authoring.md §4). */
const GRADE_BANDS = ['K-2', '3-5', '6-8', '9-12'] as const;

/** The `courses` row shape returned by `POST /v1/teacher/courses`. */
export interface CreatedCourse {
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

export interface CreateCourseModalProps {
  open: boolean;
  onClose: () => void;
  /** Called with the freshly-created course once the backend has made it. */
  onCreated: (course: CreatedCourse) => void;
}

/**
 * Create-course dialog (task 3.3).
 *
 * A teacher names a course and sets its subject + grade band;
 * `POST /v1/teacher/courses` creates the `courses` row (`origin='teacher'`,
 * `owner_id` = the teacher). The teaching-style paragraph — which
 * parameterises Aria's persona — is set afterward on the course page
 * (teacher-authoring.md §5, two-step flow).
 */
export function CreateCourseModal({
  open,
  onClose,
  onCreated,
}: CreateCourseModalProps) {
  const [title, setTitle] = useState('');
  const [subject, setSubject] = useState('');
  const [gradeBand, setGradeBand] = useState('');

  const createMut = useMutation({
    mutationFn: (input: {
      title: string;
      subject: string;
      grade_band: string;
    }) =>
      api<CreatedCourse>('/v1/teacher/courses', {
        method: 'POST',
        json: input,
      }),
    onSuccess: (course) => onCreated(course),
  });

  // Reset the form each time the dialog opens.
  useEffect(() => {
    if (open) {
      setTitle('');
      setSubject('');
      setGradeBand('');
      createMut.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Esc closes the dialog (unless a create is in flight).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !createMut.isPending) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, createMut.isPending]);

  if (!open) return null;

  const canCreate = title.trim().length > 0 && !createMut.isPending;
  const submit = () => {
    if (title.trim().length === 0 || createMut.isPending) return;
    createMut.mutate({
      title: title.trim(),
      subject: subject.trim(),
      grade_band: gradeBand,
    });
  };

  const fieldClass =
    'w-full rounded-xl border border-border-2 bg-paper px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-muted focus:border-indigo focus:bg-white focus:ring-2 focus:ring-indigo/15';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm animate-fade-in"
      onClick={() => !createMut.isPending && onClose()}
      role="presentation"
    >
      <div
        className="w-full max-w-[420px] rounded-[22px] bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="New course"
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="font-display text-[20px] font-bold tracking-[-0.02em]">
              New course
            </div>
            <div className="mt-0.5 text-[13px] text-ink-3">
              You can set your teaching style on the course page next.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            disabled={createMut.isPending}
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label className="mb-4 block">
            <span className="mb-1.5 block text-[12px] font-semibold text-ink-2">
              Course title
            </span>
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. AP Physics 1"
              className={fieldClass}
            />
          </label>
          <label className="mb-4 block">
            <span className="mb-1.5 block text-[12px] font-semibold text-ink-2">
              Subject
            </span>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="e.g. Physics"
              className={fieldClass}
            />
          </label>
          <label className="mb-6 block">
            <span className="mb-1.5 block text-[12px] font-semibold text-ink-2">
              Grade band
            </span>
            <select
              value={gradeBand}
              onChange={(e) => setGradeBand(e.target.value)}
              className={fieldClass}
            >
              <option value="">Select a grade band…</option>
              {GRADE_BANDS.map((g) => (
                <option key={g} value={g}>
                  Grades {g}
                </option>
              ))}
            </select>
          </label>

          {createMut.isError && (
            <div className="mb-4 rounded-xl bg-coral-soft px-3.5 py-2.5 text-[12px] font-medium text-coral">
              Couldn&apos;t create the course. Please try again.
            </div>
          )}

          <div className="flex justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              disabled={createMut.isPending}
              className="rounded-xl px-4 py-2.5 text-sm font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canCreate}
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Icon name="plus" size={15} />
              {createMut.isPending ? 'Creating…' : 'Create course'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
