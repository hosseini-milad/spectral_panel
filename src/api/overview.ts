import { apiPath, type InventoryDay } from "./days";
export interface OverviewReport {
  id: string;
  schema_version: string;
  day: string;
  window_days: number;
  inventory_snapshot_id: string;
  generated_at: string;
  inventory_observed_at: string;
  metrics: {
    raw_records: number;
    chunk_coverage_percent: number | null;
    normalized_records: number;
    estimated_daily_eps: number;
    normalization_coverage_percent: number | null;
    acceptance_rate_percent: null;
    source_groups: number;
    unknown_source_records: number;
    source_health: null;
    completed_chunks: number;
    expected_chunks: number | null;
    layer1_completion_percent: number | null;
    operational_notices: number;
  };
  readiness: {
    stage: string;
    observed_chunks: number | null;
    expected_chunks: number | null;
    percent: number | null;
    evidence: string;
  }[];
  trend: {
    day: string;
    raw_records: number | null;
    coverage_percent: number | null;
    status: string | null;
    available: boolean;
  }[];
  notices: { code: string; count: number | null; priority: string }[];
  latest_operation_id: string | null;
  sources_url: string;
  download_url: string;
}
export interface Overview {
  day: InventoryDay;
  report: OverviewReport | null;
  build_required: boolean;
  stale: boolean;
  freshness_scope: string;
}
export interface OverviewSource {
  group_key: string;
  source_type: string | null;
  records: number;
  last_stored_at: string | null;
  health: null;
}
export interface OverviewJob {
  id: string;
  report_id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: { code: string; detail: string } | null;
  worker: { online: boolean; busy: boolean };
  queue_position: number | null;
  poll_after_seconds: number | null;
  status_url: string;
  result_url: string | null;
}
export async function buildOverview(
  day: string,
  snapshot: string,
  windowDays: number,
  key: string,
  signal: AbortSignal,
) {
  let response: Response;
  try {
    response = await fetch(apiPath(`days/${day}/overview/reports/`), {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify({ snapshot_id: snapshot, window_days: windowDays }),
    });
  } catch (e) {
    if (signal.aborted) throw e;
    throw new Error(
      "ارتباط قطع شد؛ تلاش دوباره با همان تنظیمات، درخواست تکراری ایجاد نمی‌کند.",
    );
  }
  if (!response.ok)
    throw new Error(
      response.status === 409
        ? "اطلاعات روز تغییر کرده است؛ روز را بازخوانی و دوباره درخواست دهید."
        : "ثبت درخواست گزارش ممکن نشد؛ دوباره تلاش کنید.",
    );
  return response.json() as Promise<{ created: boolean; job: OverviewJob }>;
}
export const readinessLabels: Record<string, string> = {
  normalize: "نرمال‌سازی",
  sample: "کاندیدها",
  components: "گراف و مولفه‌ها",
  representatives: "نماینده‌ها",
  spectral: "تحلیل طیفی",
  learning: "یادگیری",
};
export const noticeLabels: Record<string, string> = {
  missing_chunks: "برخی پارتیشن‌های مورد انتظار هنوز مشاهده نشده‌اند",
  attention_chunks: "چانک‌هایی نیازمند بررسی داده هستند",
  inventory_warnings: "هشدارهای ثبت‌شدهٔ اطلاعات روز",
  partition_size_unknown: "اندازهٔ پارتیشن و تعداد چانک مورد انتظار مشخص نیست",
  latest_operation_failed: "آخرین عملیات ثبت‌شده ناموفق یا متوقف‌شده است",
  normalization_count_inconsistent:
    "شمار نرمال‌شده از شمار رکورد خام بیشتر است",
};
