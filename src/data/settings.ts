export type KeyKind = "api" | "service" | "signing";
export type KeyStatus = "active" | "revoked" | "expired";
export const keyKindLabels: Record<KeyKind, string> = {
  api: "API پنل",
  service: "دسترسی سرویس",
  signing: "امضای وب‌هوک",
};
export const keyStatusLabels: Record<KeyStatus, string> = {
  active: "فعال در نمونه",
  revoked: "لغوشده",
  expired: "منقضی",
};
export const keyScopes = [
  { id: "data:read", label: "خواندن داده‌ها" },
  { id: "reports:read", label: "خواندن گزارش‌ها" },
  { id: "jobs:run", label: "اجرای عملیات" },
] as const;
export const webhookEvents = [
  { id: "job.succeeded", label: "پایان موفق اجرا" },
  { id: "job.failed", label: "خطای اجرا" },
  { id: "model.created", label: "ثبت نسخهٔ مدل" },
  { id: "report.ready", label: "آماده‌شدن گزارش" },
] as const;
export type WebhookEvent = (typeof webhookEvents)[number]["id"];
export interface MockAccessKey {
  id: string;
  name: string;
  kind: KeyKind;
  scopes: string[];
  status: KeyStatus;
  suffix: string;
  createdAt: string;
  expiresAt: string;
  lastUsedAt: string | null;
  generation: number;
}
export interface MockWebhook {
  id: string;
  name: string;
  url: string;
  events: WebhookEvent[];
  signingKeyId: string;
  enabled: boolean;
  timeoutSeconds: number;
  retries: number;
  version: number;
}
export interface MockDelivery {
  id: string;
  hookId: string;
  hookVersion: number;
  origin: string;
  event: WebhookEvent;
  outcome: "success" | "failure" | "timeout";
  statusCode: number | null;
  time: string;
}
export interface GeneralSettings {
  projectName: string;
  teamName: string;
  description: string;
  timezone: "Asia/Tehran" | "UTC";
}
export interface SecuritySettings {
  requireMfa: boolean;
  idleMinutes: number;
  passwordLength: number;
  maxAttempts: number;
  confirmSensitive: boolean;
  defaultRole: "viewer" | "operator";
  allowedIPs: string;
}
export interface NotificationSettings {
  email: string;
  emailEnabled: boolean;
  inAppEnabled: boolean;
  jobFailures: boolean;
  jobSuccesses: boolean;
  modelUpdates: boolean;
  dailySummary: boolean;
}
export type SettingsCategory =
  "general" | "keys" | "webhooks" | "security" | "notifications";
export interface SettingsAudit {
  id: string;
  time: string;
  category: SettingsCategory;
  action: string;
  target: string;
  outcome: "saved" | "simulated" | "failed";
}
export interface SettingsState {
  general: GeneralSettings;
  security: SecuritySettings;
  notifications: NotificationSettings;
  keys: MockAccessKey[];
  webhooks: MockWebhook[];
  deliveries: MockDelivery[];
  audit: SettingsAudit[];
}
export const categoryLabels: Record<SettingsCategory, string> = {
  general: "عمومی",
  keys: "کلیدها",
  webhooks: "وب‌هوک",
  security: "امنیت",
  notifications: "اعلان‌ها",
};
export const settingsFixture: SettingsState = {
  general: {
    projectName: "Spectral Project",
    teamName: "تیم تحلیل داده",
    description: "مدیریت و مشاهدهٔ چارچوب تحلیل طیفی و رفتار.",
    timezone: "Asia/Tehran",
  },
  security: {
    requireMfa: true,
    idleMinutes: 30,
    passwordLength: 12,
    maxAttempts: 5,
    confirmSensitive: true,
    defaultRole: "viewer",
    allowedIPs: "192.0.2.0/24",
  },
  notifications: {
    email: "alerts@example.com",
    emailEnabled: true,
    inAppEnabled: true,
    jobFailures: true,
    jobSuccesses: false,
    modelUpdates: true,
    dailySummary: false,
  },
  keys: [
    {
      id: "mock-key-api-01",
      name: "پنل گزارش‌گیری",
      kind: "api",
      scopes: ["data:read", "reports:read"],
      status: "active",
      suffix: "A71C",
      createdAt: "2026-11-01T07:00:00Z",
      expiresAt: "2027-01-30T07:00:00Z",
      lastUsedAt: "2026-11-05T07:30:00Z",
      generation: 1,
    },
    {
      id: "mock-key-signing-01",
      name: "امضای اعلان‌های پردازش",
      kind: "signing",
      scopes: ["webhooks:sign"],
      status: "active",
      suffix: "B29F",
      createdAt: "2026-11-02T08:00:00Z",
      expiresAt: "2027-01-31T08:00:00Z",
      lastUsedAt: null,
      generation: 1,
    },
    {
      id: "mock-key-service-01",
      name: "سرویس دریافت آزمایشی",
      kind: "service",
      scopes: ["data:read"],
      status: "expired",
      suffix: "C83D",
      createdAt: "2026-10-01T06:00:00Z",
      expiresAt: "2026-10-31T06:00:00Z",
      lastUsedAt: "2026-10-29T09:00:00Z",
      generation: 1,
    },
  ],
  webhooks: [
    {
      id: "mock-hook-jobs",
      name: "اعلان پایان پردازش",
      url: "https://hooks.example.com/siem/jobs",
      events: ["job.succeeded", "job.failed"],
      signingKeyId: "mock-key-signing-01",
      enabled: true,
      timeoutSeconds: 10,
      retries: 3,
      version: 1,
    },
    {
      id: "mock-hook-models",
      name: "ثبت نسخهٔ مدل",
      url: "https://audit.example.org/siem/models",
      events: ["model.created"],
      signingKeyId: "mock-key-signing-01",
      enabled: false,
      timeoutSeconds: 15,
      retries: 2,
      version: 1,
    },
  ],
  deliveries: [],
  audit: [
    {
      id: "mock-audit-02",
      time: "2026-11-05T07:30:00Z",
      category: "webhooks",
      action: "ثبت وب‌هوک نمونه",
      target: "mock-hook-jobs",
      outcome: "saved",
    },
    {
      id: "mock-audit-01",
      time: "2026-11-04T08:15:00Z",
      category: "security",
      action: "ذخیرهٔ خط‌مشی نمایشی",
      target: "security-policy",
      outcome: "saved",
    },
  ],
};
export const initialSettingsState = () => structuredClone(settingsFixture);
export const makeSettingsId = (kind: string) =>
  `mock-${kind}-${crypto.randomUUID().slice(0, 8)}`;
