import { lazy, Suspense, useState } from "react";
import {
  BarChart3,
  Download,
  Layers3,
  FileText,
  AlertTriangle,
  Check,
} from "lucide-react";
import { dateLabel, stages } from "../../data/days";
import { ChunkTable } from "./ChunkTable";
import {
  apiPath,
  type InventoryDay,
  displayNumber as number,
  inventorySummary as summarizeDay,
  observationTime,
} from "../../api/days";
import { useApi } from "../../hooks/useApi";

const HierarchyExplorer = lazy(() => import("./HierarchyExplorer"));
const DailySchematic = lazy(() => import("./ChunkSchematic"));

export function DayDetail({ day: initialDay }: { day: InventoryDay }) {
  const resource = useApi<InventoryDay>(apiPath(`days/${initialDay.day}/`));
  const day = resource.data ?? initialDay;
  const [tab, setTab] = useState<"chunks" | "report">("chunks");
  const [exported, setExported] = useState(false);
  const summary = summarizeDay(day);
  function downloadReport() {
    const report = {
      inventory_report: true,
      scientific_result: false,
      day,
      chunks_url: apiPath(`days/${day.day}/chunks/`),
      note: "خلاصهٔ ذخیره‌شدهٔ روز؛ جزئیات چانک‌ها صفحه‌بندی می‌شود. شناسهٔ snapshot_id نسخهٔ دادهٔ فهرست است، نه شناسهٔ اجرای علمی.",
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], {
        type: "application/json;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `day-inventory-report-${day.day}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExported(true);
  }
  if (resource.error)
    return (
      <div
        className="day-detail"
        id={`day-detail-${initialDay.day}`}
        role="alert"
      >
        <p>{resource.error.message}</p>
        <button className="days-text-button" onClick={resource.retry}>
          تلاش دوباره
        </button>
      </div>
    );
  return (
    <div className="day-detail" id={`day-detail-${day.day}`}>
      <div className="day-quick-stats">
        <div>
          <span>دادهٔ نرمال‌شده</span>
          <strong>
            {number(summary.normalized)}
            <small> رکورد</small>
          </strong>
        </div>
        <div>
          <span>تکمیل لایهٔ اول</span>
          <strong>
            {number(summary.complete)}
            <small> از {number(day.expected_chunks)} چانک</small>
          </strong>
        </div>
        <div>
          <span>رکورد خام کل روز</span>
          <strong>{number(summary.records)}</strong>
        </div>
      </div>
      <div
        className="day-detail-tabs"
        role="tablist"
        aria-label={`اطلاعات ${dateLabel(day.day)}`}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
            return;
          event.preventDefault();
          const next =
            event.key === "Home"
              ? "chunks"
              : event.key === "End"
                ? "report"
                : tab === "chunks"
                  ? "report"
                  : "chunks";
          setTab(next);
          document.getElementById(`${next}-tab-${day.day}`)?.focus();
        }}
      >
        <button
          id={`chunks-tab-${day.day}`}
          role="tab"
          aria-selected={tab === "chunks"}
          tabIndex={tab === "chunks" ? 0 : -1}
          aria-controls={`panel-${day.day}`}
          onClick={() => setTab("chunks")}
        >
          <Layers3 size={16} />
          چانک‌ها
        </button>
        <button
          id={`report-tab-${day.day}`}
          role="tab"
          aria-selected={tab === "report"}
          tabIndex={tab === "report" ? 0 : -1}
          aria-controls={`panel-${day.day}`}
          onClick={() => setTab("report")}
        >
          <FileText size={16} />
          گزارش روز
        </button>
        <span className="detail-mock-note">اطلاعات ثبت‌شده</span>
      </div>
      <div
        role="tabpanel"
        id={`panel-${day.day}`}
        aria-labelledby={`${tab}-tab-${day.day}`}
        tabIndex={0}
      >
        {tab === "chunks" ? (
          <ChunkTable day={day} />
        ) : (
          <div className="day-report">
            <div className="report-heading">
              <div>
                <h3>
                  <BarChart3 size={18} />
                  گزارش {dateLabel(day.day)}
                </h3>
                <p>جمع‌بندی همین روز بر اساس اطلاعات ثبت‌شدهٔ سرور</p>
              </div>
              <button className="days-button" onClick={downloadReport}>
                <Download size={15} />
                دریافت JSON
              </button>
            </div>
            <div className="report-assessment">
              <span
                className={`assessment-icon ${summary.failed ? "warning" : ""}`}
              >
                {summary.failed ? (
                  <AlertTriangle size={20} />
                ) : (
                  <Check size={20} />
                )}
              </span>
              <div>
                <h4>
                  {summary.failed
                    ? `${number(summary.failed)} چانک نیازمند بررسی است`
                    : summary.complete === day.expected_chunks
                      ? "لایهٔ اول همهٔ چانک‌ها تکمیل شده است"
                      : "پردازش روز هنوز کامل نشده است"}
                </h4>
                <p>
                  {summary.missing == null
                    ? "تعداد پارتیشن‌های مورد انتظار مشخص نیست. "
                    : summary.missing
                      ? `${number(summary.missing)} چانک از ورودی روز در دسترس نیست. `
                      : "تمام پارتیشن‌های مورد انتظار در دسترس‌اند. "}
                  {summary.running
                    ? `${number(summary.running)} چانک دارای نشانگر پردازش است.`
                    : "این خلاصه، وضعیت زندهٔ worker یا نتیجهٔ تشخیص حمله نیست."}
                </p>
              </div>
            </div>
            <Suspense
              fallback={
                <p className="chunk-detail-note">
                  در حال آماده‌سازی مرور داده‌های روز…
                </p>
              }
            >
              <HierarchyExplorer key={day.day} day={day} />
            </Suspense>
            <Suspense
              fallback={
                <p className="chunk-detail-note">
                  در حال آماده‌سازی نمایش روزانه…
                </p>
              }
            >
              <DailySchematic key={`${day.day}:${day.snapshot_id}`} day={day} />
            </Suspense>
            <h4 className="report-section-title">پوشش مراحل پردازش</h4>
            <div className="report-stages">
              {stages.map((stage) => (
                <div key={stage}>
                  <span>{stage}</span>
                  <progress
                    value={0}
                    max={day.expected_chunks ?? 1}
                    aria-label={`شمارش تکمیل مرحلهٔ ${stage} در API گزارش نشده است`}
                  />
                  <strong>— / {number(day.expected_chunks)}</strong>
                </div>
              ))}
            </div>
            <details className="report-method">
              <summary>منبع داده و زمان مشاهده</summary>
              <dl>
                <div>
                  <dt>منبع اطلاعات</dt>
                  <dd dir="ltr">processing_days</dd>
                </div>
                <div>
                  <dt>پوشش ورودی</dt>
                  <dd>
                    {number(day.observed_chunks)} از{" "}
                    {number(day.expected_chunks)} چانک (
                    {number(summary.coverage)}
                    {summary.coverage == null ? "" : "٪"})
                  </dd>
                </div>
                <div>
                  <dt>حجم تقریبی</dt>
                  <dd>
                    {summary.volumeMB == null
                      ? "اندازه‌گیری نشده"
                      : `${number(summary.volumeMB)} مگابایت`}
                  </dd>
                </div>
              </dl>
              <p>
                اطلاعات از کالکشن روزها خوانده شده است؛ حجم، زمان اجرا، درصد
                پیشرفت و شمارش تکمیل تک‌تک مراحل در این API گزارش نمی‌شوند.
                آخرین مشاهده: {observationTime(day.updated_at)}. شناسهٔ نسخهٔ
                فهرست: {day.snapshot_id}. پوشش چانک با دقت تشخیص حمله تفاوت
                دارد.
              </p>
            </details>
            <p className="export-feedback" role="status">
              {exported
                ? "فایل خلاصهٔ ثبت‌شده برای دانلود آماده شد."
                : "خروجی شامل خلاصهٔ روز، شناسهٔ نسخه و نشانی دریافت صفحه‌بندی‌شدهٔ چانک‌هاست."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
