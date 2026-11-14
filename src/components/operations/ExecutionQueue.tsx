import { useEffect, useState } from "react";
import {
  Activity,
  ArrowUpLeft,
  Check,
  Clock3,
  ListOrdered,
  RefreshCw,
  Server,
  TriangleAlert,
} from "lucide-react";
import { apiPath, getJSON, type Page } from "../../api/days";
import {
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
}: {
  day: string | null;
  selectedId: string | null;
  onSelect: (run: Run) => void;
}) {
  const [onlyDay, setOnlyDay] = useState(false);
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<{ url: string; value: Snapshot }>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const url = apiPath("operations/queue/", {
    limit: 5,
    offset,
    day: onlyDay && day ? day : undefined,
  });
  // Preserve the same queue while paging; keep selection and polling independent.
  const snapshot = data?.value;
  const current = data?.url === url;
  useEffect(() => {
    if (onlyDay) setOffset(0);
  }, [day, onlyDay]);
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
  return (
    <section className="op-card execution-queue" aria-label="صف اجراها">
      <header className="execution-queue-header">
        <div>
          <ListOrdered size={19} />
          <h2>صف اجراها</h2>
          <span>{number(snapshot?.queued_total ?? 0)} منتظر</span>
        </div>
        <button
          className="days-button"
          aria-label="بازخوانی صف اجراها"
          onClick={() => setAttempt((n) => n + 1)}
          disabled={loading}
        >
          <RefreshCw size={14} />
          بازخوانی
        </button>
      </header>
      {error && (
        <p className="op-failure-note" role="alert">
          {error}
        </p>
      )}
      {!snapshot && !error && (
        <p className="execution-queue-empty" role="status">
          در حال دریافت وضعیت صف…
        </p>
      )}
      {snapshot && (
        <>
          <div
            className={`execution-worker-state ${snapshot.worker.online && !error ? "online" : "offline"}`}
          >
            <Server size={14} />
            <strong>
              {error
                ? "دریافت وضعیت تازه ممکن نشد"
                : snapshot.worker.online
                  ? "worker متصل است"
                  : "worker پاسخ تازه‌ای ندارد"}
            </strong>
            <span>پایش هر ۱۰ ثانیه</span>
          </div>
          <div className={`execution-active ${verified ? "is-running" : ""}`}>
            <div className="execution-active-heading">
              <span>
                <Activity size={16} />
                {verified
                  ? stateText[snapshot.execution_state]
                  : active
                    ? "اجرای ثبت‌شده، تأییدنشده"
                    : "اجرای فعال"}
              </span>
              {verified && <b>فعال روی سرور</b>}
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
                    ? `چانک ${number(active.current_task.chunk_index)} · ${labels[active.current_task.stage]} · ${phaseLabels[active.current_task.phase ?? ""] ?? "پردازش"} · ${durationLabel(active.current_task.elapsed_seconds)}`
                    : active.current_stage
                      ? `چانک ${active.current_chunk === null ? "—" : number(active.current_chunk)} · ${labels[active.current_stage]}`
                      : stateText[snapshot.execution_state]}
                </p>
                <progress
                  value={
                    active.progress.processed_percent ?? active.progress.percent
                  }
                  max={100}
                  aria-label="پیشرفت اجرای فعال صف"
                />
                <div className="execution-active-footer">
                  <span>
                    {number(
                      active.progress.processed_percent ??
                        active.progress.percent,
                    )}
                    ٪ رسیدگی‌شده
                    {active.cancel_requested
                      ? " · توقف پس از چانک جاری درخواست شده"
                      : ""}
                  </span>
                  <button
                    className="days-text-button"
                    onClick={() => onSelect(active)}
                  >
                    {selectedId === active.id ? (
                      <>
                        <Check size={13} />
                        در حال مشاهده
                      </>
                    ) : (
                      <>
                        مشاهدهٔ اجرای فعال
                        <ArrowUpLeft size={13} />
                      </>
                    )}
                  </button>
                </div>
              </>
            ) : (
              <p>
                {stateText[snapshot.execution_state]}
                {snapshot.execution_state === "idle"
                  ? "؛ فعلاً اجرای فعالی ثبت نشده است."
                  : snapshot.execution_state === "offline"
                    ? "؛ اجرای صف به run_api_worker نیاز دارد."
                    : ""}
              </p>
            )}
            {snapshot.execution_state === "unconfirmed" && (
              <p className="op-failure-note">
                مالکیت یا ارتباط worker تأیید نمی‌شود؛ این مورد به‌عنوان اجرای
                فعال قطعی نشان داده نمی‌شود.
              </p>
            )}
          </div>
          {!!snapshot.unconfirmed_runs.length && (
            <div className="execution-unconfirmed">
              <TriangleAlert size={15} />
              <span>
                برای {number(snapshot.unconfirmed_runs.length)} اجرای ثبت‌شده،
                مالک فعال تأیید نشده است.
              </span>
              {snapshot.unconfirmed_runs.map((run) => (
                <button
                  key={run.id}
                  className="days-text-button"
                  onClick={() => onSelect(run)}
                >
                  {dateLabel(run.day)} · {scope(run)}
                  <ArrowUpLeft size={12} />
                </button>
              ))}
            </div>
          )}
          <div className="execution-waiting-header">
            <h3>
              <Clock3 size={15} />
              در انتظار اجرا
            </h3>
            <label>
              نمایش
              <select
                aria-label="محدودهٔ صف انتظار"
                value={onlyDay && day ? "day" : "all"}
                onChange={(e) => {
                  setOnlyDay(e.target.value === "day");
                  setOffset(0);
                }}
              >
                <option value="all">همهٔ روزها</option>
                <option value="day" disabled={!day}>
                  روز انتخاب‌شده
                </option>
              </select>
            </label>
          </div>
          <div
            className="execution-waiting-list"
            aria-busy={loading && !current}
          >
            {snapshot.results.map((run) => (
              <button
                disabled={!current}
                key={run.id}
                className={`execution-waiting-row ${selectedId === run.id ? "is-selected" : ""}`}
                onClick={() => onSelect(run)}
                aria-label={`مشاهده اجرای ${run.id}`}
              >
                <span className="execution-position">
                  {run.queue_position === null
                    ? "—"
                    : number(run.queue_position)}
                </span>
                <span>
                  <strong>{dateLabel(run.day)}</strong>
                  <small>
                    {scope(run)} ·{" "}
                    <bdi title={run.id}>{run.id.slice(0, 8)}</bdi>
                  </small>
                </span>
                <span className="execution-waiting-label">
                  {run.status === "preparing"
                    ? "در حال ثبت"
                    : snapshot.worker.online
                      ? "در صف انتظار"
                      : "منتظر worker"}
                  {selectedId === run.id && <small>در حال مشاهده</small>}
                </span>
                <ArrowUpLeft size={14} />
              </button>
            ))}
            {!snapshot.results.length && (
              <p className="execution-queue-empty">
                اجرای منتظری در این محدوده نیست.
              </p>
            )}
          </div>
          <footer className="execution-queue-footer">
            <span>
              ترتیب صف علمی سرور · {number(snapshot.count)} مورد
              {!current ? " · در حال دریافت صفحه…" : ""}
            </span>
            <div>
              <button
                className="days-button"
                disabled={!offset || loading}
                onClick={() => setOffset(Math.max(0, offset - 5))}
              >
                قبلی
              </button>
              <span>صفحهٔ {number(Math.floor(offset / 5) + 1)}</span>
              <button
                className="days-button"
                disabled={offset + 5 >= snapshot.count || loading}
                onClick={() => setOffset(offset + 5)}
              >
                بعدی
              </button>
            </div>
          </footer>
        </>
      )}
    </section>
  );
}
