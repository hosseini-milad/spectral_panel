import { useRef } from "react";
import { ArrowUpLeft, BarChart3 } from "lucide-react";
import { Link } from "react-router-dom";
import {
  mockDays,
  type ProcessingDay,
  number,
  summarizeDay,
  dateLabel,
  utcDate,
} from "../../data/days";
import { useSvgWidth } from "../../lib/useSvgWidth";
import { dayDetailsPath } from "../../lib/dayNavigation";

export function IngestionTrend({ selected }: { selected: ProcessingDay }) {
  const svg = useRef<SVGSVGElement>(null);
  const width = useSvgWidth(svg, 700);
  const days = mockDays
    .filter((day) => day.date <= selected.date)
    .slice(0, 7)
    .reverse();
  const ceiling =
    Math.ceil(
      Math.max(...days.map((day) => summarizeDay(day).records)) / 500000,
    ) * 500000;
  const left = 57,
    right = width - 18,
    bottom = 190,
    top = 24;
  const band = (right - left) / days.length;
  const shortDate = (date: string) =>
    new Intl.DateTimeFormat("fa-IR", {
      timeZone: "UTC",
      day: "2-digit",
      month: "2-digit",
    }).format(utcDate(date));
  return (
    <section className="ov-card ov-trend" aria-labelledby="ingestion-title">
      <div className="ov-card-heading">
        <div>
          <span className="ov-title-icon">
            <BarChart3 size={17} />
          </span>
          <div>
            <h2 id="ingestion-title">روند حجم ورودی</h2>
            <p>رکورد خام روزهای نمونه تا روز انتخاب‌شده</p>
          </div>
        </div>
        <Link to={dayDetailsPath(selected.date)}>
          جزئیات روز
          <ArrowUpLeft size={14} />
        </Link>
      </div>
      <div className="ov-chart-legend">
        <span>
          <i />
          رکوردهای موجود
        </span>
        <span>ستون هر روز برای مشاهدهٔ جزئیات قابل انتخاب است.</span>
      </div>
      <svg
        ref={svg}
        viewBox={`0 0 ${width} 235`}
        className="ov-trend-svg"
        role="group"
        aria-label="روند حجم رویدادها؛ لینک جزئیات هر روز"
        direction="ltr"
      >
        <title>رکورد خام روزانه — دادهٔ ماک</title>
        {Array.from({ length: 4 }, (_, index) => {
          const value = (ceiling * index) / 3;
          const y = bottom - ((bottom - top) * index) / 3;
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
                className="ov-chart-axis"
              >
                {decimalMillions(value)}
              </text>
            </g>
          );
        })}
        {days.map((day, index) => {
          const summary = summarizeDay(day);
          const center = left + band * (index + 0.5);
          const bar = Math.min(48, band * 0.55);
          const height = (summary.records / ceiling) * (bottom - top);
          return (
            <a
              key={day.date}
              href={`#${dayDetailsPath(day.date)}`}
              aria-label={`جزئیات روز ${dateLabel(day.date)}؛ ${number(summary.records)} رویداد`}
              className={`ov-trend-link${selected.date === day.date ? " is-selected" : ""}`}
            >
              <rect
                x={center - band * 0.45}
                y="15"
                width={band * 0.9}
                height="209"
                fill="transparent"
                rx="7"
                className="ov-chart-hit"
              />
              <rect
                x={center - bar / 2}
                y={bottom - height}
                width={bar}
                height={height}
                rx="4"
                fill={
                  selected.date === day.date
                    ? "var(--accent)"
                    : "var(--chart-green)"
                }
                opacity={selected.date === day.date ? 1 : 0.62}
              />
              <text
                x={center}
                y="215"
                textAnchor="middle"
                className="ov-chart-axis"
              >
                {shortDate(day.date)}
              </text>
              <title>{`${dateLabel(day.date)}: ${number(summary.records)} رکورد؛ پوشش ${number(summary.coverage)}٪ — برای جزئیات انتخاب کنید`}</title>
            </a>
          );
        })}
      </svg>
      <p className="ov-chart-note">
        حجم ورودی با پوشش همان روز خوانده شود؛ افت حجم در روز جزئی، به‌تنهایی
        نشانهٔ افت فعالیت یا تهدید نیست.
      </p>
    </section>
  );
}

function decimalMillions(value: number) {
  return value === 0
    ? "۰"
    : `${new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 }).format(value / 1000000)}m`;
}
