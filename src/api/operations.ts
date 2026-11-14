import { apiPath, getJSON, type Page } from "./days";
export const stages = [
  "normalize",
  "sample",
  "components",
  "representatives",
] as const;
export type Stage = (typeof stages)[number];
export type Selection =
  | { mode: "single"; chunk_index: number }
  | { mode: "range"; start_chunk: number; end_chunk: number }
  | { mode: "page"; page: number; page_size: number }
  | { mode: "all" }
  | { mode: "chunks"; chunk_indices: number[] };
export interface Settings {
  chunk_size: number;
  stage_timeout_seconds: number;
  batch_size: number;
  sample_ratio: number;
  representative_ratio: number;
  neighbors: number;
  threshold: number;
  degree_cap: number;
}
export interface ActiveTask {
  chunk_index: number;
  stage: Stage;
  started_at: string;
  elapsed_seconds: number;
  timeout_seconds: number | null;
  remaining_seconds: number | null;
  last_output_at: string | null;
  seconds_since_output: number | null;
  phase: string | null;
  phase_elapsed_seconds: number | null;
}
export const phaseLabels: Record<string, string> = {
  starting: "آماده‌سازی مرحله",
  building_graph: "آماده‌سازی گراف",
  communities: "استخراج اجتماع‌ها",
  centralities: "محاسبهٔ مرکزیت گره‌ها",
  anomaly_scores: "محاسبهٔ امتیاز ناهنجاری",
  combined_scores: "ترکیب امتیاز گره‌ها",
  representative_selection: "انتخاب و فاصله‌گذاری نماینده‌ها",
  saving_representatives: "ذخیرهٔ نماینده‌ها",
  rendering_graph: "تولید تصویر گراف",
  validating_components: "بررسی و به‌روزرسانی مولفه‌ها",
};
export function durationLabel(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  const n = new Intl.NumberFormat("fa-IR");
  return value < 60
    ? `${n.format(value)} ثانیه`
    : `${n.format(Math.floor(value / 60))} دقیقه و ${n.format(value % 60)} ثانیه`;
}
export interface OperationError {
  code: string;
  reason_code?: string;
  message?: string;
  suggestion?: string;
  diagnostic_id?: string | null;
  context?: {
    expected_count?: number;
    actual_count?: number;
    timeout_seconds?: number;
    exit_code?: number;
    resource?: string;
  };
}
export interface Run {
  id: string;
  day: string;
  execution_policy?: string;
  current_task?: ActiveTask | null;
  retry_of_run_id?: string | null;
  failed_chunks?: number[];
  recent_errors?: {
    chunk_index: number;
    stage: Stage;
    error: OperationError;
    finished_at: string | null;
  }[];
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  observed_at: string;
  chunk_start: number;
  chunk_end: number;
  chunk_count: number;
  settings: Settings;
  cancel_requested: boolean;
  cancel_requested_at: string | null;
  selection: Selection;
  current_chunk: number | null;
  current_stage: Stage | null;
  error: OperationError | null;
  inventory_refresh: string;
  configuration_version: string;
  configuration_hash: string;
  progress: {
    failed_units?: number;
    blocked_units?: number;
    settled_units?: number;
    processed_percent?: number;
    completed_units: number;
    total_units: number;
    reused_units: number;
    percent: number;
    current_task_percent: null;
  };
  stages: {
    stage: Stage;
    status: string;
    completed_units: number;
    total_units: number;
    failed_units?: number;
    blocked_units?: number;
    percent: number;
    input: number | null;
    output: number | null;
  }[];
  worker: {
    online: boolean;
    busy: boolean;
    heartbeat_age_seconds: number | null;
  };
  queue_position: number | null;
  poll_after_seconds: number;
}
export interface Task {
  position: number;
  chunk_index: number;
  stage: Stage;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  result: {
    input: number;
    output: number;
    reused: boolean;
    unit: string;
    graph_parameters?: Record<string, unknown>;
  } | null;
  error: OperationError | null;
}
export interface RunEvent {
  sequence: number;
  time: string;
  level: "info" | "success" | "error" | "warning";
  code: string;
  chunk_index: number | null;
  stage: Stage | null;
}
export interface Request {
  snapshot_id: string;
  selection: Selection;
  stage: "all" | Stage;
  settings: Settings;
}
export const labels: Record<Stage, string> = {
  normalize: "نرمال‌سازی",
  sample: "انتخاب کاندید",
  components: "گراف و مولفه‌ها",
  representatives: "انتخاب نماینده",
};
export const statusLabels: Record<string, string> = {
  preparing: "در حال ثبت",
  pending: "در انتظار",
  queued: "در صف",
  running: "در حال اجرا",
  succeeded: "تکمیل‌شده",
  failed: "ناموفق",
  interrupted: "متوقف‌شده",
  cancelled: "لغوشده",
  blocked: "متوقف به علت خطای مرحلهٔ قبلی",
};
const messages: Record<string, string> = {
  run_started: "پردازش آغاز شد",
  run_completed: "پردازش پایان یافت",
  run_cancelled: "ادامهٔ پردازش لغو شد؛ خروجی چانک‌های تکمیل‌شده حفظ شد",
  stage_started: "مرحله آغاز شد",
  stage_completed: "مرحله تکمیل شد",
  stage_reused: "خروجی سازگار موجود استفاده شد",
  inventory_refresh_failed:
    "به‌روزرسانی اطلاعات روز انجام نشد؛ همگام‌سازی را دوباره اجرا کنید",
  partition_changed: "اندازهٔ چانک با داده‌های ذخیره‌شده سازگار نیست",
  prerequisite_missing: "ورودی یا مرحلهٔ پیش‌نیاز موجود نیست",
  incompatible_output:
    "خروجی قبلی با ورودی یا تنظیمات سازگار نیست؛ بازنویسی انجام نشد",
  upstream_has_dependents:
    "خروجی‌های مراحل بعدی وجود دارند؛ تغییر ورودی انجام نشد",
  incomplete_output: "خروجی مرحله کامل نیست",
  source_changed: "تعداد رکوردهای مبدأ تغییر کرده است",
  worker_interrupted: "worker پیش از پایان اجرا متوقف شده است",
  stage_timeout:
    "مهلت مرحله تمام شد؛ مراحل وابستهٔ این چانک اجرا نمی‌شوند و پردازش به چانک بعدی می‌رود",
  stage_process_failed:
    "پردازش مرحله بدون نتیجهٔ معتبر پایان یافت؛ این چانک ناموفق ثبت شد",
  stage_cleanup_failed:
    "پایان پردازش قبلی تأیید نشد؛ اجرا برای جلوگیری از تداخل متوقف شد",
  database_unavailable:
    "ارتباط با پایگاه داده برقرار نیست؛ ادامهٔ امن پردازش ممکن نشد",
  chunks_failed:
    "پردازش با چانک‌های ناموفق پایان یافت؛ خطای هر چانک در فهرست ثبت شده است",
  operation_failed:
    "اجرای این مرحله ناموفق بود؛ جزئیات فنی در لاگ سرور ثبت شده است",
};
export const eventMessage = (code: string) =>
  messages[code] ?? "وضعیت اجرا به‌روزرسانی شد";
