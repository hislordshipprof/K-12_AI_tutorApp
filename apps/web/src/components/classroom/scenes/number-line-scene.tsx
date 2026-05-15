/**
 * NumberLineScene — a horizontal axis with labelled positions and an
 * optional displacement arrow. The reference scene implementation; other
 * scenes follow the same shape (see `types.ts` for the contract).
 *
 * params:
 *   title?:  string                          — caption above the line
 *   unit?:   string                          — axis unit label, e.g. "m"
 *   min?:    number  (default 0)              — value at the left end
 *   max?:    number  (default 10)             — value at the right end
 *   points?: { value:number; label:string; color?:'blue'|'yellow'|'pink'|'green' }[]
 *   arrow?:  { from:number; to:number; label:string }   — displacement vector
 *
 * Drawing timeline:
 *   [0,    .22]  axis line draws on left→right
 *   [.22,  .60]  points appear in sequence
 *   [.60, 1.0]   displacement arrow draws on
 */
import {
  CHALK,
  chalkStroke,
  numParam,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const X0 = 90; // left edge of the axis in viewBox units
const X1 = 810; // right edge
const Y = 300; // axis y-position
const COLORS: Record<string, string> = {
  blue: CHALK.blue,
  yellow: CHALK.yellow,
  pink: CHALK.pink,
  green: CHALK.green,
};

interface LinePoint {
  value: number;
  label: string;
  color?: string;
}
interface LineArrow {
  from: number;
  to: number;
  label: string;
}

export const NumberLineScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const unit = strParam(params, 'unit', '');
  const min = numParam(params, 'min', 0);
  const max = numParam(params, 'max', 10);
  const span = max - min || 1;

  const rawPoints = Array.isArray(params.points) ? params.points : [];
  const points: LinePoint[] = rawPoints
    .filter((p): p is LinePoint => !!p && typeof p === 'object')
    .slice(0, 6);
  const arrow =
    params.arrow && typeof params.arrow === 'object'
      ? (params.arrow as LineArrow)
      : null;

  const toX = (value: number) => X0 + ((value - min) / span) * (X1 - X0);

  const axisLen = X1 - X0;
  const axisLocal = revealWindow(progress, 0, 0.22);

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="170"
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

      {/* Axis line — draws left→right */}
      <line
        x1={X0}
        y1={Y}
        x2={X1}
        y2={Y}
        stroke={CHALK.white}
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        {...chalkStroke(axisLen, axisLocal)}
      />
      {/* Right-end arrowhead */}
      <polygon
        points={`${X1},${Y} ${X1 - 14},${Y - 7} ${X1 - 14},${Y + 7}`}
        fill={CHALK.white}
        opacity={revealWindow(progress, 0.18, 0.24)}
      />
      {/* Axis unit label */}
      {unit ? (
        <text
          x={X1 + 6}
          y={Y + 5}
          fill="rgba(255,255,255,.55)"
          fontSize="15"
          fontFamily="DM Sans, sans-serif"
          opacity={revealWindow(progress, 0.2, 0.28)}
        >
          {unit}
        </text>
      ) : null}

      {/* Position points — appear in sequence over [.22, .60] */}
      {points.map((p, i) => {
        const slot = 0.22 + (i / Math.max(1, points.length)) * 0.38;
        const local = revealWindow(progress, slot, slot + 0.1);
        const cx = toX(p.value);
        const color = COLORS[p.color ?? ''] ?? CHALK.yellow;
        return (
          <g key={i} opacity={local}>
            {/* tick */}
            <line
              x1={cx}
              y1={Y - 10}
              x2={cx}
              y2={Y + 10}
              stroke={color}
              strokeWidth="3"
              filter="url(#chalk)"
            />
            {/* dot */}
            <circle
              cx={cx}
              cy={Y}
              r={6 * local}
              fill={color}
              filter="url(#chalk)"
            />
            {/* label above */}
            <text
              x={cx}
              y={Y - 24}
              textAnchor="middle"
              fill={color}
              fontSize="20"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
            >
              {p.label}
            </text>
            {/* value below */}
            <text
              x={cx}
              y={Y + 34}
              textAnchor="middle"
              fill="rgba(255,255,255,.6)"
              fontSize="14"
              fontFamily="DM Sans, sans-serif"
            >
              {p.value}
              {unit ? ` ${unit}` : ''}
            </text>
          </g>
        );
      })}

      {/* Displacement arrow — draws on over [.60, 1.0] */}
      {arrow ? (
        (() => {
          const ax0 = toX(arrow.from);
          const ax1 = toX(arrow.to);
          const ay = Y - 70;
          const local = revealWindow(progress, 0.6, 0.92);
          const dir = ax1 >= ax0 ? 1 : -1;
          const tipX = ax0 + (ax1 - ax0) * local;
          return (
            <g>
              <line
                x1={ax0}
                y1={ay}
                x2={tipX}
                y2={ay}
                stroke={CHALK.pink}
                strokeWidth="3"
                strokeLinecap="round"
                filter="url(#chalk)"
              />
              <polygon
                points={`${tipX},${ay} ${tipX - dir * 14},${ay - 7} ${tipX - dir * 14},${ay + 7}`}
                fill={CHALK.pink}
                opacity={revealWindow(progress, 0.88, 0.94)}
              />
              {/* connector ticks down to the axis */}
              <line
                x1={ax0}
                y1={ay}
                x2={ax0}
                y2={Y}
                stroke="rgba(240,154,175,.4)"
                strokeWidth="1.5"
                strokeDasharray="4,4"
                opacity={local}
              />
              <line
                x1={ax1}
                y1={ay}
                x2={ax1}
                y2={Y}
                stroke="rgba(240,154,175,.4)"
                strokeWidth="1.5"
                strokeDasharray="4,4"
                opacity={revealWindow(progress, 0.85, 1)}
              />
              <text
                x={(ax0 + ax1) / 2}
                y={ay - 14}
                textAnchor="middle"
                fill={CHALK.pink}
                fontSize="20"
                fontFamily="Bricolage Grotesque, serif"
                fontStyle="italic"
                filter="url(#chalk)"
                opacity={revealWindow(progress, 0.92, 1)}
              >
                {arrow.label}
              </text>
            </g>
          );
        })()
      ) : null}
    </g>
  );
};
