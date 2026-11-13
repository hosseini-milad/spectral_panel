import { lazy, Suspense, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CalendarDays, Database, ArrowUpLeft } from "lucide-react";
import {
  apiPath,
  type InventoryDay,
  type Page,
  displayNumber as number,
} from "../api/days";
import { dateLabel } from "../data/days";
import { isISODate, dayDetailsPath } from "../lib/dayNavigation";
import { useApi } from "../hooks/useApi";
import type { InspectionNavigation } from "../components/days/HierarchyExplorer";
import "../components/days/hierarchy-explorer.css";
const HierarchyExplorer = lazy(
  () => import("../components/days/HierarchyExplorer"),
);
const DailySchematic = lazy(() => import("../components/days/ChunkSchematic"));
export function VisualizationsPage() {
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const latest = useApi<Page<InventoryDay>>(apiPath("days/", { limit: 1 }));
  const days = useApi<Page<InventoryDay>>(
    apiPath("days/", { limit: 10, offset }),
  );
  const requested = params.get("day");
  const selected = requested ?? latest.data?.results[0]?.day;
  const date = selected && isISODate(selected) ? selected : null;
  const day = useApi<InventoryDay>(date ? apiPath(`days/${date}/`) : null);
  const navigation: InspectionNavigation = {
    reportId: params.get("inspection_report") ?? undefined,
    metaId: params.get("meta") ?? undefined,
    componentId: params.get("component") ?? undefined,
    observationId: params.get("observation") ?? undefined,
    jobId: params.get("inspection_job") ?? undefined,
  };
  function navigate(next: InspectionNavigation) {
    setParams((previous) => {
      const q = new URLSearchParams(previous);
      q.set("day", date!);
      for (const [field, key] of [
        ["reportId", "inspection_report"],
        ["metaId", "meta"],
        ["componentId", "component"],
        ["observationId", "observation"],
        ["jobId", "inspection_job"],
      ] as const) {
        if (next[field]) q.set(key, next[field]!);
        else q.delete(key);
      }
      return q;
    });
  }
  return (
    <main
      id="main-content"
      className="main-content inspection-page"
      tabIndex={-1}
    >
      <div className="page-heading">
        <div>
          <p className="eyebrow">تحلیل و پردازش / گزارش قابل مرور</p>
          <h1>گزارش روز و داده‌های اصلی</h1>
          <p className="page-description">
            از فرامولفه تا مشاهده و IPهای رکورد اصلی پیش بروید؛ هر سطح به نسخهٔ
            مشخص گزارش متصل است.
          </p>
        </div>
        <label className="hi-day-select">
          <CalendarDays size={17} />
          روز گزارش
          <select
            aria-label="روز گزارش سلسله‌مراتبی"
            value={date ?? ""}
            onChange={(e) =>
              setParams(e.target.value ? { day: e.target.value } : {})
            }
          >
            <option value="">یک روز را انتخاب کنید…</option>
            {day.data &&
              !days.data?.results.some((row) => row.day === date) && (
                <option value={date!}>{dateLabel(date!)}</option>
              )}
            {days.data?.results.map((row) => (
              <option key={row.day} value={row.day}>
                {dateLabel(row.day)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {days.data && days.data.count > 10 && (
        <div className="hi-pages">
          <button
            className="days-button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 10))}
          >
            روزهای جدیدتر
          </button>
          <span>صفحهٔ {number(Math.floor(offset / 10) + 1)}</span>
          <button
            className="days-button"
            disabled={offset + 10 >= days.data.count}
            onClick={() => setOffset(offset + 10)}
          >
            روزهای قدیمی‌تر
          </button>
        </div>
      )}
      {(day.loading || latest.loading) && (
        <p role="status" className="hi-note">
          در حال دریافت روز گزارش…
        </p>
      )}
      {(day.error || days.error || latest.error) && (
        <p role="alert" className="hi-error">
          {day.error?.message ?? days.error?.message ?? latest.error?.message}
          <button
            className="days-button"
            onClick={() => {
              day.retry();
              days.retry();
              latest.retry();
            }}
          >
            تلاش دوباره
          </button>
        </p>
      )}
      {requested && !date && (
        <p role="alert" className="hi-warning">
          تاریخ گزارش معتبر نیست؛ یک روز واقعی سرور انتخاب کنید.
        </p>
      )}
      {latest.data?.count === 0 && !requested && (
        <p className="hi-note">
          روزی در کالکشن اطلاعات روزها ثبت نشده است. ابتدا اطلاعات روزها را
          همگام کنید.
        </p>
      )}
      {day.data && (
        <>
          <div className="hi-report-day">
            <span>
              <Database size={16} />
              {dateLabel(day.data.day)} · {number(day.data.raw_records)} رکورد
              خام در اطلاعات روز
            </span>
            <Link to={dayDetailsPath(day.data.day)}>
              روزها و چانک‌ها
              <ArrowUpLeft size={14} />
            </Link>
          </div>
          <Suspense
            fallback={
              <p role="status" className="hi-note">
                در حال آماده‌سازی مرور گزارش…
              </p>
            }
          >
            <HierarchyExplorer
              key={day.data.day}
              day={day.data}
              navigation={navigation}
              onNavigate={navigate}
            />
          </Suspense>
          <details className="hi-optional-diagram">
            <summary>تصویر شماتیک روزانه (اختیاری)</summary>
            <Suspense
              fallback={<p className="hi-note">در حال بارگذاری ابزار تصویر…</p>}
            >
              <DailySchematic day={day.data} />
            </Suspense>
          </details>
        </>
      )}
    </main>
  );
}
