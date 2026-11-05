import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowUpLeft,
  CalendarDays,
  CheckCheck,
  ChevronLeft,
  Database,
  FlaskConical,
  Info,
  Layers3,
  Radio,
  ShieldCheck,
  AlertCircle,
  CircleCheck,
  Workflow,
  Server,
  ExternalLink,
} from "lucide-react";
import {
  mockDays,
  mockSnapshotDate,
  dateLabel,
  number,
  summarizeDay,
  dayStatusLabels,
} from "../data/days";
import { getOverview, decimal, sourceStateLabels } from "../data/overview";
import { dayDetailsPath } from "../lib/dayNavigation";
import { IngestionTrend } from "../components/overview/IngestionTrend";
import "./overview.css";

export function OverviewPage() {
  const [params, setParams] = useSearchParams();
  const requestedDate = params.get("day");
  const date = mockDays.some((item) => item.date === requestedDate)
    ? requestedDate!
    : mockSnapshotDate;
  const day = mockDays.find((item) => item.date === date)!;
  const overview = getOverview(day);
  const details = dayDetailsPath(date);
  const metrics = [
    {
      label: "رویداد دریافت‌شده",
      value: number(overview.records),
      hint: `${number(day.chunks.length)} از ${number(day.expectedChunks)} چانک موجود`,
      icon: Database,
      tone: "green",
    },
    {
      label: "نرخ تخمینی روزانه",
      value: decimal(overview.estimatedEPS),
      unit: "EPS",
      hint: "رکورد موجود ÷ ۸۶٬۴۰۰ ثانیه",
      icon: Activity,
      tone: "blue",
    },
    {
      label: "منابع در دسترس",
      value: `${number(overview.availableSources)} از ${number(overview.sources.length)}`,
      hint: "شامل منابع با تأخیر · ماک",
      icon: Radio,
      tone: "lilac",
    },
    {
      label: "نرخ پذیرش داده",
      value:
        overview.acceptanceRate === null
          ? "—"
          : `${decimal(overview.acceptanceRate, 2)}٪`,
      hint: "در چانک‌های نرمال‌شده",
      icon: CheckCheck,
      tone: "green",
    },
    {
      label: "پیشرفت پردازش روز",
      value: `${number(overview.progress)}٪`,
      hint: `${number(overview.complete)} از ${number(day.expectedChunks)} چانک کاملاً پردازش‌شده`,
      icon: Layers3,
      tone: "blue",
    },
    {
      label: "موارد باز عملیاتی",
      value: number(overview.notices.length),
      hint: "نیازمند پیگیری · بدون برچسب حمله",
      icon: AlertCircle,
      tone: "amber",
    },
  ];
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
            وضعیت ورودی‌ها، سلامت داده و آمادگی پردازش در یک نگاه.
          </p>
        </div>
        <label className="ov-date-filter">
          <CalendarDays size={16} />
          <span>روز گزارش</span>
          <select
            aria-label="روز گزارش مدیریتی"
            value={date}
            onChange={(event) => setParams({ day: event.target.value })}
          >
            {mockDays.map((item) => (
              <option value={item.date} key={item.date}>
                {dateLabel(item.date)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="ov-mock-notice">
        <FlaskConical size={15} />
        <span>
          نمای مدیریتی SIEM · داده‌های ثابت ماک، بدون اتصال زنده یا تشخیص حمله
        </span>
        <span className="ov-snapshot">
          نمونه تا {dateLabel(mockSnapshotDate)}
        </span>
      </div>
      {requestedDate !== null && requestedDate !== date && (
        <p className="ov-date-fallback" role="status">
          روز درخواستی در داده‌های ماک موجود نیست؛ آخرین روز نمونه نمایش داده
          می‌شود.
        </p>
      )}
      <section
        className={`ov-brief${overview.notices.length ? " has-notices" : ""}`}
        aria-label="خلاصهٔ وضعیت روز"
      >
        <div>
          <span
            className={`ov-brief-icon ${overview.notices.length ? "attention" : ""}`}
          >
            {overview.notices.length ? (
              <AlertCircle size={21} />
            ) : (
              <ShieldCheck size={21} />
            )}
          </span>
          <div>
            <h2>
              {overview.notices.length
                ? "چند مورد برای پیگیری وجود دارد"
                : "پردازش روز نمونه تکمیل شده است"}
            </h2>
            <p>
              {dateLabel(date, true)}
              <span>·</span>پوشش ورودی {number(overview.coverage)}٪
              <span>·</span>
              {number(overview.failed)} چانک ناموفق
            </p>
          </div>
        </div>
        <Link className="ov-primary-link" to={details}>
          مشاهدهٔ جزئیات روز
          <ArrowUpLeft size={15} />
        </Link>
      </section>
      <section className="ov-metrics" aria-label="شاخص‌های کلیدی مدیریتی">
        {metrics.map((metric) => (
          <Link className="ov-card ov-metric" to={details} key={metric.label}>
            <div className="ov-metric-top">
              <span className={`ov-metric-icon ${metric.tone}`}>
                <metric.icon size={20} strokeWidth={1.7} />
              </span>
              <ArrowUpLeft size={14} className="ov-card-arrow" />
            </div>
            <span className="ov-metric-label">{metric.label}</span>
            <strong>
              {metric.value}
              {metric.unit && <small>{metric.unit}</small>}
            </strong>
            <span className="ov-metric-hint">{metric.hint}</span>
          </Link>
        ))}
      </section>
      <p className="ov-rate-note">
        <Info size={13} />
        EPS این صفحه نرخ لحظه‌ای نیست؛ میانگین تخمینی یک روز تقویمی بر اساس
        رکوردهای موجود است. کیفیت داده نیز فقط روی چانک‌های نرمال‌شده سنجیده
        می‌شود.
      </p>
      <div className="ov-main-grid">
        <IngestionTrend selected={day} />
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
                  تکمیل هر مرحله از {number(day.expectedChunks)} چانک مورد
                  انتظار
                </p>
              </div>
            </div>
            <Link to={details} aria-label="جزئیات آمادگی پردازش روز">
              <ArrowUpLeft size={15} />
            </Link>
          </div>
          <div className="ov-stage-bars">
            {overview.stageCoverage.map((stage) => (
              <Link to={details} key={stage.label}>
                <span>{stage.label}</span>
                <progress
                  max={stage.expected}
                  value={stage.completed}
                  aria-label={`پوشش ${stage.label}`}
                />
                <strong>
                  <bdi dir="ltr">
                    {number(stage.completed)} / {number(stage.expected)}
                  </bdi>
                </strong>
              </Link>
            ))}
          </div>
          <div className="ov-readiness-bottom">
            <span>
              <i className="ov-dot blue" />
              {number(overview.running)} در حال پردازش
            </span>
            <span>
              <i className="ov-dot muted" />
              {number(overview.pending)} در انتظار
            </span>
            <span>
              <i className="ov-dot amber" />
              {number(overview.missing)} ناموجود
            </span>
          </div>
          <div className="ov-model-note">
            <ShieldCheck size={16} />
            <p>
              <strong>وضعیت امنیتی: ارزیابی نشده</strong>مدل و مرجع نرمال به این
              نمای ماک متصل نیستند؛ نبود هشدار، به معنی نبود تهدید نیست.
            </p>
            <Link to={details} aria-label="بررسی دادهٔ روز برای وضعیت امنیتی">
              <ChevronLeft size={15} />
            </Link>
          </div>
        </section>
      </div>

      <div className="ov-secondary-grid">
        <section className="ov-card ov-sources" aria-labelledby="sources-title">
          <div className="ov-card-heading">
            <div>
              <span className="ov-title-icon">
                <Server size={17} />
              </span>
              <div>
                <h2 id="sources-title">سلامت منابع ورودی</h2>
                <p>گروه‌های نمایشی منابع؛ شمارش‌ها با مجموع روز یکسان‌اند</p>
              </div>
            </div>
            <Link to={details}>
              بررسی دادهٔ روز
              <ArrowUpLeft size={14} />
            </Link>
          </div>
          <div
            className="ov-table-scroll"
            role="region"
            aria-label="وضعیت منابع نمونه"
            tabIndex={0}
          >
            <table className="ov-source-table">
              <thead>
                <tr>
                  <th scope="col">منبع رویداد</th>
                  <th scope="col">رکورد دریافتی</th>
                  <th scope="col">آخرین دریافت نمونه</th>
                  <th scope="col">وضعیت</th>
                  <th scope="col">
                    <span className="ov-sr-only">جزئیات روز</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {overview.sources.map((source) => (
                  <tr key={source.id}>
                    <th scope="row">
                      <span className="ov-source-name">{source.name}</span>
                      <small dir="ltr">{source.type}</small>
                    </th>
                    <td>
                      {number(source.records)}
                      <div className="ov-source-bar">
                        <span
                          style={{
                            width: `${overview.records ? (source.records / overview.records) * 100 : 0}%`,
                          }}
                        />
                      </div>
                    </td>
                    <td className="ov-last-received">
                      {source.lastReceived ?? "—"}
                    </td>
                    <td>
                      <span className={`ov-state ${source.state}`}>
                        <i />
                        {sourceStateLabels[source.state]}
                      </span>
                    </td>
                    <td>
                      <Link
                        to={details}
                        className="ov-table-link"
                        aria-label={`جزئیات روز ${dateLabel(date)} برای ${source.name}`}
                      >
                        <ArrowUpLeft size={15} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="ov-quality-strip">
            <span>
              <CheckCheck size={15} />
              کیفیت نرمال‌سازی
            </span>
            <strong>
              {number(overview.excludedRecords)} رکورد کنارگذاشته‌شده
            </strong>
            <span>
              {number(overview.unassessedRecords)} رکورد هنوز ارزیابی نشده
            </span>
            <Link to={details} aria-label="جزئیات کیفیت دادهٔ روز">
              <ChevronLeft size={14} />
            </Link>
          </div>
        </section>

        <section className="ov-card ov-notices" aria-labelledby="notices-title">
          <div className="ov-card-heading">
            <div>
              <span className="ov-title-icon amber">
                <AlertCircle size={17} />
              </span>
              <div>
                <h2 id="notices-title">
                  موارد نیازمند پیگیری{" "}
                  <span className="ov-count-badge">
                    {number(overview.notices.length)}
                  </span>
                </h2>
                <p>اولویت عملیاتی؛ رخداد امنیتی تأییدشده نیست</p>
              </div>
            </div>
          </div>
          {overview.notices.length ? (
            <div className="ov-notice-list">
              {overview.notices.map((notice) => (
                <Link key={notice.id} to={dayDetailsPath(notice.date)}>
                  <span className={`ov-notice-mark ${notice.priority}`} />
                  <div>
                    <div className="ov-notice-title">
                      <h3>{notice.title}</h3>
                      <span className={`ov-priority ${notice.priority}`}>
                        {notice.priority === "high" ? "بالا" : "متوسط"}
                      </span>
                    </div>
                    <p>
                      {notice.description.replace(/\d+/g, (value) =>
                        number(Number(value)),
                      )}
                    </p>
                  </div>
                  <ChevronLeft size={15} />
                </Link>
              ))}
            </div>
          ) : (
            <div className="ov-notices-empty">
              <CircleCheck size={31} />
              <h3>مورد عملیاتی بازی ثبت نشده است</h3>
              <p>
                این وضعیت فقط به سناریوی ماک مربوط است و تأیید سلامت امنیتی
                نیست.
              </p>
              <Link to={details}>
                بررسی جزئیات روز
                <ArrowUpLeft size={14} />
              </Link>
            </div>
          )}
          <div className="ov-notice-footer">
            <Info size={13} />
            <span>
              این موارد نمونه‌اند؛ هیچ پاسخ خودکار یا مسدودسازی اجرا نمی‌شود.
            </span>
          </div>
        </section>
      </div>

      <section
        className="ov-card ov-recent"
        aria-labelledby="overview-recent-title"
      >
        <div className="ov-card-heading">
          <div>
            <span className="ov-title-icon">
              <CalendarDays size={17} />
            </span>
            <div>
              <h2 id="overview-recent-title">وضعیت روزهای اخیر</h2>
              <p>برای ادامهٔ بررسی، روز مورد نظر را باز کنید.</p>
            </div>
          </div>
          <Link to={details}>
            روزها و چانک‌ها
            <ExternalLink size={13} />
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
                <th scope="col">روز گزارش</th>
                <th scope="col">رویداد خام</th>
                <th scope="col">پوشش ورودی</th>
                <th scope="col">چانک کامل</th>
                <th scope="col">وضعیت روز</th>
                <th scope="col">بررسی</th>
              </tr>
            </thead>
            <tbody>
              {mockDays.map((item) => {
                const summary = summarizeDay(item);
                return (
                  <tr
                    key={item.date}
                    className={item.date === date ? "ov-selected-row" : ""}
                  >
                    <th scope="row">
                      <Link to={dayDetailsPath(item.date)}>
                        {dateLabel(item.date)}
                        <small>
                          <bdi>{item.date}</bdi>
                        </small>
                      </Link>
                    </th>
                    <td>{number(summary.records)}</td>
                    <td>
                      <div className="ov-coverage-cell">
                        <progress
                          max={100}
                          value={summary.coverage}
                          aria-label={`پوشش ورودی ${dateLabel(item.date)}`}
                        />
                        <span>{number(summary.coverage)}٪</span>
                      </div>
                    </td>
                    <td>
                      {number(summary.complete)}{" "}
                      <small>از {number(item.expectedChunks)}</small>
                    </td>
                    <td>
                      <span className={`ov-day-status ${summary.status}`}>
                        {dayStatusLabels[summary.status]}
                      </span>
                    </td>
                    <td>
                      <Link
                        className="ov-row-details"
                        to={dayDetailsPath(item.date)}
                        aria-label={`باز کردن جزئیات ${dateLabel(item.date)}`}
                      >
                        جزئیات
                        <ArrowUpLeft size={14} />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <div className="ov-bottom-note">
        <FlaskConical size={14} />
        <span>
          منبع: داده‌های نمونهٔ روزها و پروفایل‌های نمایشی SIEM · همهٔ لینک‌های
          جزئیات به روز مشخص در صفحهٔ روزها و چانک‌ها می‌روند.
        </span>
      </div>
    </main>
  );
}
