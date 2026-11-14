import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Trash2,
  Activity,
  ArrowUpLeft,
  Check,
  Clock3,
  ListOrdered,
  RefreshCw,
  Layers3,
  Server,
  TriangleAlert,
} from "lucide-react";
import { apiPath, getJSON, type Page } from "../../api/days";
import {
  clearWaitingQueue,
  labels,
  phaseLabels,
  durationLabel,
  type Run,
} from "../../api/operations";
import { dateLabel, number } from "../../data/days";
interface Snapshot extends Page<Run> {
  execution_state:
    | "offline"
    | "unconfirmed"
    | "idle"
    | "starting"
    | "running"
    | "finalizing"
    | "other";
  worker: Run["worker"];
  active_run: Run | null;
  unconfirmed_runs: Run[];
  queued_total: number;
  observed_at: string;
}
const stateText = {
  offline: "worker در دسترس نیست",
  unconfirmed: "وضعیت اجرای فعال تأیید نشده",
  idle: "worker آماده است",
  starting: "در حال آغاز",
  running: "در حال اجرا",
  finalizing: "در حال ثبت نتیجه",
  other: "عملیات علمی دیگری در حال اجراست",
};
function scope(run: Run) {
  return run.selection.mode === "chunks"
    ? `${number(run.chunk_count)} چانک انتخابی`
    : `چانک ${number(run.chunk_start)} تا ${number(run.chunk_end)}`;
}
export function ExecutionQueue({
  day,
  selectedId,
  onSelect,
  offset,
  onPageChange,
  filters,
}: {
  day: string | null;
  selectedId: string | null;
  onSelect: (run: Run) => void;
  offset: number;
  onPageChange: (offset: number) => void;
  filters: ReactNode;
}) {
  const [clearBefore, setClearBefore] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const clearFlight = useRef(false);
  const [clearError, setClearError] = useState("");
  const [clearMessage, setClearMessage] = useState("");
  async function clearQueue() {
    if (!clearBefore || clearFlight.current) return;
    clearFlight.current = true;
    setClearing(true);
    setClearError("");
    try {
      const result = await clearWaitingQueue(clearBefore);
      setClearMessage(
        `${number(result.cancelled_count)} اجرای منتظر لغو شد؛ ${number(result.remaining_queued_count)} اجرا در صف باقی است.${result.skipped_count ? ` ${number(result.skipped_count)} مورد به دلیل تغییر وضعیت کنار گذاشته شد.` : ""}`,
      );
      setClearBefore(null);
      onPageChange(0);
      setAttempt((n) => n + 1);
    } catch (e) {
      setClearError((e as Error).message);
    } finally {
      clearFlight.current = false;
      setClearing(false);
    }
  }
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<{ url: string; value: Snapshot }>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const url = apiPath("operations/queue/", {
    limit: 5,
    offset,
    day: day ?? undefined,
  });
  // Preserve the same queue while paging; keep selection and polling independent.
  const snapshot = data?.value;
  const current = data?.url === url;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      setLoading(true);
      try {
        const value = await getJSON<Snapshot>(url, controller.signal);
        if (!controller.signal.aborted) {
          setData({ url, value });
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = setTimeout(load, 10000);
        }
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [url, attempt]);
  const active = snapshot?.active_run;
  const verified =
    snapshot &&
    !error &&
    ["starting", "running", "finalizing"].includes(snapshot.execution_state);
  const verifiedNow = !!verified;
  const online = !!snapshot?.worker.online && !error;
  const cards = [
    {
      label: "در انتظار اجرا",
      value: snapshot ? number(snapshot.queued_total) : "—",
      hint: "در صف علمی همهٔ روزها",
      icon: Clock3,
      tone: "queued",
    },
    {
      label: "اجرای فعال",
      value:
        snapshot && !error && snapshot.execution_state !== "unconfirmed"
          ? number(verifiedNow || snapshot.execution_state === "other" ? 1 : 0)
          : "—",
      hint: verifiedNow
        ? stateText[snapshot!.execution_state]
        : "براساس مالکیت worker",
      icon: Activity,
      tone: "running",
    },
    {
      label: "وضعیت worker",
      value: !snapshot || error ? "—" : online ? "متصل" : "قطع",
      hint: "پردازش علمی به‌ترتیب صف",
      icon: Server,
      tone: online ? "connected" : "offline",
    },
    {
      label: "وضعیت تأییدنشده",
      value: snapshot ? number(snapshot.unconfirmed_runs.length) : "—",
      hint: "اجراهای گزارش‌شده برای بررسی",
      icon: TriangleAlert,
      tone: "uncertain",
    },
  ];
  return (
    <section className="jq-live-queue" aria-label="صف اجراها">
      <div className="jq-stats">
        {cards.map(({ label, value, hint, icon: Icon, tone }) => (
          <div className={`jq-stat ${tone}`} key={label}>
            <div>
              <span>{label}</span>
              <Icon size={19} />
            </div>
            <strong>{value}</strong>
            <small>{hint}</small>
          </div>
        ))}
      </div>
      <div className="jq-queue-strip">
        <div>
          <i className={`jq-live-dot ${online ? "on" : ""}`} />
          <strong>صف علمی</strong>
          <span>
            {error
              ? "دریافت وضعیت تازه ممکن نشد"
              : online
                ? "worker متصل است"
                : snapshot
                  ? "worker پاسخ تازه‌ای ندارد"
                  : "در حال اتصال…"}
          </span>
        </div>
        <div>
          <span>به‌روزرسانی هر ۱۰ ثانیه</span>
          <button
            className="jq-text-button"
            aria-label="بازخوانی صف اجراها"
            disabled={loading}
            onClick={() => setAttempt((n) => n + 1)}
          >
            <RefreshCw size={13} />
            بازخوانی
          </button>
        </div>
      </div>
      <div className="jq-queue-actions">
        <span>
          پاک‌کردن صف شامل همهٔ روزهاست؛ اجرای فعال و خروجی‌ها حفظ می‌شوند.
        </span>
        <button
          className="jq-clear-button"
          disabled={
            !snapshot?.queued_total || !!error || clearing || !!clearBefore
          }
          onClick={() => {
            setClearBefore(snapshot!.observed_at);
            setClearError("");
            setClearMessage("");
          }}
        >
          <Trash2 size={14} />
          پاک‌کردن همهٔ صف انتظار
        </button>
      </div>
      {clearBefore && (
        <div
          className="jq-clear-confirm"
          role="region"
          aria-label="تأیید پاک‌کردن صف"
        >
          <div>
            <strong>همهٔ اجراهای منتظرِ مشاهده‌شده لغو شوند؟</strong>
            <p>
              فیلتر روز و صفحه‌بندی محدودیتی ایجاد نمی‌کنند. اجرای فعال ادامه
              می‌یابد؛ سوابق اجراها حذف نمی‌شوند.
            </p>
          </div>
          <div>
            <button
              className="jq-clear-button"
              disabled={clearing}
              onClick={() => void clearQueue()}
            >
              {clearing ? "در حال پاک‌کردن…" : "تأیید پاک‌کردن صف"}
            </button>
            <button
              className="jq-text-button"
              disabled={clearing}
              onClick={() => {
                setClearBefore(null);
                setClearError("");
              }}
            >
              انصراف
            </button>
          </div>
          {clearError && <p role="alert">{clearError}</p>}
        </div>
      )}
      {clearMessage && (
        <p className="jq-clear-result" role="status">
          {clearMessage}
        </p>
      )}
      {error && (
        <p className="jq-notice warning" role="alert">
          {error}
        </p>
      )}
      {!snapshot && !error && (
        <p className="jq-empty" role="status">
          در حال دریافت وضعیت صف…
        </p>
      )}
      {snapshot && (
        <>
          <div className="jq-overview-grid">
            <section
              className={`jq-card execution-active ${verifiedNow ? "is-running" : ""}`}
              aria-label="اجرای فعال سرور"
            >
              <div className="jq-card-title">
                <h2>
                  <Activity size={17} />
                  {verifiedNow
                    ? stateText[snapshot.execution_state]
                    : active
                      ? "اجرای ثبت‌شده، تأییدنشده"
                      : "اجرای فعال"}
                </h2>
                {verifiedNow && (
                  <span className="jq-status running">فعال روی سرور</span>
                )}
              </div>
              {active ? (
                <>
                  <div className="execution-active-scope">
                    <strong>
                      {dateLabel(active.day)} · {scope(active)}
                    </strong>
                    <bdi title={active.id}>{active.id.slice(0, 8)}</bdi>
                  </div>
                  <p>
                    {active.current_task
                      ? `چانک ${number(active.current_task.chunk_index)} · ${labels[active.current_task.stage]} · ${phaseLabels[active.current_task.phase ?? ""] ?? "پردازش"}`
                      : active.current_stage
                        ? `چانک ${active.current_chunk === null ? "—" : number(active.current_chunk)} · ${labels[active.current_stage]}`
                        : stateText[snapshot.execution_state]}
                  </p>
                  <div className="jq-active-progress">
                    <progress
                      value={
                        active.progress.processed_percent ??
                        active.progress.percent
                      }
                      max={100}
                      aria-label="پیشرفت اجرای فعال صف"
                    />
                    <b>
                      {number(
                        active.progress.processed_percent ??
                          active.progress.percent,
                      )}
                      ٪
                    </b>
                  </div>
                  <div className="execution-active-footer">
                    <span>
                      {active.current_task
                        ? durationLabel(active.current_task.elapsed_seconds)
                        : "در انتظار گزارش مرحله"}
                      {active.cancel_requested
                        ? " · توقف پس از چانک جاری درخواست شده"
                        : ""}
                    </span>
                    <button
                      className="jq-text-button"
                      onClick={() => onSelect(active)}
                    >
                      مشاهدهٔ اجرای فعال
                      <ArrowUpLeft size={14} />
                    </button>
                  </div>
                </>
              ) : (
                <p className="jq-active-empty">
                  {stateText[snapshot.execution_state]}
                  {snapshot.execution_state === "idle"
                    ? "؛ فعلاً اجرای فعالی ثبت نشده است."
                    : snapshot.execution_state === "offline"
                      ? "؛ اجرای صف به run_api_worker نیاز دارد."
                      : ""}
                </p>
              )}
              {(snapshot.execution_state === "unconfirmed" || error) && (
                <p className="jq-inline-warning">
                  وضعیت این اجرا قطعی نیست؛ آخرین اطلاعات ذخیره‌شده نمایش داده
                  می‌شود.
                </p>
              )}
            </section>
            <aside className="jq-card jq-worker-card">
              <h2>
                <Server size={17} />
                وضعیت اجراکننده
              </h2>
              <dl>
                <div>
                  <dt>ارتباط</dt>
                  <dd className={online ? "jq-good" : "jq-muted"}>
                    {error ? "نامشخص" : online ? "برقرار" : "قطع / تأییدنشده"}
                  </dd>
                </div>
                <div>
                  <dt>روش اجرا</dt>
                  <dd>یک اجرای علمی در هر نوبت</dd>
                </div>
                <div>
                  <dt>آخرین ضربان worker</dt>
                  <dd>
                    {snapshot.worker.heartbeat_age_seconds === null
                      ? "گزارش نشده"
                      : `${durationLabel(snapshot.worker.heartbeat_age_seconds)} پیش`}
                  </dd>
                </div>
                <div>
                  <dt>آخرین بررسی صف</dt>
                  <dd>
                    {new Date(snapshot.observed_at).toLocaleTimeString(
                      "fa-IR",
                      {
                        timeZone: "Asia/Tehran",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      },
                    )}{" "}
                    تهران
                  </dd>
                </div>
              </dl>
            </aside>
          </div>
          {!!snapshot.unconfirmed_runs.length && (
            <div className="jq-notice warning">
              <TriangleAlert size={16} />
              <span>
                مالک فعال برای {number(snapshot.unconfirmed_runs.length)} اجرای
                ثبت‌شده تأیید نمی‌شود.
              </span>
              {snapshot.unconfirmed_runs.map((run) => (
                <button
                  className="jq-text-button"
                  key={run.id}
                  onClick={() => onSelect(run)}
                >
                  {dateLabel(run.day)} · {scope(run)}
                  <ArrowUpLeft size={12} />
                </button>
              ))}
            </div>
          )}
          <section className="jq-card jq-waiting-card">
            <div className="jq-card-title">
              <div>
                <h2>
                  <ListOrdered size={17} />
                  در انتظار اجرا
                </h2>
                <p>به‌ترتیب واگذاری به worker علمی</p>
              </div>
              <span>{number(snapshot.count)} اجرا در این نما</span>
            </div>
            <div className="jq-filters">{filters}</div>
            <div
              className="jq-table-scroll"
              role="region"
              aria-label="جدول صف انتظار"
              tabIndex={0}
              aria-busy={loading && !current}
            >
              <table className="jq-table">
                <thead>
                  <tr>
                    <th>جایگاه</th>
                    <th>شناسهٔ اجرا</th>
                    <th>روز داده</th>
                    <th>دامنهٔ چانک‌ها</th>
                    <th>مراحل</th>
                    <th>وضعیت</th>
                    <th>بررسی</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.results.map((run) => (
                    <tr
                      key={run.id}
                      className={`execution-waiting-row ${selectedId === run.id ? "is-selected" : ""}`}
                    >
                      <td>
                        <span className="jq-position">
                          {run.queue_position === null
                            ? "—"
                            : number(run.queue_position)}
                        </span>
                      </td>
                      <td>
                        <bdi className="jq-run-id" title={run.id}>
                          {run.id.slice(0, 8)}
                        </bdi>
                        {selectedId === run.id && (
                          <small className="jq-selected-label">
                            <Check size={10} />
                            انتخاب‌شده
                          </small>
                        )}
                      </td>
                      <td>
                        {dateLabel(run.day)}
                        <small className="jq-cell-note">
                          <bdi>{run.day}</bdi>
                        </small>
                      </td>
                      <td>
                        <span className="jq-chunk-range">
                          <Layers3 size={13} />
                          {scope(run)}
                        </span>
                      </td>
                      <td>
                        {run.stages.length === 4
                          ? "مسیر کامل چانک"
                          : run.stages.map((s) => labels[s.stage]).join("، ")}
                      </td>
                      <td>
                        <span className="jq-status queued">
                          <Clock3 size={11} />
                          {run.status === "preparing"
                            ? "در حال ثبت"
                            : online
                              ? "در صف انتظار"
                              : "منتظر worker"}
                        </span>
                      </td>
                      <td>
                        <button
                          className="jq-row-action"
                          disabled={!current}
                          onClick={() => onSelect(run)}
                          aria-label={`مشاهده اجرای ${run.id}`}
                        >
                          جزئیات
                          <ArrowUpLeft size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!snapshot.results.length && (
                <p className="jq-empty">اجرای منتظری در این محدوده نیست.</p>
              )}
            </div>
            <footer className="jq-pagination">
              <span>
                {number(snapshot.count)} اجرا · صفحهٔ{" "}
                {number(Math.floor(offset / 5) + 1)}
              </span>
              <div>
                <button
                  disabled={!offset || loading}
                  onClick={() => onPageChange(Math.max(0, offset - 5))}
                >
                  قبلی
                </button>
                <button
                  disabled={offset + 5 >= snapshot.count || loading}
                  onClick={() => onPageChange(offset + 5)}
                >
                  بعدی
                </button>
              </div>
            </footer>
          </section>
        </>
      )}
    </section>
  );
}
