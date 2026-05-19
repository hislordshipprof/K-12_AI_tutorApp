'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { useSupabase } from '@/components/providers';

/** Map raw Supabase auth errors to friendly, student-readable messages. */
function friendlySignInError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes('invalid login credentials')) {
    return 'That email and password don’t match. Check them and try again.';
  }
  if (m.includes('email not confirmed')) {
    return 'Please confirm your email first — check your inbox for the link.';
  }
  return message;
}

/** Inline Google "G" mark for the OAuth button. */
function GoogleGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="shrink-0">
      <path
        fill="#EA4335"
        d="M9 3.48c1.69 0 2.83.73 3.48 1.34l2.54-2.48C13.46 1.2 11.43 0 9 0 5.48 0 2.44 2.02.96 4.96l2.91 2.26C4.6 5.05 6.62 3.48 9 3.48z"
      />
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.74-.06-1.28-.19-1.84H9v3.34h4.96c-.1.83-.64 2.08-1.84 2.92l2.84 2.2c1.7-1.57 2.68-3.88 2.68-6.62z"
      />
      <path
        fill="#FBBC05"
        d="M3.88 10.78A5.54 5.54 0 0 1 3.58 9c0-.62.11-1.22.29-1.78L.96 4.96A9 9 0 0 0 0 9c0 1.45.35 2.82.96 4.04l2.92-2.26z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.84-2.2c-.76.53-1.78.9-3.12.9-2.38 0-4.4-1.57-5.12-3.74L.97 13.04C2.45 15.98 5.48 18 9 18z"
      />
    </svg>
  );
}

function SignInForm() {
  const supabase = useSupabase();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [oauthing, setOauthing] = useState(false);

  // An explicit `?redirectTo=` deep link is honoured as-is after sign-in.
  // With no param, the post-login destination is resolved from the user's
  // role (teacher/admin -> /teach, student -> /dashboard).
  const explicitRedirect = searchParams.get('redirectTo');
  const redirectTo = explicitRedirect ?? '/dashboard';

  // Surface server-side redirects (e.g. from /auth/callback) as toasts.
  useEffect(() => {
    const error = searchParams.get('error');
    if (error) {
      toast.error('Sign-in failed', { description: error });
    }
  }, [searchParams]);

  async function handleSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase) {
      toast.error('Auth is not configured', {
        description: 'Supabase environment variables are missing.',
      });
      return;
    }
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      toast.error('Enter your email and password to continue');
      return;
    }

    setSubmitting(true);
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: trimmedEmail,
        password,
      });
      if (error) {
        toast.error('Could not sign in', {
          description: friendlySignInError(error.message),
        });
        return;
      }
      toast.success('Welcome back!');
      // Explicit deep link wins; otherwise route by the signed-in role.
      let destination = redirectTo;
      if (!explicitRedirect) {
        const {
          data: { user },
        } = await supabase.auth.getUser();
        if (user) {
          const { data: profile } = await supabase
            .from('profiles')
            .select('role')
            .eq('id', user.id)
            .single();
          const role = (profile?.role as string | undefined) ?? 'student';
          if (role === 'teacher' || role === 'admin') destination = '/teach';
        }
      }
      router.push(destination);
      router.refresh();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogle() {
    if (!supabase) {
      toast.error('Auth is not configured', {
        description: 'Supabase environment variables are missing.',
      });
      return;
    }
    setOauthing(true);
    try {
      const callbackUrl =
        typeof window !== 'undefined'
          ? `${window.location.origin}/auth/callback`
          : undefined;
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: callbackUrl },
      });
      if (error) {
        toast.error('Google sign-in failed', { description: error.message });
        setOauthing(false);
      }
      // On success the browser is redirected to Google — no follow-up here.
    } catch {
      setOauthing(false);
    }
  }

  return (
    <form onSubmit={handleSignIn} className="flex w-full flex-col gap-3" noValidate>
      <label htmlFor="email" className="text-[13px] font-semibold text-ink-2">
        Email
      </label>
      <input
        id="email"
        name="email"
        type="email"
        autoComplete="email"
        required
        placeholder="you@school.edu"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        className="w-full rounded-[12px] border-[1.5px] border-border-2 bg-white px-4 py-3 text-[15px] text-ink shadow-sm outline-none transition-colors placeholder:text-muted focus:border-indigo focus:shadow-glow"
      />

      <label htmlFor="password" className="mt-1 text-[13px] font-semibold text-ink-2">
        Password
      </label>
      <input
        id="password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        placeholder="Your password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        className="w-full rounded-[12px] border-[1.5px] border-border-2 bg-white px-4 py-3 text-[15px] text-ink shadow-sm outline-none transition-colors placeholder:text-muted focus:border-indigo focus:shadow-glow"
      />

      <button
        type="submit"
        disabled={submitting}
        className="mt-2 inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo px-5 py-3 text-[15px] font-semibold text-white shadow-[0_4px_14px_rgba(91,91,229,.32),inset_0_-2px_0_rgba(0,0,0,.18)] transition-all duration-200 hover:-translate-y-px hover:bg-indigo-deep active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
      >
        {submitting ? 'Signing in…' : 'Sign in'}
      </button>

      <div className="my-1 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-3">
        <span className="h-px flex-1 bg-border-2" />
        or
        <span className="h-px flex-1 bg-border-2" />
      </div>

      <button
        type="button"
        onClick={handleGoogle}
        disabled={oauthing}
        className="inline-flex items-center justify-center gap-2.5 rounded-2xl border-[1.5px] border-border-2 bg-white px-5 py-3 text-[15px] font-semibold text-ink shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-ink-3 hover:bg-paper-2 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
      >
        <GoogleGlyph />
        {oauthing ? 'Redirecting…' : 'Continue with Google'}
      </button>

      <p className="mt-2 text-center text-[13px] text-ink-3">
        New to EduMind?{' '}
        <Link
          href={
            redirectTo === '/dashboard'
              ? '/signup'
              : `/signup?redirectTo=${encodeURIComponent(redirectTo)}`
          }
          className="font-semibold text-indigo hover:text-indigo-deep"
        >
          Create an account
        </Link>
      </p>
    </form>
  );
}

