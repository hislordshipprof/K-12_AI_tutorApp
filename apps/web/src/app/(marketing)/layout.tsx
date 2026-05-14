import type { ReactNode } from 'react';

/**
 * Marketing route-group layout — intentionally a pass-through.
 *
 * The landing screen at `/` lives at the app root and has its own
 * `<TopNav>`. Onboarding (the only current member of this group) is
 * full-bleed and brings its own chrome too. The group exists today
 * to keep marketing concerns segmented from the future authed shell.
 */
export default function MarketingLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
