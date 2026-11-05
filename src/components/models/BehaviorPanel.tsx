import { Link } from "react-router-dom";
import {
  ShieldCheck,
  Activity,
  ArrowUpLeft,
  Info,
  CircleHelp,
  Fingerprint,
} from "lucide-react";
import { number, dateLabel } from "../../data/days";
import { scoreNumber, type ModelRun } from "../../data/models";
import { dayDetailsPath } from "../../lib/dayNavigation";

export function BehaviorPanel({ model }: { model: ModelRun }) {
  const reference = model.reference;
  if (!reference)
    return (
      <section className="mdl-card mdl-missing-reference">
        <CircleHelp size={33} />
        <h2>
          {model.status === "draft"
            ? "مرجع و ارزیابی هنوز ساخته نشده‌اند"
            : "مرجع رفتار به این نسخه متصل نیست"}
        </h2>
        <p>
          {model.status === "draft"
            ? "ثبت تنظیمات، آموزش یا کالیبراسیون محسوب نمی‌شود. پس از اجرای واقعی، مدل، scaler و آستانه باید در یک بستهٔ نسخه‌دار ثبت شوند."
            : "سنجه‌های بازسازی این نسخه به‌تنهایی امتیاز رفتار کالیبره‌شده نیستند. برای این مدل دادهٔ مرجع یا انحراف عددی نمایش نمی‌دهیم."}
        </p>
        <Link
          className="mdl-secondary-button"
          to={dayDetailsPath(model.config.day)}
        >
          بررسی روز داده
          <ArrowUpLeft size={14} />
        </Link>
      </section>
    );
  const unknown = reference.evaluatedNodes - reference.validNodes;
  const unflagged = reference.validNodes - reference.flaggedNodes;
  return (
    <>
      <div className="mdl-behavior-notice">
        <ShieldCheck size={18} />
        <div>
          <h2>انحراف رفتاری، احتمال یا تأیید حمله نیست</h2>
          <p>
            این ارزیابی ماک به بستهٔ مرجع همین نسخه متصل است. سیاست ترکیبی از
            خروجی سه گونه استفاده می‌کند و به انتخاب گونه در تب مدل وابسته نیست.
          </p>
        </div>
      </div>
      <div className="mdl-behavior-grid">
        <section className="mdl-card mdl-reference">
          <div className="mdl-section-heading">
            <div>
              <Fingerprint size={17} />
              <div>
                <h2>مرجع نرمال نسخه‌دار</h2>
                <p>مدل، scaler و آستانهٔ منجمد در یک بستهٔ نمونه</p>
              </div>
            </div>
            <span className="mdl-state ready">ماک ثبت‌شده</span>
          </div>
          <dl className="mdl-metadata-list">
            <div>
              <dt>شناسهٔ مرجع</dt>
              <dd>
                <bdi>{reference.id}</bdi>
              </dd>
            </div>
            <div>
              <dt>مدل مربوط</dt>
              <dd>
                <bdi>{model.id}</bdi>
              </dd>
            </div>
            <div>
              <dt>روز مرجع نرمال</dt>
              <dd>{dateLabel(model.config.day)}</dd>
            </div>
            <div>
              <dt>روز ارزیابی</dt>
              <dd>
                <Link to={dayDetailsPath(reference.evaluationDay)}>
                  {dateLabel(reference.evaluationDay)}
                  <ArrowUpLeft size={12} />
                </Link>
              </dd>
            </div>
            <div>
              <dt>سیاست امتیازدهی</dt>
              <dd>
                <bdi>{model.config.score_policy}</bdi>
              </dd>
            </div>
            <div>
              <dt>α اسمی کالیبراسیون</dt>
              <dd>{scoreNumber(model.config.alpha, 2)}</dd>
            </div>
            <div>
              <dt>گره‌های کالیبراسیون</dt>
              <dd>{number(reference.calibrationNodes)}</dd>
            </div>
            <div>
              <dt>آستانهٔ نمونهٔ سیاست</dt>
              <dd>{scoreNumber(reference.threshold)}</dd>
            </div>
          </dl>
          <p className="mdl-reference-note">
            آستانه یک مقدار سناریوی ماک است؛ α تضمین FPR نیست و ارزیابی واقعی
            هویت رکوردها انجام نشده است.
          </p>
        </section>
        <section className="mdl-card mdl-signal-coverage">
          <div className="mdl-section-heading">
            <div>
              <Activity size={17} />
              <div>
                <h2>پوشش سیگنال‌ها</h2>
                <p>
                  مقادیر معتبر نسبت به {number(reference.evaluatedNodes)} گرهٔ
                  نمونه
                </p>
              </div>
            </div>
          </div>
          <div className="mdl-signal-bars">
            {reference.signals.map((signal) => (
              <div key={signal.name}>
                <div>
                  <span>{signal.name}</span>
                  <strong>
                    {scoreNumber((signal.valid / signal.total) * 100, 1)}٪
                  </strong>
                </div>
                <progress
                  max={signal.total}
                  value={signal.valid}
                  aria-label={`پوشش ${signal.name}`}
                />
                <small>
                  {number(signal.valid)} از {number(signal.total)} گره
                </small>
              </div>
            ))}
          </div>
          <p className="mdl-reference-note">
            <Info size={13} />
            فقدان پوشش، رفتار عادی محسوب نمی‌شود؛ علت می‌تواند mask نامعتبر یا
            محدودیت پایهٔ طیفی باشد.
          </p>
        </section>
      </div>
      <section className="mdl-card mdl-behavior-summary">
        <div className="mdl-section-heading">
          <div>
            <Activity size={17} />
            <div>
              <h2>جمع‌بندی ارزیابی رفتار</h2>
              <p>
                روز {dateLabel(reference.evaluationDay)} · دادهٔ ثابت نمایشی
              </p>
            </div>
          </div>
          <Link to={dayDetailsPath(reference.evaluationDay)}>
            جزئیات روز
            <ArrowUpLeft size={14} />
          </Link>
        </div>
        <div className="mdl-behavior-counts">
          <div>
            <span>گره‌های ارزیابی</span>
            <strong>{number(reference.evaluatedNodes)}</strong>
          </div>
          <div>
            <span>امتیاز معتبر</span>
            <strong>{number(reference.validNodes)}</strong>
          </div>
          <div>
            <span>نیازمند بررسی انحراف</span>
            <strong>{number(reference.flaggedNodes)}</strong>
          </div>
          <div>
            <span>بدون ارزیابی معتبر</span>
            <strong>{number(unknown)}</strong>
          </div>
        </div>
        <div className="mdl-behavior-track" aria-label="توزیع ارزیابی نمونه">
          <span style={{ flex: unflagged, background: "var(--chart-green)" }} />
          <span
            style={{
              flex: reference.flaggedNodes,
              background: "var(--chart-amber)",
            }}
          />
          <span style={{ flex: unknown, background: "var(--chart-muted)" }} />
        </div>
        <div className="mdl-behavior-legend">
          <span>
            <i />
            {number(unflagged)} بدون پرچم در سیاست نمونه
          </span>
          <span>
            <i className="flagged" />
            {number(reference.flaggedNodes)} نیازمند بررسی
          </span>
          <span>
            <i className="unknown" />
            {number(unknown)} فاقد امتیاز معتبر
          </span>
        </div>
        <p className="mdl-reference-note">
          پرچم نمونه به معنی incident، شدت حمله یا احتمال آن نیست. مختصات نهفتهٔ
          مدل‌های مستقل نیز بدون هم‌ترازی قابل مقایسه نیستند.
        </p>
      </section>
    </>
  );
}
