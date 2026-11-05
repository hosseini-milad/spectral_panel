import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  ArrowUpLeft,
  ArrowDown,
  Check,
  CirclePlay,
  Database,
  FlaskConical,
  Info,
  Layers3,
  ListChecks,
  LoaderCircle,
  Pause,
  RotateCcw,
  Settings2,
  ChevronDown,
  ShieldCheck,
  LockKeyhole,
  AlertCircle,
} from "lucide-react";
import { mockDays, dateLabel, number, summarizeDay } from "../data/days";
import {
  defaultPipelineSettings,
  operationSteps,
  type Scenario,
} from "../data/operations";
import { useMockPipeline } from "../hooks/useMockPipeline";
import { dayDetailsPath } from "../lib/dayNavigation";
import { OperationStep } from "../components/operations/OperationStep";
import { PipelineLogs } from "../components/operations/PipelineLogs";
import type { ProcessingDay } from "../data/days";
import "./operations.css";

export function OperationsPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("day");
  const day = mockDays.find((item) => item.date === requested);
  return (
    <OperationsWorkspace
      key={day?.date ?? "no-day"}
      day={day}
      invalidDay={requested !== null && !day}
      onDayChange={(date) =>
        setParams((previous) => {
          const next = new URLSearchParams(previous);
          if (date) next.set("day", date);
          else next.delete("day");
          return next;
        })
      }
    />
  );
}

