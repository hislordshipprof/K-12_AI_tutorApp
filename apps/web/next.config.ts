import type { NextConfig } from 'next';

// HARD GUARD: refuse to build for Vercel production when demo-mode bypass
// is set. NEXT_PUBLIC_DEMO_MODE short-circuits middleware auth gating in
// `apps/web/src/middleware.ts` — fine for marketing previews, catastrophic
// in prod (leaves /dashboard, /classroom etc. publicly reachable).
if (
  process.env.VERCEL_ENV === 'production' &&
  process.env.NEXT_PUBLIC_DEMO_MODE === 'true'
) {
  throw new Error(
    'Refusing to build: VERCEL_ENV=production with NEXT_PUBLIC_DEMO_MODE=true. ' +
      'Unset NEXT_PUBLIC_DEMO_MODE on the production Vercel project.',
  );
}

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseHost = (() => {
  if (!supabaseUrl) return undefined;
  try {
    return new URL(supabaseUrl).hostname;
  } catch {
    return undefined;
  }
})();

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typescript: {
    ignoreBuildErrors: false,
  },
  eslint: {
    ignoreDuringBuilds: false,
  },
  images: {
    remotePatterns: [
      ...(supabaseHost
        ? [
            {
              protocol: 'https' as const,
              hostname: supabaseHost,
              pathname: '/storage/v1/object/public/**',
            },
          ]
        : []),
      {
        protocol: 'http' as const,
        hostname: '127.0.0.1',
        port: '54321',
        pathname: '/storage/v1/object/public/**',
      },
      {
        protocol: 'http' as const,
        hostname: 'localhost',
        port: '54321',
        pathname: '/storage/v1/object/public/**',
      },
    ],
  },
};

export default nextConfig;
