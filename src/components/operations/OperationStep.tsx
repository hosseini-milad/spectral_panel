import {
  Check,
  ChevronDown,
  LockKeyhole,
  Play,
  LoaderCircle,
  AlertCircle,
  CirclePause,
  SlidersHorizontal,
  ArrowLeft,
  FileCheck2,
} from "lucide-react";
import { number } from "../../data/days";
import {
  operationSteps,
  type StepExecution,
  type PipelineSettings,
  pipelineLogTime,
} from "../../data/operations";

export function OperationStep({
  index,
  execution,
  ready,
  busy,
  hasDay,
  settings,
  onRun,
}: {
  index: number;
  execution: StepExecution;
  ready: boolean;
  busy: boolean;
  hasDay: boolean;
  settings: PipelineSettings;
  onRun: () => void;
}) {
  const step = operationSteps[index];
  const complete = execution.status === "succeeded";
  const running = execution.status === "running";
  const failed = execution.status === "failed";
  const interrupted = execution.status === "interrupted";
  const label = complete
    ? "تکمیل‌شده"
    : running
      ? "در حال اجرا"
      : execution.status === "queued"
        ? "در صف نمایش"
        : failed
          ? "ناموفق"
          : interrupted
            ? "متوقف‌شده"
            : ready
              ? "آمادهٔ اجرا"
              : "در انتظار پیش‌نیاز";
  const Icon = complete
    ? Check
    : running
      ? LoaderCircle
      : failed
        ? AlertCircle
        : interrupted
          ? CirclePause
          : ready
            ? Play
            : LockKeyhole;
  return (
    <li
      className={`op-step op-card ${execution.status}${ready && !complete ? " is-ready" : ""}`}
    >
      <div className="op-step-heading">
        <span className="op-step-number" aria-hidden="true">
          {complete ? <Check size={19} /> : number(index + 2)}
        </span>
        <div>
          <span className="op-step-kicker">گام {number(index + 2)} از ۵</span>
          <h3>{step.label}</h3>
          <p>{step.description}</p>
        </div>
        <span
          className={`op-status ${execution.status}${ready ? " ready" : ""}`}
        >
          <Icon size={12} className={running ? "op-spin" : ""} />
          {label}
        </span>
      </div>
      <div className="op-step-body">
        <div className="op-step-dependency">
          <span>
            <SlidersHorizontal size={13} />
            {index === 0
              ? "ورودی: رکوردهای خام روز"
              : `پیش‌نیاز: ${operationSteps[index - 1].shortLabel}`}
          </span>
          <span>
            {index === 1
              ? `سهم نمونه: ${number(settings.samplePercent)}٪`
              : index === 2
                ? `سهم نماینده: ${number(settings.representativePercent)}٪`
                : index === 3
                  ? "خروجی: گراف و مولفه‌های نمونه"
                  : "دامنه: چانک‌های موجود روز"}
          </span>
        </div>
        {running && (
          <div className="op-step-progress">
            <progress
              max={100}
              value={execution.progress}
              aria-label={`پیشرفت نمایشی ${step.shortLabel}`}
            />
            <span>{number(execution.progress)}٪</span>
          </div>
        )}
        {execution.error && (
          <div className="op-step-error" role="alert">
            <AlertCircle size={15} />
            {execution.error}
          </div>
        )}
        <div className="op-step-footer">
          <details className="op-step-details">
            <summary>
              <FileCheck2 size={14} />
              {complete ? "مشاهدهٔ نتیجهٔ ماک" : "ورودی و خروجی مرحله"}
              <ChevronDown size={13} />
            </summary>
            <div className="op-result-grid">
              <div>
                <span>{step.input}</span>
                <strong>
                  {execution.result ? number(execution.result.input) : "—"}
                </strong>
              </div>
              <ArrowLeft size={17} />
              <div>
                <span>{step.output}</span>
                <strong>
                  {execution.result ? number(execution.result.output) : "—"}
                </strong>
              </div>
            </div>
            {execution.result ? (
              <p className="op-result-extra">
                {execution.result.extraLabel}: {number(execution.result.extra)}
              </p>
            ) : (
              <p className="op-result-extra">
                {hasDay
                  ? "پس از تکمیل این مرحله، خروجی نمایشی اینجا ظاهر می‌شود."
                  : "ابتدا یک روز دارای داده انتخاب کنید."}
              </p>
            )}
            {execution.runId && (
              <dl className="op-result-meta">
                <div>
                  <dt>شناسهٔ اجرای نمونه</dt>
                  <dd>
                    <bdi>{execution.runId}</bdi>
                  </dd>
                </div>
                {execution.startedAt && (
                  <div>
                    <dt>شروع نمایش · تهران</dt>
                    <dd>{pipelineLogTime(execution.startedAt)}</dd>
                  </div>
                )}
              </dl>
            )}
          </details>
          <button
            className={`op-stage-button${ready && !complete ? " primary" : ""}`}
            disabled={!ready || busy || complete}
            onClick={onRun}
            aria-label={`اجرای ${step.shortLabel}`}
            title={
              !hasDay
                ? "ابتدا روز را انتخاب کنید"
                : !ready && !complete
                  ? step.dependency
                  : undefined
            }
          >
            {running ? (
              <LoaderCircle size={14} className="op-spin" />
            ) : complete ? (
              <Check size={14} />
            ) : ready ? (
              <Play size={13} />
            ) : (
              <LockKeyhole size={13} />
            )}
            {running
              ? "در حال اجرا"
              : complete
                ? "انجام شد"
                : failed || interrupted
                  ? "تلاش دوباره"
                  : "اجرای مرحله"}
          </button>
        </div>
      </div>
    </li>
  );
}
