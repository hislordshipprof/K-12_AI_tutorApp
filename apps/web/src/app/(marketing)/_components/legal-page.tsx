import Link from 'next/link';
import type { ReactNode } from 'react';

/**
 * Shared chrome for the static legal pages (`/privacy`, `/terms`).
 *
 * Renders the marketing header, a title, a prominent "draft — not legal
 * advice" notice, a last-updated line, and the page body. Kept here so the
 * two legal pages share one consistent layout without duplicating markup.
 */
export function LegalPage({
  title,
  lastUpdated,
  children,
}: {
  title: string;
  lastUpdated: string;
  children: ReactNode;
}) {
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

      <main className="relative z-[1] flex flex-1 justify-center px-6 py-10">
        <article className="w-full max-w-[720px]">
          <h1 className="mb-2 font-display text-[clamp(30px,4vw,40px)] font-bold leading-[1.1] tracking-[-0.03em] text-ink">
            {title}
          </h1>
          <p className="mb-6 text-[13px] text-ink-3">Last updated: {lastUpdated}</p>

          {/* Draft notice — this content is NOT legal advice. */}
          <div className="mb-8 rounded-[14px] border-[1.5px] border-amber/50 bg-amber/10 px-5 py-4">
            <p className="text-[13.5px] font-semibold leading-[1.55] text-ink-2">
              Draft — pending legal review. This is placeholder content
              written for an early build of EduMind. It is{' '}
              <span className="font-bold">not final and not legal advice</span>
              , and must be reviewed and approved by a qualified lawyer before
              EduMind onboards real students.
            </p>
          </div>

          <div className="flex flex-col gap-6 text-[15px] leading-[1.65] text-ink-2">
            {children}
          </div>
        </article>
      </main>
    </div>
  );
}

/** A titled section within a legal page. */
export function LegalSection({
  heading,
  children,
}: {
  heading: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-display text-[19px] font-bold tracking-[-0.01em] text-ink">
        {heading}
      </h2>
      {children}
    </section>
  );
}
