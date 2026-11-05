import { useState, type RefObject, type KeyboardEvent } from "react";
import { type Chunk, number } from "../../data/days";
import type { ChartSelection } from "../../data/visualizations";
import { useSvgWidth } from "../../lib/useSvgWidth";

const series = [
  { key: "records", label: "خام", color: "var(--chart-green)" },
  { key: "normalized", label: "نرمال‌شده", color: "var(--chart-blue)" },
  { key: "candidates", label: "کاندید", color: "var(--chart-lilac)" },
] as const;
export function activate(
  event: KeyboardEvent<SVGElement>,
  callback: () => void,
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    callback();
  }
}

export function VolumeChart({
  chunks,
  selection,
  onToggle,
  onRange,
  svgRef,
  bounds,
}: {
  chunks: Chunk[];
  selection: ChartSelection;
  onToggle: (index: number) => void;
  onRange: (range: [number, number] | null) => void;
  svgRef: RefObject<SVGSVGElement | null>;
  bounds: [number, number];
}) {
  const [visible, setVisible] = useState<string[]>(
    series.map((item) => item.key),
  );
  const [hovered, setHovered] = useState<number | null>(null);
  const viewportWidth = useSvgWidth(svgRef, 800);
  const left = 50,
    right = viewportWidth - 15,
    top = 24,
    bottom = 213;
  const max = Math.max(
    1,
    ...chunks.flatMap((chunk) =>
      series
        .filter((item) => visible.includes(item.key))
        .map((item) => chunk[item.key]),
    ),
  );
  const ceiling = Math.ceil(max / 50000) * 50000;
  const groupWidth = (right - left) / Math.max(chunks.length, 1);
  const barWidth = Math.min(24, groupWidth / 5);
  const [minimum, maximum] = bounds;
  const range = selection.range ?? [minimum, maximum];
  const focused = chunks.find((chunk) => chunk.index === hovered);
  return (
    <>
      <div className="chart-legend" aria-label="سری‌های حجم داده">
        {series.map((item) => (
          <button
            key={item.key}
            aria-pressed={visible.includes(item.key)}
            disabled={visible.length === 1 && visible.includes(item.key)}
            title={
              visible.length === 1 && visible.includes(item.key)
                ? "حداقل یک سری باید نمایش داده شود"
                : undefined
            }
            onClick={() =>
              setVisible((current) =>
                current.includes(item.key)
                  ? current.length > 1
                    ? current.filter((key) => key !== item.key)
                    : current
                  : [...current, item.key],
              )
            }
          >
            <i style={{ background: item.color }} />
            {item.label}
          </button>
        ))}
        <span>واحد: رکورد</span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${viewportWidth} 253`}
        className="volume-svg"
        role="group"
        aria-label="نمودار حجم داده؛ ستون هر چانک را برای فیلتر انتخاب کنید"
        direction="ltr"
      >
        <title>حجم رکورد خام، نرمال‌شده و کاندید هر چانک — ماک</title>
        <desc>
          انتخاب چند چانک با کلیک یا Enter؛ چانک‌ها ترتیب زمانی ندارند. برای
          اطلاعات دقیق از جدول داده‌ها استفاده کنید.
        </desc>
        {Array.from({ length: 5 }, (_, index) => {
          const y = bottom - (index / 4) * (bottom - top);
          return (
            <g key={index}>
              <line
                x1={left}
                x2={right}
                y1={y}
                y2={y}
                stroke="var(--chart-grid)"
                strokeDasharray={index ? "4 5" : undefined}
              />
              <text
                x={left - 12}
                y={y + 4}
                textAnchor="end"
                className="chart-axis"
              >
                {number(Math.round((ceiling * index) / 4000))}k
              </text>
            </g>
          );
        })}
        {chunks.map((chunk, index) => {
          const active =
            (!selection.chunks.length ||
              selection.chunks.includes(chunk.index)) &&
            (!selection.range ||
              (chunk.index >= range[0] && chunk.index <= range[1]));
          const middle = left + groupWidth * (index + 0.5);
          return (
            <g
              key={chunk.id}
              role="button"
              tabIndex={0}
              aria-label={`انتخاب چانک ${number(chunk.index)}؛ ${number(chunk.records)} رکورد خام`}
              aria-pressed={selection.chunks.includes(chunk.index)}
              className={`chart-bar-group${active ? "" : " muted"}`}
              onClick={() => onToggle(chunk.index)}
              onKeyDown={(event) =>
                activate(event, () => onToggle(chunk.index))
              }
              onMouseEnter={() => setHovered(chunk.index)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(chunk.index)}
              onBlur={() => setHovered(null)}
            >
              <rect
                x={middle - groupWidth * 0.42}
                y={top - 5}
                width={groupWidth * 0.84}
                height={bottom - top + 28}
                rx={6}
                fill={
                  selection.chunks.includes(chunk.index)
                    ? "var(--accent-soft)"
                    : "transparent"
                }
                stroke={
                  selection.chunks.includes(chunk.index)
                    ? "var(--accent-border)"
                    : "transparent"
                }
              />
              {series
                .filter((item) => visible.includes(item.key))
                .map((item, seriesIndex, displayed) => {
                  const height = (chunk[item.key] / ceiling) * (bottom - top);
                  return (
                    <rect
                      key={item.key}
                      x={
                        middle +
                        (seriesIndex - displayed.length / 2) * (barWidth + 5) +
                        2.5
                      }
                      y={bottom - height}
                      width={barWidth}
                      height={height}
                      fill={item.color}
                      rx={3}
                    />
                  );
                })}
              <text
                x={middle}
                y={bottom + 24}
                textAnchor="middle"
                className="chart-axis"
              >
                چانک {number(chunk.index)}
              </text>
              <title>{`چانک ${number(chunk.index)} — خام: ${number(chunk.records)}، نرمال‌شده: ${number(chunk.normalized)}، کاندید: ${number(chunk.candidates)}`}</title>
            </g>
          );
        })}
        {!chunks.length && (
          <text
            x={viewportWidth / 2}
            y="130"
            textAnchor="middle"
            className="chart-no-data"
          >
            داده‌ای در این محدوده نیست
          </text>
        )}
      </svg>
      <div className="chart-readout" aria-live="polite">
        {focused
          ? `چانک ${number(focused.index)}: ${number(focused.records)} خام · ${number(focused.normalized)} نرمال‌شده · ${number(focused.candidates)} کاندید`
          : "برای دیدن مقدار دقیق، نشانگر را روی ستون‌ها ببرید یا با Tab انتخاب کنید."}
      </div>
      <div className="chunk-brush">
        <span>محدودهٔ چانک</span>
        <label>
          از <strong>{number(range[0])}</strong>
          <input
            type="range"
            aria-label="ابتدای محدودهٔ چانک"
            min={minimum}
            max={maximum}
            value={range[0]}
            disabled={!chunks.length}
            onChange={(event) =>
              onRange([
                Math.min(Number(event.target.value), range[1]),
                range[1],
              ])
            }
          />
        </label>
        <label>
          تا <strong>{number(range[1])}</strong>
          <input
            type="range"
            aria-label="انتهای محدودهٔ چانک"
            min={minimum}
            max={maximum}
            value={range[1]}
            disabled={!chunks.length}
            onChange={(event) =>
              onRange([
                range[0],
                Math.max(Number(event.target.value), range[0]),
              ])
            }
          />
        </label>
        <button
          className="viz-text-button"
          disabled={!selection.range}
          onClick={() => onRange(null)}
        >
          کل محدوده
        </button>
      </div>
    </>
  );
}
