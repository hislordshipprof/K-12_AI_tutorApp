'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { ApiError, api } from '@/lib/api';

/** The shape returned by `POST /v1/classes/join`. */
interface JoinResult {
  class_id: string;
  class_name: string | null;
  status: 'pending' | 'active';
}

export interface JoinClassModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Join-a-class dialog (task 4.2).
 *
 * A student enters a class join code; `POST /v1/classes/join` lands a
 * `pending` `class_members` row that the teacher then approves (the §14
 * consent checkpoint). On success the dashboard course list is refetched
 * so the class appears as "Awaiting approval" until that approval lands
 * (teacher-authoring.md §8).
 */
export function JoinClassModal({ open, onClose }: JoinClassModalProps) {
  const [code, setCode] = useState('');
  const queryClient = useQueryClient();

  const joinMut = useMutation({
    mutationFn: (joinCode: string) =>
      api<JoinResult>('/v1/classes/join', {
        method: 'POST',
        json: { join_code: joinCode },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard-courses'] });
    },
  });

  // Reset the form each time the dialog opens.
  useEffect(() => {
    if (open) {
      setCode('');
      joinMut.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Esc closes the dialog (unless a join is in flight).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !joinMut.isPending) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, joinMut.isPending]);

  if (!open) return null;

  const canJoin = code.trim().length > 0 && !joinMut.isPending;
  const submit = () => {
    if (code.trim().length === 0 || joinMut.isPending) return;
    joinMut.mutate(code.trim().toUpperCase());
  };

  const fieldClass =
    'w-full rounded-xl border border-border-2 bg-paper px-3.5 py-2.5 text-sm font-semibold tracking-[0.06em] text-ink outline-none transition placeholder:font-normal placeholder:tracking-normal placeholder:text-muted focus:border-indigo focus:bg-white focus:ring-2 focus:ring-indigo/15';

  const errMessage =
    joinMut.error instanceof ApiError && joinMut.error.status === 404
      ? "We couldn't find a class with that code. Check it and try again."
      : "Couldn't join the class. Please try again.";

  const result = joinMut.data;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm animate-fade-in"
      onClick={() => !joinMut.isPending && onClose()}
      role="presentation"
    >
      <div
        className="w-full max-w-[420px] rounded-[22px] bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Join a class"
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="font-display text-[20px] font-bold tracking-[-0.02em]">
              Join a class
            </div>
            <div className="mt-0.5 text-[13px] text-ink-3">
              Enter the code your teacher gave you.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            disabled={joinMut.isPending}
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        {result ? (
          <div>
            <div className="mb-4 rounded-xl bg-mint-soft px-3.5 py-3 text-[13px] text-[#1C7A47]">
              {result.status === 'active' ? (
                <>
                  You&apos;re already in{' '}
                  <b className="font-semibold">
                    {result.class_name ?? 'this class'}
                  </b>
                  . Its courses are on your dashboard.
                </>
              ) : (
                <>
                  Request sent to{' '}
                  <b className="font-semibold">
                    {result.class_name ?? 'the class'}
                  </b>
                  . Your teacher needs to approve you — the class&apos;s
                  courses appear once they do.
                </>
              )}
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <label className="mb-5 block">
              <span className="mb-1.5 block text-[12px] font-semibold text-ink-2">
                Class code
              </span>
              <input
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="e.g. PHYS-7K2M"
                className={fieldClass}
              />
            </label>

            {joinMut.isError && (
              <div className="mb-4 rounded-xl bg-coral-soft px-3.5 py-2.5 text-[12px] font-medium text-coral">
                {errMessage}
              </div>
            )}

            <div className="flex justify-end gap-2.5">
              <button
                type="button"
                onClick={onClose}
                disabled={joinMut.isPending}
                className="rounded-xl px-4 py-2.5 text-sm font-semibold text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canJoin}
                className="inline-flex items-center gap-1.5 rounded-xl bg-indigo px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-deep disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Icon name="plus" size={15} />
                {joinMut.isPending ? 'Joining…' : 'Join class'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
