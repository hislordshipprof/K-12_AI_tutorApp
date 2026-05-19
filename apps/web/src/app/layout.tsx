import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import { Providers } from '@/components/providers';

import './globals.css';

// Fonts loaded at runtime via <link> below (NOT via next/font/google) so the
// build doesn't require network access to fonts.googleapis.com. CSS variables
// are set in globals.css :root.

export const metadata: Metadata = {
  title: 'EduMind — Your AI Classroom',
  description: 'A live AI classroom for K-12 students. Learn with Aria, your personal tutor.',
  applicationName: 'EduMind',
  authors: [{ name: 'EduMind' }],
  keywords: ['EduMind', 'AI tutor', 'K-12', 'classroom', 'learning', 'education'],
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  themeColor: '#FFFBF3',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700;12..96,800&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap"
        />
        {/* Material Symbols — the classroom redesign uses this icon font. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
        />
      </head>
      <body className="font-body antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
