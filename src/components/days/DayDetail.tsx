import { useState } from "react";
import {
  BarChart3,
  Download,
  Layers3,
  FileText,
  AlertTriangle,
  Check,
} from "lucide-react";
import {
  type ProcessingDay,
  dateLabel,
  number,
  stages,
  summarizeDay,
} from "../../data/days";
import { ChunkTable } from "./ChunkTable";

export function DayDetail({ day }: { day: ProcessingDay }) {
  const [tab, setTab] = useState<"chunks" | "report">("chunks");
  const [exported, setExported] = useState(false);
  const summary = summarizeDay(day);
  function downloadReport() {
    const report = {
      mock: true,
      scientific_result: false,
      day: day.date,
      expected_chunks: day.expectedChunks,
      source: day.source,
      summary,
      estimate_method:
        "mean available chunk records multiplied by expected chunk count",
      chunks: day.chunks,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], {
        type: "application/json;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `mock-day-report-${day.date}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExported(true);
  }
  return (
    <div className="day-detail" id={`day-detail-${day.date}`}>
      <div className="day-quick-stats">
        <div>
          <span>دادهٔ نرمال‌شده</span>
          <strong>
            {number(summary.normalized)}
            <small> رکورد</small>
          </strong>
        </div>
        <div>
          <span>تکمیل تمام مراحل</span>
          <strong>
            {number(summary.complete)}
            <small> از {number(day.expectedChunks)} چانک</small>
          </strong>
        </div>
        <div>
          <span>برآورد رکورد کل روز</span>
          <strong>≈ {number(summary.estimatedRecords)}</strong>
        </div>
      </div>
      <div
        className="day-detail-tabs"
        role="tablist"
        aria-label={`اطلاعات ${dateLabel(day.date)}`}
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
          document.getElementById(`${next}-tab-${day.date}`)?.focus();
        }}
      >
        <button
          id={`chunks-tab-${day.date}`}
          role="tab"
          aria-selected={tab === "chunks"}
          tabIndex={tab === "chunks" ? 0 : -1}
          aria-controls={`panel-${day.date}`}
          onClick={() => setTab("chunks")}
        >
          <Layers3 size={16} />
          چانک‌ها
        </button>
        <button
          id={`report-tab-${day.date}`}
          role="tab"
          aria-selected={tab === "report"}
          tabIndex={tab === "report" ? 0 : -1}
          aria-controls={`panel-${day.date}`}
          onClick={() => setTab("report")}
        >
          <FileText size={16} />
          گزارش روز
        </button>
        <span className="detail-mock-note">دادهٔ نمایشی</span>
      </div>
      <div
        role="tabpanel"
        id={`panel-${day.date}`}
        aria-labelledby={`${tab}-tab-${day.date}`}
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
                  گزارش {dateLabel(day.date)}
                </h3>
                <p>جمع‌بندی همین روز بر اساس چانک‌های موجود در ماک</p>
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
                    : summary.complete === day.expectedChunks
                      ? "پردازش همهٔ چانک‌ها تکمیل شده است"
                      : "پردازش روز هنوز کامل نشده است"}
                </h4>
                <p>
                  {summary.missing
                    ? `${number(summary.missing)} چانک از ورودی روز در دسترس نیست. `
                    : "تمام پارتیشن‌های مورد انتظار در دسترس‌اند. "}
                  {summary.running
                    ? `${number(summary.running)} چانک در وضعیت پردازش نمونه است.`
                    : "وضعیت‌ها فقط برای نمایش رابط کاربری هستند."}
                </p>
              </div>
            </div>
            <h4 className="report-section-title">پوشش مراحل پردازش</h4>
            <div className="report-stages">
              {stages.map((stage, index) => {
                const count = day.chunks.filter(
                  (chunk) => chunk.completedStages > index,
                ).length;
                return (
                  <div key={stage}>
                    <span>{stage}</span>
                    <progress
                      value={count}
                      max={day.expectedChunks}
                      aria-label={`پوشش ${stage}`}
                    />
                    <strong>
                      {number(count)} / {number(day.expectedChunks)}
                    </strong>
                  </div>
                );
              })}
            </div>
            <details className="report-method">
              <summary>منبع داده و روش برآورد</summary>
              <dl>
                <div>
                  <dt>فایل نمونه</dt>
                  <dd dir="ltr">{day.source}</dd>
                </div>
                <div>
                  <dt>پوشش ورودی</dt>
                  <dd>
                    {number(day.chunks.length)} از {number(day.expectedChunks)}{" "}
                    چانک ({number(summary.coverage)}٪)
                  </dd>
                </div>
                <div>
                  <dt>حجم تقریبی</dt>
                  <dd>
                    {number(summary.volumeMB)} مگابایت، با فرض ۳۱۲ بایت برای هر
                    رکورد
                  </dd>
                </div>
              </dl>
              <p>
                برآورد کل روز = میانگین رکورد خام چانک‌های موجود × تعداد چانک
                مورد انتظار. این تخمین فرض می‌کند اندازهٔ پارتیشن‌ها نزدیک است و
                تضمین کامل‌بودن داده نیست. چانک‌های ناموجود در پیشرفت کل، صفر در
                نظر گرفته می‌شوند. این گزارش ماک است و نتیجهٔ علمی یا تشخیص حمله
                محسوب نمی‌شود.
              </p>
            </details>
            <p className="export-feedback" role="status">
              {exported
                ? "فایل گزارش ماک برای دانلود آماده شد."
                : "خروجی شامل تاریخ، منبع، پارامترهای برآورد، شناسه‌های اجرای نمونه و جزئیات چانک‌هاست."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
