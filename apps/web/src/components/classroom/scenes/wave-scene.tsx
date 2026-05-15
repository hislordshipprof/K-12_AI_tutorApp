/**
 * WaveScene — a transverse sine wave on an equilibrium line, with optional
 * amplitude / wavelength annotations. Follows the scene contract in
 * `types.ts`; matches NumberLineScene's style.
 *
 * params:
 *   title?:  string                                      — caption above
 *   label?:  'wavelength' | 'amplitude' | 'both' | 'none' (default 'both')
 *   cycles?: number  (default 2.5)                        — full waves shown
 *
 * Drawing timeline:
 *   [0,    .18]  equilibrium dashed line draws on left→right
 *   [.18,  .72]  the sine wave path draws on left→right
 *   [.72,  .86]  amplitude double-arrow (if label includes 'amplitude')
 *   [.86, 1.0]   wavelength double-arrow (if label includes 'wavelength')
 */
import {
  CHALK,
  chalkStroke,
  numParam,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const X0 = 90; // left edge of the wave
const X1 = 810; // right edge
const Y = 270; // equilibrium y-position
const AMP = 95; // amplitude in viewBox px
const SAMPLES = 160; // path resolution

export const WaveScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const labelRaw = strParam(params, 'label', 'both');
  const label =
    labelRaw === 'wavelength' ||
    labelRaw === 'amplitude' ||
    labelRaw === 'both' ||
    labelRaw === 'none'
      ? labelRaw
      : 'both';
  const showAmp = label === 'amplitude' || label === 'both';
  const showWave = label === 'wavelength' || label === 'both';

  // clamp cycles to something that renders sensibly
  const cycles = Math.max(0.5, Math.min(6, numParam(params, 'cycles', 2.5)));
  const span = X1 - X0;

  // y of the sine wave at a given x (first crest sits up = negative dy)
  const waveY = (x: number) => {
    const phase = ((x - X0) / span) * cycles * 2 * Math.PI;
    return Y - AMP * Math.sin(phase);
  };

  // Build the full sine path and approximate its arc length so chalkStroke
  // can "draw it on" left→right.
  let d = `M ${X0} ${waveY(X0)}`;
  let pathLen = 0;
  let prevX = X0;
  let prevY = waveY(X0);
  for (let i = 1; i <= SAMPLES; i++) {
    const x = X0 + (span * i) / SAMPLES;
    const y = waveY(x);
    d += ` L ${x.toFixed(2)} ${y.toFixed(2)}`;
    pathLen += Math.hypot(x - prevX, y - prevY);
    prevX = x;
    prevY = y;
  }

  const waveLocal = revealWindow(progress, 0.18, 0.72);

  // First crest is a quarter cycle in from the left edge.
  const crestX = X0 + span / (cycles * 4);
  const crestY = Y - AMP;

  // One full wavelength, placed near the start of the wave.
  const lambda = span / cycles;
  const wlX0 = X0;
  const wlX1 = X0 + lambda;
  const wlY = Y + AMP + 46;

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="70"
          textAnchor="middle"
          fill={CHALK.white}
          fontSize="26"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#chalk)"
          opacity={revealWindow(progress, 0, 0.12)}
        >
          {title}
        </text>
      ) : null}

      {/* Equilibrium line — draws left→right */}
      <line
        x1={X0}
        y1={Y}
        x2={X0 + (X1 - X0) * revealWindow(progress, 0, 0.18)}
        y2={Y}
        stroke="rgba(255,255,255,.5)"
        strokeWidth="2"
        strokeDasharray="7,7"
        strokeLinecap="round"
        filter="url(#chalk)"
      />
      <text
        x={X1 + 6}
        y={Y + 5}
        fill="rgba(255,255,255,.5)"
        fontSize="14"
        fontFamily="DM Sans, sans-serif"
        opacity={revealWindow(progress, 0.12, 0.2)}
      >
        equilibrium
      </text>

      {/* Sine wave path — draws on left→right */}
      <path
        d={d}
        fill="none"
        stroke={CHALK.blue}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#chalk)"
        {...chalkStroke(pathLen, waveLocal)}
      />

      {/* Amplitude double-arrow — equilibrium → crest */}
      {showAmp ? (
        (() => {
          const local = revealWindow(progress, 0.72, 0.86);
          if (local <= 0) return null;
          const tipY = Y - AMP * local;
          return (
            <g>
              {/* shaft */}
              <line
                x1={crestX}
                y1={Y}
                x2={crestX}
                y2={tipY}
                stroke={CHALK.pink}
                strokeWidth="3"
                strokeLinecap="round"
                filter="url(#chalk)"
              />
              {/* arrowhead at crest (points up) */}
              <polygon
                points={`${crestX},${crestY} ${crestX - 7},${crestY + 14} ${crestX + 7},${crestY + 14}`}
                fill={CHALK.pink}
                opacity={revealWindow(progress, 0.82, 0.86)}
              />
              {/* arrowhead at equilibrium (points down) */}
              <polygon
                points={`${crestX},${Y} ${crestX - 7},${Y - 14} ${crestX + 7},${Y - 14}`}
                fill={CHALK.pink}
                opacity={revealWindow(progress, 0.82, 0.86)}
              />
              <text
                x={crestX + 18}
                y={(Y + crestY) / 2 + 7}
                fill={CHALK.pink}
                fontSize="22"
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={revealWindow(progress, 0.8, 0.86)}
              >
                A
              </text>
            </g>
          );
        })()
      ) : null}

      {/* Wavelength double-arrow — spans one full cycle */}
      {showWave ? (
        (() => {
          const local = revealWindow(progress, 0.86, 1);
          if (local <= 0) return null;
          const tipX = wlX0 + (wlX1 - wlX0) * local;
          return (
            <g>
              {/* drop guides from crests to the measure line */}
              <line
                x1={wlX0}
                y1={Y}
                x2={wlX0}
                y2={wlY}
                stroke="rgba(125,212,168,.4)"
                strokeWidth="1.5"
                strokeDasharray="4,4"
                opacity={local}
              />
              <line
                x1={wlX1}
                y1={Y}
                x2={wlX1}
                y2={wlY}
                stroke="rgba(125,212,168,.4)"
                strokeWidth="1.5"
                strokeDasharray="4,4"
                opacity={revealWindow(progress, 0.92, 1)}
              />
              {/* shaft */}
              <line
                x1={wlX0}
                y1={wlY}
                x2={tipX}
                y2={wlY}
                stroke={CHALK.green}
                strokeWidth="3"
                strokeLinecap="round"
                filter="url(#chalk)"
              />
              {/* arrowhead left (points left) */}
              <polygon
                points={`${wlX0},${wlY} ${wlX0 + 14},${wlY - 7} ${wlX0 + 14},${wlY + 7}`}
                fill={CHALK.green}
                opacity={revealWindow(progress, 0.96, 1)}
              />
              {/* arrowhead right (points right) */}
              <polygon
                points={`${wlX1},${wlY} ${wlX1 - 14},${wlY - 7} ${wlX1 - 14},${wlY + 7}`}
                fill={CHALK.green}
                opacity={revealWindow(progress, 0.96, 1)}
              />
              <text
                x={(wlX0 + wlX1) / 2}
                y={wlY + 26}
                textAnchor="middle"
                fill={CHALK.green}
                fontSize="22"
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={revealWindow(progress, 0.94, 1)}
              >
                λ
              </text>
            </g>
          );
        })()
      ) : null}
    </g>
  );
};
