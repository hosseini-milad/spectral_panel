import { apiPath } from "./days";
import type { OverviewJob } from "./overview";
export interface LabelCounts {
  attack: number;
  normal: number;
  unknown: number;
}
export interface GroupStats {
  labels: LabelCounts;
  composition: "attack_only" | "normal_only" | "mixed" | "unknown";
  observation_count: number;
  layer1_representatives: number;
  daily_representatives: number | null;
  missing_raw_records: number;
  label_conflicts: number;
}
export interface InspectionReport extends GroupStats {
  id: string;
  day: string;
  schema_version: string;
  hierarchy_run_id: string | null;
  source_kind?: "saved_hierarchy" | "available_components";
  included_chunk_indices?: number[] | null;
  expected_chunk_count?: number | null;
  missing_chunk_indices?: number[] | null;
  daily_representative_run_id: string | null;
  inventory_snapshot_id: string;
  generated_at: string;
  coverage_status: string;
  meta_count: number;
  component_count: number;
  attack_meta_count: number;
  normal_meta_count: number;
  unknown_meta_count: number;
  source_signature: string;
  metas_url: string;
  limitations: string[];
}
export interface InspectionContext {
  inventory_snapshot_id?: string;
  active_hierarchy_run_id: string | null;
  available_hierarchy: boolean;
  can_build?: boolean;
  ready_chunk_indices?: number[];
  ready_chunk_count?: number;
  report: InspectionReport | null;
  stale: boolean;
  build_required: boolean;
}
export interface InspectionMeta extends GroupStats {
  meta_id: string;
  meta_index: number;
  component_count: number;
  source_chunks: number[];
  density: number;
  internal_edges: number;
}
export interface InspectionComponent extends GroupStats {
  component_id: string;
  meta_id: string;
  chunk_index: number;
  component_index: number;
}
export type StoredValue = string | number | boolean | null;
export interface InspectionObservation {
  observation_id: string;
  original_id: string;
  meta_id: string;
  component_id: string;
  chunk_index: number;
  label: "attack" | "normal" | "unknown";
  label_origin: string;
  raw_available: boolean;
  normalized_available: boolean;
  layer1_representative: boolean;
  daily_representative: boolean | null;
  raw_summary: Record<string, StoredValue>;
}
export interface InspectionFlow extends InspectionObservation {
  raw_fields: Record<string, StoredValue>;
  normalized_fields: Record<string, StoredValue>;
  candidate_fields: Record<string, StoredValue>;
  omitted_fields: Record<string, string[]>;
  source_file_basename: string | null;
  row_index: number | null;
}
export type InspectionJob = OverviewJob;
export const inspectionRoot = (day: string) =>
  apiPath(`days/${day}/inspection/`);
export async function createInspection(
  day: string,
  snapshot: string,
  hierarchy: string | null,
  key: string,
  signal: AbortSignal,
) {
  let response: Response;
  try {
    response = await fetch(inspectionRoot(day), {
      method: "POST",
      signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify({
        snapshot_id: snapshot,
        ...(hierarchy ? { hierarchy_run_id: hierarchy } : {}),
      }),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new Error(
      "ارتباط قطع شد؛ تلاش دوباره با همان تنظیمات، درخواست تکراری ایجاد نمی‌کند.",
    );
  }
  if (!response.ok)
    throw new Error(
      response.status === 409
        ? "اطلاعات روز تغییر کرده یا چانک آماده‌ای برای گزارش وجود ندارد؛ اطلاعات را بازخوانی کنید."
        : "ثبت گزارش جزئیات انجام نشد؛ دوباره تلاش کنید.",
    );
  return response.json() as Promise<{ created: boolean; job: InspectionJob }>;
}
export const labelNames = {
  attack: "حمله",
  normal: "نرمال",
  unknown: "نامشخص",
};
export const compositionNames = {
  attack_only: "فقط برچسب حمله",
  normal_only: "فقط برچسب نرمال",
  mixed: "مختلط؛ دارای حمله",
  unknown: "شامل برچسب نامشخص",
};
