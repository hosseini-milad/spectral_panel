import type { DayStatus } from "../data/days";

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
export interface InventoryDay {
  day: string;
  schema_version: number;
  snapshot_id: string;
  status: DayStatus;
  processing_scope: string;
  raw_records: number;
  raw_document_bytes: number | null;
  chunk_size: number | null;
  expected_chunks: number | null;
  observed_chunks: number;
  complete_chunks: number;
  processing_chunks: number;
  attention_chunks: number;
  missing_chunks: number | null;
  chunk_coverage_percent: number | null;
  normalized_records: number;
  candidate_records: number;
  unassigned_records: { normalized_records: number; candidate_records: number };
  warnings: string[];
  created_at: string;
  updated_at: string;
}
export interface InventoryChunk {
  day: string;
  snapshot_id: string;
  chunk_index: number;
  status: DayStatus;
  expected_raw_records: number | null;
  normalized_records: number;
  normalization_complete: boolean | null;
  candidate_records: number;
  components: number;
  representatives: number;
  updated_at: string;
  graph: {
    source_file: string;
    nodes: number;
    edges: number;
    component_status?: string | null;
    component_count?: number | null;
    component_revision?: string | null;
    graph_parameters?: Record<string, unknown>;
  } | null;
}
export interface ChunkPage extends Page<InventoryChunk> {
  day: string;
  snapshot_id: string;
  chunks_are_processing_partitions: boolean;
}
export function apiPath(
  path: string,
  query: Record<string, string | number | undefined> = {},
) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return `/api/v1/${path}${params.size ? `?${params}` : ""}`;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function getJSON<T>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, "ارتباط با سرور برقرار نشد. دوباره تلاش کنید.");
  }
  if (!response.ok)
    throw new ApiError(
      response.status,
      response.status === 404
        ? "اطلاعات این روز در فهرست سرور ثبت نشده است."
        : response.status === 400
          ? "فیلترهای درخواست معتبر نیستند."
          : "دریافت اطلاعات از سرور ممکن نشد. دوباره تلاش کنید.",
    );
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(0, "پاسخ سرور قابل خواندن نیست.");
  }
}
export const displayNumber = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat("fa-IR").format(value);
export function inventorySummary(day: InventoryDay) {
  return {
    records: day.raw_records,
    normalized: day.normalized_records,
    complete: day.complete_chunks,
    failed: day.attention_chunks,
    running: day.processing_chunks,
    status: day.status,
    missing: day.missing_chunks,
    coverage: day.chunk_coverage_percent,
    volumeMB:
      day.raw_document_bytes == null
        ? null
        : day.raw_document_bytes / 1024 / 1024,
  };
}
export function observationTime(value: string) {
  return new Intl.DateTimeFormat("fa-IR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Tehran",
  }).format(new Date(value));
}

export interface SchematicResult {
  schema_version: string;
  render_id: string;
  day: string;
  chunk_index: number;
  inventory_snapshot_id: string;
  source_signature: string;
  generated_at: string;
  component_revision: string | null;
  layout: "global";
  label_source: string;
  metrics: {
    nodes: number;
    edges: number;
    representatives: number;
    components: number;
    represented_components: number;
    isolated_nodes: number;
    mean_degree: number;
    density: number;
    node_reduction_percent: number;
    normal_label_nodes: number;
    attack_label_nodes: number;
    unknown_label_nodes: number;
  };
  image_url: string;
  png_download_url: string;
  svg_download_url: string;
}
export interface SchematicJob {
  id: string;
  render_id: string;
  status:
    "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  status_url: string;
  progress: { phase: string; percent: number | null };
  error: { code: string; detail: string } | null;
  result: SchematicResult | null;
}
export async function createSchematic(
  day: string,
  chunk: number,
  snapshot: string,
  key: string,
  signal: AbortSignal,
) {
  let response: Response;
  try {
    response = await fetch(apiPath(`days/${day}/chunks/${chunk}/schematic/`), {
      method: "POST",
      signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify({ snapshot_id: snapshot }),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ApiError(
      0,
      "ارتباط با سرور برقرار نشد. تلاش دوباره، درخواست تکراری ایجاد نمی‌کند.",
    );
  }
  if (!response.ok)
    throw new ApiError(
      response.status,
      response.status === 409
        ? "اطلاعات روز تغییر کرده یا گراف و نماینده‌های ذخیره‌شده آماده نیستند؛ روز را دوباره باز کنید."
        : response.status === 404
          ? "چانک در فهرست سرور پیدا نشد."
          : "ثبت درخواست تصویر ممکن نشد. دوباره تلاش کنید.",
    );
  try {
    return (await response.json()) as { job: SchematicJob; created: boolean };
  } catch {
    throw new ApiError(
      0,
      "پاسخ ثبت درخواست قابل خواندن نیست؛ دوباره تلاش کنید.",
    );
  }
}
