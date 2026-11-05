import type { RefObject } from "react";
import {
  type Chunk,
  type ChunkStatus,
  chunkStatusLabels,
  number,
} from "../../data/days";
import { statusColors, statusOrder } from "../../data/visualizations";
import { activate } from "./VolumeChart";

export function StatusChart({
  chunks,
  selected,
  onSelect,
  svgRef,
}: {
  chunks: Chunk[];
  selected: ChunkStatus | null;
  onSelect: (status: ChunkStatus) => void;
  svgRef: RefObject<SVGSVGElement | null>;
}) {
  let offset = 0;
  const circumference = 2 * Math.PI * 73;
  const counts = statusOrder.map((status) => ({
    status,
    count: chunks.filter((chunk) => chunk.status === status).length,
  }));
  return (
    <div className="status-chart-layout">
      <svg
        ref={svgRef}
        viewBox="0 0 300 255"
        role="group"
        aria-label="نمودار توزیع وضعیت؛ هر بخش برای فیلتر قابل انتخاب است"
        className="status-svg"
        direction="ltr"
      >
        <title>توزیع وضعیت چانک‌ها — ماک</title>
        <circle
          cx="150"
          cy="125"
          r="73"
          fill="none"
          stroke="var(--chart-track)"
          strokeWidth="26"
        />
        {counts.map(({ status, count }) => {
          const length = chunks.length
            ? (count / chunks.length) * circumference
            : 0;
          const start = offset;
          offset += length;
          return count > 0 ? (
            <circle
              key={status}
              cx="150"
              cy="125"
              r="73"
              fill="none"
              stroke={statusColors[status]}
              strokeWidth={selected === status ? 34 : 26}
              strokeDasharray={`${Math.max(0, length - (chunks.length === count ? 0 : 6))} ${circumference}`}
              strokeDashoffset={-start}
              transform="rotate(-90 150 125)"
              className={`status-segment${selected && selected !== status ? " muted" : ""}`}
              role="button"
              tabIndex={0}
              aria-label={`فیلتر ${chunkStatusLabels[status]}؛ ${number(count)} چانک`}
              aria-pressed={selected === status}
              onClick={() => onSelect(status)}
              onKeyDown={(event) => activate(event, () => onSelect(status))}
            >
              <title>{`${chunkStatusLabels[status]}: ${number(count)} چانک (${number(Math.round((count / chunks.length) * 100))}٪)`}</title>
            </circle>
          ) : null;
        })}
        <text x="150" y="125" textAnchor="middle" className="donut-total">
          {number(chunks.length)}
        </text>
        <text x="150" y="148" textAnchor="middle" className="chart-axis">
          چانک در محدوده
        </text>
      </svg>
      <div className="status-chart-legend" aria-label="فیلتر وضعیت از نمودار">
        {counts.map(({ status, count }) => (
          <button
            key={status}
            aria-pressed={selected === status}
            disabled={count === 0 && selected !== status}
            onClick={() => onSelect(status)}
          >
            <i style={{ background: statusColors[status] }} />
            <span>{chunkStatusLabels[status]}</span>
            <strong>{number(count)}</strong>
            <small>
              {number(
                chunks.length ? Math.round((count / chunks.length) * 100) : 0,
              )}
              ٪
            </small>
          </button>
        ))}
      </div>
    </div>
  );
}
