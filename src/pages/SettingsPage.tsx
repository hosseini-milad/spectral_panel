import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Settings2,
  SlidersHorizontal,
  KeyRound,
  Webhook,
  ShieldCheck,
  Bell,
  FileClock,
  Download,
  Plus,
  RotateCw,
  Trash2,
  Pencil,
  FlaskConical,
} from "lucide-react";
import {
  initialSettingsState,
  makeSettingsId,
  settingsTime,
  destinationOrigin,
  keyKindLabels,
  keyStatusLabels,
  redactedSettingsExport,
  downloadSettingsJSON,
  type SettingsCategory,
  type SettingsState,
  type MockAccessKey,
  type MockWebhook,
  type SettingsAudit,
} from "../data/settings";
import { useThemePreference } from "../hooks/useThemePreference";
import { GeneralSettings } from "../components/settings/GeneralSettings";
import { SecuritySettings } from "../components/settings/SecuritySettings";
import { NotificationSettings } from "../components/settings/NotificationSettings";
import { SettingsActivity } from "../components/settings/SettingsActivity";
import {
  SettingSwitch,
  SettingsDialog,
  ConfirmSettingAction,
} from "../components/settings/SettingsShared";
import {
  KeyForm,
  TokenView,
  WebhookForm,
  WebhookTest,
} from "../components/settings/IntegrationForms";
import "./settings.css";
const sections = [
  { id: "general", label: "عمومی و ظاهر", icon: SlidersHorizontal },
  { id: "keys", label: "کلیدهای دسترسی", icon: KeyRound },
  { id: "webhooks", label: "وب‌هوک‌ها", icon: Webhook },
  { id: "security", label: "امنیت و نقش‌ها", icon: ShieldCheck },
  { id: "notifications", label: "اعلان‌ها", icon: Bell },
  { id: "activity", label: "تاریخچهٔ تغییرات", icon: FileClock },
];
type Modal = { id: string } & (
  | { kind: "create-key" }
  | { kind: "token"; token: string }
  | { kind: "rotate" | "revoke"; key: MockAccessKey }
  | { kind: "create-hook" }
  | { kind: "edit-hook" | "delete-hook" | "test-hook"; hook: MockWebhook }
  | { kind: "security"; value: SettingsState["security"] }
  | { kind: "notification" }
);
export function SettingsPage() {
  const [params] = useSearchParams();
  const section = sections.some((s) => s.id === params.get("section"))
    ? params.get("section")!
    : "general";
  const [state, setState] = useState(initialSettingsState);
  const [general, setGeneral] = useState(state.general);
  const [security, setSecurity] = useState(state.security);
  const [notifications, setNotifications] = useState(state.notifications);
  const [modal, setModal] = useState<Modal | null>(null);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState("all");
  const handled = useRef("");
  const theme = useThemePreference();
  useEffect(() => {
    setModal(null);
    setSearch("");
    setKindFilter("all");
  }, [section]);
  const open = (
    value: Omit<
      Extract<Modal, { kind: "create-key" | "create-hook" | "notification" }>,
      "id"
    >,
  ) => setModal({ ...value, id: makeSettingsId("dialog") } as Modal);
  const audit = (
    category: SettingsCategory,
    action: string,
    target: string,
    outcome: SettingsAudit["outcome"] = "saved",
  ): SettingsAudit => ({
    id: makeSettingsId("audit"),
    time: new Date().toISOString(),
    category,
    action,
    target,
    outcome,
  });
  function update(
    transform: (s: SettingsState) => SettingsState,
    entry: SettingsAudit,
    message: string,
  ) {
    setState((s) => ({
      ...transform(s),
      audit: [entry, ...s.audit].slice(0, 100),
    }));
    setNotice(message);
  }
  function claim() {
    if (!modal || handled.current === modal.id) return false;
    handled.current = modal.id;
    return true;
  }
  function issueKey(key: MockAccessKey) {
    const token = `MOCK_ONLY_${key.kind.toUpperCase()}_${crypto.randomUUID().replaceAll("-", "")}`;
    return { token, key: { ...key, suffix: token.slice(-4) } };
  }
  const activeSign = (hook: MockWebhook) =>
    state.keys.some(
      (k) =>
        k.id === hook.signingKeyId &&
        k.kind === "signing" &&
        k.status === "active",
    );
  const title =
    modal?.kind === "create-key"
      ? "کلید دسترسی جدید"
      : modal?.kind === "token"
        ? "کلید جعلی · نمایش یک‌باره"
        : modal?.kind === "rotate"
          ? "چرخش کلید نمونه"
          : modal?.kind === "revoke"
            ? "لغو کلید نمونه"
            : modal?.kind === "create-hook"
              ? "وب‌هوک جدید"
              : modal?.kind === "edit-hook"
                ? "ویرایش وب‌هوک"
                : modal?.kind === "delete-hook"
                  ? "حذف وب‌هوک"
                  : modal?.kind === "test-hook"
                    ? "شبیه‌سازی تست وب‌هوک"
                    : modal?.kind === "security"
                      ? "بازبینی خط‌مشی امنیت"
                      : "پیش‌نمایش اعلان";
  return (
    <main id="main-content" className="main-content stg-page" tabIndex={-1}>
      <header className="stg-page-heading">
        <div>
          <span className="stg-eyebrow">
            <Settings2 size={14} />
            مدیریت فضای کاری
          </span>
          <h1>تنظیمات</h1>
          <p>پیکربندی پروژه، اتصال سرویس‌ها و خط‌مشی دسترسی</p>
        </div>
        <button
          className="stg-secondary-button"
          onClick={() =>
            downloadSettingsJSON("spectral-settings-mock.json", {
              ...redactedSettingsExport(state),
              appearance: theme.preference,
            })
          }
        >
          <Download size={15} />
          دریافت پیکربندی ماک
        </button>
      </header>
      <div className="stg-summary">
        <span>
          <i />
          محیط نمونه
        </span>
        <span>
          {state.keys.filter((k) => k.status === "active").length} کلید فعال
        </span>
        <span>
          {state.webhooks.filter((h) => h.enabled).length} وب‌هوک فعال
        </span>
        <span>ذخیره در حافظهٔ همین بازدید</span>
      </div>
      <p className="stg-section-callout">
        همهٔ کلیدها، اتصال‌ها و سیاست‌های امنیتی این صفحه ماک‌اند؛ با بازخوانی
        صفحه بازنشانی می‌شوند. فقط انتخاب تم در مرورگر ذخیره می‌شود. احراز هویت
        و سیاست استقرار واقعی جداگانه تعیین خواهد شد.
      </p>
      {notice && (
        <div className="stg-notice" role="status">
          {notice}
        </div>
      )}
      <div className="stg-layout">
        <nav className="stg-navigation" aria-label="بخش‌های تنظیمات">
          {sections.map((item) => (
            <Link
              key={item.id}
              to={`/settings?section=${item.id}`}
              aria-current={section === item.id ? "page" : undefined}
            >
              <item.icon size={17} />
              {item.label}
            </Link>
          ))}
          <div className="stg-nav-note">
            <ShieldCheck size={22} />
            <strong>کنترل شفاف دسترسی</strong>
            <p>تغییرات حساس با بازبینی و تأیید صریح ثبت می‌شوند.</p>
          </div>
        </nav>
        <div className="stg-content">
          {section === "general" && (
            <GeneralSettings
              value={general}
              saved={state.general}
              onChange={setGeneral}
              onSave={() => {
                const value = {
                  ...general,
                  projectName: general.projectName.trim(),
                  teamName: general.teamName.trim(),
                  description: general.description.trim(),
                };
                setGeneral(value);
                update(
                  (s) => ({ ...s, general: value }),
                  audit("general", "ذخیرهٔ مشخصات پروژه", "project"),
                  "تنظیمات عمومی در نمونه ذخیره شد.",
                );
              }}
              preference={theme.preference}
              theme={theme.theme}
              onTheme={theme.chooseTheme}
            />
          )}
          {section === "security" && (
            <SecuritySettings
              value={security}
              saved={state.security}
              onChange={setSecurity}
              onReview={() =>
                setModal({
                  kind: "security",
                  value: { ...security },
                  id: makeSettingsId("dialog"),
                })
              }
            />
          )}
          {section === "notifications" && (
            <NotificationSettings
              value={notifications}
              saved={state.notifications}
              onChange={setNotifications}
              onSave={() => {
                const value = {
                  ...notifications,
                  email: notifications.email.trim(),
                };
                setNotifications(value);
                update(
                  (s) => ({ ...s, notifications: value }),
                  audit(
                    "notifications",
                    "ذخیرهٔ ترجیحات اعلان",
                    "notifications",
                  ),
                  "ترجیحات نمونه ذخیره شد؛ پیامی ارسال نشد.",
                );
              }}
              onPreview={() => open({ kind: "notification" })}
            />
          )}
          {section === "activity" && (
            <SettingsActivity
              entries={state.audit}
              timezone={state.general.timezone}
            />
          )}
          {section === "keys" && (
            <section className="stg-card">
              <div className="stg-card-heading">
                <div>
                  <KeyRound size={19} />
                  <div>
                    <h2>کلیدهای دسترسی</h2>
                    <p>کلیدهای API، سرویس و امضا · فقط متادیتای نمونه</p>
                  </div>
                </div>
                <button
                  className="stg-primary-button"
                  onClick={() => open({ kind: "create-key" })}
                >
                  <Plus size={14} />
                  کلید جدید
                </button>
              </div>
              <div className="stg-table-toolbar">
                <input
                  aria-label="جست‌وجوی کلید"
                  placeholder="جست‌وجوی نام کلید…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <select
                  aria-label="فیلتر نوع کلید"
                  value={kindFilter}
                  onChange={(e) => setKindFilter(e.target.value)}
                >
                  <option value="all">همهٔ کلیدها</option>
                  {Object.entries(keyKindLabels).map(([id, label]) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div
                className="stg-table-scroll"
                tabIndex={0}
                role="region"
                aria-label="جدول کلیدها"
              >
                <table>
                  <thead>
                    <tr>
                      {[
                        "نام و دسترسی",
                        "کلید",
                        "وضعیت",
                        "آخرین استفاده / انقضا",
                        "عملیات",
                      ].map((t) => (
                        <th key={t}>{t}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {state.keys
                      .filter(
                        (k) =>
                          k.name.includes(search) &&
                          (kindFilter === "all" || k.kind === kindFilter),
                      )
                      .map((k) => (
                        <tr key={k.id}>
                          <td>
                            <strong>{k.name}</strong>
                            <small>{keyKindLabels[k.kind]}</small>
                            <small dir="ltr">{k.scopes.join(" · ")}</small>
                          </td>
                          <td>
                            <code dir="ltr">•••• {k.suffix}</code>
                            <small>نسخه {k.generation}</small>
                          </td>
                          <td>
                            <span
                              className={`stg-state ${k.status === "active" ? "active" : "warning"}`}
                            >
                              {keyStatusLabels[k.status]}
                            </span>
                          </td>
                          <td>
                            {settingsTime(k.lastUsedAt, state.general.timezone)}
                            <small>
                              انقضا:{" "}
                              {settingsTime(
                                k.expiresAt,
                                state.general.timezone,
                              )}
                            </small>
                          </td>
                          <td>
                            <div className="stg-row-actions">
                              <button
                                aria-label={`چرخش ${k.name}`}
                                disabled={k.status !== "active"}
                                onClick={() =>
                                  setModal({
                                    kind: "rotate",
                                    key: k,
                                    id: makeSettingsId("dialog"),
                                  })
                                }
                              >
                                <RotateCw size={15} />
                                چرخش
                              </button>
                              <button
                                aria-label={`لغو ${k.name}`}
                                disabled={k.status !== "active"}
                                onClick={() =>
                                  setModal({
                                    kind: "revoke",
                                    key: k,
                                    id: makeSettingsId("dialog"),
                                  })
                                }
                              >
                                <Trash2 size={15} />
                                لغو
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    {!state.keys.some(
                      (k) =>
                        k.name.includes(search) &&
                        (kindFilter === "all" || k.kind === kindFilter),
                    ) && (
                      <tr>
                        <td colSpan={5} className="stg-table-empty">
                          کلیدی پیدا نشد.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="stg-help stg-help-padded">
                مقدار کامل کلیدهای جعلی در تاریخچه یا خروجی ذخیره نمی‌شود. لغو
                کلید امضا، وب‌هوک‌های وابسته را غیرفعال می‌کند.
              </p>
            </section>
          )}
          {section === "webhooks" && (
            <div className="stg-section-stack">
              <section className="stg-card">
                <div className="stg-card-heading">
                  <div>
                    <Webhook size={19} />
                    <div>
                      <h2>اتصال‌های وب‌هوک</h2>
                      <p>رویداد، امضا و سیاست تحویل پیشنهادی</p>
                    </div>
                  </div>
                  <button
                    className="stg-primary-button"
                    onClick={() => open({ kind: "create-hook" })}
                  >
                    <Plus size={14} />
                    وب‌هوک جدید
                  </button>
                </div>
                <div className="stg-hook-list">
                  {state.webhooks.map((h) => (
                    <article className="stg-hook" key={h.id}>
                      <header>
                        <div>
                          <h3>{h.name}</h3>
                          <p dir="ltr">{destinationOrigin(h.url)}</p>
                        </div>
                        <SettingSwitch
                          label={`فعال بودن ${h.name}`}
                          checked={h.enabled}
                          disabled={!activeSign(h)}
                          onChange={(enabled) =>
                            update(
                              (s) => ({
                                ...s,
                                webhooks: s.webhooks.map((item) =>
                                  item.id === h.id
                                    ? {
                                        ...item,
                                        enabled,
                                        version: item.version + 1,
                                      }
                                    : item,
                                ),
                              }),
                              audit("webhooks", "تغییر وضعیت اتصال", h.id),
                              "وضعیت وب‌هوک نمونه تغییر کرد.",
                            )
                          }
                        />
                      </header>
                      <div className="stg-hook-tags">
                        {h.events.map((e) => (
                          <span className="stg-tag" key={e}>
                            {e}
                          </span>
                        ))}
                      </div>
                      <p className="stg-help">
                        نسخه {h.version} · مهلت {h.timeoutSeconds} ثانیه ·{" "}
                        {h.retries} تلاش مجدد ·{" "}
                        {activeSign(h)
                          ? "کلید امضای فعال در نمونه"
                          : "کلید امضای فعال لازم است"}
                      </p>
                      <div className="stg-row-actions">
                        <button
                          onClick={() =>
                            setModal({
                              kind: "edit-hook",
                              hook: h,
                              id: makeSettingsId("dialog"),
                            })
                          }
                        >
                          <Pencil size={14} />
                          ویرایش
                        </button>
                        <button
                          disabled={!h.enabled || !activeSign(h)}
                          onClick={() =>
                            setModal({
                              kind: "test-hook",
                              hook: h,
                              id: makeSettingsId("dialog"),
                            })
                          }
                        >
                          <FlaskConical size={14} />
                          شبیه‌سازی تست
                        </button>
                        <button
                          onClick={() =>
                            setModal({
                              kind: "delete-hook",
                              hook: h,
                              id: makeSettingsId("dialog"),
                            })
                          }
                        >
                          <Trash2 size={14} />
                          حذف
                        </button>
                      </div>
                    </article>
                  ))}
                  {!state.webhooks.length && (
                    <p className="stg-table-empty">اتصالی تعریف نشده است.</p>
                  )}
                </div>
              </section>
              <section className="stg-card">
                <div className="stg-card-heading">
                  <div>
                    <FileClock size={18} />
                    <div>
                      <h2>تاریخچهٔ تحویل آزمایشی</h2>
                      <p>پاسخ فرضی، بدون ارسال HTTP یا امضای واقعی</p>
                    </div>
                  </div>
                </div>
                <div className="stg-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>مقصد / نسخه</th>
                        <th>رویداد</th>
                        <th>نتیجهٔ فرضی</th>
                        <th>زمان</th>
                      </tr>
                    </thead>
                    <tbody>
                      {state.deliveries.map((d) => (
                        <tr key={d.id}>
                          <td>
                            <bdi>{d.origin}</bdi>
                            <small>
                              {d.hookId} · v{d.hookVersion}
                            </small>
                          </td>
                          <td>
                            <bdi>{d.event}</bdi>
                          </td>
                          <td>
                            {d.statusCode
                              ? `HTTP ${d.statusCode}`
                              : "پایان مهلت پاسخ"}
                          </td>
                          <td>
                            {settingsTime(d.time, state.general.timezone)}
                          </td>
                        </tr>
                      ))}
                      {!state.deliveries.length && (
                        <tr>
                          <td colSpan={4} className="stg-table-empty">
                            هنوز تستی شبیه‌سازی نشده است.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}
        </div>
      </div>
      <SettingsDialog
        open={!!modal}
        identity={modal?.id ?? ""}
        title={title}
        onClose={() => setModal(null)}
      >
        <div key={modal?.id}>
          {modal?.kind === "create-key" && (
            <KeyForm
              onSave={(name, kind, scopes, days) => {
                if (!claim()) return;
                const now = new Date();
                const issued = issueKey({
                  id: makeSettingsId("key"),
                  name,
                  kind,
                  scopes,
                  status: "active",
                  suffix: "",
                  createdAt: now.toISOString(),
                  expiresAt: new Date(
                    now.getTime() + days * 86400000,
                  ).toISOString(),
                  lastUsedAt: null,
                  generation: 1,
                });
                update(
                  (s) => ({ ...s, keys: [issued.key, ...s.keys] }),
                  audit("keys", "ساخت کلید جعلی", issued.key.id),
                  "کلید جعلی ساخته شد.",
                );
                setModal({
                  kind: "token",
                  token: issued.token,
                  id: makeSettingsId("dialog"),
                });
              }}
            />
          )}
          {modal?.kind === "token" && <TokenView token={modal.token} />}
          {(modal?.kind === "rotate" || modal?.kind === "revoke") && (
            <ConfirmSettingAction
              description={`${modal.kind === "rotate" ? "چرخش" : "لغو"} کلید «${modal.key.name}» را تأیید می‌کنید؟`}
              details={
                <p className="stg-help">
                  {modal.kind === "revoke"
                    ? `${state.webhooks.filter((h) => h.signingKeyId === modal.key.id).length} وب‌هوک وابسته غیرفعال می‌شود.`
                    : "پسوند و نسخه تغییر می‌کند؛ مقدار قبلی در سناریو معتبر نخواهد بود."}
                </p>
              }
              button={modal.kind === "rotate" ? "تأیید چرخش" : "تأیید لغو"}
              onCancel={() => setModal(null)}
              onConfirm={() => {
                if (!claim()) return;
                const key = modal.key;
                if (modal.kind === "rotate") {
                  const issued = issueKey({
                    ...key,
                    generation: key.generation + 1,
                    lastUsedAt: null,
                  });
                  update(
                    (s) => ({
                      ...s,
                      keys: s.keys.map((k) =>
                        k.id === key.id ? issued.key : k,
                      ),
                    }),
                    audit("keys", "چرخش کلید جعلی", key.id),
                    "نسخهٔ کلید نمونه تغییر کرد.",
                  );
                  setModal({
                    kind: "token",
                    token: issued.token,
                    id: makeSettingsId("dialog"),
                  });
                } else {
                  update(
                    (s) => ({
                      ...s,
                      keys: s.keys.map((k) =>
                        k.id === key.id ? { ...k, status: "revoked" } : k,
                      ),
                      webhooks: s.webhooks.map((h) =>
                        h.signingKeyId === key.id
                          ? { ...h, enabled: false, version: h.version + 1 }
                          : h,
                      ),
                    }),
                    audit("keys", "لغو کلید جعلی", key.id),
                    "کلید لغو و وب‌هوک‌های وابسته غیرفعال شدند.",
                  );
                  setModal(null);
                }
              }}
            />
          )}
          {(modal?.kind === "create-hook" || modal?.kind === "edit-hook") && (
            <WebhookForm
              initial={modal.kind === "edit-hook" ? modal.hook : undefined}
              keys={state.keys}
              onSave={(value) => {
                if (!claim()) return;
                const hook = {
                  ...value,
                  id:
                    modal.kind === "edit-hook"
                      ? modal.hook.id
                      : makeSettingsId("hook"),
                  version:
                    modal.kind === "edit-hook" ? modal.hook.version + 1 : 1,
                };
                update(
                  (s) => ({
                    ...s,
                    webhooks:
                      modal.kind === "edit-hook"
                        ? s.webhooks.map((h) => (h.id === hook.id ? hook : h))
                        : [hook, ...s.webhooks],
                  }),
                  audit("webhooks", "ذخیرهٔ اتصال نمونه", hook.id),
                  "وب‌هوک ذخیره شد؛ هیچ درخواستی ارسال نشد.",
                );
                setModal(null);
              }}
            />
          )}
          {modal?.kind === "delete-hook" && (
            <ConfirmSettingAction
              description={`وب‌هوک «${modal.hook.name}» حذف شود؟ تاریخچهٔ تست‌های نمونه حفظ می‌شود.`}
              button="تأیید حذف"
              onCancel={() => setModal(null)}
              onConfirm={() => {
                if (!claim()) return;
                update(
                  (s) => ({
                    ...s,
                    webhooks: s.webhooks.filter((h) => h.id !== modal.hook.id),
                  }),
                  audit("webhooks", "حذف اتصال نمونه", modal.hook.id),
                  "وب‌هوک نمونه حذف شد.",
                );
                setModal(null);
              }}
            />
          )}
          {modal?.kind === "test-hook" && (
            <WebhookTest
              hook={modal.hook}
              onRun={(event, outcome) => {
                if (!claim()) return;
                const hook = modal.hook;
                const delivery = {
                  id: makeSettingsId("delivery"),
                  hookId: hook.id,
                  hookVersion: hook.version,
                  origin: destinationOrigin(hook.url),
                  event,
                  outcome,
                  statusCode:
                    outcome === "success"
                      ? 200
                      : outcome === "failure"
                        ? 500
                        : null,
                  time: new Date().toISOString(),
                };
                update(
                  (s) => ({
                    ...s,
                    deliveries: [delivery, ...s.deliveries].slice(0, 50),
                  }),
                  audit(
                    "webhooks",
                    "تست فرضی اتصال",
                    hook.id,
                    outcome === "success" ? "simulated" : "failed",
                  ),
                  "نتیجهٔ فرضی ثبت شد؛ هیچ HTTP ارسال نشد.",
                );
                setModal(null);
              }}
            />
          )}
          {modal?.kind === "security" && (
            <ConfirmSettingAction
              description="این مقادیر فقط در سناریوی ماک ذخیره می‌شوند؛ هیچ خط‌مشی واقعی اعمال نخواهد شد."
              details={
                <dl className="stg-definition-list">
                  {Object.entries(modal.value)
                    .filter(
                      ([key, value]) =>
                        value !==
                        state.security[key as keyof typeof state.security],
                    )
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt>
                          {
                            (
                              {
                                requireMfa: "احراز دومرحله‌ای",
                                idleMinutes: "مهلت نشست",
                                passwordLength: "طول گذرواژه",
                                maxAttempts: "تلاش ناموفق",
                                confirmSensitive: "تأیید حساس",
                                defaultRole: "نقش پیش‌فرض",
                                allowedIPs: "IPv4 مجاز",
                              } as Record<string, string>
                            )[key]
                          }
                        </dt>
                        <dd>
                          {typeof value === "boolean"
                            ? value
                              ? "فعال"
                              : "غیرفعال"
                            : String(value) || "بدون محدودیت"}
                        </dd>
                      </div>
                    ))}
                </dl>
              }
              button="تأیید و ذخیرهٔ خط‌مشی"
              onCancel={() => setModal(null)}
              onConfirm={() => {
                if (!claim()) return;
                const value = {
                  ...modal.value,
                  allowedIPs: modal.value.allowedIPs.trim(),
                };
                setSecurity(value);
                update(
                  (s) => ({ ...s, security: value }),
                  audit("security", "ذخیرهٔ خط‌مشی نمایشی", "security-policy"),
                  "خط‌مشی نمونه ذخیره شد؛ امنیت واقعی تغییری نکرد.",
                );
                setModal(null);
              }}
            />
          )}
          {modal?.kind === "notification" && (
            <div className="stg-modal-form">
              <span className="stg-tag">پیش‌نمایش · تنظیمات ذخیره‌شده</span>
              <h3>گزارش وضعیت پردازش</h3>
              <p>
                اجرای نمونهٔ روز انتخاب‌شده تکمیل شده است. جزئیات را در روزها و
                چانک‌ها ببینید.
              </p>
              <p>
                کانال داخل پنل:{" "}
                {state.notifications.inAppEnabled ? "فعال در نمونه" : "غیرفعال"}
              </p>
              <p>
                ایمیل:{" "}
                {state.notifications.emailEnabled
                  ? state.notifications.email
                  : "غیرفعال"}
              </p>
              <small>
                این پیش‌نمایش ارسال نمی‌شود و بیانگر وقوع رویداد واقعی نیست.
              </small>
            </div>
          )}
        </div>
      </SettingsDialog>
    </main>
  );
}
