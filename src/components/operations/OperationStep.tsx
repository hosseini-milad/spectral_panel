import {
  Check,
  ChevronDown,
  Play,
  LoaderCircle,
  FileCheck2,
  Clock3,
  AlertTriangle,
} from "lucide-react";
import { number } from "../../data/days";
import {
  statusLabels,
  phaseLabels,
  durationLabel,
  type ActiveTask,
  type Run,
} from "../../api/operations";
export function OperationStep({
  index,
  title,
  description,
  step,
  ready,
  busy,
  onRun,
  runId,
  activeTask,
}: {
  index: number;
  title: string;
  description: string;
  step: Run["stages"][number] | undefined;
  ready: boolean;
  busy: boolean;
  onRun: () => void;
  runId?: string;
  activeTask?: ActiveTask | null;
}) {
  const status = step?.status ?? "pending";
  return (
    <li className={`op-step op-card ${status}${ready ? " is-ready" : ""}`}>
      <div className="op-step-heading">
        <span className="op-step-number" aria-hidden="true">
          {status === "succeeded" ? <Check size={19} /> : number(index + 2)}
        </span>
        <div>
          <span className="op-step-kicker">گام {number(index + 2)} از ۵</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <span className={`op-status ${status}`}>
          {status === "running" ? (
            <LoaderCircle size={12} className="op-spin" />
          ) : status === "succeeded" ? (
            <Check size={12} />
          ) : null}
          {step ? statusLabels[status] : "هنوز در این اجرا ثبت نشده"}
        </span>
      </div>
      <div className="op-step-body">
        <div className="op-step-dependency">
          <span>
            {index === 0
              ? "ورودی: رکوردهای خام چانک"
              : "پیش‌نیاز: خروجی سازگار مرحلهٔ قبل"}
          </span>
          <span>دامنه: چانک‌های انتخاب‌شده</span>
        </div>
        {step && (
          <div className="op-step-progress">
            <progress
              max={100}
              value={step.percent}
              aria-label={`پیشرفت ${title}`}
            />
            <span>
              {number(step.completed_units)} / {number(step.total_units)}
            </span>
          </div>
        )}
        {!!step?.failed_units && (
          <p className="op-step-errors">
            <AlertTriangle size={13} />
            {number(step.failed_units)} چانک ناموفق
            {step.blocked_units
              ? ` · ${number(step.blocked_units)} مورد اجرا نشده به علت خطای پیش‌نیاز`
              : ""}
          </p>
        )}
        {activeTask && (
          <div className="op-task-runtime" role="status">
            <div>
              <Clock3 size={14} />
              <strong>چانک {number(activeTask.chunk_index)}</strong>
              <span>
                {phaseLabels[activeTask.phase ?? ""] ?? "در حال پردازش"}
              </span>
            </div>
            <dl>
              <div>
                <dt>زمان سپری‌شده</dt>
                <dd>{durationLabel(activeTask.elapsed_seconds)}</dd>
              </div>
              <div>
                <dt>مهلت این مرحله</dt>
                <dd>
                  {activeTask.timeout_seconds === null
                    ? "برای این اجرای قدیمی ثبت نشده"
                    : durationLabel(activeTask.timeout_seconds)}
                </dd>
              </div>
            </dl>
            <p>
              {activeTask.seconds_since_output === null
                ? "هنوز خروجی متنی تازه‌ای ثبت نشده است."
                : `آخرین خروجی مرحله: ${durationLabel(activeTask.seconds_since_output)} پیش.`}{" "}
              نبود خروجی تازه به‌تنهایی نشانهٔ خطا نیست.
            </p>
          </div>
        )}
        <div className="op-step-footer">
          <details className="op-step-details">
            <summary>
              <FileCheck2 size={14} />
              ورودی و خروجی مرحله
              <ChevronDown size={13} />
            </summary>
            <div className="op-result-grid">
              <div>
                <span>ورودی کارهای تکمیل‌شده</span>
                <strong>
                  {step?.input == null ? "—" : number(step.input)}
                </strong>
              </div>
              <div>
                <span>خروجی کارهای تکمیل‌شده</span>
                <strong>
                  {step?.output == null ? "—" : number(step.output)}
                </strong>
              </div>
            </div>
            <p className="op-result-extra">
              این شمارش مربوط به اجرای انتخاب‌شده است؛ جزئیات هر چانک در جدول
              کارهاست.
            </p>
            {runId && <bdi>{runId}</bdi>}
          </details>
          <button
            className={`op-stage-button${ready ? " primary" : ""}`}
            disabled={!ready || busy}
            onClick={onRun}
            aria-label={`اجرای ${title}`}
          >
            <Play size={13} />
            ثبت مرحله در صف
          </button>
        </div>
      </div>
    </li>
  );
}
