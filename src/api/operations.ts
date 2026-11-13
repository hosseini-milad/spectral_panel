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
  | { mode: "all" };
export interface Settings {
  chunk_size: number;
  batch_size: number;
  sample_ratio: number;
  representative_ratio: number;
  neighbors: number;
  threshold: number;
  degree_cap: number;
}
export interface Run {
  id: string;
  day: string;
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
  error: { code: string } | null;
  inventory_refresh: string;
  configuration_version: string;
  configuration_hash: string;
  progress: {
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
  error: { code: string } | null;
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
  operation_failed:
    "اجرای مرحله ناموفق بود؛ جزئیات فنی را در لاگ سرور بررسی کنید",
};
export const eventMessage = (code: string) =>
  messages[code] ?? "وضعیت اجرا به‌روزرسانی شد";
export const runPath = (id: string) => apiPath(`operations/runs/${id}/`);
export const getRun = (id: string, signal?: AbortSignal) =>
  getJSON<Run>(runPath(id), signal);
export const getTasks = (id: string, offset: number, signal?: AbortSignal) =>
  getJSON<Page<Task>>(
    apiPath(`operations/runs/${id}/tasks/`, { limit: 10, offset }),
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
