'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { useAuth } from '@/components/auth-provider';
import { api, ApiError } from '@/lib/api';

/**
 * Redeem a teacher invite code.
 *
 * A signed-in user enters an admin-issued code; on success the API sets
 * their `profiles.role` to `'teacher'`. The route is auth-gated in
 * `middleware.ts`, so a signed-out visitor is bounced to `/login` first.
 */
export default function RedeemInvitePage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [code, setCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleRedeem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) {
      toast.error('Enter your invite code to continue');
      return;
    }

    setSubmitting(true);
    try {
      await api('/v1/auth/redeem-teacher-invite', {
        method: 'POST',
        json: { code: trimmed },
      });
      setDone(true);
      toast.success('You are now a teacher', {
        description: 'Your account has been upgraded.',
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : 'Something went wrong. Please try again.';
      toast.error('Could not redeem code', { description: message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-paper">
      {/* gradient blobs */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 60% 50% at 85% 15%, rgba(91,91,229,.10) 0%, transparent 60%), radial-gradient(ellipse 50% 50% at 10% 85%, rgba(255,122,89,.08) 0%, transparent 60%)',
        }}
      />
      {/* dotted grid */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(27,31,46,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(27,31,46,.04) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
          maskImage:
            'radial-gradient(ellipse 60% 60% at 50% 45%, #000 0%, transparent 90%)',
          WebkitMaskImage:
            'radial-gradient(ellipse 60% 60% at 50% 45%, #000 0%, transparent 90%)',
        }}
      />

      <header className="relative z-[1] flex items-center justify-between px-7 py-5">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="logo-mark">E</div>
          <span className="font-display text-[18px] font-bold tracking-[-0.02em] text-ink">
            EduMind
          </span>
        </Link>
        <Link
          href="/dashboard"
          className="text-[13px] font-semibold text-ink-3 transition-colors hover:text-ink"
        >
          Back to dashboard
        </Link>
      </header>

      <main className="relative z-[1] flex flex-1 items-center justify-center px-6 py-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border-2 bg-white px-3.5 py-1.5 text-[13px] font-semibold text-ink-2 shadow-sm">
            <span className="h-2 w-2 animate-soft-pulse rounded-full bg-mint shadow-[0_0_0_3px_rgba(52,201,122,0.2)]" />
            Teacher access
          </div>

          <h1 className="mb-3 font-display text-[clamp(34px,4.5vw,44px)] font-bold leading-[1.05] tracking-[-0.03em] text-ink">
            Have a <span className="text-indigo">teacher invite</span> code?
          </h1>
          <p className="mb-8 text-[15px] leading-[1.55] text-ink-2">
            Teachers join EduMind by invitation. Enter the code an admin gave
            you to upgrade your account and start authoring courses.
          </p>

          <div className="rounded-[20px] border border-border bg-white/80 p-6 shadow-md backdrop-blur-sm">
            {done ? (
              <div className="flex flex-col gap-3 text-center">
                <p className="text-[15px] font-semibold text-ink">
                  You&apos;re all set — your account is now a teacher account.
                </p>
                <Link
                  href="/dashboard"
                  className="mt-1 inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo px-5 py-3 text-[15px] font-semibold text-white shadow-[0_4px_14px_rgba(91,91,229,.32),inset_0_-2px_0_rgba(0,0,0,.18)] transition-all duration-200 hover:-translate-y-px hover:bg-indigo-deep active:scale-[0.97]"
                >
                  Go to dashboard
                </Link>
              </div>
            ) : (
              <form
                onSubmit={handleRedeem}
                className="flex w-full flex-col gap-3"
                noValidate
              >
                <label
                  htmlFor="invite-code"
                  className="text-[13px] font-semibold text-ink-2"
                >
                  Invite code
                </label>
                <input
                  id="invite-code"
                  name="invite-code"
                  type="text"
                  autoComplete="off"
                  autoCapitalize="characters"
                  placeholder="TEACH-XXXXXX"
                  value={code}
                  onChange={(event) => setCode(event.target.value.toUpperCase())}
                  className="w-full rounded-[12px] border-[1.5px] border-border-2 bg-white px-4 py-3 text-[15px] tracking-[0.05em] text-ink shadow-sm outline-none transition-colors placeholder:text-muted focus:border-indigo focus:shadow-glow"
                />

                <button
                  type="submit"
                  disabled={submitting || loading || !user}
                  className="mt-2 inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo px-5 py-3 text-[15px] font-semibold text-white shadow-[0_4px_14px_rgba(91,91,229,.32),inset_0_-2px_0_rgba(0,0,0,.18)] transition-all duration-200 hover:-translate-y-px hover:bg-indigo-deep active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
                >
                  {submitting ? 'Redeeming…' : 'Redeem code'}
                </button>

                {!loading && !user && (
                  <p className="mt-1 text-center text-[13px] text-ink-3">
                    You need to be signed in.{' '}
                    <button
                      type="button"
                      onClick={() => router.push('/login?redirectTo=/redeem-invite')}
                      className="font-semibold text-indigo hover:text-indigo-deep"
                    >
                      Sign in
                    </button>
                  </p>
                )}
              </form>
            )}
          </div>

          <p className="mt-5 text-center text-[12.5px] text-ink-3">
            Don&apos;t have a code? Teacher access is invite-only.
          </p>
        </div>
      </main>
    </div>
  );
}
