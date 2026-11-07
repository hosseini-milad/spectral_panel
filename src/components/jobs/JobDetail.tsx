import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Download,
  ExternalLink,
  RotateCcw,
  Square,
  AlertCircle,
  Terminal,
} from "lucide-react";
import {
  canCancel,
  canRetry,
  jobTime,
  downloadJobJSON,
  type QueueJob,
} from "../../data/jobs";
import { number } from "../../data/days";
import { dayDetailsPath } from "../../lib/dayNavigation";
export function JobDetail({
  job,
  jobs,
  onCancel,
  onRetry,
  onRelated,
}: {
  job: QueueJob;
  jobs: QueueJob[];
  onCancel: () => void;
  onRetry: () => void;
  onRelated: (id: string) => void;
}) {
  const [tab, setTab] = useState("overview");
  const [confirm, setConfirm] = useState(false);
  const [ack, setAck] = useState(false);
  const [level, setLevel] = useState("all");
  const retries = jobs.filter((j) => j.retryOf === job.id);
  return (
    <section className="jq-detail" aria-label={`جزئیات ${job.id}`}>
      <header>
        <div>
          <span className="jq-eyebrow">جزئیات اجرای نمونه</span>
          <h2>
            <bdi>{job.id}</bdi>
            <span>تلاش {number(job.attempt)}</span>
          </h2>
        </div>
        <div className="jq-actions">
          <button
            onClick={() =>
              downloadJobJSON(`${job.id}.json`, {
                mock: true,
                scientific_output_generated: false,
                job,
              })
            }
          >
            <Download size={14} />
            دریافت جزئیات
          </button>
          <Link to={dayDetailsPath(job.day)}>
            <ExternalLink size={14} />
            مشاهدهٔ روز
          </Link>
        </div>
      </header>
      <div
        className="jq-detail-tabs"
        role="tablist"
        aria-label="نمای جزئیات اجرا"
      >
        {[
          { id: "overview", label: "مشخصات اجرا" },
          { id: "parameters", label: "پارامترها و منبع" },
          { id: "logs", label: `لاگ‌ها (${number(job.logs.length)})` },
        ].map((item) => (
          <button
            key={item.id}
            id={`${job.id}-${item.id}-tab`}
            role="tab"
            aria-selected={tab === item.id}
            aria-controls={`${job.id}-panel`}
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => setTab(item.id)}
            onKeyDown={(e) => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
                e.preventDefault();
                const ids = ["overview", "parameters", "logs"];
                const next =
                  e.key === "Home"
                    ? 0
                    : e.key === "End"
                      ? 2
                      : (ids.indexOf(tab) + (e.key === "ArrowLeft" ? 1 : 2)) %
                        3;
                setTab(ids[next]);
                document.getElementById(`${job.id}-${ids[next]}-tab`)?.focus();
              }
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        id={`${job.id}-panel`}
        role="tabpanel"
        aria-labelledby={`${job.id}-${tab}-tab`}
      >
        {tab === "overview" && (
          <>
            <dl className="jq-detail-grid">
              {[
                ["شناسهٔ اجرا", job.id],
                ["صف", "scientific.mock"],
                ["Worker", job.worker ?? "هنوز تخصیص نیافته"],
                ["ثبت درخواست", jobTime(job.createdAt)],
                ["شروع پردازش", jobTime(job.startedAt)],
                ["پایان پردازش", jobTime(job.finishedAt)],
                ["خروجی نمونه", job.outputId ?? "بدون خروجی"],
                ["عامل درخواست", "مدیر نمایشی"],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>
                    <bdi>{value}</bdi>
                  </dd>
                </div>
              ))}
            </dl>
            {job.error && (
              <div className="jq-error" role="note">
                <AlertCircle size={17} />
                <div>
                  <strong>خطای پردازش نمونه</strong>
                  <p>{job.error}</p>
                </div>
              </div>
            )}
            {job.retryOf && (
              <p className="jq-relation">
                ادامهٔ زنجیرهٔ تلاش:{" "}
                <button onClick={() => onRelated(job.retryOf!)}>
                  {job.retryOf}
                </button>
              </p>
            )}
            {retries.map((j) => (
              <p className="jq-relation" key={j.id}>
                تلاش بعدی:{" "}
                <button onClick={() => onRelated(j.id)}>{j.id}</button>
              </p>
            ))}
          </>
        )}
        {tab === "parameters" && (
          <div className="jq-provenance">
            <dl className="jq-detail-grid">
              <div>
                <dt>روز داده</dt>
                <dd>
                  <bdi>{job.day}</bdi>
                </dd>
              </div>
              <div>
                <dt>چانک</dt>
                <dd>
                  <bdi>{job.chunkId ?? "همهٔ روز"}</bdi>
                </dd>
              </div>
              <div>
                <dt>نسخهٔ داده</dt>
                <dd>
                  <bdi>{job.dataId}</bdi>
                </dd>
              </div>
              <div>
                <dt>مدل مرجع</dt>
                <dd>
                  {job.modelId ? (
                    <Link
                      to={`/models?model=${encodeURIComponent(job.modelId)}`}
                    >
                      {job.modelId}
                    </Link>
                  ) : (
                    "برای این مرحله کاربرد ندارد"
                  )}
                </dd>
              </div>
            </dl>
            <pre dir="ltr" aria-label="پارامترهای اجرا">
              {JSON.stringify(job.parameters, null, 2)}
            </pre>
            <p className="jq-help">
              منبع و پارامترهای همین تلاش؛ تلاش مجدد شناسهٔ مستقل می‌گیرد. این
              پارامترها قرارداد نهایی API نیستند.
            </p>
          </div>
        )}
        {tab === "logs" && (
          <div className="jq-log-section">
            <div className="jq-log-heading">
              <span>
                <Terminal size={15} />
                رویدادهای همین تلاش
              </span>
              <select
                aria-label="سطح لاگ"
                value={level}
                onChange={(e) => setLevel(e.target.value)}
              >
                <option value="all">همهٔ سطوح</option>
                <option value="info">اطلاعات</option>
                <option value="success">موفق</option>
                <option value="warning">هشدار</option>
                <option value="error">خطا</option>
              </select>
            </div>
            <ol className="jq-logs">
              {job.logs
                .filter((log) => level === "all" || log.level === level)
                .map((log, i) => (
                  <li key={`${log.time}-${i}`}>
                    <time>{jobTime(log.time)}</time>
                    <span className={`jq-log-level ${log.level}`}>
                      {log.level.toUpperCase()}
                    </span>
                    <p>{log.message}</p>
                  </li>
                ))}
            </ol>
            {!job.logs.some(
              (log) => level === "all" || log.level === level,
            ) && <p className="jq-help">لاگی با این سطح وجود ندارد.</p>}
          </div>
        )}
      </div>
      <footer>
        <p>اجرای ماک · بدون اتصال به worker واقعی</p>
        <div className="jq-actions">
          {canRetry(job, jobs) && (
            <button onClick={onRetry}>
              <RotateCcw size={14} />
              تلاش مجدد ماک
            </button>
          )}
          {canCancel(job) && (
            <button
              className="jq-cancel-button"
              onClick={() => {
                setConfirm(true);
                setAck(false);
              }}
            >
              <Square size={12} />
              لغو اجرا
            </button>
          )}
        </div>
      </footer>
      {confirm && canCancel(job) && (
        <div className="jq-confirm" role="group" aria-label="تأیید لغو اجرا">
          <strong>اجرای «{job.id}» لغو شود؟</strong>
          <p>
            پیشرفت فعلی حفظ و وضعیت این تلاش لغوشده ثبت می‌شود؛ دادهٔ روز حذف
            نمی‌شود.
          </p>
          <label>
            <input
              type="checkbox"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />
            لغو این اجرای نمونه را تأیید می‌کنم.
          </label>
          <div className="jq-actions">
            <button
              className="jq-cancel-button"
              disabled={!ack}
              onClick={() => {
                onCancel();
                setConfirm(false);
              }}
            >
              تأیید لغو
            </button>
            <button onClick={() => setConfirm(false)}>انصراف</button>
          </div>
        </div>
      )}
    </section>
  );
}
