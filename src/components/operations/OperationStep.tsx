import {
  Check,
  ChevronDown,
  Play,
  LoaderCircle,
  FileCheck2,
} from "lucide-react";
import { number } from "../../data/days";
import { statusLabels, type Run } from "../../api/operations";
export function OperationStep({
  index,
  title,
  description,
  step,
  ready,
  busy,
  onRun,
  runId,
}: {
  index: number;
  title: string;
  description: string;
  step: Run["stages"][number] | undefined;
  ready: boolean;
  busy: boolean;
  onRun: () => void;
  runId?: string;
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
