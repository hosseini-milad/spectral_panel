import type { ProcessingDay } from "./days";

export const operationSteps = [
  {
    id: "normalize",
    label: "نرمال‌سازی داده‌ها",
    shortLabel: "نرمال‌سازی",
    description: "آماده‌سازی ویژگی‌ها و یکسان‌سازی داده‌های ورودی روز.",
    input: "رکورد خام",
    output: "رکورد نرمال‌شده",
    dependency: "انتخاب روز دارای داده",
  },
  {
    id: "sample",
    label: "نمونه‌برداری و انتخاب کاندید",
    shortLabel: "نمونه‌برداری",
    description: "انتخاب مجموعهٔ کاندید از داده‌های نرمال‌شدهٔ روز.",
    input: "رکورد نرمال‌شده",
    output: "کاندید",
    dependency: "تکمیل نرمال‌سازی",
  },
  {
    id: "representatives",
    label: "انتخاب نماینده‌ها",
    shortLabel: "انتخاب نماینده",
    description: "آماده‌سازی نماینده‌های مجموعهٔ کاندید در این سناریوی نمایشی.",
    input: "کاندید",
    output: "نماینده",
    dependency: "تکمیل نمونه‌برداری",
  },
  {
    id: "components",
    label: "ساخت گراف و ایجاد مولفه",
    shortLabel: "ایجاد مولفه",
    description: "نمایش ساخت گراف شباهت و گروه‌بندی مولفه‌های روز.",
    input: "کاندید",
    output: "مولفه",
    dependency: "تکمیل انتخاب نماینده در مسیر نمایشی",
  },
] as const;

export type StepStatus =
  "pending" | "queued" | "running" | "succeeded" | "failed" | "interrupted";
export type Scenario = "success" | "sampling-error";
export interface PipelineSettings {
  samplePercent: number;
  representativePercent: number;
}
export const defaultPipelineSettings: PipelineSettings = {
  samplePercent: 10,
  representativePercent: 10,
};
export interface StepResult {
  input: number;
  output: number;
  extraLabel: string;
  extra: number;
}
export interface StepExecution {
  status: StepStatus;
  progress: number;
  runId: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  result: StepResult | null;
  error: string | null;
}
export interface PipelineLog {
  id: string;
  time: string;
  level: "info" | "success" | "error" | "warning";
  message: string;
}
export interface PipelineState {
  steps: StepExecution[];
  logs: PipelineLog[];
  runId: string | null;
  runDay: string | null;
  settings: PipelineSettings | null;
  status: "idle" | "running" | "finished" | "failed" | "interrupted";
}
export function initialPipelineState(): PipelineState {
  return {
    steps: operationSteps.map(() => ({
      status: "pending",
      progress: 0,
      runId: null,
      startedAt: null,
      finishedAt: null,
      result: null,
      error: null,
    })),
    logs: [],
    runId: null,
    runDay: null,
    settings: null,
    status: "idle",
  };
}

// UI fixtures only. These ratios/counts are not the scientific pipeline.
export function mockPipelineResults(
  day: ProcessingDay,
  settings: PipelineSettings,
): StepResult[] {
  const raw = day.chunks.reduce((sum, chunk) => sum + chunk.records, 0);
  const excluded = day.chunks.reduce(
    (sum, chunk) => sum + 32 + chunk.index * 7,
    0,
  );
  const normalized = Math.max(0, raw - excluded);
  const candidates = Math.round((normalized * settings.samplePercent) / 100);
  const representatives = Math.round(
    (candidates * settings.representativePercent) / 100,
  );
  return [
    {
      input: raw,
      output: normalized,
      extraLabel: "رکورد کنارگذاشته‌شدهٔ نمونه",
      extra: excluded,
    },
    {
      input: normalized,
      output: candidates,
      extraLabel: "درصد نمونه‌برداری",
      extra: settings.samplePercent,
    },
    {
      input: candidates,
      output: representatives,
      extraLabel: "درصد نماینده از کاندید",
      extra: settings.representativePercent,
    },
    {
      input: candidates,
      output: Math.max(1, Math.round(candidates / 125)),
      extraLabel: "یال نمونهٔ گراف",
      extra: candidates * 4,
    },
  ];
}
export function pipelineLogTime(time: string) {
  return new Intl.DateTimeFormat("fa-IR", {
    timeZone: "Asia/Tehran",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(time));
}
