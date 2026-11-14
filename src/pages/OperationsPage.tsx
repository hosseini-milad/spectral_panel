import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  ChevronDown,
  Check,
  CirclePlay,
  ListChecks,
  LoaderCircle,
  Layers3,
  Database,
  Settings2,
  ArrowUpLeft,
  Square,
  Clock3,
} from "lucide-react";
import { dateLabel, number } from "../data/days";
import { apiPath, type InventoryDay, type Page } from "../api/days";
import { useApi } from "../hooks/useApi";
import { useOperations } from "../hooks/useOperations";
import {
  submitOperation,
  cancelOperation,
  retryFailedOperation,
  type Run,
  stages,
  labels,
  statusLabels,
  eventMessage,
  type Selection,
  type Settings,
  type Request,
} from "../api/operations";
import { OperationProgress } from "../components/operations/OperationProgress";
import { ExecutionQueue } from "../components/operations/ExecutionQueue";
import { OperationStep } from "../components/operations/OperationStep";
import { PipelineLogs } from "../components/operations/PipelineLogs";
import { dayDetailsPath, isISODate } from "../lib/dayNavigation";
import "./operations.css";

export function OperationsPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("day");
  const dayCode = selected && isISODate(selected) ? selected : null;
  const runId = params.get("run");
  const [dayOffset, setDayOffset] = useState(0);
  const days = useApi<Page<InventoryDay>>(
    apiPath("days/", { limit: 10, offset: dayOffset }),
  );
  const day = useApi<InventoryDay>(
    dayCode ? apiPath(`days/${dayCode}/`) : null,
  );
  const [mode, setMode] = useState<Selection["mode"]>("all");
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(9);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [taskOffset, setTaskOffset] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
  const [settings, setSettings] = useState<Settings>({
    chunk_size: 20000,
    stage_timeout_seconds: 300,
    batch_size: 2000,
    sample_ratio: 0.1,
    representative_ratio: 0.1,
    neighbors: 12,
    threshold: 0.95,
    degree_cap: 20,
  });
  useEffect(() => {
    setSettings((s) => ({ ...s, chunk_size: day.data?.chunk_size ?? 20000 }));
  }, [day.data?.day, day.data?.chunk_size]);
  const monitor = useOperations(dayCode, runId, taskOffset, eventOffset);
  const latestRun = useApi<Page<Run>>(
    dayCode && !runId
      ? apiPath("operations/runs/", { day: dayCode, limit: 1 })
      : null,
  );
  useEffect(() => {
    const id = latestRun.data?.results[0]?.id;
    if (!id || runId || !dayCode) return;
    setParams(
      (previous) => {
        if (previous.get("run") || previous.get("day") !== dayCode)
          return previous;
        const next = new URLSearchParams(previous);
        next.set("run", id);
        return next;
      },
      { replace: true },
    );
  }, [latestRun.data, runId, dayCode, setParams]);
  const run = monitor.run;
  const [sending, setSending] = useState(false);
  const [cancellingRun, setCancellingRun] = useState<string | null>(null);
  const [cancelAcknowledged, setCancelAcknowledged] = useState<string | null>(
    null,
  );
  const [cancelError, setCancelError] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const cancellingRef = useRef(false);
  const [submitError, setSubmitError] = useState("");
  const inFlight = useRef(false);
  const savedRetry = useRef<{ identity: string; key: string } | null>(null);
  const savedRequest = useRef<{ identity: string; key: string } | null>(null);
  const selection: Selection =
    mode === "single"
      ? { mode, chunk_index: start }
      : mode === "range"
        ? { mode, start_chunk: start, end_chunk: end }
        : mode === "page"
          ? { mode, page, page_size: pageSize }
          : { mode: "all" };
  const total = day.data
    ? Math.ceil(day.data.raw_records / settings.chunk_size)
    : 0;
  const first =
    mode === "page" ? (page - 1) * pageSize : mode === "all" ? 0 : start;
  const last =
    mode === "page"
      ? Math.min(total - 1, first + pageSize - 1)
      : mode === "all"
        ? total - 1
        : mode === "single"
          ? start
          : end;
  const valid =
    !!day.data &&
    Number.isInteger(first) &&
    Number.isInteger(last) &&
    first >= 0 &&
    last >= first &&
    last < total &&
    last - first < 1000;
  const running =
    run?.status === "running" ||
    run?.status === "queued" ||
    run?.status === "preparing";
  const cancelPending =
    !!run && running && (run.cancel_requested || cancelAcknowledged === run.id);
  async function cancelCurrentRun() {
    if (!run || !running || cancelPending || cancellingRef.current) return;
    const id = run.id;
    cancellingRef.current = true;
    setCancellingRun(id);
    setCancelError(null);
    try {
      const result = await cancelOperation(id);
      if (result.cancel_requested) setCancelAcknowledged(id);
      monitor.retry();
    } catch (error) {
      setCancelError({ id, message: (error as Error).message });
      monitor.retry();
    } finally {
      cancellingRef.current = false;
      setCancellingRun(null);
    }
  }
  useEffect(() => {
    if (run?.cancel_requested || run?.status === "cancelled")
      setCancelError(null);
  }, [run?.id, run?.cancel_requested, run?.status]);
  const stageDescriptions = [
    "آماده‌سازی ویژگی‌های رکوردهای خام چانک؛ حدود نرمال‌سازی از کل روز.",
    "انتخاب کاندیدها با روش موجود خوشه‌بندی و ریسک/نوآوری.",
    "ساخت گراف شباهت کسینوسی و ذخیرهٔ مولفه‌های چانک.",
    "انتخاب مشاهدات نماینده از گراف و به‌روزرسانی اطلاعات مولفه‌ها.",
  ];
  function chooseRun(id: string, date?: string) {
    setTaskOffset(0);
    setEventOffset(0);
    setParams((p) => {
      const q = new URLSearchParams(p);
      q.set("run", id);
      if (date) q.set("day", date);
      return q;
    });
  }
  async function submit(stage: Request["stage"]) {
    if (!valid || !day.data || inFlight.current) return;
    const body: Request = {
      snapshot_id: day.data.snapshot_id,
      selection,
      stage,
      settings,
    };
    const identity = JSON.stringify({ day: dayCode, ...body });
    if (savedRequest.current?.identity !== identity)
      savedRequest.current = { identity, key: crypto.randomUUID() };
    inFlight.current = true;
    setSending(true);
    setSubmitError("");
    try {
      const result = await submitOperation(
        day.data.day,
        body,
        savedRequest.current.key,
      );
      savedRequest.current = null;
      chooseRun(result.run.id);
      monitor.retry();
    } catch (e) {
      setSubmitError((e as Error).message);
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }
  async function retryFailed() {
    if (!run || running || inFlight.current || !run.failed_chunks?.length)
      return;
    const timeout = settings.stage_timeout_seconds;
    const identity = `${run.id}:${timeout}`;
    if (savedRetry.current?.identity !== identity)
      savedRetry.current = { identity, key: crypto.randomUUID() };
    inFlight.current = true;
    setSending(true);
    setSubmitError("");
    try {
      const result = await retryFailedOperation(
        run.id,
        timeout,
        savedRetry.current.key,
      );
      savedRetry.current = null;
      chooseRun(result.run.id);
      monitor.retry();
    } catch (error) {
      setSubmitError((error as Error).message);
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }
  const logs = (monitor.events?.results ?? []).map((e) => ({
    id: String(e.sequence),
    time: e.time,
    level: e.level,
    message: `${eventMessage(e.code)}${e.chunk_index === null ? "" : ` · چانک ${number(e.chunk_index)}`}${e.stage ? ` · ${labels[e.stage]}` : ""}`,
  }));
  const pagination = (
    offset: number,
    count: number,
    size: number,
    change: (v: number) => void,
  ) => (
    <div className="op-pagination">
      <button
        className="days-button"
        disabled={offset === 0}
        onClick={() => change(Math.max(0, offset - size))}
      >
        قبلی
      </button>
      <span>
        {number(Math.floor(offset / size) + 1)} /{" "}
        {number(Math.max(1, Math.ceil(count / size)))}
      </span>
      <button
        className="days-button"
        disabled={offset + size >= count}
        onClick={() => change(offset + size)}
      >
        بعدی
      </button>
    </div>
  );
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
        </div>
        <span className="op-mock-badge">
          <Database size={15} />
          اطلاعات سرور
        </span>
      </div>
      <ExecutionQueue
        day={dayCode}
        selectedId={runId}
        onSelect={(item) => chooseRun(item.id, item.day)}
      />
      <section
        className={`op-card op-day-card${day.data ? " day-chosen" : ""}`}
        aria-labelledby="processing-day-title"
      >
        <div className="op-day-main">
          <span className="op-day-step">
            {day.data ? <Check size={20} /> : "۰۱"}
          </span>
          <div className="op-day-label">
            <span>گام اول</span>
            <h2 id="processing-day-title">انتخاب روز پردازش</h2>
            <p>دامنهٔ عملیات پیش از ثبت تثبیت می‌شود.</p>
          </div>
          <label className="op-day-picker">
            <CalendarDays size={17} />
            <select
              aria-label="روز پردازش"
              value={dayCode ?? ""}
              disabled={sending}
              onChange={(e) => {
                setTaskOffset(0);
                setEventOffset(0);
                setSubmitError("");
                setParams(e.target.value ? { day: e.target.value } : {});
              }}
            >
              <option value="">یک روز را انتخاب کنید…</option>
              {day.data &&
                !days.data?.results.some((d) => d.day === dayCode) && (
                  <option value={dayCode!}>{dateLabel(dayCode!)}</option>
                )}
              {days.data?.results.map((d) => (
                <option key={d.day} value={d.day}>
                  {dateLabel(d.day)}
                </option>
              ))}
            </select>
            <ChevronDown size={15} />
          </label>
        </div>
        {days.data &&
          days.data.count > 10 &&
          pagination(dayOffset, days.data.count, 10, setDayOffset)}
        {(days.error || day.error) && (
          <p className="op-failure-note" role="alert">
            {days.error?.message ?? day.error?.message}
            <button
              onClick={() => {
                days.retry();
                day.retry();
              }}
            >
              تلاش دوباره
            </button>
          </p>
        )}
        {day.data ? (
          <div className="op-day-context">
            <span>
              <Database size={14} />
              <strong>{number(day.data.raw_records)}</strong> رکورد خام
            </span>
            <span>
              <Layers3 size={14} />
              <strong>{number(total)}</strong> چانک ورودی
            </span>
            <Link to={dayDetailsPath(day.data.day)}>
              جزئیات روز
              <ArrowUpLeft size={14} />
            </Link>
            <button className="days-button" onClick={day.retry}>
              بازخوانی روز
            </button>
          </div>
        ) : (
          <div className="op-day-empty">
            {day.loading || days.loading
              ? "در حال دریافت روزها…"
              : "یک روز از فهرست سرور انتخاب کنید."}
          </div>
        )}
        {day.data &&
          (day.data.chunk_size === null ||
            day.data.chunk_size === settings.chunk_size) && (
            <OperationProgress
              key={day.data.day}
              day={day.data.day}
              snapshot={day.data.snapshot_id}
              settings={settings}
              onContinue={(range) => {
                setMode("range");
                setStart(range.start_chunk);
                setEnd(range.end_chunk);
              }}
              onSettings={(saved) =>
                setSettings({
                  ...saved,
                  stage_timeout_seconds: saved.stage_timeout_seconds ?? 300,
                })
              }
              onRefresh={day.retry}
            />
          )}
        <div className="op-scope-fields">
          <label>
            دامنهٔ اجرا
            <select
              aria-label="دامنهٔ چانک‌ها"
              value={mode}
              onChange={(e) => setMode(e.target.value as Selection["mode"])}
            >
              <option value="all">همهٔ چانک‌ها</option>
              <option value="single">چانک مشخص</option>
              <option value="range">بازهٔ چانک‌ها</option>
              <option value="page">صفحهٔ چانک‌ها</option>
            </select>
          </label>
          {(mode === "single" || mode === "range") && (
            <label>
              {mode === "single" ? "شمارهٔ چانک" : "از چانک"}
              <input
                aria-label="از چانک"
                type="number"
                min={0}
                value={start}
                onChange={(e) => setStart(Number(e.target.value))}
              />
            </label>
          )}
          {mode === "range" && (
            <label>
              تا چانک
              <input
                aria-label="تا چانک"
                type="number"
                min={0}
                value={end}
                onChange={(e) => setEnd(Number(e.target.value))}
              />
            </label>
          )}
          {mode === "page" && (
            <>
              <label>
                صفحه
                <input
                  aria-label="صفحهٔ چانک‌ها"
                  type="number"
                  min={1}
                  value={page}
                  onChange={(e) => setPage(Number(e.target.value))}
                />
              </label>
              <label>
                چانک در صفحه
                <select
                  aria-label="تعداد چانک در صفحه"
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                >
                  {[5, 10, 20, 50, 100].map((n) => (
                    <option key={n} value={n}>
                      {number(n)}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </div>
        <p className="op-day-empty">
          شمارهٔ واقعی چانک از صفر است؛ صفحهٔ اول با اندازهٔ ۱۰ شامل چانک‌های ۰
          تا ۹ است. حداکثر ۱۰۰۰ چانک در هر درخواست.
          {day.data && (
            <strong role="status">
              {valid
                ? ` دامنهٔ انتخابی: ${number(first)} تا ${number(last)}، ${number(last - first + 1)} چانک.`
                : " محدودهٔ انتخاب‌شده معتبر نیست."}
            </strong>
          )}
        </p>
      </section>
      {(submitError || monitor.error || latestRun.error) && (
        <p className="op-failure-note" role="alert">
          {submitError || monitor.error || latestRun.error?.message}
          {(monitor.error || latestRun.error) && (
            <button
              onClick={() => {
                monitor.retry();
                latestRun.retry();
              }}
            >
              تلاش دوباره
            </button>
          )}
        </p>
      )}
      <div className="op-workspace">
        <section className="op-stages" aria-labelledby="processing-steps-title">
          <div className="op-section-heading">
            <div>
              <ListChecks size={18} />
              <h2 id="processing-steps-title">مراحل پردازش روز</h2>
            </div>
            <span>
              {run ? "وضعیت اجرای انتخاب‌شده" : "هنوز اجرایی انتخاب نشده"}
            </span>
          </div>
          {!!run?.recent_errors?.length && (
            <div className="op-chunk-failures" role="alert">
              <strong>
                {number(run.failed_chunks?.length ?? run.recent_errors.length)}{" "}
                چانک ناموفق
                {running ? "؛ پردازش سایر چانک‌ها ادامه دارد" : " در این اجرا"}
              </strong>
              <ul>
                {run.recent_errors.map((item) => (
                  <li key={`${item.chunk_index}:${item.stage}`}>
                    <b>
                      چانک {number(item.chunk_index)} · {labels[item.stage]}
                    </b>
                    <span>{eventMessage(item.error.code)}</span>
                  </li>
                ))}
              </ul>
              <small>
                آخرین خطاها؛ فهرست کامل کارها و رویدادها پایین صفحه است.
              </small>
            </div>
          )}
          <ol className="op-steps-list">
            {stages.map((stage, index) => {
              const step = run?.stages.find((s) => s.stage === stage);
              return (
                <OperationStep
                  key={stage}
                  index={index}
                  title={labels[stage]}
                  description={stageDescriptions[index]}
                  step={step}
                  ready={valid && !sending}
                  busy={sending}
                  onRun={() => void submit(stage)}
                  runId={run?.id}
                  activeTask={
                    run?.current_task?.stage === stage ? run.current_task : null
                  }
                />
              );
            })}
          </ol>
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
                <p>چانک‌ها و مراحل، به‌ترتیب و بدون هم‌پوشانی</p>
              </div>
            </div>
            <div className="op-summary-scope">
              <span>دامنهٔ درخواست جدید</span>
              <strong>
                {day.data
                  ? `${dateLabel(day.data.day)} · ${number(first)} تا ${number(last)}`
                  : "روز انتخاب نشده"}
              </strong>
            </div>
            <button
              className="op-run-all"
              disabled={!valid || sending}
              onClick={() => void submit("all")}
            >
              {sending ? (
                <LoaderCircle size={17} className="op-spin" />
              ) : (
                <CirclePlay size={17} />
              )}
              ثبت همهٔ مراحل در صف
            </button>
            <p className="op-run-help">
              بازنویسی اجباری و حذف داده از این صفحه انجام نمی‌شود. صف روی سرور
              باقی می‌ماند.
            </p>
            <details className="op-settings">
              <summary>
                <Settings2 size={15} />
                تنظیمات پردازش
                <ChevronDown size={14} />
              </summary>
              <div>
                {(
                  [
                    ["chunk_size", "ظرفیت هر چانک", 1, 1000000, 1],
                    [
                      "sample_ratio",
                      "نسبت کاندید (۰ تا ۱)",
                      0.001,
                      0.999,
                      0.01,
                    ],
                    [
                      "representative_ratio",
                      "نسبت نماینده (۰ تا ۱)",
                      0.001,
                      0.999,
                      0.01,
                    ],
                    ["neighbors", "تعداد همسایه", 1, 100, 1],
                    ["threshold", "آستانهٔ کسینوسی", -1, 1, 0.001],
                    ["degree_cap", "سقف درجه", 1, 1000, 1],
                    [
                      "stage_timeout_seconds",
                      "مهلت هر مرحله (ثانیه)",
                      30,
                      86400,
                      30,
                    ],
                  ] as const
                ).map(([key, label, min, max, step]) => (
                  <label key={key}>
                    {label}
                    <input
                      aria-label={label}
                      type="number"
                      min={min}
                      max={max}
                      step={step}
                      value={settings[key]}
                      disabled={
                        sending ||
                        (key === "chunk_size" && day.data?.chunk_size != null)
                      }
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          [key]: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                ))}
                <p className="op-settings-note">
                  آستانهٔ پیش‌فرض ۰٫۹۵ متعلق به فرمان فعلی ساخت گراف است. مسیر
                  فعلی ZCA اعمال نمی‌کند. تنظیمات گراف فقط برای گراف تازه
                  استفاده می‌شوند؛ پارامترهای واقعی گراف موجود در جزئیات هر کار
                  هستند.
                </p>
              </div>
            </details>
            {run && (
              <>
                <div className="op-summary-scope">
                  <span>اجرای در حال مشاهده</span>
                  <strong>
                    {dateLabel(run.day)} ·{" "}
                    {run.selection.mode === "chunks"
                      ? `${number(run.chunk_count)} چانک انتخابی`
                      : `${number(run.chunk_start)} تا ${number(run.chunk_end)}`}
                  </strong>
                </div>
                {!!run.failed_chunks?.length && (
                  <div className="op-retry-control">
                    <button
                      className="days-button op-retry-failed"
                      disabled={running || sending}
                      onClick={() => void retryFailed()}
                    >
                      <CirclePlay size={15} />
                      {sending
                        ? "در حال ثبت…"
                        : `اجرای مجدد ${number(run.failed_chunks.length)} چانک ناموفق`}
                    </button>
                    {running && (
                      <small>
                        پس از پایان این اجرا، چانک‌های ناموفق قابل اجرای مجدد
                        هستند.
                      </small>
                    )}
                  </div>
                )}
                {run.retry_of_run_id && (
                  <p className="op-retry-caption">
                    اجرای مجدد چانک‌های ناموفق · {number(run.chunk_count)} چانک
                  </p>
                )}
                <div className="op-run-id">
                  <bdi>{run.id}</bdi>
                </div>
                <div className="op-total-progress">
                  <div>
                    <span>پیشرفت رسیدگی به چانک‌ـ‌مرحله‌ها</span>
                    <strong>
                      {number(
                        run.progress.processed_percent ?? run.progress.percent,
                      )}
                      ٪
                    </strong>
                  </div>
                  <progress
                    max={100}
                    value={
                      run.progress.processed_percent ?? run.progress.percent
                    }
                    aria-label="پیشرفت کل عملیات"
                  />
                </div>
                <div
                  className={`op-execution-state ${run.status}`}
                  role="status"
                >
                  {statusLabels[run.status] ?? run.status}
                  {run.queue_position !== null
                    ? ` · جایگاه صف ${number(run.queue_position)}`
                    : ""}
                </div>
                <p className="op-run-help">
                  {number(run.progress.completed_units)} از{" "}
                  {number(run.progress.total_units)} واحد موفق ·{" "}
                  {number(run.progress.reused_units)} خروجی استفاده‌شده
                  {!!run.progress.failed_units &&
                    ` · ${number(run.progress.failed_units)} ناموفق`}
                  {!!run.progress.blocked_units &&
                    ` · ${number(run.progress.blocked_units)} اجرا نشده به علت خطای پیش‌نیاز`}
                  {run.current_chunk !== null
                    ? ` · چانک ${number(run.current_chunk)}`
                    : ""}
                  {run.current_stage ? ` · ${labels[run.current_stage]}` : ""}.
                  درصد داخل محاسبه اندازه‌گیری نشده است.
                </p>
                {running && (
                  <div className="op-cancel-control">
                    <button
                      className="op-cancel-button"
                      disabled={cancelPending || cancellingRun === run.id}
                      onClick={() => void cancelCurrentRun()}
                    >
                      {cancelPending ? (
                        <Clock3 size={15} />
                      ) : (
                        <Square size={13} />
                      )}
                      {cancellingRun === run.id
                        ? "در حال ثبت لغو…"
                        : cancelPending
                          ? "در انتظار توقف"
                          : "لغو ادامهٔ پردازش"}
                    </button>
                    <p role={cancelPending ? "status" : undefined}>
                      {cancelPending
                        ? run.current_chunk !== null
                          ? `درخواست لغو ثبت شد؛ چانک ${number(run.current_chunk)} تکمیل می‌شود و چانک بعدی شروع نخواهد شد.`
                          : "درخواست لغو ثبت شد؛ وضعیت توقف در حال دریافت است."
                        : "چانک جاری کامل می‌شود؛ سپس ادامهٔ این اجرا لغو خواهد شد."}
                    </p>
                  </div>
                )}
                {run.status === "cancelled" && (
                  <p className="op-cancel-completed" role="status">
                    <Square size={12} />
                    ادامهٔ اجرا لغو شد؛ خروجی چانک‌های تکمیل‌شده حفظ شده است.
                  </p>
                )}
                {cancelError?.id === run.id && (
                  <p className="op-failure-note" role="alert">
                    {cancelError.message}
                  </p>
                )}
                {running && run.execution_policy === "legacy_stop_on_error" && (
                  <p className="op-failure-note">
                    این اجرا با worker قدیمی شروع شده است؛ ادامه پس از خطا و
                    مهلت زمانی به نسخهٔ جدید worker نیاز دارد.
                  </p>
                )}
                {running && !run.worker.online && (
                  <p className="op-failure-note" role="status">
                    worker علمی فعال نیست؛ فرمان run_api_worker را بررسی کنید.
                  </p>
                )}
                {run.error && (
                  <p role="alert" className="op-failure-note">
                    {eventMessage(run.error.code)}
                  </p>
                )}
                <p className="op-settings-note">
                  نسخهٔ تنظیمات: <bdi>{run.configuration_version}</bdi> · آخرین
                  دریافت:{" "}
                  {new Intl.DateTimeFormat("fa-IR", {
                    timeZone: "Asia/Tehran",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  }).format(new Date(run.observed_at))}
                </p>
                {run.inventory_refresh === "failed" && (
                  <p role="alert">
                    اطلاعات روز همگام نشده؛ sync_processing_days را اجرا کنید.
                  </p>
                )}
              </>
            )}
          </section>
        </aside>
      </div>
      {run && (
        <section className="op-card op-queue">
          <div className="op-section-heading">
            <h2>جزئیات کارهای اجرا</h2>
            <span>{number(monitor.tasks?.count ?? 0)} چانک‌ـ‌مرحله</span>
          </div>
          <div className="op-task-scroll">
            <table className="op-task-table">
              <thead>
                <tr>
                  <th>چانک</th>
                  <th>مرحله</th>
                  <th>وضعیت</th>
                  <th>ورودی / خروجی</th>
                  <th>جزئیات</th>
                </tr>
              </thead>
              <tbody>
                {monitor.tasks?.results.map((task) => (
                  <tr key={task.position}>
                    <td>{number(task.chunk_index)}</td>
                    <td>{labels[task.stage]}</td>
                    <td>{statusLabels[task.status] ?? task.status}</td>
                    <td>
                      {task.result
                        ? `${number(task.result.input)} / ${number(task.result.output)}`
                        : "—"}
                    </td>
                    <td>
                      {task.error
                        ? eventMessage(task.error.code)
                        : task.result?.reused
                          ? "استفاده از خروجی موجود"
                          : "—"}
                      {task.result?.graph_parameters && (
                        <details>
                          <summary>پارامترهای گراف</summary>
                          <pre dir="ltr">
                            {JSON.stringify(
                              task.result.graph_parameters,
                              null,
                              2,
                            )}
                          </pre>
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {monitor.tasks &&
            pagination(taskOffset, monitor.tasks.count, 10, setTaskOffset)}
        </section>
      )}
      <PipelineLogs logs={logs} busy={!!running} />
      {monitor.events &&
        pagination(eventOffset, monitor.events.count, 20, setEventOffset)}
    </main>
  );
}
