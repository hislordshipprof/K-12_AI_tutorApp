'use client';

import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';

import { AccountMenu } from '@/components/account-menu';
import { TopNav } from '@/components/aria/top-nav';
import { TeachRail } from '@/components/teach/teach-rail';
import { useMe } from '@/hooks/use-me';

/**
 * Client-side chrome wrapping every `/teach` admin-board screen.
 *
 * Mirrors the student `AppChrome` — `TopNav` + a left rail + scrollable
 * `main` — but with the teacher-scoped `TeachRail` and a "Teach" breadcrumb.
 * Teachers have no learning streak, so the streak pill is suppressed.
 */
export function TeachChrome({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: me } = useMe();
  const name = me?.full_name ?? 'Teacher';

  return (
    <div className="flex h-screen flex-col bg-paper">
      <TopNav
        crumb={{ section: 'Teach', page: 'Home' }}
        streak={0}
        name={name}
        onLogo={() => router.push('/teach')}
        hideAvatar
        right={<AccountMenu name={name} />}
      />
      <div className="flex min-h-0 flex-1">
        <TeachRail />
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
