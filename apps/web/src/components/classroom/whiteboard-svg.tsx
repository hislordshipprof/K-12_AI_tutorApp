import { TimedReveal } from '@/components/aria/timed-reveal';
import { cn } from '@/lib/utils';

import { getScene } from './scenes';

interface WhiteboardSVGProps {
  /** 0-7. 0 is the "preparing" placeholder. */
  step?: number;
  className?: string;
  /**
   * Which scene to draw on the chalkboard.
   *   - `waves`   — the prototype's 8-step wave-properties scene (wave, λ,
   *                 amplitude, v=f·λ etc.). Used by the wave-properties demo
   *                 slug and the Oscillations topic.
   *   - `generic` — clean chalkboard backdrop. Pulls the highlighted phrase
   *                 from the current step's HTML and renders it big-and-chalky.
   *                 Used for every other real DB topic so we don't render
   *                 wave imagery on a Kinematics or Cell Biology lesson.
   */
  kind?: 'waves' | 'generic';
  /**
   * Current step HTML (only consulted when `kind === 'generic'`). We grab
   * the first `<span class="hl-*">…</span>` token as the chalk headline.
   */
  stepHtml?: string;
  /** Current step's plain caption — used as fallback when no highlight. */
  stepTts?: string;
  /** Topic title for the watermark on generic chalkboard. */
  topicTitle?: string;
  /**
   * 0→1 TTS playback progress. When set, the generic chalkboard headline
   * "writes itself" word-by-word in sync with Aria's voice (Phase A).
   */
  revealProgress?: number;
  /**
   * Optional animated diagram for the current step (Phase B). When the
   * `type` resolves in the scene registry it replaces the text
   * chalkboard — the scene draws itself in sync with `revealProgress`.
   */
  scene?: { type: string; params: Record<string, unknown> } | null;
  /**
   * Signed URL of the teacher slide this step is taught over
   * (`teacher-authoring.md` §7). When set it is drawn as the board
   * backdrop and the scene SVG (if any) annotates on top; the text
   * chalkboard is suppressed. Steps with no slide keep the chalkboard.
   */
  slideUrl?: string | null;
}

const WAVE_D =
  'M60,265 C95,265 105,130 145,130 C185,130 195,400 235,400 C275,400 285,130 325,130 C365,130 375,400 415,400 C455,400 465,130 505,130 C545,130 555,400 595,400 C635,400 645,130 685,130 C725,130 735,400 775,400 C805,400 825,340 840,265';

const baseLine = {
  stroke: 'rgba(255,255,255,.18)',
  strokeWidth: 1.5,
  strokeDasharray: '8,5',
  filter: 'url(#chalk)',
} as const;

/**
 * Pull the first `<span class="hl-*">…</span>` phrase out of step HTML so
 * we can render it as the chalkboard headline. Keeps the inner content
 * including any LaTeX `$...$` so `MathContent` typesets it. Falls back
 * to the first sentence of plain text when no highlight is present.
 */
function extractHeadline(html: string, fallback: string): string {
  if (!html) return fallback;
  const hlMatch = html.match(/<span class="hl-[^"]*">([^<]+)<\/span>/);
  if (hlMatch?.[1]) return hlMatch[1].trim();
  // Strip tags but PRESERVE LaTeX delimiters so the renderer can typeset.
  const plain = html.replace(/<[^>]+>/g, '').trim();
  const firstChunk = plain.split(/[.?!]/)[0]?.trim() ?? plain;
  return firstChunk.slice(0, 80);
}

/**
 * Chalk-on-blackboard SVG. Two render modes: the wave-properties scene
 * (legacy prototype + Oscillations) and a generic chalkboard that shows the
 * lesson's current key phrase. Both share the chalk turbulence filter so
 * the texture is consistent across topics.
 */
