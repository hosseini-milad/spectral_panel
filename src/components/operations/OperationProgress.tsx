import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowUpLeft,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Clock3,
  GitBranch,
  Info,
  Layers3,
  RefreshCw,
  RotateCcw,
  ScanLine,
  ShieldAlert,
} from "lucide-react";
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
  const [mapPage, setMapPage] = useState(0);
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
    limit: 1,
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
  const completion = summary?.total_chunks
    ? Math.min(
        100,
        Math.max(0, (summary.complete_chunks / summary.total_chunks) * 100),
      )
    : 0;
  const mapPages = Math.max(1, Math.ceil((summary?.total_chunks ?? 0) / 50));
  const visibleMapPage = Math.min(mapPage, mapPages - 1);
  const mapStart = visibleMapPage * 50;
  const suggestion = summary?.suggested_selection;
  const metrics = summary
    ? [
        {
          label: "چانک کامل",
          value: summary.complete_chunks,
          note: `از ${number(summary.total_chunks)} چانک روز`,
          icon: CircleCheck,
          tone: "green",
        },
        {
          label: "باقی‌مانده",
          value: summary.remaining_chunks,
          note: "تا تکمیل پردازش روز",
          icon: Layers3,
          tone: "neutral",
        },
        {
          label: "در صف / اجرا",
          value: summary.reserved_remaining_chunks,
          note: "از چانک‌های باقی‌مانده",
          icon: Clock3,
          tone: "blue",
        },
        {
          label: "نیمه‌کاره",
          value: summary.partial_chunks,
          note: "دارای خروجی برخی مراحل",
          icon: ScanLine,
          tone: "lilac",
        },
        {
          label: "نیازمند بررسی",
          value: summary.attention_chunks,
          note: "خروجی ناقص یا ناسازگار",
          icon: ShieldAlert,
          tone: "amber",
        },
      ]
    : [];
  return (
    <section className="op-progress" aria-label="آمار پردازش چانک‌ها">
      <header className="op-progress-header">
        <div className="op-progress-title">
          <span className="op-progress-title-icon">
            <Activity size={19} />
          </span>
          <div>
            <h3>وضعیت پردازش چانک‌های روز</h3>
            <p>پوشش پردازش و مسیر ادامه، در یک نگاه</p>
          </div>
        </div>
        <div className="op-progress-header-actions">
          <span className="op-progress-poll">
            <i aria-hidden="true" />
            پایش هر ۱۰ ثانیه
          </span>
          <button
            className="days-button op-progress-refresh"
            disabled={busy}
            onClick={() => void refresh()}
          >
            <RefreshCw
              size={14}
              className={busy ? "op-progress-spin" : undefined}
            />
            {busy ? "در حال بازخوانی…" : "بازخوانی آمار از خروجی‌ها"}
          </button>
        </div>
      </header>
      {refreshError && (
        <div className="op-progress-message is-warning" role="alert">
          <ShieldAlert size={16} />
          {refreshError}
        </div>
      )}
      {busy && job && (
        <div className="op-progress-message" role="status">
          <Clock3 size={16} />
          <span>
            {job.worker.online
              ? "در انتظار تکمیل بازخوانی"
              : "برای بازخوانی، run_api_worker را اجرا کنید."}
            {job.queue_position !== null
              ? ` · جایگاه صف: ${number(job.queue_position)}`
              : ""}
          </span>
        </div>
      )}
      {notice && (
        <div className="op-progress-message is-success" role="status">
          <CheckCheck size={16} />
          {notice}
        </div>
      )}
      {error && (
        <div className="op-progress-message is-warning" role="alert">
          <ShieldAlert size={16} />
          <span>{error}</span>
          <button
            className="days-button"
            onClick={() => setAttempt((n) => n + 1)}
          >
            تلاش دوباره
          </button>
        </div>
      )}
      {!summary && !error && (
        <div className="op-progress-skeleton" role="status">
          <span>در حال دریافت آمار…</span>
          <div>
            {[0, 1, 2, 3, 4].map((n) => (
              <i key={n} />
            ))}
          </div>
        </div>
      )}
      {summary && (
        <>
          <div className="op-progress-metrics">
            {metrics.map(({ label, value, note, icon: Icon, tone }) => (
              <div key={label} className={`op-progress-metric tone-${tone}`}>
                <div className="op-progress-metric-label">
                  <span>{label}</span>
                  <Icon size={17} />
                </div>
                <strong>{number(value)}</strong>
                <span className="op-progress-metric-note">{note}</span>
              </div>
            ))}
          </div>
          <div className="op-progress-workspace">
            <div className="op-coverage-card">
              <div className="op-coverage-heading">
                <div>
                  <h4>
                    <Layers3 size={16} />
                    پوشش چانک‌ها
                  </h4>
                  <p>شمارهٔ هر خانه، شناسهٔ واقعی چانک است.</p>
                </div>
                <div className="op-coverage-percent">
                  <strong>
                    {summary.total_chunks
                      ? number(Math.round(completion))
                      : "—"}
                    <small>٪</small>
                  </strong>
                  <span>
                    {number(summary.complete_chunks)} از{" "}
                    {number(summary.total_chunks)}
                  </span>
                </div>
              </div>
              <progress
                className="op-coverage-bar"
                value={summary.complete_chunks}
                max={summary.total_chunks || 1}
                aria-label="پوشش تکمیل چانک‌ها"
              />
              <div
                className="op-chunk-map"
                role="list"
                aria-label="نقشهٔ تکمیل چانک‌ها"
              >
                {Array.from(
                  {
                    length: Math.min(
                      50,
                      Math.max(0, summary.total_chunks - mapStart),
                    ),
                  },
                  (_, n) => {
                    const index = mapStart + n;
                    const done = summary.completed_ranges.some(
                      (r) => index >= r.start_chunk && index <= r.end_chunk,
                    );
                    const proposed =
                      suggestion &&
                      index >= suggestion.start_chunk &&
                      index <= suggestion.end_chunk;
                    const unknown = !done && summary.completed_ranges_truncated;
                    const text = done
                      ? "کامل"
                      : unknown
                        ? "اطلاعات تکمیل نامشخص"
                        : "باقی‌مانده";
                    return (
                      <span
                        role="listitem"
                        key={index}
                        className={`op-chunk-cell${done ? " is-complete" : ""}${proposed ? " is-proposed" : ""}${unknown ? " is-unknown" : ""}`}
                        title={`چانک ${number(index)} · ${text}${proposed ? " · بازهٔ پیشنهادی" : ""}`}
                        aria-label={`چانک ${number(index)}: ${text}${proposed ? "، بازهٔ پیشنهادی" : ""}`}
                      >
                        {number(index)}
                      </span>
                    );
                  },
                )}
              </div>
              {!summary.total_chunks && (
                <p className="op-progress-empty">
                  چانکی برای این روز ثبت نشده است.
                </p>
              )}
              <div className="op-chunk-map-footer">
                <div className="op-chunk-legend">
                  <span>
                    <i className="is-complete" />
                    کامل
                  </span>
                  <span>
                    <i />
                    باقی‌مانده
                  </span>
                  <span>
                    <i className="is-proposed" />
                    پیشنهاد ادامه
                  </span>
                  {summary.completed_ranges_truncated && (
                    <span>
                      <i className="is-unknown" />
                      نامشخص
                    </span>
                  )}
                </div>
                {mapPages > 1 && (
                  <div className="op-map-pagination">
                    <button
                      aria-label="چانک‌های قبلی در نقشه"
                      disabled={visibleMapPage === 0}
                      onClick={() => setMapPage(visibleMapPage - 1)}
                    >
                      <ChevronRight size={15} />
                    </button>
                    <span>
                      {number(mapStart)} تا{" "}
                      {number(
                        Math.min(summary.total_chunks - 1, mapStart + 49),
                      )}
                    </span>
                    <button
                      aria-label="چانک‌های بعدی در نقشه"
                      disabled={visibleMapPage + 1 >= mapPages}
                      onClick={() => setMapPage(visibleMapPage + 1)}
                    >
                      <ChevronLeft size={15} />
                    </button>
                  </div>
                )}
              </div>
              <div className="op-coverage-facts">
                <span>
                  آخرین شمارهٔ کامل{" "}
                  <b>
                    {summary.highest_completed_chunk === null
                      ? "—"
                      : number(summary.highest_completed_chunk)}
                  </b>
                </span>
                <span>
                  اولین چانک باقی‌مانده{" "}
                  <b>
                    {summary.first_remaining_chunk === null
                      ? "همه کامل‌اند"
                      : number(summary.first_remaining_chunk)}
                  </b>
                </span>
              </div>
              <div className="op-completed-ranges">
                <span>بازه‌های کامل</span>
                <div>
                  {summary.completed_ranges.length ? (
                    summary.completed_ranges.map((r) => (
                      <b key={r.start_chunk}>
                        {r.start_chunk === r.end_chunk
                          ? number(r.start_chunk)
                          : `${number(r.start_chunk)} تا ${number(r.end_chunk)}`}
                      </b>
                    ))
                  ) : (
                    <small>هنوز چانک کاملی ثبت نشده است.</small>
                  )}
                  {summary.completed_ranges_truncated && (
                    <small>ادامه در فهرست چانک‌ها</small>
                  )}
                </div>
              </div>
            </div>
            <aside
              className="op-resume-card"
              aria-label="پیشنهاد ادامهٔ پردازش"
            >
              <div className="op-resume-card-title">
                <span className="op-resume-icon">
                  <ArrowUpLeft size={20} />
                </span>
                <div>
                  <h4>نوبت بعدی پردازش</h4>
                  <p>ادامه از اولین چانکِ خارج از صف</p>
                </div>
              </div>
              {suggestion ? (
                <div className="op-resume-range">
                  <span>بازهٔ پیشنهادی</span>
                  <div>
                    <strong>{number(suggestion.start_chunk)}</strong>
                    <ArrowLeft size={20} />
                    <strong>{number(suggestion.end_chunk)}</strong>
                    <small>{number(suggestion.count)} چانک</small>
                  </div>
                </div>
              ) : (
                <div className="op-resume-empty">
                  <CircleCheck size={26} />
                  <strong>
                    {summary.total_chunks === 0
                      ? "چانکی برای پردازش وجود ندارد"
                      : summary.remaining_chunks === 0
                        ? "پردازش روز کامل است"
                        : "باقی‌مانده‌ها در صف هستند"}
                  </strong>
                  <p>
                    {summary.total_chunks === 0
                      ? "ابتدا داده‌های ورودی این روز را بررسی کنید."
                      : summary.remaining_chunks === 0
                        ? "همهٔ چانک‌ها کامل‌اند."
                        : "تمام چانک‌های باقی‌مانده در صف یا در حال اجرا هستند."}
                  </p>
                </div>
              )}
              <label className="op-resume-size">
                اندازهٔ نوبت ادامه
                <div>
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
                  <ChevronDown size={14} aria-hidden="true" />
                </div>
              </label>
              <button
                className="op-resume"
                disabled={!suggestion || !!error}
                onClick={() => {
                  if (suggestion) {
                    onContinue(suggestion);
                    setNotice(
                      "بازهٔ ادامه در فرم انتخاب شد؛ برای اجرا، آن را در صف ثبت کنید.",
                    );
                  }
                }}
              >
                <span>
                  ادامهٔ پردازش
                  {suggestion
                    ? ` از ${number(suggestion.start_chunk)} تا ${number(suggestion.end_chunk)}`
                    : ""}
                </span>
                <ArrowLeft size={16} />
              </button>
              <p className="op-resume-hint">
                با انتخاب ادامه، بازه در فرم قرار می‌گیرد؛ اجرای آن پس از ثبت در
                صف شروع می‌شود.
              </p>
              {suggestion && (
                <div className="op-resume-reuse">
                  <CheckCheck size={14} />
                  <span>
                    {number(suggestion.reused_count)} چانک کامل در این بازه قابل
                    استفادهٔ مجدد است.
                  </span>
                </div>
              )}
              {summary.latest_settings_compatible &&
                summary.latest_run_settings && (
                  <button
                    className="op-previous-settings"
                    onClick={() => onSettings(summary.latest_run_settings!)}
                  >
                    <RotateCcw size={13} />
                    استفاده از تنظیمات آخرین اجرا
                  </button>
                )}
            </aside>
          </div>
          <div className="op-stage-coverage" aria-label="پوشش مراحل پردازش">
            <div className="op-stage-coverage-heading">
              <GitBranch size={15} />
              <h4>تکمیل مراحل</h4>
              <span>تعداد چانک در هر مرحله</span>
            </div>
            <div className="op-stage-coverage-grid">
              {stages.map((stage, index) => (
                <div className="op-stage-coverage-item" key={stage}>
                  <div>
                    <span className="op-stage-index">{number(index + 1)}</span>
                    <span>{labels[stage]}</span>
                    <b>
                      {number(summary.stage_counts[stage])}
                      <small> از {number(summary.total_chunks)}</small>
                    </b>
                  </div>
                  <progress
                    value={summary.stage_counts[stage]}
                    max={summary.total_chunks || 1}
                    aria-label={`پوشش ${labels[stage]}`}
                  />
                </div>
              ))}
            </div>
          </div>
          <footer className="op-progress-footer">
            <span>
              <Info size={13} />
              شمارهٔ چانک‌ها از صفر است؛ آمار از خروجی‌های ذخیره‌شده خوانده
              می‌شود.
            </span>
            <span title="زمان مشاهده به وقت تهران است. برای خروجی‌های تازهٔ اجرای مستقیم، بازخوانی آمار را بزنید. شمارش‌ها براساس تنظیمات فعلی‌اند؛ اعتبارسنجی نهایی هنگام اجرا انجام می‌شود.">
              <Clock3 size={12} />
              آخرین مشاهده:{" "}
              <time dateTime={summary.inventory_observed_at}>
                {new Date(summary.inventory_observed_at).toLocaleString(
                  "fa-IR",
                  {
                    timeZone: "Asia/Tehran",
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  },
                )}
              </time>{" "}
              تهران
            </span>
          </footer>
        </>
      )}
    </section>
  );
}
