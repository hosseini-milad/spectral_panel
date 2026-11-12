import { useRef } from "react";
import { ArrowUpLeft, BarChart3 } from "lucide-react";
import { Link } from "react-router-dom";
import { number, dateLabel, utcDate } from "../../data/days";
import type { OverviewReport } from "../../api/overview";
import { useSvgWidth } from "../../lib/useSvgWidth";
import { dayDetailsPath } from "../../lib/dayNavigation";

export function IngestionTrend({
  selected,
  points,
}: {
  selected: string;
  points: OverviewReport["trend"];
}) {
  const svg = useRef<SVGSVGElement>(null);
  const width = useSvgWidth(svg, 700);
  const days = points;
  const highest = Math.max(0, ...days.map((day) => day.raw_records ?? 0));
  const magnitude = highest > 0 ? 10 ** Math.floor(Math.log10(highest / 3)) : 1;
  const tickStep = Math.max(1, Math.ceil(highest / 3 / magnitude) * magnitude);
  const ceiling = tickStep * 3;
  const left = 57,
    right = width - 18,
    bottom = 190,
    top = 24;
  const band = (right - left) / Math.max(1, days.length);
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
            <p>رکورد خام ثبت‌شده؛ روز فاقد اطلاعات با «ناموجود» مشخص است</p>
          </div>
        </div>
        <Link to={dayDetailsPath(selected)}>
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
        <title>رکورد خام روزانه — گزارش ذخیره‌شده</title>
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
          const records = day.raw_records;
          const center = left + band * (index + 0.5);
          const bar = Math.min(48, band * 0.55);
          const height = ((records ?? 0) / ceiling) * (bottom - top);
          return (
            <a
              key={day.day}
              href={day.available ? `#${dayDetailsPath(day.day)}` : undefined}
              aria-label={`جزئیات روز ${dateLabel(day.day)}؛ ${records === null ? "اطلاعات ناموجود" : number(records) + " رویداد"}`}
              className={`ov-trend-link${selected === day.day ? " is-selected" : ""}`}
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
                data-day={day.day}
                data-records={records ?? "unknown"}
                x={center - bar / 2}
                y={bottom - height}
                width={bar}
                height={height}
                rx="4"
                fill={
                  selected === day.day ? "var(--accent)" : "var(--chart-green)"
                }
                opacity={selected === day.day ? 1 : 0.62}
              />
              <text
                x={center}
                y="215"
                textAnchor="middle"
                className="ov-chart-axis"
              >
                {index % Math.max(1, Math.ceil((days.length - 1) / 6)) === 0 ||
                index === days.length - 1
                  ? shortDate(day.day)
                  : ""}
              </text>
              {records === null && (
                <text
                  x={center}
                  y={bottom - 7}
                  textAnchor="middle"
                  className="ov-chart-axis"
                >
                  ؟
                </text>
              )}
              <title>{`${dateLabel(day.day)}: ${records === null ? "اطلاعات ناموجود" : number(records) + " رکورد"}؛ پوشش ${day.coverage_percent === null ? "نامشخص" : number(day.coverage_percent) + "٪"}${day.available ? " — برای جزئیات انتخاب کنید" : ""}`}</title>
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
  return new Intl.NumberFormat("fa-IR", {
    maximumFractionDigits: 1,
    notation: "compact",
  }).format(value);
}
