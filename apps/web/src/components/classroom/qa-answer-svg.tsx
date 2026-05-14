export type QATopic = 'amplitude' | 'wavelength' | 'equation' | null;

interface QAAnswerSVGProps {
  topic: QATopic;
}

/**
 * Pre-built chalk-drawn answers for keyword-matched Q&A topics.
 * Ported verbatim from prototype `whiteboard.jsx` `QAAnswerSVG`.
 */
export function QAAnswerSVG({ topic }: QAAnswerSVGProps) {
  return (
    <svg
      viewBox="0 0 900 530"
      preserveAspectRatio="xMidYMid meet"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 1,
      }}
      aria-hidden="true"
    >
      <defs>
        <filter id="qa-chalk">
          <feTurbulence
            type="fractalNoise"
            baseFrequency=".7"
            numOctaves="3"
            stitchTiles="stitch"
            result="n"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="n"
            scale="2"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>

      {topic === 'amplitude' && (
        <g key="amp">
          <line
            x1="60"
            y1="265"
            x2="840"
            y2="265"
            stroke="rgba(255,255,255,.15)"
            strokeWidth="1.5"
            strokeDasharray="8,5"
            filter="url(#qa-chalk)"
          />
          <path
            d="M60,265 Q170,130 280,265 T500,265 T720,265 T840,265"
            fill="none"
            stroke="var(--chalk-blue)"
            strokeWidth="3"
            filter="url(#qa-chalk)"
            style={{
              strokeDasharray: 1200,
              strokeDashoffset: 1200,
              animation: 'draw 1.6s ease-out forwards',
            }}
          />
          <line
            x1="170"
            y1="265"
            x2="170"
            y2="130"
            stroke="var(--chalk-pink)"
            strokeWidth="3"
            filter="url(#qa-chalk)"
            style={{
              strokeDasharray: 200,
              strokeDashoffset: 200,
              animation: 'draw .9s ease 1.6s forwards',
            }}
          />
          <polygon
            points="170,130 162,150 178,150"
            fill="var(--chalk-pink)"
            style={{ opacity: 0, animation: 'fade-in .3s ease 2.4s forwards' }}
          />
          <polygon
            points="170,265 162,245 178,245"
            fill="var(--chalk-pink)"
            style={{ opacity: 0, animation: 'fade-in .3s ease 2.4s forwards' }}
          />
          <text
            x="190"
            y="205"
            fill="var(--chalk-pink)"
            fontSize="32"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            style={{ opacity: 0, animation: 'fade-in .4s ease 2.6s forwards' }}
          >
            A = amplitude
          </text>
          <text
            x="190"
            y="232"
            fill="rgba(240,154,175,.7)"
            fontSize="14"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            style={{ opacity: 0, animation: 'fade-in .4s ease 2.9s forwards' }}
          >
            height from rest to crest
          </text>
        </g>
      )}

      {topic === 'wavelength' && (
        <g key="wl">
          <path
            d="M60,265 Q160,130 260,265 T460,265 T660,265 T860,265"
            fill="none"
            stroke="var(--chalk-blue)"
            strokeWidth="3"
            filter="url(#qa-chalk)"
            opacity="0.6"
            style={{
              strokeDasharray: 1200,
              strokeDashoffset: 1200,
              animation: 'draw 1.2s ease-out forwards',
            }}
          />
          <line
            x1="60"
            y1="100"
            x2="260"
            y2="100"
            stroke="var(--chalk-green)"
            strokeWidth="3"
            filter="url(#qa-chalk)"
            style={{
              strokeDasharray: 240,
              strokeDashoffset: 240,
              animation: 'draw .9s ease 1.2s forwards',
            }}
          />
          <polygon
            points="60,100 78,92 78,108"
            fill="var(--chalk-green)"
            style={{ opacity: 0, animation: 'fade-in .3s ease 2s forwards' }}
          />
          <polygon
            points="260,100 242,92 242,108"
            fill="var(--chalk-green)"
            style={{ opacity: 0, animation: 'fade-in .3s ease 2s forwards' }}
          />
          <text
            x="160"
            y="86"
            textAnchor="middle"
            fill="var(--chalk-green)"
            fontSize="36"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            style={{ opacity: 0, animation: 'fade-in .4s ease 2.2s forwards' }}
          >
            λ
          </text>
          <text
            x="290"
            y="92"
            fill="var(--chalk-green)"
            fontSize="18"
            fontFamily="DM Sans, sans-serif"
            fontWeight="700"
            style={{ opacity: 0, animation: 'fade-in .4s ease 2.5s forwards' }}
          >
            = wavelength
          </text>
          <text
            x="290"
            y="116"
            fill="rgba(125,212,168,.7)"
            fontSize="13"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            style={{ opacity: 0, animation: 'fade-in .4s ease 2.8s forwards' }}
          >
            one full cycle, peak to peak
          </text>
        </g>
      )}

      {topic === 'equation' && (
        <g key="eq">
          <rect
            x="260"
            y="160"
            width="380"
            height="120"
            rx="18"
            fill="rgba(255,255,255,.05)"
            stroke="rgba(255,200,87,.4)"
            strokeWidth="2"
            filter="url(#qa-chalk)"
            style={{ opacity: 0, animation: 'fade-in .5s ease forwards' }}
          />
          <text
            x="450"
            y="240"
            textAnchor="middle"
            fill="var(--chalk-yellow)"
            fontSize="56"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            style={{ opacity: 0, animation: 'fade-in .6s ease .4s forwards' }}
          >
            v = f · λ
          </text>
          <text
            x="450"
            y="324"
            textAnchor="middle"
            fill="rgba(255,255,255,.7)"
            fontSize="14"
            fontFamily="Bricolage Grotesque, serif"
            fontStyle="italic"
            style={{ opacity: 0, animation: 'fade-in .4s ease 1.2s forwards' }}
          >
            speed = frequency × wavelength
          </text>
        </g>
      )}
    </svg>
  );
}
