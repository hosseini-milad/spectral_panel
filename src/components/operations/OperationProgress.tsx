import { useEffect, useRef, useState } from "react";
import { apiPath, getJSON } from "../../api/days";
import {
  labels,
  stages,
  type Settings,
  type Stage,
} from "../../api/operations";
import { number } from "../../data/days";

type Range = { start_chunk: number; end_chunk: number; count: number };
interface Summary {
  snapshot_id: string;
  inventory_observed_at: string;
  total_chunks: number;
  complete_chunks: number;
  remaining_chunks: number;
  partial_chunks: number;
  attention_chunks: number;
  reserved_remaining_chunks: number;
  first_remaining_chunk: number | null;
  highest_completed_chunk: number | null;
  completed_ranges: Range[];
  completed_ranges_truncated: boolean;
  stage_counts: Record<Stage, number>;
  suggested_selection:
    (Range & { reused_count: number; remaining_count: number }) | null;
  latest_run_settings: Settings | null;
  latest_settings_compatible: boolean;
  count: number;
  results: {
    chunk_index: number;
    status: string;
    stages: Record<Stage, boolean>;
    reserved: boolean;
  }[];
}
interface Job {
  status: string;
  status_url: string;
  worker: { online: boolean };
  queue_position: number | null;
}
const statusText: Record<string, string> = {
  complete: "کامل",
  partial: "نیمه‌کاره",
  attention: "نیازمند بررسی",
};