function OperationsWorkspace({
  day,
  invalidDay,
  onDayChange,
}: {
  day: ProcessingDay | undefined;
  invalidDay: boolean;
  onDayChange: (date: string) => void;
}) {
  const [settings, setSettings] = useState({ ...defaultPipelineSettings });
  const [scenario, setScenario] = useState<Scenario>("success");
  const { state, run, stop, reset, busy } = useMockPipeline(day);
  const completed = state.steps.filter(
    (step) => step.status === "succeeded",
  ).length;
  const finished = completed === operationSteps.length;
  const progress = Math.round(
    state.steps.reduce((sum, step) => sum + step.progress, 0) /
      operationSteps.length,
  );
  const current = state.steps.findIndex((step) => step.status === "running");
  const first = state.steps.findIndex((step) => step.status !== "succeeded");
  const settingsLocked = state.steps.some((step) => step.status !== "pending");
  const summary = day ? summarizeDay(day) : null;
  const executionLabel = !day
    ? "ابتدا روز را انتخاب کنید"
    : finished
      ? "همهٔ مراحل نمایشی تکمیل شدند"
      : busy
        ? `${operationSteps[current >= 0 ? current : 0].shortLabel} در حال نمایش است`
        : state.status === "failed"
          ? "اجرا به خطای نمونه رسید"
          : state.status === "interrupted"
            ? "شبیه‌سازی متوقف شده است"
            : completed
              ? "آمادهٔ ادامهٔ مراحل"
              : "آمادهٔ شروع پردازش";

  function newSimulation() {
    reset();
    setSettings({ ...defaultPipelineSettings });
    setScenario("success");
  }
  return (
    <main
      id="main-content"
      className="main-content operations-page"
      tabIndex={-1}
    >
      <div className="page-heading op-page-heading">
        <div>
          <p className="eyebrow">تحلیل و پردازش / مسیر آماده‌سازی داده</p>
          <h1>عملیات و پردازش</h1>
          <p className="page-description">
            روز را انتخاب کنید و مراحل آماده‌سازی را با یک مسیر روشن پیش ببرید.
          </p>
        </div>
        <span className="op-mock-badge">
          <FlaskConical size={15} />
          اجرای نمایشی
        </span>
      </div>
      <p className="op-mock-notice">
        <Info size={15} />
        <span>
          این صفحه ماک است؛ دکمه‌ها فقط شبیه‌سازی را اجرا می‌کنند و دادهٔ واقعی
          تغییر نمی‌کند.
        </span>
        <span className="op-sequential-hint">
          <ListChecks size={14} />
          اجرای ترتیبی مراحل
        </span>
      </p>

      <section
        className={`op-card op-day-card${day ? " day-chosen" : ""}`}
        aria-labelledby="processing-day-title"
      >
        <div className="op-day-main">
          <span className="op-day-step">
            {day ? <Check size={20} /> : "۰۱"}
          </span>
          <div className="op-day-label">
            <span>گام اول</span>
            <h2 id="processing-day-title">انتخاب روز پردازش</h2>
            <p>تمام مراحل روی چانک‌های موجود همین روز اعمال می‌شوند.</p>
          </div>
          <label className="op-day-picker">
            <CalendarDays size={17} />
            <select
              aria-label="روز پردازش"
              value={day?.date ?? ""}
              disabled={busy}
              onChange={(event) => onDayChange(event.target.value)}
            >
              <option value="">یک روز را انتخاب کنید…</option>
              {mockDays.map((item) => (
                <option key={item.date} value={item.date}>
                  {dateLabel(item.date)}
                </option>
              ))}
            </select>
            <ChevronDown size={15} />
          </label>
        </div>
        {day && summary ? (
          <div className="op-day-context">
            <span>
              <Database size={14} />
              <strong>{number(summary.records)}</strong> رکورد خام
            </span>
            <span>
              <Layers3 size={14} />
              <strong>{number(day.chunks.length)}</strong> از{" "}
              {number(day.expectedChunks)} چانک موجود
            </span>
            <span className="op-source-file" dir="ltr">
              {day.source}
            </span>
            <Link to={dayDetailsPath(day.date)}>
              جزئیات روز
              <ArrowUpLeft size={14} />
            </Link>
          </div>
        ) : (
          <div className="op-day-empty">
            <LockKeyhole size={14} />
            {invalidDay
              ? "روز موجود در آدرس، در نمونه داده‌ای ندارد؛ یک روز از فهرست انتخاب کنید."
              : "با انتخاب روز، اولین مرحله فعال می‌شود. هنوز هیچ اجرایی شروع نشده است."}
          </div>
        )}
        {busy && (
          <p className="op-day-lock">
            <LockKeyhole size={12} />
            هنگام اجرا نمی‌توان روز یا پارامترها را تغییر داد.
          </p>
        )}
      </section>
      {day && summary && summary.missing > 0 && (
        <p className="op-coverage-note">
          <Info size={13} />
          {number(summary.missing)} چانک از روز نمونه موجود نیست؛ این مسیر فقط{" "}
          {number(day.chunks.length)} چانک موجود را شبیه‌سازی می‌کند.
        </p>
      )}

      <div className="op-workspace">
        <section className="op-stages" aria-labelledby="processing-steps-title">
          <div className="op-section-heading">
            <div>
              <ListChecks size={18} />
              <h2 id="processing-steps-title">مراحل پردازش روز</h2>
            </div>
            <span>{number(completed)} از ۴ مرحله تکمیل‌شده</span>
          </div>
          <ol className="op-steps-list">
            {operationSteps.map((step, index) => (
              <OperationStep
                key={step.id}
                index={index}
                execution={state.steps[index]}
                hasDay={!!day}
                ready={!!day && index === first && !busy}
                busy={busy}
                settings={state.settings ?? settings}
                onRun={() => run(index, settings, scenario)}
              />
            ))}
          </ol>
          <div className="op-stage-note">
            <ShieldCheck size={15} />
            <p>
              وضعیت این مسیر مستقل از صفحهٔ روزها و چانک‌هاست؛ اجرای نمایشی،
              گزارش‌ها یا خروجی‌های قبلی را بازنویسی نمی‌کند.
            </p>
          </div>
        </section>

        <aside className="op-run-sidebar">
          <section
            className="op-card op-run-summary"
            aria-labelledby="execution-summary-title"
          >
            <div className="op-summary-heading">
              <span className="op-summary-icon">
                <CirclePlay size={21} />
              </span>
              <div>
                <h2 id="execution-summary-title">اجرای یکپارچه</h2>
                <p>مراحل باقی‌مانده، به‌ترتیب و بدون هم‌پوشانی</p>
              </div>
            </div>
            <div className="op-summary-scope">
              <span>دامنهٔ اجرا</span>
              <strong>{day ? dateLabel(day.date) : "روز انتخاب نشده"}</strong>
            </div>
            <div className="op-total-progress">
              <div>
                <span>پیشرفت مسیر ماک</span>
                <strong>{number(progress)}٪</strong>
              </div>
              <progress
                max={100}
                value={progress}
                aria-label="پیشرفت کل مسیر نمایشی"
              />
            </div>
            <div
              className={`op-execution-state ${state.status}${finished ? " all-complete" : ""}`}
              role="status"
            >
              <span className="op-state-dot" />
              {executionLabel}
            </div>
            <button
              className="op-run-all"
              onClick={() => run("all", settings, scenario)}
              disabled={!day || busy || finished}
            >
              {busy ? (
                <LoaderCircle size={17} className="op-spin" />
              ) : finished ? (
                <Check size={17} />
              ) : (
                <CirclePlay size={17} />
              )}
              {busy
                ? "در حال اجرای نمایشی"
                : finished
                  ? "مراحل تکمیل شدند"
                  : "اجرای همهٔ مراحل"}
            </button>
            <p className="op-run-help">
              مراحل تکمیل‌شده تکرار نمی‌شوند؛ هر مرحله پس از موفقیت مرحلهٔ قبلی
              شروع می‌شود.
            </p>
            {busy && (
              <button className="op-stop-button" onClick={stop}>
                <Pause size={14} />
                توقف شبیه‌سازی
              </button>
            )}
            <button
              className="op-reset-button"
              disabled={busy || !settingsLocked}
              onClick={newSimulation}
            >
              <RotateCcw size={13} />
              شروع نمایش جدید
            </button>
            {state.runId && (
              <div className="op-run-id">
                <span>شناسهٔ آخرین اجرای ماک</span>
                <bdi>{state.runId}</bdi>
              </div>
            )}
            <details className="op-settings">
              <summary>
                <Settings2 size={15} />
                تنظیمات سناریو
                <ChevronDown size={14} />
              </summary>
              <div>
                <label>
                  سهم نمونه از دادهٔ نرمال‌شده
                  <select
                    aria-label="درصد نمونه‌برداری"
                    value={settings.samplePercent}
                    disabled={!day || settingsLocked || busy}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        samplePercent: Number(event.target.value),
                      })
                    }
                  >
                    {[5, 10, 15, 20, 30, 50].map((value) => (
                      <option key={value} value={value}>
                        {number(value)}٪
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  سهم نماینده از کاندیدها
                  <select
                    aria-label="درصد انتخاب نماینده"
                    value={settings.representativePercent}
                    disabled={!day || settingsLocked || busy}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        representativePercent: Number(event.target.value),
                      })
                    }
                  >
                    {[5, 10, 15, 20, 30].map((value) => (
                      <option key={value} value={value}>
                        {number(value)}٪
                      </option>
                    ))}
                  </select>
                </label>
                <p className="op-settings-note">
                  برای تغییر پارامترها پس از شروع، «نمایش جدید» بسازید.
                </p>
                <label>
                  حالت شبیه‌سازی
                  <select
                    aria-label="سناریوی شبیه‌سازی"
                    value={scenario}
                    disabled={!day || busy}
                    onChange={(event) =>
                      setScenario(event.target.value as Scenario)
                    }
                  >
                    <option value="success">اجرای موفق</option>
                    <option value="sampling-error">خطا در نمونه‌برداری</option>
                  </select>
                </label>
                <p className="op-settings-note">
                  سناریوی خطا فقط برای بررسی ظاهر شکست و تلاش مجدد است.
                </p>
              </div>
            </details>
          </section>
          <div className="op-local-note">
            <Info size={15} />
            <p>
              نمایش محلی است؛ با خروج از صفحه یا بازخوانی، شبیه‌سازی متوقف و
              وضعیت آن پاک می‌شود.
            </p>
          </div>
        </aside>
      </div>
      {finished && day && (
        <div className="op-completion-banner" role="status">
          <Check size={19} />
          <div>
            <strong>مسیر نمایشی این روز تکمیل شد</strong>
            <p>
              خروجی‌های هر مرحله در کارت همان مرحله قابل مشاهده‌اند. دادهٔ ماک
              روزها تغییری نکرده است.
            </p>
          </div>
          <Link to={dayDetailsPath(day.date)}>
            مشاهدهٔ روز
            <ArrowUpLeft size={14} />
          </Link>
        </div>
      )}
      {state.status === "failed" && (
        <p className="op-failure-note">
          <AlertCircle size={15} />
          مراحل بعدی اجرا نشده‌اند. برای تلاش مجدد موفق، حالت شبیه‌سازی را تغییر
          دهید؛ مرحله‌های موفق حفظ می‌شوند.
        </p>
      )}
      <PipelineLogs logs={state.logs} busy={busy} />
      <div className="op-bottom-note">
        <FlaskConical size={14} />
        <span>
          بدون درخواست API، حذف یا بازسازی واقعی · درصدها و خروجی‌ها صرفاً برای
          نمایش رابط کاربری‌اند
        </span>
        <ArrowDown size={12} aria-hidden="true" />
      </div>
    </main>
  );
}
