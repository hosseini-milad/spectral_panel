import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowUpLeft,
  CalendarDays,
  CheckCheck,
  Database,
  Info,
  Layers3,
  Radio,
  ShieldCheck,
  AlertCircle,
  Workflow,
  Server,
  Download,
  RefreshCw,
} from "lucide-react";
import { dateLabel, dayStatusLabels } from "../data/days";
import {
  apiPath,
  getJSON,
  type InventoryDay,
  type Page,
  displayNumber as number,
} from "../api/days";
import {
  type Overview,
  type OverviewJob,
  type OverviewSource,
  buildOverview,
  readinessLabels,
  noticeLabels,
} from "../api/overview";
import { useApi } from "../hooks/useApi";
import { dayDetailsPath, isISODate } from "../lib/dayNavigation";
import { IngestionTrend } from "../components/overview/IngestionTrend";
import "./overview.css";
const DailySchematic = lazy(() => import("../components/days/ChunkSchematic"));
const time = (value: string) =>
  new Intl.DateTimeFormat("fa-IR", {
    timeZone: "Asia/Tehran",
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
const decimal = (value: number | null) =>
  value === null
    ? "—"
    : new Intl.NumberFormat(
        "fa-IR",
        value > 0 && value < 0.01
          ? { maximumSignificantDigits: 3 }
          : { maximumFractionDigits: 2 },
      ).format(value);
const percent = (value: number | null) =>
  value === null ? "—" : `${decimal(value)}٪`;

export function OverviewPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("day");
  const latest = useApi<Page<InventoryDay>>(apiPath("days/", { limit: 1 }));
  const selected = requested ?? latest.data?.results[0]?.day ?? null;
  const date = selected && isISODate(selected) ? selected : null;
  const [dayOffset, setDayOffset] = useState(0);
  const days = useApi<Page<InventoryDay>>(
    apiPath("days/", { limit: 7, offset: dayOffset }),
  );
  const windowDays = Number(params.get("window") ?? 7);
  const validWindow =
    Number.isInteger(windowDays) && windowDays >= 1 && windowDays <= 90;
  const endpoint =
    date && validWindow
      ? apiPath(`days/${date}/overview/`, { window_days: windowDays })
      : null;
  const overview = useApi<Overview>(endpoint);
  const report = overview.data?.report;
  const day = overview.data?.day;
  const [sourceOffset, setSourceOffset] = useState(0);
  const sources = useApi<Page<OverviewSource>>(
    report
      ? apiPath(`days/${report.day}/overview/reports/${report.id}/sources/`, {
          limit: 5,
          offset: sourceOffset,
        })
      : null,
  );
  const jobId = params.get("report_job");
  const [jobState, setJobState] = useState<{
    scope: string;
    job?: OverviewJob;
    error?: string;
  }>({ scope: "" });
  const jobScope = `${date}:${windowDays}:${jobId}`;
  const job = jobState.scope === jobScope ? jobState.job : undefined;
  const [pollAttempt, setPollAttempt] = useState(0);
  const [posting, setPosting] = useState(false);
  const [buildError, setBuildError] = useState("");
  const requestRef = useRef<{ identity: string; key: string } | null>(null);
  const submission = useRef<AbortController | null>(null);
  useEffect(() => () => submission.current?.abort(), []);
  useEffect(() => {
    setSourceOffset(0);
    setBuildError("");
  }, [date, windowDays]);
  useEffect(() => {
    if (!date || !jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getJSON<OverviewJob>(
          apiPath(`days/${date}/overview/jobs/${jobId}/`),
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setJobState({ scope: jobScope, job: next });
        if (next.status === "queued" || next.status === "running")
          timer = setTimeout(poll, 10000);
      } catch (e) {
        if (!controller.signal.aborted)
          setJobState((previous) => ({
            scope: jobScope,
            job: previous.scope === jobScope ? previous.job : undefined,
            error: (e as Error).message,
          }));
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [date, jobId, jobScope, pollAttempt]);
  useEffect(() => {
    if (job?.status === "succeeded") {
      overview.retry();
      days.retry();
      setSourceOffset(0);
    }
  }, [job?.id, job?.status]);
  const busy = posting || job?.status === "queued" || job?.status === "running";
  async function build(fresh = false) {
    if (!day || submission.current) return;
    const identity = `${day.day}:${day.snapshot_id}:${windowDays}`;
    if (fresh || requestRef.current?.identity !== identity)
      requestRef.current = { identity, key: crypto.randomUUID() };
    const controller = new AbortController();
    submission.current = controller;
    setPosting(true);
    setBuildError("");
    try {
      const payload = await buildOverview(
        day.day,
        day.snapshot_id,
        windowDays,
        requestRef.current.key,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setJobState({
        scope: `${day.day}:${windowDays}:${payload.job.id}`,
        job: payload.job,
      });
      setParams((p) => {
        const q = new URLSearchParams(p);
        q.set("day", day.day);
        q.set("report_job", payload.job.id);
        return q;
      });
    } catch (e) {
      if (!controller.signal.aborted) setBuildError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setPosting(false);
      submission.current = null;
    }
  }
  const details = date ? dayDetailsPath(date) : "/days";
  const metrics = report
    ? [
        {
          label: "رویداد دریافت‌شده",
          value: number(report.metrics.raw_records),
          hint: "رکورد خام ذخیره‌شدهٔ روز",
          icon: Database,
          tone: "green",
        },
        {
          label: "میانگین تخمینی روزانه",
          value: decimal(report.metrics.estimated_daily_eps),
          hint: "رکورد خام ÷ ۸۶٬۴۰۰ ثانیه؛ EPS زنده نیست",
          icon: Activity,
          tone: "blue",
        },
        {
          label: "گروه‌های منبع مشاهده‌شده",
          value: number(report.metrics.source_groups),
          hint: "بر اساس source_type؛ شامل گروه نامشخص",
          icon: Radio,
          tone: "lilac",
        },
        {
          label: "پوشش نرمال‌سازی رکوردها",
          value: percent(report.metrics.normalization_coverage_percent),
          hint: "نرمال‌شده ÷ خام؛ نرخ پذیرش یا کیفیت نیست",
          icon: CheckCheck,
          tone: "green",
        },
        {
          label: "تکمیل چانک‌های لایهٔ اول",
          value: percent(report.metrics.layer1_completion_percent),
          hint: `${number(report.metrics.completed_chunks)} از ${number(report.metrics.expected_chunks)} چانک؛ مراحل بالاتر را شامل نمی‌شود`,
          icon: Layers3,
          tone: "blue",
        },
        {
          label: "موارد نیازمند پیگیری",
          value: number(report.metrics.operational_notices),
          hint: "مشاهدات عملیاتی؛ هشدار امنیتی نیست",
          icon: AlertCircle,
          tone: "amber",
        },
      ]
    : [];
  const paginate = (
    offset: number,
    count: number,
    size: number,
    change: (n: number) => void,
  ) => (
    <div className="ov-pagination">
      <button
        className="days-button"
        disabled={offset === 0}
        onClick={() => change(Math.max(0, offset - size))}
      >
        قبلی
      </button>
      <span>
        صفحهٔ {number(Math.floor(offset / size) + 1)} از{" "}
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
      className="main-content overview-page"
      tabIndex={-1}
    >
      <div className="page-heading ov-page-heading">
        <div>
          <p className="eyebrow">فضای کار / دید مدیریتی</p>
          <h1>نمای کلی</h1>
          <p className="page-description">
            وضعیت ورودی‌ها و آمادگی پردازش، بر اساس گزارش ذخیره‌شدهٔ روز.
          </p>
        </div>
        <label className="ov-date-filter">
          <CalendarDays size={16} />
          <span>روز گزارش</span>
          <select
            aria-label="روز گزارش مدیریتی"
            value={date ?? ""}
            disabled={posting}
            onChange={(e) =>
              setParams({ day: e.target.value, window: String(windowDays) })
            }
          >
            <option value="">روز را انتخاب کنید…</option>
            {day && !days.data?.results.some((d) => d.day === day.day) && (
              <option value={day.day}>{dateLabel(day.day)}</option>
            )}
            {days.data?.results.map((d) => (
              <option key={d.day} value={d.day}>
                {dateLabel(d.day)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {days.data &&
        days.data.count > 7 &&
        paginate(dayOffset, days.data.count, 7, setDayOffset)}
      <div className="ov-report-controls">
        <label>
          بازهٔ نمودار
          <select
            aria-label="بازهٔ نمودار"
            value={validWindow ? windowDays : 7}
            disabled={posting}
            onChange={(e) => {
              setParams((p) => {
                const q = new URLSearchParams(p);
                q.set("window", e.target.value);
                q.delete("report_job");
                return q;
              });
            }}
          >
            {[...new Set([7, 14, 30, ...(validWindow ? [windowDays] : [])])]
              .sort((a, b) => a - b)
              .map((n) => (
                <option key={n} value={n}>
                  {number(n)} روز
                </option>
              ))}
          </select>
        </label>
        <button
          className="days-button"
          disabled={!day || busy || !validWindow}
          onClick={() =>
            void build(
              !buildError &&
                (Boolean(report) ||
                  job?.status === "failed" ||
                  job?.status === "interrupted"),
            )
          }
        >
          <RefreshCw size={14} />
          {busy
            ? "در حال تولید گزارش…"
            : report
              ? "به‌روزرسانی گزارش نمودارها"
              : "ایجاد گزارش نمودارها"}
        </button>
        <button
          className="days-button"
          onClick={() => {
            overview.retry();
            days.retry();
            latest.retry();
          }}
        >
          بازخوانی اطلاعات
        </button>
        {report && (
          <a className="days-button" href={report.download_url}>
            <Download size={14} />
            دریافت JSON گزارش
          </a>
        )}
      </div>
      {(overview.loading || latest.loading) && (
        <p className="ov-mock-notice" role="status">
          در حال دریافت اطلاعات سرور…
        </p>
      )}
      {(overview.error || latest.error || days.error) && (
        <p className="ov-date-fallback" role="alert">
          {overview.error?.message ??
            latest.error?.message ??
            days.error?.message}
          <button
            className="days-button"
            onClick={() => {
              overview.retry();
              latest.retry();
              days.retry();
            }}
          >
            تلاش دوباره
          </button>
        </p>
      )}
      {(!validWindow || (requested && !date)) && (
        <p role="alert" className="ov-date-fallback">
          روز یا بازهٔ گزارش معتبر نیست؛ تاریخ میلادی و بازهٔ ۱ تا ۹۰ روز انتخاب
          کنید.
        </p>
      )}
      {!latest.loading &&
        !latest.error &&
        latest.data?.count === 0 &&
        !requested && (
          <p className="ov-date-fallback">
            روزی در کالکشن اطلاعات سرور ثبت نشده است. ابتدا اطلاعات روزها را
            همگام کنید.
          </p>
        )}
      {(buildError || (jobState.scope === jobScope && jobState.error)) && (
        <p className="ov-date-fallback" role="alert">
          {buildError || jobState.error}
          <button
            className="days-button"
            onClick={() => {
              if (buildError) void build();
              else if (jobId) setPollAttempt((v) => v + 1);
            }}
          >
            تلاش دوباره
          </button>
        </p>
      )}
      {job && (
        <p className="ov-mock-notice" role="status">
          {job.status === "queued"
            ? `گزارش در صف است${job.queue_position !== null ? "؛ جایگاه " + number(job.queue_position) : ""}.`
            : job.status === "running"
              ? "گزارش در حال محاسبه است؛ درصد ساخت اندازه‌گیری نشده است."
              : job.status === "succeeded"
                ? "گزارش ساخته و در دیتابیس ذخیره شد."
                : "ساخت گزارش انجام نشد؛ روز را بازخوانی و گزارش تازه درخواست کنید."}
          {(job.status === "queued" || job.status === "running") &&
            !job.worker.online &&
            " worker گزارش فعال نیست؛ فرمان run_api_worker را بررسی کنید."}
          <bdi>{job.id}</bdi>
        </p>
      )}
      {overview.data?.stale && (
        <p className="ov-date-fallback" role="status">
          اطلاعات کالکشن روزها پس از تولید این گزارش تغییر کرده است. نمودارها
          متعلق به زمان گزارش‌اند؛ برای دادهٔ جدید گزارش را به‌روزرسانی کنید.
        </p>
      )}
      {day && !report && !overview.loading && (
        <section className="ov-brief" aria-label="گزارش موجود نیست">
          <div>
            <Info size={24} />
            <div>
              <h2>هنوز گزارش نمودارهای این روز و بازه ساخته نشده است</h2>
              <p>
                {number(day.raw_records)} رکورد خام در اطلاعات روز موجود است.
                برای محاسبه و ذخیرهٔ نمودارها «ایجاد گزارش نمودارها» را بزنید.
              </p>
            </div>
          </div>
        </section>
      )}
      {report && (
        <>
          <p className="ov-mock-notice">
            <Database size={14} />
            <span>
              منبع: گزارش واقعی ذخیره‌شده؛ بدون اتصال به تشخیص زندهٔ حمله
            </span>
            <span className="ov-snapshot">
              تولید: {time(report.generated_at)}
            </span>
          </p>
          <section
            className={`ov-brief${report.notices.length ? " has-notices" : ""}`}
            aria-label="خلاصهٔ وضعیت روز"
          >
            <div>
              <span className="ov-brief-icon">
                <AlertCircle size={21} />
              </span>
              <div>
                <h2>
                  {report.notices.length
                    ? "مواردی برای بررسی داده و پردازش ثبت شده است"
                    : "در این گزارش مورد عملیاتی برای پیگیری ثبت نشده است"}
                </h2>
                <p>
                  {dateLabel(report.day)} · پوشش ورودی{" "}
                  {percent(report.metrics.chunk_coverage_percent)} · وضعیت
                  امنیتی ارزیابی نشده
                </p>
              </div>
            </div>
            <Link className="ov-primary-link" to={details}>
              مشاهدهٔ جزئیات روز
              <ArrowUpLeft size={15} />
            </Link>
          </section>
          <section className="ov-metrics" aria-label="شاخص‌های کلیدی مدیریتی">
            {metrics.map((m) => (
              <Link className="ov-card ov-metric" to={details} key={m.label}>
                <div className="ov-metric-top">
                  <span className={`ov-metric-icon ${m.tone}`}>
                    <m.icon size={20} />
                  </span>
                  <ArrowUpLeft size={14} className="ov-card-arrow" />
                </div>
                <span className="ov-metric-label">{m.label}</span>
                <strong>{m.value}</strong>
                <span className="ov-metric-hint">{m.hint}</span>
              </Link>
            ))}
          </section>
          <p className="ov-rate-note">
            <Info size={13} />
            پوشش نرمال‌سازی، نرخ پذیرش داده و دقت تشخیص حمله نیست. سلامت زندهٔ
            منبع و نرخ پذیرش در داده‌های موجود اندازه‌گیری نشده‌اند.
          </p>
          <div className="ov-main-grid">
            <IngestionTrend selected={report.day} points={report.trend} />
            <section
              className="ov-card ov-readiness"
              aria-labelledby="readiness-title"
            >
              <div className="ov-card-heading">
                <div>
                  <span className="ov-title-icon">
                    <Workflow size={17} />
                  </span>
                  <div>
                    <h2 id="readiness-title">آمادگی پردازش</h2>
                    <p>
                      پوشش خروجی ثبت‌شده از{" "}
                      {number(report.metrics.expected_chunks)} چانک مورد انتظار
                    </p>
                  </div>
                </div>
                <Link to={details} aria-label="جزئیات آمادگی پردازش روز">
                  <ArrowUpLeft size={15} />
                </Link>
              </div>
              <div className="ov-stage-bars">
                {report.readiness.map((stage) => (
                  <Link to={details} key={stage.stage}>
                    <span>
                      {readinessLabels[stage.stage] ?? stage.stage}
                      {stage.evidence === "output_observed"
                        ? " (دارای خروجی)"
                        : ""}
                    </span>
                    {stage.percent === null ? (
                      <span
                        className="ov-unknown-track"
                        aria-label={`${readinessLabels[stage.stage]} اندازه‌گیری نشده`}
                      />
                    ) : (
                      <progress
                        max={100}
                        value={stage.percent}
                        aria-label={`پوشش ${readinessLabels[stage.stage]}`}
                      />
                    )}
                    <strong>
                      <bdi dir="ltr">
                        {number(stage.observed_chunks)} /{" "}
                        {number(stage.expected_chunks)}
                      </bdi>
                    </strong>
                  </Link>
                ))}
              </div>
              <div className="ov-model-note">
                <ShieldCheck size={16} />
                <p>
                  <strong>وضعیت امنیتی: ارزیابی نشده</strong>وجود خروجی،
                  به‌تنهایی پایان کامل کاندیدسازی یا انتخاب نماینده را اثبات
                  نمی‌کند. نبود هشدار به معنای نبود تهدید نیست.
                </p>
              </div>
              {day && (
                <Suspense
                  fallback={
                    <p className="ov-chart-note">
                      در حال بارگذاری ابزار تصویر…
                    </p>
                  }
                >
                  <DailySchematic day={day} />
                </Suspense>
              )}
            </section>
          </div>
          <div className="ov-secondary-grid">
            <section
              className="ov-card ov-sources"
              aria-labelledby="sources-title"
            >
              <div className="ov-card-heading">
                <div>
                  <span className="ov-title-icon">
                    <Server size={17} />
                  </span>
                  <div>
                    <h2 id="sources-title">منابع ورودی مشاهده‌شده</h2>
                    <p>
                      گروه‌بندی واقعی source_type؛ سلامت جمع‌آورنده اندازه‌گیری
                      نشده است.
                    </p>
                  </div>
                </div>
              </div>
              {sources.error && (
                <p role="alert" className="ov-date-fallback">
                  {sources.error.message}
                  <button onClick={sources.retry}>تلاش دوباره</button>
                </p>
              )}
              <div
                className="ov-table-scroll"
                role="region"
                aria-label="جدول منابع ورودی"
                tabIndex={0}
              >
                <table className="ov-source-table">
                  <thead>
                    <tr>
                      <th>نوع منبع ثبت‌شده</th>
                      <th>رکورد خام</th>
                      <th>آخرین ثبت در پایگاه</th>
                      <th>سلامت</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sources.data?.results.map((source) => (
                      <tr key={source.group_key}>
                        <th scope="row">{source.source_type ?? "نامشخص"}</th>
                        <td>
                          {number(source.records)}
                          <div className="ov-source-bar">
                            <span
                              style={{
                                width: `${report.metrics.raw_records ? (100 * source.records) / report.metrics.raw_records : 0}%`,
                              }}
                            />
                          </div>
                        </td>
                        <td className="ov-last-received">
                          {source.last_stored_at
                            ? time(source.last_stored_at)
                            : "—"}
                        </td>
                        <td>
                          <span className="ov-state unknown">ارزیابی نشده</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!sources.loading && sources.data?.count === 0 && (
                  <p className="ov-chart-note">
                    رکوردی برای گروه‌بندی منبع وجود ندارد.
                  </p>
                )}
              </div>
              {sources.data &&
                paginate(sourceOffset, sources.data.count, 5, setSourceOffset)}
              <div className="ov-quality-strip">
                <Info size={14} />
                <span>
                  زمان ثبت رکورد، زمان رخداد یا آخرین دریافت از جمع‌آورنده نیست.
                  منبع نامشخص: {number(report.metrics.unknown_source_records)}{" "}
                  رکورد.
                </span>
              </div>
            </section>
            <section
              className="ov-card ov-notices"
              aria-labelledby="notices-title"
            >
              <div className="ov-card-heading">
                <div>
                  <AlertCircle size={17} />
                  <h2 id="notices-title">موارد نیازمند پیگیری</h2>
                </div>
                <span>{number(report.notices.length)}</span>
              </div>
              <div className="ov-notice-list">
                {report.notices.length ? (
                  report.notices.map((notice) => (
                    <Link
                      key={notice.code}
                      className="ov-notice-item"
                      to={
                        notice.code === "latest_operation_failed"
                          ? `/operations?day=${report.day}${report.latest_operation_id ? "&run=" + report.latest_operation_id : ""}`
                          : details
                      }
                    >
                      <span className={`ov-priority ${notice.priority}`}>
                        {notice.priority === "high" ? "بالا" : "متوسط"}
                      </span>
                      <div>
                        <h3>
                          {noticeLabels[notice.code] ?? "بررسی اطلاعات روز"}
                        </h3>
                        <p>شمار ثبت‌شده: {number(notice.count)}</p>
                      </div>
                      <ArrowUpLeft size={14} />
                    </Link>
                  ))
                ) : (
                  <p className="ov-chart-note">
                    در این گزارش موردی ثبت نشده است.
                  </p>
                )}
              </div>
              <div className="ov-notice-footer">
                <Info size={13} />
                <span>
                  مشاهدات عملیاتی‌اند؛ هیچ پاسخ خودکار یا مسدودسازی اجرا
                  نمی‌شود.
                </span>
              </div>
            </section>
          </div>
        </>
      )}
      <section
        className="ov-card ov-recent"
        aria-labelledby="overview-recent-title"
      >
        <div className="ov-card-heading">
          <div>
            <CalendarDays size={17} />
            <div>
              <h2 id="overview-recent-title">وضعیت روزهای اخیر</h2>
              <p>اطلاعات کالکشن روزها؛ مستقل از زمان گزارش نمودارها.</p>
            </div>
          </div>
          <Link to="/days">
            روزها و چانک‌ها
            <ArrowUpLeft size={14} />
          </Link>
        </div>
        <div
          className="ov-table-scroll"
          role="region"
          aria-label="جدول مدیریتی روزهای اخیر"
          tabIndex={0}
        >
          <table className="ov-recent-table">
            <thead>
              <tr>
                <th>روز گزارش</th>
                <th>رویداد خام</th>
                <th>پوشش ورودی</th>
                <th>چانک کامل</th>
                <th>وضعیت روز</th>
                <th>بررسی</th>
              </tr>
            </thead>
            <tbody>
              {days.data?.results.map((item) => (
                <tr
                  key={item.day}
                  className={item.day === date ? "ov-selected-row" : ""}
                >
                  <th scope="row">
                    <Link to={dayDetailsPath(item.day)}>
                      {dateLabel(item.day)}
                      <small>
                        <bdi>{item.day}</bdi>
                      </small>
                    </Link>
                  </th>
                  <td>{number(item.raw_records)}</td>
                  <td>
                    <div className="ov-coverage-cell">
                      {item.chunk_coverage_percent !== null && (
                        <progress
                          max={100}
                          value={item.chunk_coverage_percent}
                          aria-label={`پوشش ورودی ${dateLabel(item.day)}`}
                        />
                      )}
                      <span>{percent(item.chunk_coverage_percent)}</span>
                    </div>
                  </td>
                  <td>
                    {number(item.complete_chunks)}{" "}
                    <small>از {number(item.expected_chunks)}</small>
                  </td>
                  <td>
                    <span className={`ov-day-status ${item.status}`}>
                      {dayStatusLabels[item.status]}
                    </span>
                  </td>
                  <td>
                    <Link
                      className="ov-row-details"
                      to={dayDetailsPath(item.day)}
                    >
                      جزئیات
                      <ArrowUpLeft size={14} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {days.data && paginate(dayOffset, days.data.count, 7, setDayOffset)}
      </section>
      <div className="ov-bottom-note">
        <Database size={14} />
        <span>
          {report
            ? `شناسهٔ گزارش: ${report.id} · نسخه: ${report.schema_version} · نمودارها از سری‌های ذخیره‌شده در دیتابیس رسم می‌شوند.`
            : "برای تولید نمودارها، روز و بازه را انتخاب و گزارش را ایجاد کنید."}
        </span>
      </div>
    </main>
  );
}
