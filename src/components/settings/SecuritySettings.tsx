import { useState, type Dispatch, type SetStateAction } from "react";
import {
  ShieldCheck,
  LockKeyhole,
  Users,
  Save,
  Check,
  Minus,
} from "lucide-react";
import {
  validateSecurity,
  type SecuritySettings as SecurityValues,
} from "../../data/settings";
import { SettingSwitch } from "./SettingsShared";

export function SecuritySettings({
  value,
  saved,
  onChange,
  onReview,
}: {
  value: SecurityValues;
  saved: SecurityValues;
  onChange: Dispatch<SetStateAction<SecurityValues>>;
  onReview: () => void;
}) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const dirty = JSON.stringify(value) !== JSON.stringify(saved);
  const switches = [
    {
      key: "requireMfa",
      title: "الزام احراز هویت دومرحله‌ای",
      detail:
        "خط‌مشی پیشنهادی برای ورود اعضا؛ ثبت دستگاه MFA واقعی انجام نمی‌شود.",
    },
    {
      key: "confirmSensitive",
      title: "تأیید عملیات حساس",
      detail: "الگوی تأیید برای حذف، بازسازی و تغییر دسترسی در استقرار آینده.",
    },
  ] as const;
  return (
    <div className="stg-section-stack">
      <p className="stg-section-callout">
        <ShieldCheck size={17} />
        این خط‌مشی ماک است؛ ذخیرهٔ آن احراز هویت، مجوزها یا تنظیمات Django را
        اعمال نمی‌کند.
      </p>
      <form
        className="stg-card"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const next = validateSecurity(value);
          setErrors(next);
          if (!Object.keys(next).length) onReview();
        }}
      >
        <div className="stg-card-heading">
          <div>
            <LockKeyhole size={18} />
            <div>
              <h2>ورود و حفاظت دسترسی</h2>
              <p>تغییرات پیش از ذخیره در یک پنجره بازبینی می‌شوند.</p>
            </div>
          </div>
          <span className="stg-tag">خط‌مشی نمونه</span>
        </div>
        <div className="stg-card-body">
          <div className="stg-setting-rows">
            {switches.map((item) => (
              <div key={item.key}>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.detail}</p>
                </div>
                <SettingSwitch
                  label={item.title}
                  checked={value[item.key]}
                  onChange={(checked) =>
                    onChange({ ...value, [item.key]: checked })
                  }
                />
              </div>
            ))}
          </div>
          <div className="stg-form-grid stg-security-fields">
            {[
              {
                key: "idleMinutes",
                label: "پایان نشستِ بدون فعالیت",
                unit: "دقیقه · ۵ تا ۲۴۰",
                min: 5,
                max: 240,
              },
              {
                key: "passwordLength",
                label: "حداقل طول گذرواژه",
                unit: "نویسه · ۱۲ تا ۶۴",
                min: 12,
                max: 64,
              },
              {
                key: "maxAttempts",
                label: "حداکثر تلاش ورود ناموفق",
                unit: "تلاش · ۳ تا ۱۰",
                min: 3,
                max: 10,
              },
            ].map((field) => (
              <label className="stg-field" key={field.key}>
                {field.label}
                <input
                  type="number"
                  aria-label={field.label}
                  min={field.min}
                  max={field.max}
                  step={1}
                  value={
                    Number.isNaN(
                      value[
                        field.key as
                          "idleMinutes" | "passwordLength" | "maxAttempts"
                      ],
                    )
                      ? ""
                      : value[
                          field.key as
                            "idleMinutes" | "passwordLength" | "maxAttempts"
                        ]
                  }
                  aria-invalid={!!errors[field.key]}
                  onChange={(event) => {
                    setErrors({});
                    onChange({
                      ...value,
                      [field.key]:
                        event.target.value === ""
                          ? NaN
                          : Number(event.target.value),
                    });
                  }}
                />
                <small>{errors[field.key] || field.unit}</small>
              </label>
            ))}
            <label className="stg-field">
              نقش پیش‌فرض عضو جدید
              <select
                aria-label="نقش پیش‌فرض"
                value={value.defaultRole}
                onChange={(event) =>
                  onChange({
                    ...value,
                    defaultRole: event.target
                      .value as SecurityValues["defaultRole"],
                  })
                }
              >
                <option value="viewer">مشاهده‌گر</option>
                <option value="operator">اپراتور</option>
              </select>
            </label>
            <label className="stg-field stg-span-full">
              فهرست IPv4 مجاز · اختیاری
              <textarea
                aria-label="فهرست IP مجاز"
                dir="ltr"
                rows={3}
                placeholder="192.0.2.0/24"
                value={value.allowedIPs}
                aria-invalid={!!errors.allowedIPs}
                onChange={(event) => {
                  setErrors({});
                  onChange({ ...value, allowedIPs: event.target.value });
                }}
              />
              <small className={errors.allowedIPs ? "stg-field-error" : ""}>
                {errors.allowedIPs ||
                  "هر سطر یک IPv4 یا CIDR؛ مقدار خالی یعنی فهرست محدودکننده در سناریو تعریف نشده است."}
              </small>
            </label>
          </div>
          {Object.keys(errors).length > 0 && (
            <p className="stg-form-error" role="alert">
              مقادیر نامعتبر را اصلاح کنید؛ خط‌مشی ذخیره نشده است.
            </p>
          )}
        </div>
        <footer className="stg-card-actions">
          <button
            className="stg-primary-button"
            disabled={!dirty}
            type="submit"
          >
            <Save size={14} />
            بازبینی و ذخیرهٔ امنیت
          </button>
          <button
            type="button"
            className="stg-text-button"
            disabled={!dirty}
            onClick={() => {
              onChange({ ...saved });
              setErrors({});
            }}
          >
            برگرداندن تغییرات
          </button>
        </footer>
      </form>
      <section className="stg-card">
        <div className="stg-card-heading">
          <div>
            <Users size={18} />
            <div>
              <h2>ماتریس نقش‌های نمونه</h2>
              <p>
                برای طراحی دسترسی آینده؛ RBAC واقعی در این نسخه اعمال نمی‌شود.
              </p>
            </div>
          </div>
        </div>
        <div
          className="stg-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="نقش‌های نمونه"
        >
          <table>
            <thead>
              <tr>
                {[
                  "نقش",
                  "مشاهدهٔ داده",
                  "اجرای عملیات",
                  "مدیریت کلیدها",
                  "تنظیمات امنیت",
                ].map((label) => (
                  <th scope="col" key={label}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { name: "مشاهده‌گر", grants: [true, false, false, false] },
                { name: "اپراتور", grants: [true, true, false, false] },
                { name: "مدیر", grants: [true, true, true, true] },
              ].map((role) => (
                <tr key={role.name}>
                  <th scope="row">{role.name}</th>
                  {role.grants.map((allowed, index) => (
                    <td key={index}>
                      <span
                        aria-label={
                          allowed ? "مجاز در نمونه" : "غیرمجاز در نمونه"
                        }
                        className={allowed ? "stg-grant" : "stg-muted"}
                      >
                        {allowed ? <Check size={15} /> : <Minus size={14} />}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
