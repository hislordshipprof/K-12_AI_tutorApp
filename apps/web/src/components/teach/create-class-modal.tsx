'use client';

import { useMutation } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { api } from '@/lib/api';

/** The `classes` row shape returned by `POST /v1/teacher/classes`. */
export interface CreatedClass {
  id: string;
  name: string;
  subject: string | null;
  join_code: string;
  student_count: number;
  pending_count: number;
}

export interface CreateClassModalProps {
  open: boolean;
  onClose: () => void;
  /** Called with the freshly-created class once the backend has made it. */
  onCreated: (cls: CreatedClass) => void;
}

/**
 * Create-class dialog (task 3.2).
 *
 * A teacher names a class and gives it a subject; `POST /v1/teacher/classes`
 * creates the `classes` row and mints a unique join code. On success the
 * parent navigates to the new class — see `onCreated`.
 */
export function CreateClassModal({
  open,
  onClose,
  onCreated,
}: CreateClassModalProps) {
  const [name, setName] = useState('');
  const [subject, setSubject] = useState('');

  const createMut = useMutation({
    mutationFn: (input: { name: string; subject: string }) =>
      api<CreatedClass>('/v1/teacher/classes', {
        method: 'POST',
        json: input,
      }),
    onSuccess: (cls) => onCreated(cls),
  });

  // Reset the form each time the dialog opens.
  useEffect(() => {
    if (open) {
      setName('');
      setSubject('');
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

  const canCreate = name.trim().length > 0 && !createMut.isPending;
  const submit = () => {
    if (name.trim().length === 0 || createMut.isPending) return;
    createMut.mutate({ name: name.trim(), subject: subject.trim() });
  };

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
        aria-label="New class"
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="font-display text-[20px] font-bold tracking-[-0.02em]">
              New class
            </div>
            <div className="mt-0.5 text-[13px] text-ink-3">
              You&apos;ll get a join code to share with students.
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
              Class name
            </span>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Period 3 — AP Physics"
              className="w-full rounded-xl border border-border-2 bg-paper px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-muted focus:border-indigo focus:bg-white focus:ring-2 focus:ring-indigo/15"
            />
          </label>
          <label className="mb-5 block">
            <span className="mb-1.5 block text-[12px] font-semibold text-ink-2">
              Subject
            </span>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="e.g. Physics"
              className="w-full rounded-xl border border-border-2 bg-paper px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-muted focus:border-indigo focus:bg-white focus:ring-2 focus:ring-indigo/15"
            />
          </label>

          {createMut.isError && (
            <div className="mb-4 rounded-xl bg-coral-soft px-3.5 py-2.5 text-[12px] font-medium text-coral">
              Couldn&apos;t create the class. Please try again.
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
              {createMut.isPending ? 'Creating…' : 'Create class'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
