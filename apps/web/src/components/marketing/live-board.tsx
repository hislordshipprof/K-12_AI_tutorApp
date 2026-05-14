import { AriaMascot } from '@/components/aria/aria-mascot';

/**
 * Chalkboard mock that anchors the landing hero's right column.
 *
 * Wraps the dark navy board, the live status pill, Prof. Aria + lesson
 * label, the chalk wave SVG, and the caption bar. The SVG is ported
 * verbatim from the prototype (`screens-marketing.jsx` lines 56-71)
 * including the `feTurbulence` chalk filter and the colour palette.
 */
export function LiveBoard() {
  return (
    <div
      className="relative isolate overflow-hidden rounded-[28px] bg-board p-5 pt-6 shadow-[0_32px_80px_rgba(14,26,46,.32),0_12px_28px_rgba(14,26,46,.18),inset_0_1px_0_rgba(255,255,255,.06)]"
      style={{ aspectRatio: '5 / 4' }}
    >
      {/* subtle dot texture (was .l-board::before) */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'radial-gradient(circle, rgba(255,255,255,.04) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      />

      {/* top bar */}
      <div className="relative z-10 mb-4 flex items-center justify-between">
        <div className="flex items-center gap-[7px] rounded-full bg-white/[0.06] px-3 py-[5px] font-mono text-[11px] font-medium text-white/70">
          <span className="h-1.5 w-1.5 animate-soft-pulse rounded-full bg-mint" />
          LIVE · AP Physics 1
        </div>
        <div className="flex items-center gap-2">
          <AriaMascot size={34} pulse withHat />
          <div className="text-[12px] font-semibold leading-tight text-white">
            Prof. Aria
            <small className="block text-[10px] font-medium text-chalk-yellow">
              Wave Properties
            </small>
          </div>
        </div>
      </div>

      {/* chalk wave svg */}
      <svg
        viewBox="0 0 600 320"
        preserveAspectRatio="xMidYMid meet"
        className="block h-[64%] w-full"
        aria-hidden
      >
        <defs>
          <filter id="lc">
            <feTurbulence
              type="fractalNoise"
              baseFrequency=".7"
              numOctaves={3}
              result="n"
            />
            <feDisplacementMap in="SourceGraphic" in2="n" scale={1.6} />
          </filter>
        </defs>
        <line
          x1="30"
          y1="170"
          x2="570"
          y2="170"
          stroke="rgba(255,255,255,.18)"
          strokeWidth="1.2"
          strokeDasharray="6,4"
          filter="url(#lc)"
        />
        <path
          d="M30,170 C70,170 80,80 110,80 C140,80 150,260 180,260 C210,260 220,80 250,80 C280,80 290,260 320,260 C350,260 360,80 390,80 C420,80 430,260 460,260 C490,260 500,80 530,80 C555,80 565,200 570,170"
          fill="none"
          stroke="#A8C4E8"
          strokeWidth="2.5"
          strokeLinecap="round"
          filter="url(#lc)"
        />
        <circle
          cx="110"
          cy="80"
          r="6"
          fill="none"
          stroke="#F5E067"
          strokeWidth="2"
          filter="url(#lc)"
        />
        <text
          x="110"
          y="62"
          textAnchor="middle"
          fill="#F5E067"
          fontSize="11"
          fontWeight="700"
          fontFamily="DM Sans"
        >
          crest
        </text>
        <line
          x1="250"
          y1="170"
          x2="250"
          y2="80"
          stroke="#F09AAF"
          strokeWidth="2"
          filter="url(#lc)"
        />
        <text
          x="260"
          y="125"
          fill="#F09AAF"
          fontSize="22"
          fontStyle="italic"
          fontFamily="Bricolage Grotesque"
        >
          A
        </text>
        <line
          x1="110"
          y1="50"
          x2="250"
          y2="50"
          stroke="#7DD4A8"
          strokeWidth="2"
          filter="url(#lc)"
        />
        <text
          x="180"
          y="40"
          textAnchor="middle"
          fill="#7DD4A8"
          fontSize="20"
          fontStyle="italic"
          fontFamily="Bricolage Grotesque"
        >
          λ
        </text>
      </svg>

      {/* caption bar */}
      <div className="absolute inset-x-5 bottom-[18px] flex items-start gap-2.5 rounded-[14px] border border-white/[0.08] bg-board/70 px-3.5 py-[11px] backdrop-blur-md">
        <div className="grid h-[30px] w-[30px] flex-shrink-0 place-items-center rounded-full">
          <AriaMascot size={30} speaking withHat={false} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-[3px] text-[9px] font-bold uppercase tracking-[0.12em] text-chalk-yellow">
            Prof. Aria · speaking
          </div>
          <p className="font-display text-[12px] italic leading-[1.5] text-white/[0.92]">
            &ldquo;Notice how the wave&apos;s{' '}
            <em className="font-semibold not-italic text-chalk-yellow">
              amplitude
            </em>{' '}
            stays constant &mdash; that&apos;s the energy. Now, the
            wavelength&hellip;&rdquo;
          </p>
        </div>
      </div>
    </div>
  );
}
