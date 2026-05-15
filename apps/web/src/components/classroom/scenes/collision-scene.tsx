/**
 * CollisionScene — a two-body collision drawn as before/after rows. Each
 * body is a labelled square with a velocity arrow whose length is set by
 * the speed and whose direction follows the sign of `vx`.
 *
 * params:
 *   title?:  string
 *   before?: { label:string; vx:number; color?:string }[]   — vx ~ -8..8
 *   after?:  { label:string; vx:number; color?:string }[]
 *
 * Drawing timeline:
 *   [0,  .5]  "BEFORE" caption + its two blocks & arrows (upper half)
 *   [.5, 1]   "AFTER" caption + its two blocks & arrows (lower half)
 */
import {
  chalkStroke,
  CHALK,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const BLOCK = 86; // square side length
const ROW_X = [300, 600]; // centre x of the two blocks
const ARROW_SCALE = 13; // px of arrow per unit of |vx|
const ARROW_MAX = 110;

const COLORS: Record<string, string> = {
  blue: CHALK.blue,
  yellow: CHALK.yellow,
  pink: CHALK.pink,
  green: CHALK.green,
};

interface Body {
  label: string;
  vx: number;
  color?: string;
}

const DEFAULT_BEFORE: Body[] = [
  { label: 'A', vx: 6, color: 'blue' },
  { label: 'B', vx: 0, color: 'pink' },
];
const DEFAULT_AFTER: Body[] = [
  { label: 'A', vx: 2, color: 'blue' },
  { label: 'B', vx: 5, color: 'pink' },
];

function coerceBodies(raw: unknown, fallback: Body[]): Body[] {
  if (!Array.isArray(raw)) return fallback;
  const bodies = raw
    .filter((b): b is Body => !!b && typeof b === 'object')
    .map((b) => ({
      label: typeof b.label === 'string' ? b.label : '',
      vx: typeof b.vx === 'number' && Number.isFinite(b.vx) ? b.vx : 0,
      color: typeof b.color === 'string' ? b.color : undefined,
    }))
    .slice(0, 2);
  return bodies.length > 0 ? bodies : fallback;
}

/** One labelled block with a velocity arrow, revealed over [start, end]. */
function Row({
  bodies,
  caption,
  cy,
  progress,
  start,
  end,
}: {
  bodies: Body[];
  caption: string;
  cy: number;
  progress: number;
  start: number;
  end: number;
}) {
  const capLocal = revealWindow(progress, start, start + 0.08);
  const span = end - start;

  return (
    <g>
      {/* row caption */}
      <text
        x="120"
        y={cy + 6}
        textAnchor="middle"
        fill={CHALK.white}
        fontSize="22"
        fontFamily="Bricolage Grotesque, serif"
        fontStyle="italic"
        filter="url(#chalk)"
        opacity={capLocal}
      >
        {caption}
      </text>

      {bodies.map((body, i) => {
        const cx = ROW_X[i] ?? ROW_X[0] ?? 300;
        // each block reveals in its own half of the row window
        const slot = start + 0.1 + (i / bodies.length) * (span - 0.1);
        const slotW = (span - 0.1) / bodies.length;
        const blockLocal = revealWindow(progress, slot, slot + slotW * 0.55);
        const arrowLocal = revealWindow(
          progress,
          slot + slotW * 0.4,
          slot + slotW,
        );

        const color = COLORS[body.color ?? ''] ?? CHALK.blue;
        const x = cx - BLOCK / 2;
        const y = cy - BLOCK / 2;
        const perim = BLOCK * 4;

        const speed = Math.abs(body.vx);
        const dir = body.vx >= 0 ? 1 : -1;
        const fullLen = Math.min(ARROW_MAX, speed * ARROW_SCALE);
        const len = fullLen * arrowLocal;
        const ax0 = cx + dir * (BLOCK / 2 + 6);
        const tipX = ax0 + dir * len;
        const ay = cy;

        return (
          <g key={i}>
            {/* block square — strokes "draw on" */}
            <rect
              x={x}
              y={y}
              width={BLOCK}
              height={BLOCK}
              fill={color}
              fillOpacity={0.18}
              stroke={color}
              strokeWidth="3"
              strokeLinejoin="round"
              filter="url(#chalk)"
              {...chalkStroke(perim, blockLocal)}
            />
            {/* block label */}
            <text
              x={cx}
              y={cy + 8}
              textAnchor="middle"
              fill={color}
              fontSize="30"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={blockLocal}
            >
              {body.label}
            </text>

            {/* velocity arrow (only when the body is moving) */}
            {speed > 0 ? (
              <g opacity={arrowLocal > 0 ? 1 : 0}>
                <line
                  x1={ax0}
                  y1={ay}
                  x2={tipX}
                  y2={ay}
                  stroke={CHALK.yellow}
                  strokeWidth="3"
                  strokeLinecap="round"
                  filter="url(#chalk)"
                />
                <polygon
                  points={`${tipX},${ay} ${tipX - dir * 13},${ay - 7} ${tipX - dir * 13},${ay + 7}`}
                  fill={CHALK.yellow}
                  opacity={revealWindow(
                    progress,
                    slot + slotW * 0.85,
                    slot + slotW,
                  )}
                />
                <text
                  x={ax0 + dir * (fullLen / 2)}
                  y={ay - 16}
                  textAnchor="middle"
                  fill={CHALK.yellow}
                  fontSize="16"
                  fontFamily="DM Sans, sans-serif"
                  filter="url(#chalk)"
                  opacity={revealWindow(
                    progress,
                    slot + slotW * 0.8,
                    slot + slotW,
                  )}
                >
                  v = {body.vx}
                </text>
              </g>
            ) : (
              <text
                x={cx}
                y={cy + BLOCK / 2 + 26}
                textAnchor="middle"
                fill="rgba(255,255,255,.55)"
                fontSize="15"
                fontFamily="DM Sans, sans-serif"
                opacity={blockLocal}
              >
                at rest
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

export const CollisionScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const before = coerceBodies(params.before, DEFAULT_BEFORE);
  const after = coerceBodies(params.after, DEFAULT_AFTER);

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="450"
          y="56"
          textAnchor="middle"
          fill={CHALK.white}
          fontSize="26"
          fontFamily="Bricolage Grotesque, serif"
          fontStyle="italic"
          filter="url(#chalk)"
          opacity={revealWindow(progress, 0, 0.1)}
        >
          {title}
        </text>
      ) : null}

      <Row
        bodies={before}
        caption="BEFORE"
        cy={190}
        progress={progress}
        start={0}
        end={0.5}
      />

      {/* dividing line between the two rows */}
      <line
        x1="90"
        y1="280"
        x2="810"
        y2="280"
        stroke={CHALK.faint}
        strokeWidth="2"
        strokeDasharray="6,8"
        opacity={revealWindow(progress, 0.46, 0.56)}
      />

      <Row
        bodies={after}
        caption="AFTER"
        cy={370}
        progress={progress}
        start={0.5}
        end={1}
      />
    </g>
  );
};
