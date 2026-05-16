'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { useSupabase } from '@/components/providers';

/** Map raw Supabase auth errors to friendly, student-readable messages. */
function friendlySignUpError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes('already registered') || m.includes('already been registered')) {
    return 'That email already has an account. Try signing in instead.';
  }
  if (m.includes('password should be at least') || m.includes('weak password')) {
    return 'Please choose a stronger password (at least 6 characters).';
  }
  if (m.includes('invalid email') || m.includes('unable to validate email')) {
    return 'That email address doesn’t look right.';
  }
  return message;
}

function SignUpForm() {
  const supabase = useSupabase();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const redirectTo = searchParams.get('redirectTo') ?? '/dashboard';

  async function handleSignUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase) {
      toast.error('Auth is not configured', {
        description: 'Supabase environment variables are missing.',
      });
      return;
    }
    const trimmedEmail = email.trim();
    const trimmedName = fullName.trim();
    if (!trimmedEmail || !password) {
      toast.error('Enter your email and a password to continue');
      return;
    }
    if (password.length < 6) {
      toast.error('Password too short', {
        description: 'Please use at least 6 characters.',
      });
      return;
    }

    setSubmitting(true);
    try {
      // Submitting the form is the act of accepting the Terms + Privacy
      // Policy (the note below the form). We record the moment of acceptance
      // and pass it through signUp metadata — the `handle_new_user` DB
      // trigger copies `full_name` and `terms_accepted_at` onto the new
      // `public.profiles` row (§14 "recorded as accepted").
      const termsAcceptedAt = new Date().toISOString();
      const { data, error } = await supabase.auth.signUp({
        email: trimmedEmail,
        password,
        options: {
          // `full_name` and `terms_accepted_at` are read by the
          // `handle_new_user` DB trigger to seed the public.profiles row.
          data: {
            ...(trimmedName ? { full_name: trimmedName } : {}),
            terms_accepted_at: termsAcceptedAt,
          },
        },
      });
      if (error) {
        toast.error('Could not create account', {
          description: friendlySignUpError(error.message),
        });
        return;
      }

      // When email confirmation is enabled, signUp returns a user with no
      // active session — the user must confirm via the emailed link first.
      if (data.session) {
        toast.success('Account created!', {
          description: 'Welcome to EduMind.',
        });
        router.push(redirectTo);
        router.refresh();
      } else {
        toast.success('Check your inbox', {
          description: `Confirm your email at ${trimmedEmail}, then sign in.`,
        });
        router.push('/login');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    // Data minimisation (§14): sign-up collects ONLY name, email and a
    // password — the minimum a school account needs. No date of birth (an
    // age band is gathered later if needed), no address, no extra PII.
    <form onSubmit={handleSignUp} className="flex w-full flex-col gap-3" noValidate>
      <label htmlFor="full-name" className="text-[13px] font-semibold text-ink-2">
        Name
      </label>
      <input
        id="full-name"
        name="full-name"
        type="text"
        autoComplete="name"
        placeholder="Your name"
        value={fullName}
        onChange={(event) => setFullName(event.target.value)}
        className="w-full rounded-[12px] border-[1.5px] border-border-2 bg-white px-4 py-3 text-[15px] text-ink shadow-sm outline-none transition-colors placeholder:text-muted focus:border-indigo focus:shadow-glow"
      />

      <label htmlFor="email" className="mt-1 text-[13px] font-semibold text-ink-2">
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
        autoComplete="new-password"
        required
        minLength={6}
        placeholder="At least 6 characters"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        className="w-full rounded-[12px] border-[1.5px] border-border-2 bg-white px-4 py-3 text-[15px] text-ink shadow-sm outline-none transition-colors placeholder:text-muted focus:border-indigo focus:shadow-glow"
      />

      <button
        type="submit"
        disabled={submitting}
        className="mt-2 inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo px-5 py-3 text-[15px] font-semibold text-white shadow-[0_4px_14px_rgba(91,91,229,.32),inset_0_-2px_0_rgba(0,0,0,.18)] transition-all duration-200 hover:-translate-y-px hover:bg-indigo-deep active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
      >
        {submitting ? 'Creating account…' : 'Create account'}
      </button>

      <p className="mt-2 text-center text-[13px] text-ink-3">
        Already have an account?{' '}
        <Link
          href={
            redirectTo === '/dashboard'
              ? '/login'
              : `/login?redirectTo=${encodeURIComponent(redirectTo)}`
          }
          className="font-semibold text-indigo hover:text-indigo-deep"
        >
          Sign in
        </Link>
      </p>
    </form>
  );
}

/**
 * Sign-up screen — Supabase email + password.
 *
 * Mirrors the sign-in screen's visual language. On success: if email
 * confirmation is disabled the user is signed straight in and forwarded to
 * `redirectTo`; otherwise they are told to confirm their email and sent to
 * `/login`.
 */
export default function SignUpPage() {
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
            Get started
          </div>

          <h1 className="mb-3 font-display text-[clamp(34px,4.5vw,44px)] font-bold leading-[1.05] tracking-[-0.03em] text-ink">
            Create your <span className="text-indigo">EduMind</span> account
          </h1>
          <p className="mb-8 text-[15px] leading-[1.55] text-ink-2">
            Sign up with your email and a password to start learning with
            Aria, your personal tutor.
          </p>

          <div className="rounded-[20px] border border-border bg-white/80 p-6 shadow-md backdrop-blur-sm">
            <Suspense fallback={null}>
              <SignUpForm />
            </Suspense>
          </div>

          <p className="mt-5 text-center text-[12.5px] text-ink-3">
            By continuing you agree to EduMind&apos;s{' '}
            <Link
              href="/terms"
              className="font-semibold text-indigo hover:text-indigo-deep"
            >
              Terms
            </Link>{' '}
            &amp;{' '}
            <Link
              href="/privacy"
              className="font-semibold text-indigo hover:text-indigo-deep"
            >
              Privacy
            </Link>
            .
          </p>
        </div>
      </main>
    </div>
  );
}