export function OperationProgress({
  day,
  snapshot,
  settings,
  onContinue,
  onSettings,
  onRefresh,
}: {
  day: string;
  snapshot: string;
  settings: Settings;
  onContinue: (range: Range) => void;
  onSettings: (settings: Settings) => void;
  onRefresh: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("complete");
  const [size, setSize] = useState(10);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<{ url: string; value: Summary }>();
  const [error, setError] = useState("");
  const [job, setJob] = useState<Job>();
  const [sending, setSending] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const key = useRef<string | null>(null);
  const refreshCallback = useRef(onRefresh);
  refreshCallback.current = onRefresh;
  const url = apiPath(`days/${day}/operations/progress/`, {
    ...settings,
    limit: 10,
    offset,
    status,
    resume_size: size,
  });
  const summary = data?.url === url ? data.value : undefined;
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const value = await getJSON<Summary>(url, controller.signal);
        if (!controller.signal.aborted) {
          setData({ url, value });
          setError("");
        }
      } catch {
        if (!controller.signal.aborted)
          setError(
            "دریافت آمار ممکن نشد؛ اندازهٔ چانک و اجرای فعال روز را بررسی کنید.",
          );
      }
    };
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [url, snapshot, attempt]);
  useEffect(() => {
    if (
      !job ||
      ["succeeded", "failed", "interrupted", "cancelled"].includes(job.status)
    )
      return;
    const controller = new AbortController();
    const timer = setInterval(async () => {
      try {
        const next = await getJSON<Job>(job.status_url, controller.signal);
        if (controller.signal.aborted) return;
        setJob(next);
        if (next.status === "succeeded") {
          setAttempt((n) => n + 1);
          refreshCallback.current();
          setNotice("آمار از خروجی‌های موجود بازخوانی شد.");
        }
        if (["failed", "interrupted", "cancelled"].includes(next.status))
          setRefreshError("بازخوانی کامل نشد؛ دوباره تلاش کنید.");
      } catch {
        if (!controller.signal.aborted)
          setRefreshError(
            "دریافت وضعیت بازخوانی ممکن نشد؛ تلاش دوباره خودکار است.",
          );
      }
    }, 10000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [job]);
  const busy =
    sending ||
    (!!job &&
      !["succeeded", "failed", "interrupted", "cancelled"].includes(
        job.status,
      ));
  async function refresh() {
    if (pending.current || busy) return;
    pending.current = true;
    setSending(true);
    setRefreshError("");
    setNotice("");
    key.current ??= crypto.randomUUID();
    try {
      const response = await fetch(
        apiPath(`days/${day}/operations/progress/`),
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": key.current,
          },
          body: JSON.stringify({ snapshot_id: snapshot }),
        },
      );
      if (!response.ok) {
        if (response.status === 409) key.current = null;
        throw new Error();
      }
      const result = (await response.json()) as { job: Job };
      key.current = null;
      setJob(result.job);
      if (result.job.status === "succeeded") {
        setAttempt((n) => n + 1);
        refreshCallback.current();
      }
    } catch {
      setRefreshError(
        "ثبت بازخوانی انجام نشد؛ اطلاعات روز را بازخوانی و دوباره تلاش کنید.",
      );
    } finally {
      pending.current = false;
      setSending(false);
    }
  }
  return (
    <section className="op-progress" aria-label="آمار پردازش چانک‌ها">
      <div className="op-progress-heading">
        <strong>وضعیت پردازش چانک‌های روز</strong>
        <button
          className="days-button"
          disabled={busy}
          onClick={() => void refresh()}
        >
          {busy ? "در حال بازخوانی…" : "بازخوانی آمار از خروجی‌ها"}
        </button>
      </div>
      {refreshError && <p role="alert">{refreshError}</p>}
      {busy && job && (
        <p role="status">
          {job.worker.online
            ? "در انتظار تکمیل بازخوانی"
            : "برای بازخوانی، run_api_worker را اجرا کنید."}
          {job.queue_position !== null
            ? ` · جایگاه صف: ${number(job.queue_position)}`
            : ""}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            className="days-button"
            onClick={() => setAttempt((n) => n + 1)}
          >
            تلاش دوباره
          </button>
        </p>
      )}
      {!summary && !error && <p>در حال دریافت آمار…</p>}
      {summary && (
        <>
          <div className="op-progress-counts">
            <span>
              کامل{" "}
              <strong>
                {number(summary.complete_chunks)} از{" "}
                {number(summary.total_chunks)}
              </strong>
            </span>
            <span>
              باقی‌مانده <strong>{number(summary.remaining_chunks)}</strong>
            </span>
            <span>
              نیمه‌کاره <strong>{number(summary.partial_chunks)}</strong>
            </span>
            <span>
              نیازمند بررسی <strong>{number(summary.attention_chunks)}</strong>
            </span>
            <span>
              باقی‌مانده در صف / اجرا{" "}
              <strong>{number(summary.reserved_remaining_chunks)}</strong>
            </span>
          </div>
          <p>
            بازه‌های کامل:{" "}
            {summary.completed_ranges.length
              ? summary.completed_ranges
                  .map((r) =>
                    r.start_chunk === r.end_chunk
                      ? number(r.start_chunk)
                      : `${number(r.start_chunk)} تا ${number(r.end_chunk)}`,
                  )
                  .join("، ")
              : "هنوز چانک کاملی ثبت نشده است."}
            {summary.completed_ranges_truncated &&
              " … ادامه در فهرست صفحه‌بندی‌شده"}
          </p>
          <p>
            بالاترین شمارهٔ کامل:{" "}
            {summary.highest_completed_chunk === null
              ? "—"
              : number(summary.highest_completed_chunk)}{" "}
            · اولین چانک باقی‌مانده:{" "}
            {summary.first_remaining_chunk === null
              ? "همه کامل‌اند"
              : number(summary.first_remaining_chunk)}
          </p>
          <div className="op-progress-counts">
            {stages.map((stage) => (
              <span key={stage}>
                {labels[stage]}{" "}
                <strong>
                  {number(summary.stage_counts[stage])} از{" "}
                  {number(summary.total_chunks)}
                </strong>
              </span>
            ))}
          </div>
          <div className="op-progress-heading">
            <label>
              اندازهٔ نوبت ادامه{" "}
              <select
                aria-label="اندازهٔ نوبت ادامه"
                value={size}
                onChange={(e) => {
                  setSize(Number(e.target.value));
                  setNotice("");
                }}
              >
                {[5, 10, 20, 50].map((n) => (
                  <option key={n} value={n}>
                    {number(n)} چانک
                  </option>
                ))}
              </select>
            </label>
            <button
              className="days-button op-resume"
              disabled={!summary.suggested_selection || !!error}
              onClick={() => {
                if (summary.suggested_selection) {
                  onContinue(summary.suggested_selection);
                  setNotice(
                    "بازهٔ ادامه در فرم انتخاب شد؛ برای اجرا، آن را در صف ثبت کنید.",
                  );
                }
              }}
            >
              ادامهٔ پردازش
              {summary.suggested_selection
                ? ` از ${number(summary.suggested_selection.start_chunk)} تا ${number(summary.suggested_selection.end_chunk)}`
                : ""}
            </button>
            {summary.latest_settings_compatible &&
              summary.latest_run_settings && (
                <button
                  className="days-button"
                  onClick={() => onSettings(summary.latest_run_settings!)}
                >
                  استفاده از تنظیمات آخرین اجرا
                </button>
              )}
          </div>
          {summary.suggested_selection ? (
            <p>
              چانک‌های در صف از پیشنهاد کنار گذاشته می‌شوند.{" "}
              {number(summary.suggested_selection.reused_count)} چانک کامل در
              این بازه دوباره بررسی و استفاده می‌شود؛ خروجی ناسازگار نیازمند
              بررسی است.
            </p>
          ) : (
            <p>
              {summary.remaining_chunks === 0
                ? "همهٔ چانک‌ها کامل‌اند."
                : "تمام چانک‌های باقی‌مانده در صف یا در حال اجرا هستند."}
            </p>
          )}
          <details
            open={expanded}
            onToggle={(e) => setExpanded(e.currentTarget.open)}
          >
            <summary>فهرست چانک‌های پردازش‌شده</summary>
            <label>
              نمایش{" "}
              <select
                aria-label="فیلتر آمار چانک‌ها"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="complete">کامل</option>
                <option value="partial">نیمه‌کاره</option>
                <option value="attention">نیازمند بررسی</option>
                <option value="all">همهٔ موارد مشاهده‌شده</option>
              </select>
            </label>
            {summary.results.length ? (
              <div className="op-progress-table">
                <table>
                  <thead>
                    <tr>
                      <th>چانک</th>
                      <th>وضعیت</th>
                      {stages.map((s) => (
                        <th key={s}>{labels[s]}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {summary.results.map((r) => (
                      <tr key={r.chunk_index}>
                        <td>{number(r.chunk_index)}</td>
                        <td>
                          {statusText[r.status]}
                          {r.reserved ? " · در صف / اجرا" : ""}
                        </td>
                        {stages.map((s) => (
                          <td key={s}>{r.stages[s] ? "تکمیل" : "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>چانکی با این وضعیت ثبت نشده است.</p>
            )}
            <div className="op-pagination">
              <button
                className="days-button"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                قبلی
              </button>
              <span>
                {number(summary.count)} چانک · صفحهٔ {number(offset / 10 + 1)}
              </span>
              <button
                className="days-button"
                disabled={offset + 10 >= summary.count}
                onClick={() => setOffset(offset + 10)}
              >
                بعدی
              </button>
            </div>
          </details>
          <p className="op-settings-note">
            شماره‌ها از صفر هستند. آمار براساس تعداد خروجی‌های ذخیره‌شده و
            تنظیمات فعلی است؛ اعتبارسنجی نهایی هنگام اجرا انجام می‌شود. زمان
            مشاهده:{" "}
            {new Date(summary.inventory_observed_at).toLocaleString("fa-IR", {
              timeZone: "Asia/Tehran",
            })}{" "}
            تهران. دریافت وضعیت هر ۱۰ ثانیه؛ برای خروجی‌های تازهٔ اجرای مستقیم،
            بازخوانی آمار را بزنید.
          </p>
        </>
      )}
    </section>
  );
}
