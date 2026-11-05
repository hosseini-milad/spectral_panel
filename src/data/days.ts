export type ChunkStatus = "complete" | "running" | "failed" | "pending";
export type DayStatus = "complete" | "processing" | "attention" | "partial";

export const stages = [
  "نرمال‌سازی",
  "انتخاب کاندید",
  "گراف و مولفه",
  "تحلیل طیفی",
  "یادگیری",
] as const;

export interface Chunk {
  id: string;
  index: number;
  records: number;
  normalized: number;
  candidates: number;
  nodes: number;
  edges: number;
  components: number;
  representatives: number;
  completedStages: number;
  status: ChunkStatus;
  progress: number;
  durationSeconds: number;
  runId: string | null;
  updatedAt: string;
  error?: string;
}

export interface ProcessingDay {
  date: string;
  expectedChunks: number;
  chunks: Chunk[];
  source: string;
}

export const mockSnapshotDate = "2026-11-05";
export const dayStatusLabels: Record<DayStatus, string> = {
  complete: "تکمیل‌شده",
  processing: "در حال پردازش",
  attention: "نیازمند بررسی",
  partial: "دادهٔ جزئی",
};
export const chunkStatusLabels: Record<ChunkStatus, string> = {
  complete: "تکمیل‌شده",
  running: "در حال پردازش",
  failed: "ناموفق",
  pending: "در انتظار",
};

function createChunk(
  date: string,
  index: number,
  status: ChunkStatus,
  seed: number,
): Chunk {
  const records = 168000 + seed * 1700 + index * 2913;
  const completedStages =
    status === "complete"
      ? 5
      : status === "pending"
        ? 0
        : status === "running"
          ? 3
          : 2;
  const candidates = completedStages >= 2 ? Math.round(records * 0.1) : 0;
  return {
    id: `${date}-chunk-${index}`,
    index,
    records,
    normalized: completedStages >= 1 ? records - (32 + index * 7) : 0,
    candidates,
    nodes: completedStages >= 3 ? candidates : 0,
    edges: completedStages >= 3 ? candidates * 4 + index * 31 : 0,
    components: completedStages >= 3 ? 124 + seed * 3 + index * 8 : 0,
    representatives: completedStages >= 3 ? 620 + index * 27 : 0,
    completedStages,
    status,
    progress:
      status === "complete"
        ? 100
        : status === "pending"
          ? 0
          : status === "running"
            ? 68
            : 40,
    durationSeconds: status === "pending" ? 0 : 224 + seed * 21 + index * 19,
    runId:
      status === "pending"
        ? null
        : `mock-${date.replaceAll("-", "")}-${String(index).padStart(2, "0")}`,
    updatedAt:
      status === "pending"
        ? "—"
        : `۱۰:${String(12 + index * 6).padStart(2, "0")}`,
    ...(status === "failed"
      ? {
          error:
            "ساخت گراف متوقف شده است: تطبیق شناسهٔ ۱۲ کاندید با ورودی برقرار نیست. ورودی و نسخهٔ داده بررسی شود؛ اجرای مجدد خودکار انجام نشده است.",
        }
      : {}),
  };
}

// Fixed, deterministic fixtures. No API, real jobs or scientific calculations.
const fixtures: { date: string; statuses: ChunkStatus[] }[] = [
  {
    date: "2026-11-05",
    statuses: [
      "complete",
      "complete",
      "running",
      "failed",
      "pending",
      "pending",
    ],
  },
  {
    date: "2026-11-04",
    statuses: [
      "complete",
      "complete",
      "complete",
      "complete",
      "complete",
      "complete",
      "running",
      "pending",
    ],
  },
  { date: "2026-11-03", statuses: Array<ChunkStatus>(8).fill("complete") },
  { date: "2026-11-02", statuses: Array<ChunkStatus>(8).fill("complete") },
  {
    date: "2026-11-01",
    statuses: ["complete", "complete", "complete", "complete"],
  },
  { date: "2026-10-31", statuses: Array<ChunkStatus>(8).fill("complete") },
  {
    date: "2026-10-30",
    statuses: [
      "complete",
      "complete",
      "failed",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ],
  },
];

export const mockDays: ProcessingDay[] = fixtures.map((fixture, seed) => ({
  date: fixture.date,
  expectedChunks: 8,
  source: `flows-${fixture.date}.parquet`,
  chunks: fixture.statuses.map((status, index) =>
    createChunk(fixture.date, index, status, seed),
  ),
}));

export const number = (value: number) =>
  new Intl.NumberFormat("fa-IR").format(value);
export function utcDate(value: string) {
  return new Date(`${value}T12:00:00Z`);
}
export function dateLabel(value: string, weekday = false) {
  return new Intl.DateTimeFormat("fa-IR", {
    timeZone: "UTC",
    day: "numeric",
    month: "long",
    year: "numeric",
    ...(weekday ? { weekday: "long" as const } : {}),
  }).format(utcDate(value));
}
export function summarizeDay(day: ProcessingDay) {
  const records = day.chunks.reduce((sum, chunk) => sum + chunk.records, 0);
  const normalized = day.chunks.reduce(
    (sum, chunk) => sum + chunk.normalized,
    0,
  );
  const complete = day.chunks.filter(
    (chunk) => chunk.status === "complete",
  ).length;
  const failed = day.chunks.filter((chunk) => chunk.status === "failed").length;
  const running = day.chunks.filter(
    (chunk) => chunk.status === "running",
  ).length;
  const status: DayStatus = failed
    ? "attention"
    : running
      ? "processing"
      : complete === day.expectedChunks
        ? "complete"
        : "partial";
  return {
    records,
    normalized,
    complete,
    failed,
    running,
    status,
    missing: day.expectedChunks - day.chunks.length,
    coverage: Math.round((day.chunks.length / day.expectedChunks) * 100),
    progress: Math.round(
      day.chunks.reduce((sum, chunk) => sum + chunk.progress, 0) /
        day.expectedChunks,
    ),
    estimatedRecords: Math.round(
      (records / day.chunks.length) * day.expectedChunks,
    ),
    volumeMB: Math.round((records * 312) / 1024 / 1024),
  };
}

export function normalizeSearch(value: string) {
  return value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replaceAll("ي", "ی")
    .replaceAll("ك", "ک")
    .trim()
    .toLowerCase();
}
