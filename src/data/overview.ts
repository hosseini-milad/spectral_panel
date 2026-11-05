import { mockDays, type ProcessingDay, summarizeDay, stages } from "./days";

export type SourceState = "healthy" | "delayed" | "offline";
export interface MockSource {
  id: string;
  name: string;
  type: string;
  state: SourceState;
  records: number;
  lastReceived: string | null;
}
export interface OperationalNotice {
  id: string;
  priority: "high" | "medium";
  title: string;
  description: string;
  date: string;
}
export const sourceStateLabels: Record<SourceState, string> = {
  healthy: "عادی",
  delayed: "با تأخیر",
  offline: "بدون دریافت",
};
export const decimal = (value: number, digits = 1) =>
  new Intl.NumberFormat("fa-IR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);

// Additional SIEM-style display fixtures, not discovered collectors or live alerts.
const sourceProfiles = [
  {
    id: "network",
    name: "تجهیزات شبکه",
    type: "Firewall / Network",
    weight: 42,
  },
  { id: "identity", name: "ورود و هویت", type: "Authentication", weight: 24 },
  { id: "dns", name: "سرویس نام دامنه", type: "DNS", weight: 16 },
  { id: "endpoint", name: "سیستم‌های میزبان", type: "Endpoint", weight: 12 },
  { id: "cloud", name: "سرویس‌های ابری", type: "Cloud audit", weight: 6 },
];

export function getOverview(day: ProcessingDay) {
  const summary = summarizeDay(day);
  const pending = day.chunks.filter(
    (chunk) => chunk.status === "pending",
  ).length;
  const sourceGap = summary.missing > 0 || summary.failed > 0;
  const delayed = summary.running > 0;
  const profiles = sourceProfiles.map((profile) => ({
    ...profile,
    state: (profile.id === "cloud" && sourceGap
      ? "offline"
      : profile.id === "endpoint" && delayed
        ? "delayed"
        : "healthy") as SourceState,
  }));
  const activeProfiles = profiles.filter(
    (profile) => profile.state !== "offline",
  );
  const weight = activeProfiles.reduce(
    (sum, profile) => sum + profile.weight,
    0,
  );
  let allocated = 0;
  const sources: MockSource[] = profiles.map((profile) => {
    const isLastActive = profile.id === activeProfiles.at(-1)?.id;
    const records =
      profile.state === "offline"
        ? 0
        : isLastActive
          ? summary.records - allocated
          : Math.floor((summary.records * profile.weight) / weight);
    allocated += records;
    return {
      id: profile.id,
      name: profile.name,
      type: profile.type,
      state: profile.state,
      records,
      lastReceived:
        profile.state === "offline"
          ? null
          : profile.state === "delayed"
            ? "۰۹:۴۸"
            : day.date === mockDays[0].date
              ? "۱۰:۴۲"
              : "۲۳:۵۸",
    };
  });
  const assessedRecords = day.chunks
    .filter((chunk) => chunk.completedStages >= 1)
    .reduce((sum, chunk) => sum + chunk.records, 0);
  const excludedRecords = assessedRecords - summary.normalized;
  const notices: OperationalNotice[] = [];
  if (summary.failed)
    notices.push({
      id: "processing",
      priority: "high",
      title: "اجرای ناموفق در پردازش روز",
      description: `${summary.failed} چانک به بررسی خطای اجرا نیاز دارد؛ تکرار خودکار انجام نشده است.`,
      date: day.date,
    });
  if (sourceGap)
    notices.push({
      id: "source",
      priority: "high",
      title: "دریافت یک منبع متوقف است",
      description:
        "در سناریوی ماک، منبع سرویس‌های ابری در دسترس نیست؛ وضعیت دریافت را بررسی کنید.",
      date: day.date,
    });
  if (summary.missing)
    notices.push({
      id: "coverage",
      priority: "medium",
      title: "پوشش ورودی روز کامل نیست",
      description: `${summary.missing} چانک از ${day.expectedChunks} پارتیشن مورد انتظار هنوز موجود نیست.`,
      date: day.date,
    });
  if (delayed)
    notices.push({
      id: "latency",
      priority: "medium",
      title: "تأخیر در دریافت از میزبان‌ها",
      description:
        "در سناریوی ماک، ورودی منبع میزبان‌ها با تأخیر می‌رسد؛ تازگی داده بررسی شود.",
      date: day.date,
    });
  return {
    ...summary,
    sources,
    notices,
    pending,
    assessedRecords,
    excludedRecords,
    unassessedRecords: summary.records - assessedRecords,
    acceptanceRate: assessedRecords
      ? (summary.normalized / assessedRecords) * 100
      : null,
    estimatedEPS: summary.records / 86400,
    availableSources: sources.filter((source) => source.state !== "offline")
      .length,
    healthySources: sources.filter((source) => source.state === "healthy")
      .length,
    stageCoverage: stages.map((label, index) => ({
      label,
      completed: day.chunks.filter((chunk) => chunk.completedStages > index)
        .length,
      expected: day.expectedChunks,
    })),
  };
}
