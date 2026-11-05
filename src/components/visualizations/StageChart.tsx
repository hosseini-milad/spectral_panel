import type { RefObject } from "react";
import { type Chunk, number, stages } from "../../data/days";
import { activate } from "./VolumeChart";
import { useSvgWidth } from "../../lib/useSvgWidth";

export function StageChart({
  chunks,
  selected,
  onSelect,
  svgRef,
}: {
  chunks: Chunk[];
  selected: number | null;
  onSelect: (stage: number) => void;
  svgRef: RefObject<SVGSVGElement | null>;
}) {
  const viewportWidth = useSvgWidth(svgRef, 560);
  const start = 45;
  const width = viewportWidth - 175,
    max = Math.max(chunks.length, 1);
  return (
    <>
      <div className="chart-inline-note">
        <span className="legend-line" />
        چانک‌های عبورکرده از مرحله<span>از {number(chunks.length)} چانک</span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${viewportWidth} 264`}
        className="stage-svg"
        role="group"
        aria-label="نمودار پوشش مراحل؛ انتخاب مرحله برای فیلتر چانک‌ها"
        direction="ltr"
      >
        <title>تعداد چانک‌های تکمیل‌کنندهٔ هر مرحله — ماک</title>
        {stages.map((stage, index) => {
          const count = chunks.filter(
            (chunk) => chunk.completedStages > index,
          ).length;
          const y = 15 + index * 49;
          return (
            <g
              key={stage}
              role="button"
              tabIndex={0}
              aria-label={`فیلتر مرحلهٔ ${stage}؛ ${number(count)} از ${number(chunks.length)} چانک`}
              aria-pressed={selected === index + 1}
              className="stage-chart-row"
              onClick={() => onSelect(index + 1)}
              onKeyDown={(event) => activate(event, () => onSelect(index + 1))}
            >
              <rect
                x="5"
                y={y - 7}
                width={viewportWidth - 10}
                height="44"
                rx="6"
                fill={
                  selected === index + 1 ? "var(--accent-soft)" : "transparent"
                }
                stroke={
                  selected === index + 1
                    ? "var(--accent-border)"
                    : "transparent"
                }
              />
              <text
                x={viewportWidth - 12}
                y={y + 13}
                textAnchor="end"
                className="stage-chart-label"
              >
                {stage}
              </text>
              <rect
                x={start}
                y={y}
                width={width}
                height="19"
                rx="4"
                fill="var(--chart-track)"
              />
              <rect
                x={start + width - (count / max) * width}
                y={y}
                width={(count / max) * width}
                height="19"
                rx="4"
                fill={
                  selected === index + 1
                    ? "var(--accent)"
                    : "var(--chart-green)"
                }
              />
              <text
                x="25"
                y={y + 14}
                textAnchor="middle"
                className="stage-chart-count"
              >
                {number(count)}
              </text>
              <title>{`${stage}: ${number(count)} چانک از ${number(chunks.length)}`}</title>
            </g>
          );
        })}
      </svg>
      <p className="chart-explanation">
        انتخاب یک مرحله، چانک‌هایی را نگه می‌دارد که آن مرحله را کامل کرده‌اند؛
        کلیک دوباره، انتخاب را برمی‌دارد.
      </p>
    </>
  );
}
