import type { Config } from 'tailwindcss';
import typography from '@tailwindcss/typography';

const config: Config = {
  content: [
    './src/**/*.{ts,tsx,js,jsx,mdx}',
    './src/app/**/*.{ts,tsx}',
    './src/components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // ─── paper (cream backgrounds) ───
        paper: {
          DEFAULT: '#FFFBF3',
          2: '#F7F1E4',
          3: '#EFE7D4',
        },

        // ─── ink (text) ───
        ink: {
          DEFAULT: '#1B1F2E',
          2: '#3D4359',
          3: '#6B7388',
        },
        muted: '#9CA3B8',

        // ─── borders ───
        border: {
          DEFAULT: 'rgba(27,31,46,0.08)',
          2: 'rgba(27,31,46,0.14)',
        },

        // ─── brand ───
        indigo: {
          DEFAULT: '#5B5BE5',
          deep: '#3F3AC8',
          soft: '#EEEDFC',
        },
        coral: {
          DEFAULT: '#FF7A59',
          soft: '#FFE6DD',
        },
        amber: {
          DEFAULT: '#FFC857',
          soft: '#FFF1C9',
        },
        mint: {
          DEFAULT: '#34C97A',
          soft: '#D9F3E2',
        },
        lavender: {
          DEFAULT: '#A78BFA',
          soft: '#EFE9FF',
        },
        rose: '#F472B6',
        sky: '#5FB7F4',

        // ─── chalkboard ───
        board: {
          DEFAULT: '#0E1A2E',
          2: '#142340',
        },
        chalk: {
          DEFAULT: '#F2EFE3',
          blue: '#A8C4E8',
          yellow: '#F5E067',
          pink: '#F09AAF',
          green: '#7DD4A8',
          coral: '#FF9F7E',
        },
      },
      fontFamily: {
        display: ['var(--font-display)', 'Bricolage Grotesque', 'system-ui', 'sans-serif'],
        body: ['var(--font-body)', 'DM Sans', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        sm: '0 1px 2px rgba(27,31,46,0.04), 0 1px 1px rgba(27,31,46,0.02)',
        md: '0 4px 12px rgba(27,31,46,0.06), 0 1px 3px rgba(27,31,46,0.04)',
        lg: '0 14px 40px rgba(27,31,46,0.10), 0 4px 12px rgba(27,31,46,0.05)',
        xl: '0 24px 80px rgba(27,31,46,0.18), 0 8px 24px rgba(27,31,46,0.08)',
        glow: '0 0 0 6px rgba(91,91,229,0.12)',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.22, 1, 0.36, 1)',
        spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      keyframes: {
        'aria-pulse': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4%)' },
        },
        'aria-talk': {
          from: { height: '14%', width: '24%' },
          to: { height: '22%', width: '32%' },
        },
        'aria-ring': {
          '0%, 100%': { transform: 'scale(1)', opacity: '0.5' },
          '50%': { transform: 'scale(1.08)', opacity: '0.15' },
        },
        'soft-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        draw: {
          to: { strokeDashoffset: '0' },
        },
        'confetti-fall': {
          '0%': { transform: 'translateY(-20px) rotate(0deg)', opacity: '1' },
          '100%': { transform: 'translateY(110vh) rotate(720deg)', opacity: '0' },
        },
        'bounce-in': {
          from: { transform: 'scale(0.3)', opacity: '0' },
          to: { transform: 'scale(1)', opacity: '1' },
        },
        rot: {
          to: { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        'aria-pulse': 'aria-pulse 2.4s ease-in-out infinite',
        'aria-talk': 'aria-talk 0.55s ease-in-out infinite alternate',
        'aria-ring': 'aria-ring 2.5s ease-in-out infinite',
        'soft-pulse': 'soft-pulse 1.6s ease-in-out infinite',
        float: 'float 6s ease-in-out infinite',
        'fade-in': 'fade-in 0.4s ease-out forwards',
        draw: 'draw 1.2s ease-out forwards',
        'confetti-fall': 'confetti-fall 3s linear forwards',
        'bounce-in': 'bounce-in 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) both',
        rot: 'rot 20s linear infinite',
      },
    },
  },
  plugins: [typography],
};

export default config;
