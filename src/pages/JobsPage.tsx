import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ListTodo,
  Play,
  Pause,
  Download,
  Search,
  ChevronDown,
  ChevronLeft,
  Clock3,
  LoaderCircle,
  CheckCircle2,
  CircleAlert,
  Filter,
  RotateCcw,
  ExternalLink,
} from "lucide-react";
import {
  initialJobs,
  advanceJobs,
  cancelJob,
  retryJob,
  canRetry,
  jobStatuses,
  jobStages,
  jobTime,
  downloadJobJSON,
  type JobStatus,
} from "../data/jobs";
import { mockDays, number, dateLabel, normalizeSearch } from "../data/days";
import { dayDetailsPath } from "../lib/dayNavigation";
import { JobDetail } from "../components/jobs/JobDetail";
import "./jobs.css";
export function JobsPage() {
  const [jobs, setJobs] = useState(initialJobs);
  const [simulate, setSimulate] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [params, setParams] = useSearchParams();
  const requestedStatus = params.get("status") ?? "all";
  const status = Object.hasOwn(jobStatuses, requestedStatus)
    ? requestedStatus
    : "all";
  const day = params.get("day") ?? "";
  const requestedStage = params.get("stage") ?? "all";
  const stage = Object.hasOwn(jobStages, requestedStage)
    ? requestedStage
    : "all";
  const search = params.get("q") ?? "";
  const sort = params.get("sort") === "oldest" ? "oldest" : "newest";
  const size = params.get("size") === "10" ? 10 : 5;
  const expanded = params.get("job");
  const filtered = jobs
    .filter(
      (j) =>
        (status === "all" || j.status === status) &&
        (!day || j.day === day) &&
        (stage === "all" || j.stage === stage) &&
        normalizeSearch(
          `${j.id} ${j.chunkId ?? ""} ${jobStages[j.stage]} ${j.worker ?? ""}`,
        ).includes(normalizeSearch(search)),
    )
    .sort(
      (a, b) =>
        (sort === "oldest" ? 1 : -1) *
        (a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id)),
    );
  const pageCount = Math.max(1, Math.ceil(filtered.length / size));
  const rawPage = Number(params.get("page") ?? 1);
  const page = Number.isInteger(rawPage)
    ? Math.max(1, Math.min(rawPage, pageCount))
    : 1;
  const visible = filtered.slice((page - 1) * size, page * size);
  const selected = jobs.find((j) => j.id === expanded);
  const change = (changes: Record<string, string | null>, resetPage = true) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      if (resetPage) next.delete("page");
      return next;
    });
  useEffect(() => {
    if (!simulate) return;
    const timer = window.setInterval(() => {
      const now = new Date().toISOString();
      setJobs((old) => advanceJobs(old, now));
      setLastUpdate(now);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [simulate]);
  function reveal(id: string) {
    const ordered = [...jobs].sort(
      (a, b) =>
        b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id),
    );
    const index = ordered.findIndex((j) => j.id === id);
    setParams({
      job: id,
      page: String(index < 0 ? 1 : Math.floor(index / 5) + 1),
    });
  }
  function retry(id: string) {
    const newId = `mock-job-${crypto.randomUUID().slice(0, 8)}`;
    const now = new Date().toISOString();
    setJobs((old) => {
      const job = old.find((j) => j.id === id);
      return job && canRetry(job, old)
        ? [retryJob(job, newId, now), ...old]
        : old;
    });
    setNotice("تلاش جدید در صف ماک ثبت شد؛ منبع و پارامترها حفظ شدند.");
    reveal(newId);
  }
  const statusIcon = (value: JobStatus) =>
    value === "running"
      ? LoaderCircle
      : value === "queued"
        ? Clock3
        : value === "succeeded"
          ? CheckCircle2
          : CircleAlert;
  const cards = [
    {
      status: "queued",
      label: "در انتظار اجرا",
      hint: "آمادهٔ واگذاری",
      icon: Clock3,
    },
    {
      status: "running",
      label: "در حال پردازش",
      hint: "اجرای نمونه",
      icon: LoaderCircle,
    },
    {
      status: "succeeded",
      label: "تکمیل موفق",
      hint: "خروجی نمایشی",
      icon: CheckCircle2,
    },
    {
      status: "failed",
      label: "نیازمند بررسی",
      hint: "خطای پردازش",
      icon: CircleAlert,
    },
  ] as const;
  return (
    <main id="main-content" className="main-content jq-page" tabIndex={-1}>
      <header className="jq-page-heading">
        <div>
          <span className="jq-eyebrow">
            <ListTodo size={14} />
            مرکز پیگیری پردازش
          </span>
          <h1>صف اجراها</h1>
          <p>از ثبت درخواست تا پایان پردازش؛ وضعیت، پیشرفت و سابقهٔ هر تلاش</p>
        </div>
        <div className="jq-actions">
          <button
            onClick={() => {
              setSimulate(!simulate);
              setNotice(
                simulate
                  ? "شبیه‌سازی متوقف شد؛ صف واقعی تغییری نکرد."
                  : "شبیه‌سازی محلی فعال شد؛ پیشرفت هر ۱٫۵ ثانیه تغییر می‌کند.",
              );
            }}
            aria-pressed={simulate}
            className={simulate ? "jq-simulation-on" : ""}
          >
            {simulate ? <Pause size={14} /> : <Play size={14} />}{" "}
            {simulate ? "توقف شبیه‌سازی" : "شروع شبیه‌سازی"}
          </button>
          <button
            onClick={() =>
              downloadJobJSON("mock-queue-filtered.json", {
                mock: true,
                scientific_output_generated: false,
                filters: { status, day, stage, search, sort },
                jobs: filtered,
              })
            }
          >
            <Download size={14} />
            خروجی فهرست
          </button>
        </div>
      </header>
      <div className="jq-mock-banner">
        <span className="jq-mock-label">ماک</span>
        <p>
          اجراها دادهٔ نمونه‌اند و با بازخوانی صفحه بازنشانی می‌شوند. لغو، تلاش
          مجدد و پیشرفت فقط محلی‌اند؛ هیچ عملیات علمی یا درخواست API اجرا
          نمی‌شود.
        </p>
      </div>
      <div className="jq-stats">
        {cards.map((card) => (
          <button
            key={card.status}
            className={`jq-stat ${card.status}`}
            aria-pressed={status === card.status}
            onClick={() =>
              change({
                status: status === card.status ? null : card.status,
                job: null,
              })
            }
          >
            <div>
              <span>{card.label}</span>
              <card.icon size={19} />
            </div>
            <strong>
              {number(jobs.filter((j) => j.status === card.status).length)}
            </strong>
            <small>{card.hint} · همهٔ روزها</small>
          </button>
        ))}
      </div>
      <div className="jq-queue-strip">
        <div>
          <span className={`jq-live-dot ${simulate ? "on" : ""}`} />
          <strong>صف علمی · نمونه</strong>
          <span>{simulate ? "شبیه‌سازی در حال اجرا" : "نمایش ثابت"}</span>
        </div>
        <div>
          <span>ظرفیت شبیه‌ساز: ۲ worker</span>
          <span>
            به‌روزرسانی: {lastUpdate ? jobTime(lastUpdate) : "هنوز انجام نشده"}
          </span>
        </div>
      </div>
      {notice && (
        <p className="jq-notice" role="status">
          {notice}
        </p>
      )}
      <section className="jq-card">
        <div className="jq-card-title">
          <div>
            <h2>فهرست اجراها</h2>
            <p>وضعیت هر تلاش مستقل از نتیجهٔ تلاش‌های دیگر است.</p>
          </div>
          <span>
            {number(filtered.length)} از {number(jobs.length)} اجرا
          </span>
        </div>
        <div className="jq-filters">
          <label className="jq-search">
            <Search size={15} />
            <input
              aria-label="جست‌وجوی اجرا"
              placeholder="شناسهٔ اجرا، چانک یا worker…"
              value={search}
              onChange={(e) => change({ q: e.target.value, job: null })}
            />
          </label>
          <label>
            روز داده
            <select
              aria-label="فیلتر روز اجرا"
              value={day}
              onChange={(e) => change({ day: e.target.value, job: null })}
            >
              <option value="">همهٔ روزها</option>
              {day && !mockDays.some((d) => d.date === day) && (
                <option value={day}>{day}</option>
              )}
              {mockDays.map((d) => (
                <option value={d.date} key={d.date}>
                  {dateLabel(d.date)}
                </option>
              ))}
            </select>
          </label>
          <label>
            مرحله
            <select
              aria-label="فیلتر مرحله اجرا"
              value={stage}
              onChange={(e) => change({ stage: e.target.value, job: null })}
            >
              <option value="all">همهٔ مراحل</option>
              {Object.entries(jobStages).map(([id, label]) => (
                <option value={id} key={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            ترتیب
            <select
              aria-label="ترتیب اجراها"
              value={sort}
              onChange={(e) => change({ sort: e.target.value })}
            >
              <option value="newest">جدیدترین درخواست</option>
              <option value="oldest">قدیمی‌ترین درخواست</option>
            </select>
          </label>
        </div>
        <div
          className="jq-status-tabs"
          role="group"
          aria-label="فیلتر وضعیت اجرا"
        >
          <button
            aria-pressed={status === "all"}
            onClick={() => change({ status: null, job: null })}
          >
            همه <span>{number(jobs.length)}</span>
          </button>
          {Object.entries(jobStatuses).map(([value, label]) => (
            <button
              key={value}
              aria-pressed={status === value}
              onClick={() => change({ status: value, job: null })}
            >
              {label}
              <span>
                {number(jobs.filter((j) => j.status === value).length)}
              </span>
            </button>
          ))}
          {(search || day || stage !== "all" || status !== "all") && (
            <button className="jq-reset" onClick={() => setParams({})}>
              <RotateCcw size={12} />
              پاک‌کردن فیلترها
            </button>
          )}
        </div>
        <p className="jq-sr-only" aria-live="polite">
          {number(filtered.length)} اجرا در نتیجهٔ فیلترها
        </p>
        <div
          className="jq-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="جدول صف اجراها"
        >
          <table>
            <thead>
              <tr>
                <th aria-label="بازکردن جزئیات" />
                <th scope="col">اجرا / مرحله</th>
                <th scope="col">روز / محدوده</th>
                <th scope="col">وضعیت</th>
                <th scope="col">پیشرفت</th>
                <th scope="col">ثبت / worker</th>
                <th scope="col">جزئیات</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((job) => {
                const Icon = statusIcon(job.status);
                return (
                  <Fragment key={job.id}>
                    <tr className={expanded === job.id ? "selected" : ""}>
                      <td>
                        <button
                          className="jq-expand"
                          aria-label={`جزئیات ${job.id}`}
                          aria-expanded={expanded === job.id}
                          aria-controls={`detail-${job.id}`}
                          onClick={() =>
                            change(
                              { job: expanded === job.id ? null : job.id },
                              false,
                            )
                          }
                        >
                          {expanded === job.id ? (
                            <ChevronDown size={16} />
                          ) : (
                            <ChevronLeft size={16} />
                          )}
                        </button>
                      </td>
                      <td>
                        <strong>{jobStages[job.stage]}</strong>
                        <small>
                          <bdi>{job.id}</bdi> · تلاش {number(job.attempt)}
                        </small>
                      </td>
                      <td>
                        <Link to={dayDetailsPath(job.day)}>
                          {dateLabel(job.day)}
                        </Link>
                        <small>
                          {job.chunkId ? <bdi>{job.chunkId}</bdi> : "کل روز"}
                        </small>
                      </td>
                      <td>
                        <span className={`jq-status ${job.status}`}>
                          <Icon size={12} />
                          {jobStatuses[job.status]}
                        </span>
                      </td>
                      <td>
                        <div className="jq-progress-label">
                          <span>{number(job.progress)}٪</span>
                          <small>
                            {job.status === "queued"
                              ? "آمادهٔ واگذاری"
                              : job.status === "cancelled"
                                ? "متوقف‌شده"
                                : job.status === "failed"
                                  ? "متوقف در خطا"
                                  : ""}
                          </small>
                        </div>
                        <progress
                          aria-label={`پیشرفت ${job.id}`}
                          value={job.progress}
                          max={100}
                          className={job.status}
                        />
                      </td>
                      <td>
                        {jobTime(job.createdAt)}
                        <small>
                          <bdi>{job.worker ?? "در انتظار worker"}</bdi>
                        </small>
                      </td>
                      <td>
                        <button
                          className="jq-text-button"
                          onClick={() =>
                            change(
                              { job: expanded === job.id ? null : job.id },
                              false,
                            )
                          }
                        >
                          {expanded === job.id ? "بستن" : "مشاهده"}
                        </button>
                      </td>
                    </tr>
                    {expanded === job.id && (
                      <tr className="jq-detail-row" id={`detail-${job.id}`}>
                        <td colSpan={7}>
                          <JobDetail
                            job={job}
                            jobs={jobs}
                            onRetry={() => retry(job.id)}
                            onCancel={() => {
                              const now = new Date().toISOString();
                              setJobs((old) =>
                                old.map((j) =>
                                  j.id === job.id ? cancelJob(j, now) : j,
                                ),
                              );
                              setNotice("اجرای نمونه با تأیید شما لغو شد.");
                            }}
                            onRelated={reveal}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {!filtered.length && (
            <div className="jq-empty">
              <Filter size={29} />
              <h3>اجرایی با این فیلترها پیدا نشد</h3>
              <p>روز، مرحله یا عبارت جست‌وجو را تغییر دهید.</p>
              <button onClick={() => setParams({})}>نمایش همهٔ اجراها</button>
            </div>
          )}
        </div>
        <footer className="jq-pagination">
          <div>
            <span>
              {filtered.length
                ? `${number((page - 1) * size + 1)} تا ${number(Math.min(page * size, filtered.length))} از ${number(filtered.length)} اجرا`
                : "۰ اجرا"}
            </span>
            <label>
              در هر صفحه
              <select
                aria-label="تعداد اجرا در صفحه"
                value={size}
                onChange={(e) => change({ size: e.target.value })}
              >
                <option value="5">۵</option>
                <option value="10">۱۰</option>
              </select>
            </label>
          </div>
          <div>
            <button
              disabled={page === 1}
              onClick={() =>
                change({ page: String(page - 1), job: null }, false)
              }
            >
              قبلی
            </button>
            <span>
              صفحهٔ {number(page)} از {number(pageCount)}
            </span>
            <button
              disabled={page >= pageCount}
              onClick={() =>
                change({ page: String(page + 1), job: null }, false)
              }
            >
              بعدی
            </button>
          </div>
        </footer>
      </section>
      {expanded && !visible.some((j) => j.id === expanded) && (
        <div className="jq-selection-note">
          {selected ? (
            <>
              <span>اجرای انتخاب‌شده در صفحه یا فیلتر فعلی نیست.</span>
              <button onClick={() => reveal(selected.id)}>
                نمایش در فهرست کامل
              </button>
            </>
          ) : (
            <>
              <span>شناسهٔ اجرای انتخاب‌شده در داده‌های نمونه پیدا نشد.</span>
              <button onClick={() => change({ job: null }, false)}>
                بستن پیام
              </button>
            </>
          )}
        </div>
      )}
      <p className="jq-bottom-note">
        <ExternalLink size={13} />
        برای ثبت عملیات جدید از <Link to="/operations">
          عملیات و پردازش
        </Link>{" "}
        استفاده کنید. داده‌های ماک این دو صفحه هنوز به یکدیگر متصل نیستند.
      </p>
    </main>
  );
}