export function WhiteboardSVG({
  step = 0,
  className,
  kind = 'waves',
  stepHtml,
  stepTts,
  topicTitle,
  revealProgress = 1,
  scene = null,
  slideUrl = null,
}: WhiteboardSVGProps) {
  // A step-level scene wins over the text chalkboard / waves scene.
  const SceneComponent = scene ? getScene(scene.type) : null;
  return (
    <svg
      viewBox="0 0 900 530"
      preserveAspectRatio="xMidYMid meet"
      className={cn(className)}
      aria-hidden="true"
    >
      <defs>
        <filter id="chalk">
          <feTurbulence
            type="fractalNoise"
            baseFrequency=".65"
            numOctaves="3"
            stitchTiles="stitch"
            result="n"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="n"
            scale="1.5"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
        <filter id="glow">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Teacher slide backdrop — drawn first so the scene SVG annotates
          on top of it. `meet` keeps the slide's aspect ratio; any
          letterbox falls back to the dark board behind the <svg>. */}
      {slideUrl ? (
        <image
          href={slideUrl}
          x="0"
          y="0"
          width="900"
          height="530"
          preserveAspectRatio="xMidYMid meet"
        />
      ) : null}

      {SceneComponent && scene ? (
        <g>
          {/* Topic watermark + step counter stay so the board feels
              consistent across text-chalkboard and scene steps. */}
          {topicTitle ? (
            <text
              x="60"
              y="56"
              fill="rgba(255,255,255,.22)"
              fontSize="14"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
            >
              {topicTitle}
            </text>
          ) : null}
          <text
            x="840"
            y="56"
            textAnchor="end"
            fill="rgba(255,255,255,.28)"
            fontSize="13"
            fontWeight="700"
            fontFamily="DM Sans, sans-serif"
            filter="url(#chalk)"
          >
            {step === 0 ? 'Preparing…' : `Step ${step}`}
          </text>
          <SceneComponent progress={revealProgress} params={scene.params} />
        </g>
      ) : slideUrl ? null : kind === 'generic' ? (
        <GenericChalkboard
          step={step}
          stepHtml={stepHtml}
          stepTts={stepTts}
          topicTitle={topicTitle}
          revealProgress={revealProgress}
        />
      ) : (
        <WavesScene step={step} />
      )}
    </svg>
  );
}

// ── Generic chalkboard — shows the lesson's current highlighted phrase ────
function GenericChalkboard({
  step,
  stepHtml,
  stepTts,
  topicTitle,
  revealProgress,
}: {
  step: number;
  stepHtml?: string;
  stepTts?: string;
  topicTitle?: string;
  revealProgress: number;
}) {
  const headline = extractHeadline(stepHtml ?? '', stepTts ?? '');
  const stepLabel = step === 0 ? 'Preparing…' : `Step ${step}`;

  return (
    <g>
      {/* Faint horizontal chalk guideline so the board doesn't feel empty. */}
      <line x1="60" y1="265" x2="840" y2="265" {...baseLine} stroke="rgba(255,255,255,.08)" />

      {/* Topic watermark — top-left corner, italic, low-contrast. */}
      {topicTitle ? (
        <text
          x="60"
          y="60"
          fill="rgba(255,255,255,.22)"
          fontSize="14"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#chalk)"
        >
          {topicTitle}
        </text>
      ) : null}

      {/* Step counter — top-right, small. */}
      <text
        x="840"
        y="60"
        textAnchor="end"
        fill="rgba(255,255,255,.28)"
        fontSize="13"
        fontWeight="700"
        fontFamily="DM Sans, sans-serif"
        filter="url(#chalk)"
      >
        {stepLabel}
      </text>

      {/* Big chalk headline — uses a foreignObject so KaTeX can typeset
          any `$...$` math inside the highlighted phrase. SVG `<text>`
          cannot render LaTeX so we delegate to MathContent here. */}
      <foreignObject x="60" y="200" width="780" height="180">
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--chalk)',
            fontFamily: 'Bricolage Grotesque, serif',
            fontStyle: 'italic',
            textAlign: 'center',
            lineHeight: 1.2,
            filter: 'url(#glow)',
            fontSize: headline.length > 60 ? 28 : headline.length > 28 ? 36 : 48,
            padding: '0 20px',
          }}
        >
          <TimedReveal html={headline || '…'} progress={revealProgress} />
        </div>
      </foreignObject>

      {/* Subtle subline — invitation to listen / read the caption. */}
      <text
        x="450"
        y="420"
        textAnchor="middle"
        fill="rgba(255,255,255,.35)"
        fontSize="14"
        fontFamily="Bricolage Grotesque, serif"
        fontStyle="italic"
      >
        {step === 0 ? 'Aria is loading the lesson' : 'Aria is explaining — read the caption below'}
      </text>
    </g>
  );
}

