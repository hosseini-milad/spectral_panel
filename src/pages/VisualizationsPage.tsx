import { useEffect, useRef, useState } from "react";
import {
  CalendarDays,
  ChevronDown,
  SlidersHorizontal,
  RotateCcw,
  Check,
  X,
  FlaskConical,
  Info,
  Database,
  Layers3,
  TrendingUp,
  Filter,
  Table2,
  Download,
  ChartNoAxesCombined,
} from "lucide-react";
import {
  mockDays,
  number,
  dateLabel,
  stages,
  chunkStatusLabels,
  type ChunkStatus,
} from "../data/days";
import {
  defaultFilters,
  emptySelection,
  filterChunks,
  selectChunks,
  hasChartSelection,
  type VisualizationFilters,
} from "../data/visualizations";
import { PersianCalendar } from "../components/days/PersianCalendar";
import { ChartCard } from "../components/visualizations/ChartCard";
import { VolumeChart } from "../components/visualizations/VolumeChart";
import { StageChart } from "../components/visualizations/StageChart";
import { StatusChart } from "../components/visualizations/StatusChart";
import "./visualizations.css";

export function VisualizationsPage() {
  const [applied, setApplied] = useState(defaultFilters);
  const [draft, setDraft] = useState(defaultFilters);
  const [selection, setSelection] = useState(emptySelection);
  const [exportMessage, setExportMessage] = useState("");
  const calendar = useRef<HTMLDetailsElement>(null);
  const day = mockDays.find((item) => item.date === applied.day);
  const draftDay = mockDays.find((item) => item.date === draft.day);
  const base = filterChunks(day, applied);
  const selected = selectChunks(base, selection);
  const dirty = JSON.stringify(draft) !== JSON.stringify(applied);
  const extraFilters =
    applied.chunk !== "all" || applied.status !== "all" || applied.stage !== 0;
  const chartFiltered = hasChartSelection(selection);
  const totals = selected.reduce(
    (sum, chunk) => ({
      records: sum.records + chunk.records,
      normalized: sum.normalized + chunk.normalized,
      progress: sum.progress + chunk.progress,
    }),
    { records: 0, normalized: 0, progress: 0 },
  );
  const metadata = {
    mock: true,
    scientific_result: false,
    day: applied.day,
    filters: applied,
    chart_selection: selection,
    selected_chunks: selected.map((chunk) => chunk.index),
    mock_run_ids: selected.flatMap((chunk) =>
      chunk.runId ? [chunk.runId] : [],
    ),
    source: day?.source ?? null,
    generated_at: new Date().toISOString(),
    note: "Charts keep their own filter context visible. Chunk counts are processing partitions, not time intervals.",
  };

  useEffect(() => {
    function outside(event: PointerEvent) {
      if (
        calendar.current?.open &&
        !calendar.current.contains(event.target as Node)
      )
        calendar.current.open = false;
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);

  function updateDay(date: string) {
    setDraft((current) => ({ ...current, day: date, chunk: "all" }));
    if (calendar.current) calendar.current.open = false;
  }
  function applyFilters() {
    setApplied({ ...draft });
    setSelection(emptySelection());
    setExportMessage("");
  }
  function resetFilters() {
    const defaults = defaultFilters(applied.day);
    setApplied(defaults);
    setDraft(defaults);
    setSelection(emptySelection());
    setExportMessage("");
  }
  function clearFilter(key: "chunk" | "stage" | "status") {
    const next = { ...applied, [key]: key === "stage" ? 0 : "all" };
    setApplied(next);
    setDraft(next);
  }
  function exportData() {
    const header = [
      "روز",
      "چانک",
      "رکورد خام",
      "نرمال‌شده",
      "کاندید",
      "وضعیت",
      "پیشرفت ماک",
      "شناسه اجرای ماک",
    ];
    const rows = selected.map((chunk) => [
      applied.day,
      chunk.index,
      chunk.records,
      chunk.normalized,
      chunk.candidates,
      chunkStatusLabels[chunk.status],
      chunk.progress,
      chunk.runId ?? "",
    ]);
    const url = URL.createObjectURL(
      new Blob(
        ["\ufeff", [header, ...rows].map((row) => row.join(",")).join("\r\n")],
        { type: "text/csv;charset=utf-8" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `mock-chart-data-${applied.day}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExportMessage(
      `داده‌های ${number(selected.length)} چانک انتخابی در فایل ماک CSV آماده شد.`,
    );
  }
  return (
    <main
      id="main-content"
      className="main-content visualizations-page"
      tabIndex={-1}
    >
      <div className="page-heading viz-page-heading">
        <div>
          <p className="eyebrow">تحلیل و پردازش / کاوش بصری</p>
          <h1>گزارش</h1>
          <p className="page-description">
            روز را انتخاب کنید، الگوها را ببینید و روی جزئیات دقیق‌تر شوید.
          </p>
        </div>
        <span className="viz-mock-badge">
          <FlaskConical size={15} />
          نسخهٔ ماک
        </span>
      </div>
      <div className="viz-notice">
        <Info size={15} />
        <span>
          نمودارها از داده‌های ثابت نمونه ساخته شده‌اند؛ نتیجهٔ علمی یا پردازش
          واقعی نیستند.
        </span>
        <span className="viz-live-label">
          <i />
          کاوش تعاملی
        </span>
      </div>

      <form
        className="viz-card viz-filter-card"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters();
        }}
      >
        <div className="viz-filter-heading">
          <span>
            <SlidersHorizontal size={17} />
            محدودهٔ نمایش
          </span>
          <p>بدون فیلتر اضافی، آمار کل روز انتخاب‌شده نمایش داده می‌شود.</p>
        </div>
        <div className="viz-filter-grid">
          <div className="viz-date-field">
            <span className="viz-control-label" id="analysis-day-label">
              روز تحلیل
            </span>
            <details
              ref={calendar}
              className="viz-date-picker"
              onKeyDown={(event) => {
                if (event.key === "Escape" && calendar.current) {
                  calendar.current.open = false;
                  calendar.current.querySelector("summary")?.focus();
                }
              }}
            >
              <summary aria-labelledby="analysis-day-label analysis-day-value">
                <CalendarDays size={16} />
                <span id="analysis-day-value">{dateLabel(draft.day)}</span>
                <ChevronDown size={14} />
              </summary>
              <div className="viz-calendar-popover">
                <PersianCalendar
                  key={draft.day}
                  selectedDate={draft.day}
                  onSelect={updateDay}
                />
                <label className="viz-exact-date">
                  تاریخ میلادی دقیق
                  <input
                    type="date"
                    aria-label="تاریخ میلادی تحلیل"
                    value={draft.day}
                    onChange={(event) => {
                      if (event.target.value) updateDay(event.target.value);
                    }}
                  />
                </label>
              </div>
            </details>
          </div>
          <label className="viz-field">
            چانک
            <select
              aria-label="فیلتر چانک نمودار"
              value={draft.chunk}
              onChange={(event) =>
                setDraft({ ...draft, chunk: event.target.value })
              }
            >
              <option value="all">همهٔ چانک‌ها</option>
              {draftDay?.chunks.map((chunk) => (
                <option key={chunk.id} value={chunk.index}>
                  چانک {number(chunk.index)}
                </option>
              ))}
            </select>
          </label>
          <label className="viz-field">
            وضعیت
            <select
              aria-label="فیلتر وضعیت نمودار"
              value={draft.status}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  status: event.target.value as VisualizationFilters["status"],
                })
              }
            >
              <option value="all">همهٔ وضعیت‌ها</option>
              {Object.entries(chunkStatusLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="viz-field">
            مرحلهٔ تکمیل‌شده
            <select
              aria-label="فیلتر مرحله نمودار"
              value={draft.stage}
              onChange={(event) =>
                setDraft({ ...draft, stage: Number(event.target.value) })
              }
            >
              <option value="0">همهٔ مراحل</option>
              {stages.map((stage, index) => (
                <option key={stage} value={index + 1}>
                  {stage}
                </option>
              ))}
            </select>
          </label>
          <div className="viz-filter-actions">
            <button className="viz-primary-button" type="submit">
              <Filter size={15} />
              اعمال فیلتر
            </button>
            <button
              className="viz-reset icon-button"
              type="button"
              aria-label="بازنشانی به آمار کل روز"
              title="بازنشانی به کل روز انتخاب‌شده"
              onClick={resetFilters}
            >
              <RotateCcw size={16} />
            </button>
          </div>
        </div>
        {dirty && (
          <p className="viz-pending" role="status">
            فیلترها تغییر کرده‌اند؛ برای به‌روزرسانی نمودارها «اعمال فیلتر» را
            بزنید.
          </p>
        )}
      </form>

      <section className="viz-scope" aria-label="محدودهٔ اعمال‌شده">
        <div>
          <span className="viz-scope-icon">
            <CalendarDays size={20} />
          </span>
          <div>
            <strong>{dateLabel(applied.day, true)}</strong>
            <span>
              {!extraFilters && !chartFiltered
                ? "نمای روزانه · همهٔ چانک‌های موجود"
                : "نمای فیلترشده · بر اساس انتخاب فعلی"}
              {day &&
                ` · پوشش ورودی ${number(day.chunks.length)} از ${number(day.expectedChunks)} چانک`}
            </span>
          </div>
        </div>
        <span className="viz-scope-date" dir="ltr">
          {applied.day}
        </span>
      </section>
      <div className="viz-active-filters" aria-label="فیلترهای فعال">
        <span>
          <Filter size={13} />
          فیلترهای فعال
        </span>
        <span className="viz-day-chip">روز: {dateLabel(applied.day)}</span>
        {applied.chunk !== "all" && (
          <button
            className="viz-filter-chip"
            onClick={() => clearFilter("chunk")}
          >
            چانک {number(Number(applied.chunk))}
            <X size={12} />
          </button>
        )}
        {applied.status !== "all" && (
          <button
            className="viz-filter-chip"
            onClick={() => clearFilter("status")}
          >
            وضعیت: {chunkStatusLabels[applied.status]}
            <X size={12} />
          </button>
        )}
        {applied.stage > 0 && (
          <button
            className="viz-filter-chip"
            onClick={() => clearFilter("stage")}
          >
            مرحله: {stages[applied.stage - 1]}
            <X size={12} />
          </button>
        )}
        {selection.chunks.length > 0 && (
          <button
            className="viz-filter-chip"
            onClick={() => setSelection({ ...selection, chunks: [] })}
          >
            چانک‌های انتخابی: {selection.chunks.map(number).join("، ")}
            <X size={12} />
          </button>
        )}
        {selection.range && (
          <button
            className="viz-filter-chip"
            onClick={() => setSelection({ ...selection, range: null })}
          >
            بازه: {number(selection.range[0])} تا {number(selection.range[1])}
            <X size={12} />
          </button>
        )}
        {selection.status && (
          <button
            className="viz-filter-chip"
            onClick={() => setSelection({ ...selection, status: null })}
          >
            نمودار وضعیت: {chunkStatusLabels[selection.status]}
            <X size={12} />
          </button>
        )}
        {selection.stage && (
          <button
            className="viz-filter-chip"
            onClick={() => setSelection({ ...selection, stage: null })}
          >
            نمودار مرحله: {stages[selection.stage - 1]}
            <X size={12} />
          </button>
        )}
        {chartFiltered && (
          <button
            className="viz-text-button clear-chart-selection"
            onClick={() => setSelection(emptySelection())}
          >
            پاک‌کردن انتخاب نمودارها
          </button>
        )}
      </div>

      <div
        className="viz-results-announcement"
        role="status"
        aria-live="polite"
      >
        {number(selected.length)} چانک از {number(base.length)} چانک در محدودهٔ
        فیلتر؛ {number(totals.records)} رکورد خام.
      </div>
      <section className="viz-metrics" aria-label="آمار انتخاب فعلی">
        {[
          {
            label: "رکورد خام",
            value: number(totals.records),
            detail: "در چانک‌های انتخابی",
            icon: Database,
            color: "green",
          },
          {
            label: "رکورد نرمال‌شده",
            value: number(totals.normalized),
            detail: "فقط مراحل تکمیل‌شده",
            icon: Check,
            color: "blue",
          },
          {
            label: "چانک انتخابی",
            value: `${number(selected.length)} / ${number(day?.chunks.length ?? 0)}`,
            detail: "از چانک‌های موجود روز",
            icon: Layers3,
            color: "lilac",
          },
          {
            label: "میانگین پیشرفت ماک",
            value: selected.length
              ? `${number(Math.round(totals.progress / selected.length))}٪`
              : "—",
            detail: "میانگین چانک‌های انتخابی",
            icon: TrendingUp,
            color: "amber",
          },
        ].map((metric) => (
          <div key={metric.label} className="viz-card viz-metric">
            <div>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <small>{metric.detail}</small>
            </div>
            <span className={`viz-metric-icon ${metric.color}`}>
              <metric.icon size={20} strokeWidth={1.7} />
            </span>
          </div>
        ))}
      </section>

      {!day || !base.length ? (
        <section className="viz-card viz-empty">
          <ChartNoAxesCombined size={37} />
          <h2>
            {!day
              ? "برای این روز دادهٔ نمونه‌ای نداریم"
              : "داده‌ای با این ترکیب فیلتر پیدا نشد"}
          </h2>
          <p>
            {!day
              ? "از تقویم یک روز نقطه‌دار انتخاب کنید یا به آخرین روز نمونه برگردید."
              : "وضعیت، چانک یا مرحله را تغییر دهید؛ مرحله‌های اجرا‌نشده به معنی مقدار صفر محاسبه‌شده نیستند."}
          </p>
          <button
            className="viz-primary-button"
            onClick={() => {
              if (!day) {
                const next = defaultFilters();
                setDraft(next);
                setApplied(next);
                setSelection(emptySelection());
              } else resetFilters();
            }}
          >
            {!day ? "آخرین روز نمونه" : "نمایش کل روز"}
          </button>
        </section>
      ) : (
        <>
          {!selected.length && (
            <div className="viz-selection-empty" role="status">
              <Info size={16} />
              اشتراک انتخاب‌های نمودار خالی است؛ یکی از انتخاب‌ها را بردارید یا
              انتخاب نمودارها را پاک کنید.
              <button onClick={() => setSelection(emptySelection())}>
                پاک‌کردن انتخاب‌ها
              </button>
            </div>
          )}
          <div className="viz-chart-section-heading">
            <h2>سه نما، یک محدودهٔ مشترک</h2>
            <span>
              <i />
              انتخاب در نمودارها به‌صورت ترکیبی اعمال می‌شود
            </span>
          </div>
          <div className="viz-charts-grid">
            <ChartCard
              id="chunk-volume"
              number="01"
              title="حجم داده به تفکیک چانک"
              description="مقایسهٔ رکوردهای خام، نرمال‌شده و کاندید؛ چانک پارتیشن پردازش است."
              metadata={{
                ...metadata,
                chart: "chunk-volume",
                context_chunks: selectChunks(base, selection, "chunk").map(
                  (chunk) => chunk.index,
                ),
              }}
              footer="کلیک برای انتخاب چند چانک؛ با لغزنده‌ها یک بازه را محدود کنید."
              wide
            >
              {(ref) => (
                <VolumeChart
                  svgRef={ref}
                  chunks={selectChunks(base, selection, "chunk")}
                  bounds={[base[0]?.index ?? 0, base.at(-1)?.index ?? 0]}
                  selection={selection}
                  onToggle={(index) =>
                    setSelection((current) => ({
                      ...current,
                      chunks: current.chunks.includes(index)
                        ? current.chunks.filter((value) => value !== index)
                        : [...current.chunks, index].sort((a, b) => a - b),
                    }))
                  }
                  onRange={(range) => setSelection({ ...selection, range })}
                />
              )}
            </ChartCard>
            <ChartCard
              id="stage-coverage"
              number="02"
              title="پوشش مراحل پردازش"
              description="چه تعداد چانک هر مرحله را کامل کرده‌اند؟"
              metadata={{
                ...metadata,
                chart: "stage-coverage",
                context_chunks: selectChunks(base, selection, "stage").map(
                  (chunk) => chunk.index,
                ),
              }}
              footer="مرحله را انتخاب کنید تا چانک‌های عبورکرده از آن باقی بمانند."
            >
              {(ref) => (
                <StageChart
                  svgRef={ref}
                  chunks={selectChunks(base, selection, "stage")}
                  selected={selection.stage}
                  onSelect={(stage) =>
                    setSelection({
                      ...selection,
                      stage: selection.stage === stage ? null : stage,
                    })
                  }
                />
              )}
            </ChartCard>
            <ChartCard
              id="chunk-status"
              number="03"
              title="توزیع وضعیت چانک‌ها"
              description="سهم هر وضعیت در محدودهٔ فعلی، پیش از فیلتر خود این نمودار."
              metadata={{
                ...metadata,
                chart: "chunk-status",
                context_chunks: selectChunks(base, selection, "status").map(
                  (chunk) => chunk.index,
                ),
              }}
              footer="روی یک بخش یا عنوان راهنما کلیک کنید؛ کلیک دوباره لغو می‌کند."
            >
              {(ref) => (
                <StatusChart
                  svgRef={ref}
                  chunks={selectChunks(base, selection, "status")}
                  selected={selection.status}
                  onSelect={(status: ChunkStatus) =>
                    setSelection({
                      ...selection,
                      status: selection.status === status ? null : status,
                    })
                  }
                />
              )}
            </ChartCard>
          </div>
          <p className="viz-context-note">
            <Info size={14} />
            برای امکان تغییر انتخاب، هر نمودار فیلتر خودش را از زمینهٔ نمایش
            کنار می‌گذارد؛ آمار بالا و جدول زیر اشتراک تمام فیلترها را نشان
            می‌دهند. صفر در مرحلهٔ اجرا‌نشده، نتیجهٔ محاسبه‌شده نیست.
          </p>
          <details className="viz-card viz-data-table">
            <summary>
              <Table2 size={17} />
              <span>داده‌های پشت نمودارها</span>
              <span>{number(selected.length)} چانک انتخابی</span>
              <ChevronDown size={16} />
            </summary>
            <div className="viz-table-toolbar">
              <span>محدودهٔ اعمال‌شده: {dateLabel(applied.day)}</span>
              <button
                className="viz-secondary-button"
                disabled={!selected.length}
                onClick={exportData}
              >
                <Download size={14} />
                دریافت CSV ماک
              </button>
            </div>
            <div
              className="viz-table-scroll"
              role="region"
              aria-label="جدول داده‌های انتخابی نمودارها"
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    {[
                      "چانک",
                      "رکورد خام",
                      "نرمال‌شده",
                      "وضعیت",
                      "پیشرفت ماک",
                      "شناسهٔ اجرای ماک",
                    ].map((title) => (
                      <th key={title} scope="col">
                        {title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {selected.map((chunk) => (
                    <tr key={chunk.id}>
                      <th scope="row">چانک {number(chunk.index)}</th>
                      <td>{number(chunk.records)}</td>
                      <td>{number(chunk.normalized)}</td>
                      <td>
                        <span className={`viz-status-pill ${chunk.status}`}>
                          {chunkStatusLabels[chunk.status]}
                        </span>
                      </td>
                      <td>{number(chunk.progress)}٪</td>
                      <td>
                        <bdi>{chunk.runId ?? "بدون اجرا"}</bdi>
                      </td>
                    </tr>
                  ))}
                  {!selected.length && (
                    <tr>
                      <td colSpan={6}>چانکی در اشتراک انتخاب‌ها وجود ندارد.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="viz-export-message" role="status">
              {exportMessage ||
                "خروجی‌ها نمایشی‌اند و به اجرای واقعی متصل نیستند؛ فایل SVG هر نمودار شامل متادیتای فیلترها و شناسه‌های ماک است."}
            </p>
          </details>
        </>
      )}
      <div className="viz-page-footer-note">
        <FlaskConical size={14} />
        <span>
          منبع: مجموعهٔ ماک روزها · بدون درخواست API · بدون تشخیص یا برچسب‌گذاری
          حمله
        </span>
      </div>
    </main>
  );
}
