'use client';

import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useAuth } from '@/components/auth-provider';
import { api, ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

export interface AccountMenuProps {
  /** Display name for the avatar bubble (two initials are derived from it). */
  name?: string;
  /** Switch to the dark chalkboard variant used in classroom screens. */
  dark?: boolean;
}

/**
 * Avatar bubble + dropdown account menu.
 *
 * Shows the signed-in user's email and a sign-out control. When there is no
 * authenticated session the bubble links to the sign-in page instead.
 * Replaces the bare avatar button in `TopNav` so every in-app screen has a
 * way to sign out.
 */
export function AccountMenu({ name = 'Guest', dark = false }: AccountMenuProps) {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  // Two-step delete: the menu shows a "Delete account" item; clicking it
  // reveals an explicit confirm/cancel step so deletion is never one click.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close the menu on an outside click or Escape.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
        setConfirmingDelete(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        setConfirmingDelete(false);
      }
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  /** Delete the signed-in user's own account, then sign out. */
  async function handleDeleteAccount() {
    setDeleting(true);
    try {
      // DELETE /v1/me deletes the *caller's* account — the API derives the
      // target from the verified JWT, so this can only ever delete the
      // current user. A 204 means the account + its data are gone.
      await api('/v1/me', { method: 'DELETE' });
      toast.success('Your account has been deleted', {
        description: 'Your data has been removed from EduMind.',
      });
      // The account no longer exists — clear the local session.
      await signOut();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : 'Something went wrong. Please try again.';
      toast.error('Could not delete your account', { description: message });
      setDeleting(false);
      setConfirmingDelete(false);
    }
  }

  const initials = name.slice(0, 2).toUpperCase();

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'grid h-9 w-9 cursor-pointer place-items-center rounded-full border-2 text-[13px] font-bold text-white shadow-md',
          'bg-gradient-to-br from-coral to-amber',
          dark ? 'border-board' : 'border-white',
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${name} — account menu`}
      >
        {initials}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-56 overflow-hidden rounded-2xl border border-border bg-white shadow-lg"
        >
          <div className="border-b border-border-2 px-4 py-3">
            <p className="text-[13px] font-semibold text-ink">{name}</p>
            {user?.email && (
              <p className="mt-0.5 truncate text-[12px] text-ink-3">
                {user.email}
              </p>
            )}
          </div>
          {user ? (
            <>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  setConfirmingDelete(false);
                  void signOut();
                }}
                className="w-full px-4 py-3 text-left text-[13px] font-semibold text-coral transition-colors hover:bg-paper-2"
              >
                Sign out
              </button>

              <div className="border-t border-border-2">
                {!confirmingDelete ? (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => setConfirmingDelete(true)}
                    className="w-full px-4 py-3 text-left text-[13px] font-semibold text-ink-3 transition-colors hover:bg-paper-2"
                  >
                    Delete account
                  </button>
                ) : (
                  <div className="px-4 py-3">
                    <p className="text-[12.5px] font-semibold leading-[1.5] text-ink-2">
                      Delete your account?
                    </p>
                    <p className="mt-1 text-[12px] leading-[1.5] text-ink-3">
                      This permanently removes your profile and learning data.
                      It cannot be undone.
                    </p>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => void handleDeleteAccount()}
                        disabled={deleting}
                        className="flex-1 rounded-lg bg-coral px-3 py-2 text-[12.5px] font-semibold text-white transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {deleting ? 'Deleting…' : 'Delete'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingDelete(false)}
                        disabled={deleting}
                        className="flex-1 rounded-lg border border-border-2 px-3 py-2 text-[12.5px] font-semibold text-ink-2 transition-colors hover:bg-paper-2 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <a
              role="menuitem"
              href="/login"
              className="block w-full px-4 py-3 text-left text-[13px] font-semibold text-indigo transition-colors hover:bg-paper-2"
            >
              Sign in
            </a>
          )}
        </div>
      )}
    </div>
  );
}
