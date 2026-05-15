/**
 * ProjectileArcScene — a projectile's parabolic trajectory arcing over a
 * ground line, drawn left→right as the audio plays.
 *
 * params:
 *   title?:         string
 *   launchAngle?:   number  (degrees, default 45) — tunes the peak height
 *   apexLabel?:     string  (default "apex")      — label at the arc peak
 *   showVelocity?:  boolean (default false)       — tangent velocity arrows
 *
 * Drawing timeline:
 *   [0,   .15]  ground line draws on
 *   [.15, .82]  parabola path draws on left→right (partial-`d` from progress)
 *   [.82, .95]  apex marker + label appear
 *   [.60, 1.0]  if showVelocity, tangent velocity arrows fade in
 */
import {
  CHALK,
  chalkStroke,
  numParam,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const X_START = 120;
const X_END = 780;
const GROUND_Y = 430;

export const ProjectileArcScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const apexLabel = strParam(params, 'apexLabel', 'apex');
  const showVelocity = params.showVelocity === true;

  // Clamp launch angle to a sane range so the arc always stays on-board.
  const angleDeg = Math.max(15, Math.min(80, numParam(params, 'launchAngle', 45)));
  // Peak height scales with sin(angle); 45° gives a clean mid-height arc.
  const maxRise = 230;
  const peakRise = maxRise * Math.sin((angleDeg * Math.PI) / 180);
  const apexX = (X_START + X_END) / 2;
  const apexY = GROUND_Y - peakRise;

  // Parabola y(x): downward-opening, peak at (apexX, apexY), roots at the ends.
  const span = (X_END - X_START) / 2;
  const yAt = (x: number) => {
    const dx = x - apexX;
    return apexY + (peakRise / (span * span)) * dx * dx;
  };

  // Build the arc as a polyline of sample points so we can draw a *partial*
  // path from progress without touching the DOM.
  const SAMPLES = 64;
  const arcPts: { x: number; y: number }[] = [];
  for (let i = 0; i <= SAMPLES; i++) {
    const x = X_START + (i / SAMPLES) * (X_END - X_START);
    arcPts.push({ x, y: yAt(x) });
  }

  // Approximate total arc length for chalkStroke.
  let arcLen = 0;
  for (let i = 1; i < arcPts.length; i++) {
    const a = arcPts[i - 1];
    const b = arcPts[i];
    if (!a || !b) continue;
    arcLen += Math.hypot(b.x - a.x, b.y - a.y);
  }
  const arcPath = arcPts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`)
    .join(' ');

  const arcLocal = revealWindow(progress, 0.15, 0.82);

  // Projectile dot rides the arc tip as it draws.
  const tipIdx = Math.min(
    arcPts.length - 1,
    Math.round(arcLocal * (arcPts.length - 1)),
  );
  const tip = arcPts[tipIdx] ?? { x: X_START, y: GROUND_Y };

  // Velocity arrows at three fractions along the path.
  const velFracs = [0.22, 0.5, 0.78];

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="92"
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

      {/* Ground line */}
      <line
        x1={X_START - 30}
        y1={GROUND_Y}
        x2={X_END + 30}
        y2={GROUND_Y}
        stroke={CHALK.white}
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        {...chalkStroke(X_END - X_START + 60, revealWindow(progress, 0, 0.15))}
      />

      {/* Parabolic trajectory — draws on left→right */}
      <path
        d={arcPath}
        fill="none"
        stroke={CHALK.yellow}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#chalk)"
        {...chalkStroke(arcLen, arcLocal)}
      />

      {/* Projectile dot riding the path tip */}
      {arcLocal > 0 && arcLocal < 1 ? (
        <circle
          cx={tip.x}
          cy={tip.y}
          r="8"
          fill={CHALK.yellow}
          filter="url(#glow)"
        />
      ) : null}

      {/* Velocity tangent arrows */}
      {showVelocity
        ? velFracs.map((frac, i) => {
            const local = revealWindow(progress, 0.6 + i * 0.12, 0.78 + i * 0.12);
            if (local <= 0) return null;
            const x = X_START + frac * (X_END - X_START);
            const y = yAt(x);
            // Tangent slope dy/dx = 2k*dx.
            const k = peakRise / (span * span);
            const slope = 2 * k * (x - apexX);
            const dirMag = Math.hypot(1, slope);
            const ux = 1 / dirMag;
            const uy = slope / dirMag;
            const aLen = 56 * local;
            const ex = x + ux * aLen;
            const ey = y + uy * aLen;
            const headLen = 12;
            const headW = 6;
            const px = -uy;
            const py = ux;
            const bx = ex - ux * headLen;
            const by = ey - uy * headLen;
            return (
              <g key={i} opacity={local}>
                <line
                  x1={x}
                  y1={y}
                  x2={ex}
                  y2={ey}
                  stroke={CHALK.blue}
                  strokeWidth="3"
                  strokeLinecap="round"
                  filter="url(#chalk)"
                />
                <polygon
                  points={`${ex},${ey} ${bx + px * headW},${by + py * headW} ${bx - px * headW},${by - py * headW}`}
                  fill={CHALK.blue}
                  filter="url(#chalk)"
                />
                <text
                  x={ex + ux * 14}
                  y={ey + uy * 14 + 4}
                  textAnchor="middle"
                  fill={CHALK.blue}
                  fontSize="14"
                  fontFamily="DM Sans, sans-serif"
                >
                  v
                </text>
              </g>
            );
          })
        : null}

      {/* Apex marker + label */}
      {(() => {
        const local = revealWindow(progress, 0.82, 0.95);
        if (local <= 0) return null;
        return (
          <g opacity={local}>
            <line
              x1={apexX}
              y1={apexY}
              x2={apexX}
              y2={GROUND_Y}
              stroke="rgba(245,224,103,.4)"
              strokeWidth="1.5"
              strokeDasharray="4,4"
            />
            <circle
              cx={apexX}
              cy={apexY}
              r={6 * local}
              fill={CHALK.pink}
              filter="url(#chalk)"
            />
            <text
              x={apexX}
              y={apexY - 18}
              textAnchor="middle"
              fill={CHALK.pink}
              fontSize="20"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
            >
              {apexLabel}
            </text>
          </g>
        );
      })()}

      {/* Launch angle annotation at the start point */}
      {(() => {
        const local = revealWindow(progress, 0.2, 0.34);
        if (local <= 0) return null;
        return (
          <text
            x={X_START - 6}
            y={GROUND_Y + 24}
            textAnchor="middle"
            fill="rgba(255,255,255,.6)"
            fontSize="14"
            fontFamily="DM Sans, sans-serif"
            opacity={local}
          >
            {Math.round(angleDeg)}°
          </text>
        );
      })()}
    </g>
  );
};
