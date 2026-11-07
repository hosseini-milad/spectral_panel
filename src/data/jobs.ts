import { mockDays } from "./days";
export const jobStages = {
  normalize: "نرمال‌سازی",
  sample: "نمونه‌برداری",
  graph: "گراف و مولفه",
  spectral: "تحلیل طیفی",
  learning: "یادگیری مدل",
  report: "تولید گزارش",
} as const;
export type JobStage = keyof typeof jobStages;
export type JobStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";
export const jobStatuses: Record<JobStatus, string> = {
  queued: "در صف",
  running: "در حال اجرا",
  succeeded: "موفق",
  failed: "ناموفق",
  cancelled: "لغوشده",
};
export interface QueueLog {
  time: string;
  level: "info" | "success" | "error" | "warning";
  message: string;
}
export interface QueueJob {
  id: string;
  day: string;
  chunkId: string | null;
  stage: JobStage;
  status: JobStatus;
  progress: number;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  worker: string | null;
  attempt: number;
  retryOf: string | null;
  dataId: string;
  modelId: string | null;
  parameters: Record<string, string | number | boolean>;
  error: string | null;
  outputId: string | null;
  logs: QueueLog[];
}
export function initialJobs(): QueueJob[] {
  const statuses: JobStatus[] = [
    "running",
    "queued",
    "running",
    "failed",
    "queued",
    "succeeded",
    "cancelled",
    "succeeded",
    "failed",
    "succeeded",
    "succeeded",
    "queued",
    "succeeded",
    "succeeded",
    "cancelled",
    "succeeded",
  ];
  return statuses.map((status, i) => {
    const day = mockDays[Math.floor(i / 3) % mockDays.length];
    const stage = (Object.keys(jobStages) as JobStage[])[i % 6];
    const createdAt = new Date(
      Date.parse("2026-11-05T08:30:00Z") - i * 1800000,
    ).toISOString();
    const startedAt =
      status === "queued"
        ? null
        : new Date(Date.parse(createdAt) + 20000).toISOString();
    const finishedAt = ["succeeded", "failed", "cancelled"].includes(status)
      ? new Date(Date.parse(createdAt) + 260000).toISOString()
      : null;
    const error =
      status === "failed"
        ? "خطای نمونه: حافظهٔ تخصیص‌یافته برای پردازش کافی نبود. نتیجه‌ای ثبت نشده است."
        : null;
    const id = `mock-job-${String(i + 1).padStart(3, "0")}`;
    return {
      id,
      day: day.date,
      chunkId: i % 3 === 0 ? null : (day.chunks[0]?.id ?? null),
      stage,
      status,
      progress:
        status === "succeeded"
          ? 100
          : status === "running"
            ? i === 0
              ? 62
              : 34
            : status === "failed"
              ? 47
              : 0,
      createdAt,
      startedAt,
      finishedAt,
      worker:
        status === "queued" ? null : `mock-worker-${i === 2 ? "02" : "01"}`,
      attempt: 1,
      retryOf: null,
      dataId: `mock-data-${day.date}-v1`,
      modelId: stage === "learning" ? "mock-normal-model-v3" : null,
      parameters: {
        seed: 42,
        scope: i % 3 === 0 ? "day" : "chunk",
        ...(stage === "sample" ? { sample_percent: 10 } : {}),
        ...(stage === "learning" ? { epochs: 50, latent_dim: 8 } : {}),
      },
      error,
      outputId: status === "succeeded" ? `mock-output-${id}` : null,
      logs: [
        {
          time: createdAt,
          level: "info",
          message: "درخواست نمونه در صف ثبت شد.",
        },
        ...(startedAt
          ? [
              {
                time: startedAt,
                level: "info" as const,
                message: "پردازش به worker نمونه واگذار شد.",
              },
            ]
          : []),
        ...(finishedAt
          ? [
              {
                time: finishedAt,
                level:
                  status === "succeeded"
                    ? ("success" as const)
                    : status === "failed"
                      ? ("error" as const)
                      : ("warning" as const),
                message:
                  error ??
                  (status === "succeeded"
                    ? "پردازش نمونه تکمیل شد."
                    : "درخواست نمونه لغو شد."),
              },
            ]
          : []),
      ],
    };
  });
}
export const canCancel = (job: QueueJob) =>
  job.status === "running" || job.status === "queued";
export const canRetry = (job: QueueJob, jobs: QueueJob[]) =>
  ["failed", "cancelled"].includes(job.status) &&
  !jobs.some((j) => j.retryOf === job.id);
export function cancelJob(job: QueueJob, now: string): QueueJob {
  return canCancel(job)
    ? {
        ...job,
        status: "cancelled",
        finishedAt: now,
        logs: [
          ...job.logs,
          {
            time: now,
            level: "warning",
            message: "لغو با تأیید کاربر در سناریوی محلی انجام شد.",
          },
        ],
      }
    : job;
}
export function retryJob(job: QueueJob, id: string, now: string): QueueJob {
  return {
    ...job,
    id,
    status: "queued",
    progress: 0,
    createdAt: now,
    startedAt: null,
    finishedAt: null,
    worker: null,
    attempt: job.attempt + 1,
    retryOf: job.id,
    error: null,
    outputId: null,
    parameters: { ...job.parameters },
    logs: [
      {
        time: now,
        level: "info",
        message: `تلاش جدید نمونه از ${job.id} ثبت شد؛ منبع و پارامترها حفظ شدند.`,
      },
    ],
  };
}
export function advanceJobs(jobs: QueueJob[], now: string): QueueJob[] {
  const occupied = new Set(
    jobs.filter((j) => j.status === "running").map((j) => j.worker),
  );
  const free = ["mock-worker-01", "mock-worker-02"].filter(
    (w) => !occupied.has(w),
  );
  const waiting = jobs
    .filter((j) => j.status === "queued")
    .sort(
      (a, b) =>
        a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id),
    );
  const assigned = new Map(
    waiting.slice(0, free.length).map((j, i) => [j.id, free[i]]),
  );
  return jobs.map((job) => {
    const worker = assigned.get(job.id);
    if (worker)
      return {
        ...job,
        status: "running",
        startedAt: now,
        worker,
        logs: [
          ...job.logs,
          { time: now, level: "info", message: "اجرای محلی نمونه آغاز شد." },
        ],
      };
    if (job.status !== "running") return job;
    const progress = Math.min(100, job.progress + 8);
    return {
      ...job,
      progress,
      ...(progress === 100
        ? {
            status: "succeeded" as const,
            finishedAt: now,
            outputId: `mock-output-${job.id}`,
            logs: [
              ...job.logs,
              {
                time: now,
                level: "success" as const,
                message:
                  "اجرای شبیه‌سازی‌شده تکمیل شد؛ خروجی علمی ساخته نشده است.",
              },
            ],
          }
        : {}),
    };
  });
}
export function jobTime(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("fa-IR", {
        timeZone: "Asia/Tehran",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(value))
    : "—";
}
export function downloadJobJSON(filename: string, value: object) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], {
      type: "application/json;charset=utf-8",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