export const runPath = (id: string) => apiPath(`operations/runs/${id}/`);
export const getRun = (id: string, signal?: AbortSignal) =>
  getJSON<Run>(runPath(id), signal);
export const getTasks = (
  id: string,
  offset: number,
  signal?: AbortSignal,
  failedOnly = false,
) =>
  getJSON<Page<Task>>(
    apiPath(`operations/runs/${id}/tasks/`, {
      limit: 10,
      offset,
      failed_only: failedOnly ? "true" : undefined,
    }),
    signal,
  );
export async function submitOperation(day: string, body: Request, key: string) {
  let response: Response;
  try {
    response = await fetch(apiPath(`days/${day}/operations/`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "ارتباط قطع شد؛ تلاش دوباره با همین تنظیمات، کلید قبلی را حفظ می‌کند.",
    );
  }
  if (!response.ok)
    throw new Error(
      response.status === 409
        ? "اطلاعات روز، اندازهٔ چانک یا محدودهٔ انتخاب‌شده سازگار نیست؛ روز را بازخوانی و محدوده را بررسی کنید."
        : response.status === 400
          ? "پارامترهای عملیات معتبر نیستند؛ مقادیر و محدوده را بررسی کنید."
          : "ثبت عملیات انجام نشد؛ دوباره تلاش کنید.",
    );
  return response.json() as Promise<{ created: boolean; run: Run }>;
}

export async function cancelOperation(id: string): Promise<Run> {
  let response: Response;
  try {
    response = await fetch(apiPath(`operations/runs/${id}/cancel/`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({}),
    });
  } catch {
    throw new Error(
      "دریافت پاسخ لغو ممکن نشد؛ وضعیت اجرا را بررسی یا دوباره تلاش کنید.",
    );
  }
  if (!response.ok)
    throw new Error(
      response.status === 409
        ? "این اجرا پیش از ثبت لغو پایان یافته است؛ وضعیت را بازخوانی کنید."
        : "ثبت درخواست لغو انجام نشد؛ دوباره تلاش کنید.",
    );
  return response.json() as Promise<Run>;
}

export async function retryFailedOperation(
  id: string,
  timeout: number,
  key: string,
) {
  let response: Response;
  try {
    response = await fetch(apiPath(`operations/runs/${id}/retry-failed/`), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify({ stage_timeout_seconds: timeout }),
    });
  } catch {
    throw new Error(
      "دریافت پاسخ اجرای مجدد ممکن نشد؛ تلاش دوباره با همان کلید انجام می‌شود.",
    );
  }
  if (!response.ok)
    throw new Error(
      response.status === 409
        ? "اجرای مجدد ممکن نیست؛ اجرای قبلی باید تمام شده و ورودی روز و اندازهٔ چانک سازگار باشد."
        : "ثبت اجرای مجدد انجام نشد؛ مهلت مرحله و اطلاعات روز را بررسی کنید.",
    );
  return response.json() as Promise<{ created: boolean; run: Run }>;
}

export async function clearWaitingQueue(before: string) {
  let response: Response;
  try {
    response = await fetch(apiPath("operations/queue/clear/"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ before }),
    });
  } catch {
    throw new Error(
      "پاسخ پاک‌کردن صف دریافت نشد؛ تلاش دوباره فقط همان صفِ مشاهده‌شده را پاک می‌کند.",
    );
  }
  if (!response.ok)
    throw new Error(
      "پاک‌کردن صف انجام نشد؛ وضعیت را بررسی یا دوباره تلاش کنید.",
    );
  return response.json() as Promise<{
    cancelled_count: number;
    skipped_count: number;
    remaining_queued_count: number;
  }>;
}