/**
 * Sign-in screen — Supabase email + password, plus Google OAuth.
 *
 * Visual language matches the marketing landing page: cream paper
 * background, dotted-grid mask, gradient blobs, and an `indigo` primary
 * action. Email/password sends the user to `redirectTo` (default
 * `/dashboard`); Google OAuth routes through `/auth/callback`.
 */
export default function LoginPage() {
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
          href="/"
          className="text-[13px] font-semibold text-ink-3 transition-colors hover:text-ink"
        >
          Back to home
        </Link>
      </header>

      <main className="relative z-[1] flex flex-1 items-center justify-center px-6 py-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border-2 bg-white px-3.5 py-1.5 text-[13px] font-semibold text-ink-2 shadow-sm">
            <span className="h-2 w-2 animate-soft-pulse rounded-full bg-mint shadow-[0_0_0_3px_rgba(52,201,122,0.2)]" />
            Welcome back
          </div>

          <h1 className="mb-3 font-display text-[clamp(34px,4.5vw,44px)] font-bold leading-[1.05] tracking-[-0.03em] text-ink">
            Sign in to <span className="text-indigo">EduMind</span>
          </h1>
          <p className="mb-8 text-[15px] leading-[1.55] text-ink-2">
            Enter your email and password — or continue with Google — to
            jump straight back to class.
          </p>

          <div className="rounded-[20px] border border-border bg-white/80 p-6 shadow-md backdrop-blur-sm">
            <Suspense fallback={null}>
              <SignInForm />
            </Suspense>
          </div>

          <p className="mt-5 text-center text-[12.5px] text-ink-3">
            By continuing you agree to EduMind&apos;s Terms &amp; Privacy.
          </p>
        </div>
      </main>
    </div>
  );
}
