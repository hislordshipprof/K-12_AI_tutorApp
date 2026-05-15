/**
 * EnergyBarChartScene — a chalkboard bar chart of energy quantities
 * (kinetic, potential, total, …). Each bar grows up from a shared baseline.
 *
 * params:
 *   title?:    string                              — caption above the chart
 *   bars?:     { label:string; value:number;
 *                color?:'blue'|'yellow'|'pink'|'green' }[]
 *   maxValue?: number   — chart ceiling (defaults to the largest bar value)
 *   unit?:     string   (default 'J')               — value unit suffix
 *
 * Drawing timeline:
 *   [0,   .22]  baseline + y-axis draw on
 *   [.22, .90]  each bar grows up in its own sub-window, sequentially;
 *               its value number + label fade in just after the bar finishes
 */
import {
  CHALK,
  chalkStroke,
  numParam,
  revealWindow,
  strParam,
  type SceneComponent,
} from './types';

const X_AXIS = 150; // y-axis x-position
const X_END = 800; // right edge of plotting area
const Y_BASE = 430; // baseline y-position
const Y_TOP = 100; // top of the y-axis
const BAR_MAX_H = 330; // pixel height of a full-scale bar

const COLORS: Record<string, string> = {
  blue: CHALK.blue,
  yellow: CHALK.yellow,
  pink: CHALK.pink,
  green: CHALK.green,
};

interface EnergyBar {
  label: string;
  value: number;
  color?: string;
}

const DEFAULT_BARS: EnergyBar[] = [
  { label: 'KE', value: 6, color: 'blue' },
  { label: 'PE', value: 4, color: 'yellow' },
  { label: 'Total', value: 10, color: 'green' },
];

export const EnergyBarChartScene: SceneComponent = ({ progress, params }) => {
  const title = strParam(params, 'title', '');
  const unit = strParam(params, 'unit', 'J');

  const rawBars = Array.isArray(params.bars) ? params.bars : [];
  let bars: EnergyBar[] = rawBars
    .filter((b): b is EnergyBar => !!b && typeof b === 'object')
    .map((b) => ({
      label: typeof b.label === 'string' ? b.label : '',
      value:
        typeof b.value === 'number' && Number.isFinite(b.value) ? b.value : 0,
      color: typeof b.color === 'string' ? b.color : undefined,
    }))
    .slice(0, 6);
  if (bars.length === 0) bars = DEFAULT_BARS;

  const largest = bars.reduce((m, b) => Math.max(m, b.value), 0) || 1;
  const maxValue = numParam(params, 'maxValue', largest) || largest;

  // Lay bars evenly across the plotting area with comfortable gaps.
  const plotW = X_END - X_AXIS;
  const slotW = plotW / bars.length;
  const barW = Math.min(110, slotW * 0.56);

  const axisLocal = revealWindow(progress, 0, 0.22);

  return (
    <g>
      {/* Title */}
      {title ? (
        <text
          x="475"
          y="64"
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

      {/* Y-axis — draws bottom→top */}
      <line
        x1={X_AXIS}
        y1={Y_BASE}
        x2={X_AXIS}
        y2={Y_TOP}
        stroke={CHALK.white}
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        {...chalkStroke(Y_BASE - Y_TOP, axisLocal)}
      />
      {/* Baseline — draws left→right */}
      <line
        x1={X_AXIS}
        y1={Y_BASE}
        x2={X_END}
        y2={Y_BASE}
        stroke={CHALK.white}
        strokeWidth="3"
        strokeLinecap="round"
        filter="url(#chalk)"
        {...chalkStroke(X_END - X_AXIS, axisLocal)}
      />
      {/* Y-axis "energy" caption */}
      <text
        x={X_AXIS - 16}
        y={Y_TOP + 4}
        textAnchor="end"
        fill="rgba(255,255,255,.55)"
        fontSize="15"
        fontFamily="DM Sans, sans-serif"
        opacity={revealWindow(progress, 0.16, 0.24)}
      >
        energy ({unit})
      </text>

      {/* Bars — grow up sequentially over [.22, .90] */}
      {bars.map((bar, i) => {
        const span = 0.9 - 0.22;
        const slot = 0.22 + (i / bars.length) * span;
        const grow = revealWindow(progress, slot, slot + span / bars.length);
        const labelLocal = revealWindow(
          progress,
          slot + (span / bars.length) * 0.7,
          slot + span / bars.length + 0.04,
        );

        const fullH = (Math.max(0, bar.value) / maxValue) * BAR_MAX_H;
        const h = fullH * grow;
        const cx = X_AXIS + slotW * (i + 0.5);
        const x = cx - barW / 2;
        const y = Y_BASE - h;
        const color = COLORS[bar.color ?? ''] ?? CHALK.blue;

        return (
          <g key={i}>
            {/* bar body */}
            <rect
              x={x}
              y={y}
              width={barW}
              height={h}
              fill={color}
              fillOpacity={0.22}
              stroke={color}
              strokeWidth="3"
              strokeLinejoin="round"
              filter="url(#chalk)"
              opacity={grow > 0 ? 1 : 0}
            />
            {/* value number above the bar */}
            <text
              x={cx}
              y={Y_BASE - fullH - 16}
              textAnchor="middle"
              fill={color}
              fontSize="22"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={labelLocal}
            >
              {bar.value}
              {unit ? ` ${unit}` : ''}
            </text>
            {/* label below the baseline */}
            <text
              x={cx}
              y={Y_BASE + 34}
              textAnchor="middle"
              fill={CHALK.white}
              fontSize="20"
              fontFamily="Bricolage Grotesque, serif"
              fontStyle="italic"
              filter="url(#chalk)"
              opacity={labelLocal}
            >
              {bar.label}
            </text>
          </g>
        );
      })}
    </g>
  );
};