// ── Waves scene — the legacy 8-step prototype board ───────────────────────
function WavesScene({ step }: { step: number }) {
  return (
    <>
      {/* STEP 0: blank with placeholder */}
      <g className={cn('wb-step', step === 0 && 'active')}>
        <text
          x="450"
          y="265"
          textAnchor="middle"
          fill="rgba(255,255,255,.12)"
          fontSize="22"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
        >
          Preparing your lesson…
        </text>
      </g>

      {/* STEP 1: equilibrium line */}
      <g className={cn('wb-step', step === 1 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} />
        <text
          x="65"
          y="255"
          fill="rgba(255,255,255,.4)"
          fontSize="13"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
        >
          equilibrium / rest position
        </text>
      </g>

      {/* STEP 2: the wave */}
      <g className={cn('wb-step', step === 2 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} />
        <text
          x="65"
          y="255"
          fill="rgba(255,255,255,.25)"
          fontSize="12"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
        >
          equilibrium
        </text>
        <path
          d={WAVE_D}
          fill="none"
          stroke="var(--chalk-blue)"
          strokeWidth="3"
          strokeLinecap="round"
          filter="url(#chalk)"
          style={{
            strokeDasharray: 3200,
            strokeDashoffset: step === 2 ? 0 : 3200,
            transition: 'stroke-dashoffset 3.2s linear',
          }}
        />
      </g>

      {/* STEP 3: crests & troughs */}
      <g className={cn('wb-step', step === 3 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} stroke="rgba(255,255,255,.14)" />
        <path
          d={WAVE_D}
          fill="none"
          stroke="var(--chalk-blue)"
          strokeWidth="3"
          strokeLinecap="round"
          filter="url(#chalk)"
        />
        {[145, 325, 505, 685].map((x, i) => (
          <circle
            key={`c${i}`}
            cx={x}
            cy="130"
            r="8"
            fill="none"
            stroke="var(--chalk-yellow)"
            strokeWidth="2.5"
            filter="url(#chalk)"
            style={{
              opacity: step === 3 ? 1 : 0,
              transition: `opacity .4s ${i * 0.15}s`,
            }}
          />
        ))}
        <text
          x="325"
          y="110"
          textAnchor="middle"
          fill="var(--chalk-yellow)"
          fontSize="15"
          fontWeight="700"
          fontFamily="DM Sans, sans-serif"
          filter="url(#chalk)"
          style={{
            opacity: step === 3 ? 1 : 0,
            transition: 'opacity .5s .5s',
          }}
        >
          CREST
        </text>
        {[235, 415, 595, 775].map((x, i) => (
          <circle
            key={`t${i}`}
            cx={x}
            cy="400"
            r="8"
            fill="none"
            stroke="var(--chalk-pink)"
            strokeWidth="2.5"
            filter="url(#chalk)"
            style={{
              opacity: step === 3 ? 1 : 0,
              transition: `opacity .4s ${0.7 + i * 0.15}s`,
            }}
          />
        ))}
        <text
          x="415"
          y="432"
          textAnchor="middle"
          fill="var(--chalk-pink)"
          fontSize="15"
          fontWeight="700"
          fontFamily="DM Sans, sans-serif"
          filter="url(#chalk)"
          style={{
            opacity: step === 3 ? 1 : 0,
            transition: 'opacity .5s 1.1s',
          }}
        >
          TROUGH
        </text>
      </g>

      {/* STEP 4: amplitude */}
      <g className={cn('wb-step', step === 4 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} stroke="rgba(255,255,255,.13)" />
        <path
          d={WAVE_D}
          fill="none"
          stroke="var(--chalk-blue)"
          strokeWidth="3"
          strokeLinecap="round"
          filter="url(#chalk)"
          opacity="0.5"
        />
        <line
          x1="145"
          y1="265"
          x2="145"
          y2="130"
          stroke="var(--chalk-pink)"
          strokeWidth="2.5"
          filter="url(#chalk)"
          style={{
            strokeDasharray: 200,
            strokeDashoffset: step === 4 ? 0 : 200,
            transition: 'stroke-dashoffset .8s ease',
          }}
        />
        <polygon
          points="145,130 139,148 151,148"
          fill="var(--chalk-pink)"
          style={{
            opacity: step === 4 ? 1 : 0,
            transition: 'opacity .3s .7s',
          }}
        />
        <polygon
          points="145,265 139,247 151,247"
          fill="var(--chalk-pink)"
          style={{
            opacity: step === 4 ? 1 : 0,
            transition: 'opacity .3s .7s',
          }}
        />
        <text
          x="118"
          y="205"
          fill="var(--chalk-pink)"
          fontSize="34"
          fontStyle="italic"
          fontFamily="Bricolage Grotesque, serif"
          filter="url(#chalk)"
          style={{
            opacity: step === 4 ? 1 : 0,
            transition: 'opacity .4s .9s',
          }}
        >
          A
        </text>
        <text
          x="172"
          y="200"
          fill="var(--chalk-pink)"
          fontSize="15"
          fontFamily="DM Sans, sans-serif"
          fontWeight="700"
          filter="url(#chalk)"
          style={{
            opacity: step === 4 ? 1 : 0,
            transition: 'opacity .4s 1.1s',
          }}
        >
          = amplitude
        </text>
        <text
          x="172"
          y="220"
          fill="rgba(240,154,175,.7)"
          fontSize="12"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          style={{
            opacity: step === 4 ? 1 : 0,
            transition: 'opacity .4s 1.3s',
          }}
        >
          max displacement from rest
        </text>
        <line
          x1="235"
          y1="265"
          x2="235"
          y2="400"
          stroke="var(--chalk-pink)"
          strokeWidth="1.5"
          strokeDasharray="6,4"
          filter="url(#chalk)"
          style={{
            opacity: step === 4 ? 0.7 : 0,
            transition: 'opacity .4s 1.6s',
          }}
        />
      </g>

      {/* STEP 5: wavelength */}
      <g className={cn('wb-step', step === 5 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} stroke="rgba(255,255,255,.13)" />
        <path
          d={WAVE_D}
          fill="none"
          stroke="var(--chalk-blue)"
          strokeWidth="3"
          strokeLinecap="round"
          filter="url(#chalk)"
          opacity="0.5"
        />
        <line
          x1="145"
          y1="88"
          x2="325"
          y2="88"
          stroke="var(--chalk-green)"
          strokeWidth="2.5"
          filter="url(#chalk)"
          style={{
            strokeDasharray: 280,
            strokeDashoffset: step === 5 ? 0 : 280,
            transition: 'stroke-dashoffset .9s ease',
          }}
        />
        <line
          x1="145"
          y1="80"
          x2="145"
          y2="142"
          stroke="var(--chalk-green)"
          strokeWidth="1.5"
          strokeDasharray="5,3"
          filter="url(#chalk)"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .3s .8s',
          }}
        />
        <line
          x1="325"
          y1="80"
          x2="325"
          y2="142"
          stroke="var(--chalk-green)"
          strokeWidth="1.5"
          strokeDasharray="5,3"
          filter="url(#chalk)"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .3s .8s',
          }}
        />
        <polygon
          points="145,88 159,82 159,94"
          fill="var(--chalk-green)"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .3s .6s',
          }}
        />
        <polygon
          points="325,88 311,82 311,94"
          fill="var(--chalk-green)"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .3s .6s',
          }}
        />
        <text
          x="235"
          y="75"
          textAnchor="middle"
          fill="var(--chalk-green)"
          fontSize="32"
          fontStyle="italic"
          fontFamily="Bricolage Grotesque, serif"
          filter="url(#chalk)"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .5s .9s',
          }}
        >
          λ
        </text>
        <text
          x="350"
          y="75"
          fill="var(--chalk-green)"
          fontSize="15"
          fontFamily="DM Sans, sans-serif"
          fontWeight="700"
          filter="url(#chalk)"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .4s 1.1s',
          }}
        >
          = wavelength
        </text>
        <text
          x="350"
          y="93"
          fill="rgba(125,212,168,.7)"
          fontSize="12"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          style={{
            opacity: step === 5 ? 1 : 0,
            transition: 'opacity .4s 1.3s',
          }}
        >
          one full cycle · metres
        </text>
      </g>

      {/* STEP 6: frequency & period */}
      <g className={cn('wb-step', step === 6 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} stroke="rgba(255,255,255,.1)" />
        <path
          d={WAVE_D}
          fill="none"
          stroke="var(--chalk-blue)"
          strokeWidth="2.5"
          strokeLinecap="round"
          filter="url(#chalk)"
          opacity="0.4"
        />
        <text
          x="120"
          y="170"
          fill="var(--chalk-yellow)"
          fontSize="26"
          fontWeight="700"
          fontFamily="DM Sans, sans-serif"
          filter="url(#chalk)"
          style={{
            opacity: step === 6 ? 1 : 0,
            transition: 'opacity .5s',
          }}
        >
          f = frequency
        </text>
        <text
          x="120"
          y="195"
          fill="rgba(245,224,103,.65)"
          fontSize="13"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          style={{
            opacity: step === 6 ? 1 : 0,
            transition: 'opacity .4s .3s',
          }}
        >
          cycles per second · Hz
        </text>
        <text
          x="120"
          y="265"
          fill="rgba(255,255,255,.82)"
          fontSize="26"
          fontWeight="700"
          fontFamily="DM Sans, sans-serif"
          filter="url(#chalk)"
          style={{
            opacity: step === 6 ? 1 : 0,
            transition: 'opacity .5s .6s',
          }}
        >
          T = period
        </text>
        <text
          x="120"
          y="290"
          fill="rgba(255,255,255,.5)"
          fontSize="13"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          style={{
            opacity: step === 6 ? 1 : 0,
            transition: 'opacity .4s .9s',
          }}
        >
          time for one full cycle · seconds
        </text>
        <rect
          x="120"
          y="320"
          width="280"
          height="58"
          rx="10"
          fill="rgba(245,224,103,.07)"
          stroke="rgba(245,224,103,.25)"
          strokeWidth="1.5"
          style={{
            opacity: step === 6 ? 1 : 0,
            transition: 'opacity .4s 1.2s',
          }}
        />
        <text
          x="260"
          y="358"
          textAnchor="middle"
          fill="var(--chalk-yellow)"
          fontSize="22"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#chalk)"
          style={{
            opacity: step === 6 ? 1 : 0,
            transition: 'opacity .5s 1.3s',
          }}
        >
          T = 1 / f
        </text>
      </g>

      {/* STEP 7: wave equation */}
      <g className={cn('wb-step', step === 7 && 'active')}>
        <line x1="60" y1="265" x2="840" y2="265" {...baseLine} stroke="rgba(255,255,255,.08)" />
        <path
          d={WAVE_D}
          fill="none"
          stroke="var(--chalk-blue)"
          strokeWidth="2"
          strokeLinecap="round"
          filter="url(#chalk)"
          opacity="0.22"
        />
        <rect
          x="255"
          y="130"
          width="390"
          height="100"
          rx="16"
          fill="rgba(255,255,255,.04)"
          stroke="rgba(255,255,255,.16)"
          strokeWidth="1.5"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .5s',
          }}
        />
        <text
          x="450"
          y="195"
          textAnchor="middle"
          fill="var(--chalk)"
          fontSize="48"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#glow)"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .6s',
          }}
        >
          v = f · λ
        </text>
        <text
          x="270"
          y="270"
          fill="rgba(168,196,232,.85)"
          fontSize="14"
          fontFamily="DM Sans, sans-serif"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .4s .4s',
          }}
        >
          v = wave speed (m/s)
        </text>
        <text
          x="270"
          y="295"
          fill="rgba(245,224,103,.85)"
          fontSize="14"
          fontFamily="DM Sans, sans-serif"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .4s .7s',
          }}
        >
          f = frequency (Hz)
        </text>
        <text
          x="270"
          y="320"
          fill="rgba(125,212,168,.85)"
          fontSize="14"
          fontFamily="DM Sans, sans-serif"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .4s 1.0s',
          }}
        >
          λ = wavelength (m)
        </text>
        <rect
          x="270"
          y="350"
          width="360"
          height="58"
          rx="10"
          fill="rgba(125,212,168,.08)"
          stroke="rgba(125,212,168,.25)"
          strokeWidth="1.5"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .5s 1.3s',
          }}
        />
        <text
          x="288"
          y="375"
          fill="rgba(255,255,255,.7)"
          fontSize="12.5"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .4s 1.5s',
          }}
        >
          Example: f = 5 Hz, λ = 2 m
        </text>
        <text
          x="288"
          y="396"
          fill="var(--chalk-green)"
          fontSize="15"
          fontFamily="DM Sans, sans-serif"
          fontWeight="700"
          style={{
            opacity: step === 7 ? 1 : 0,
            transition: 'opacity .4s 1.8s',
          }}
        >
          ∴ v = 5 × 2 = 10 m/s
        </text>
      </g>
    </>
  );
}