export function settingsTime(
  value: string | null,
  timezone: GeneralSettings["timezone"],
) {
  return value
    ? new Intl.DateTimeFormat("fa-IR", {
        timeZone: timezone,
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "استفاده نشده";
}
export function destinationOrigin(url: string) {
  try {
    return new URL(url).origin;
  } catch {
    return "نشانی نامعتبر";
  }
}
export function validateWebhookURL(raw: string) {
  try {
    const url = new URL(raw);
    if (
      url.protocol !== "https:" ||
      !url.hostname ||
      url.username ||
      url.password ||
      url.hash
    )
      return "نشانی HTTPS معتبر، بدون نام کاربری، رمز یا fragment وارد کنید.";
    return "";
  } catch {
    return "نشانی HTTPS معتبر وارد کنید.";
  }
}
export function isIPv4Rule(value: string) {
  const [ip, prefix, extra] = value.split("/");
  if (extra !== undefined) return false;
  const parts = ip.split(".");
  return (
    parts.length === 4 &&
    parts.every(
      (part) =>
        /^\d{1,3}$/.test(part) &&
        Number(part) <= 255 &&
        String(Number(part)) === part,
    ) &&
    (prefix === undefined ||
      (/^(0|[1-9]\d?)$/.test(prefix) && Number(prefix) <= 32))
  );
}
export function validateSecurity(value: SecuritySettings) {
  const errors: Record<string, string> = {};
  for (const [key, min, max] of [
    ["idleMinutes", 5, 240],
    ["passwordLength", 12, 64],
    ["maxAttempts", 3, 10],
  ] as const)
    if (!Number.isInteger(value[key]) || value[key] < min || value[key] > max)
      errors[key] = `عدد صحیح بین ${min} و ${max} وارد کنید.`;
  if (
    value.allowedIPs
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .some((line) => !isIPv4Rule(line))
  )
    errors.allowedIPs =
      "هر سطر باید IPv4 یا CIDR معتبر باشد؛ مانند 192.0.2.0/24.";
  return errors;
}
export function redactedSettingsExport(state: SettingsState) {
  return {
    mock: true,
    secrets_included: false,
    destinations_redacted: true,
    exported_at: new Date().toISOString(),
    general: state.general,
    security: state.security,
    notifications: state.notifications,
    keys: state.keys,
    webhooks: state.webhooks.map(({ url, ...hook }) => ({
      ...hook,
      destination_origin: destinationOrigin(url),
    })),
    deliveries: state.deliveries,
    audit: state.audit,
    note: "Only saved visit-local metadata. No usable credentials, full destination URLs, authentication enforcement or live deliveries.",
  };
}
export function downloadSettingsJSON(filename: string, value: object) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], {
      type: "application/json;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
