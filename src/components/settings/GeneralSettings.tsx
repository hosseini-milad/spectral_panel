import { useState, type Dispatch, type SetStateAction } from "react";
import {
  Building2,
  Monitor,
  Moon,
  Save,
  Sun,
  Undo2,
  Database,
} from "lucide-react";
import type { GeneralSettings as GeneralValues } from "../../data/settings";
import type { Theme, ThemePreference } from "../../lib/theme";

export function GeneralSettings({
  value,
  saved,
  onChange,
  onSave,
  preference,
  theme,
  onTheme,
}: {
  value: GeneralValues;
  saved: GeneralValues;
  onChange: Dispatch<SetStateAction<GeneralValues>>;
  onSave: () => void;
  preference: ThemePreference;
  theme: Theme;
  onTheme: (preference: ThemePreference) => void;
}) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const dirty = JSON.stringify(value) !== JSON.stringify(saved);
  return (
    <div className="stg-section-stack">
      <form
        className="stg-card"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const next: Record<string, string> = {};
          if (
            value.projectName.trim().length < 3 ||
            value.projectName.trim().length > 60
          )
            next.projectName = "نام پروژه باید ۳ تا ۶۰ نویسه باشد.";
          if (
            value.teamName.trim().length < 2 ||
            value.teamName.trim().length > 60
          )
            next.teamName = "نام تیم باید ۲ تا ۶۰ نویسه باشد.";
          if (value.description.length > 240)
            next.description = "توضیح حداکثر ۲۴۰ نویسه است.";
          setErrors(next);
          if (!Object.keys(next).length) onSave();
        }}
      >
        <div className="stg-card-heading">
          <div>
            <Building2 size={18} />
            <div>
              <h2>اطلاعات پروژه</h2>
              <p>مشخصات پروژه در سناریوی تنظیمات</p>
            </div>
          </div>
          <span className="stg-tag">
            {dirty ? "تغییرات ذخیره‌نشده" : "ذخیره‌شده در نمونه"}
          </span>
        </div>
        <div className="stg-card-body">
          <div className="stg-form-grid">
            <label className="stg-field">
              نام نمایشی پروژه
              <input
                aria-label="نام پروژه"
                value={value.projectName}
                maxLength={60}
                aria-invalid={!!errors.projectName}
                onChange={(event) =>
                  onChange({ ...value, projectName: event.target.value })
                }
              />
              {errors.projectName && (
                <small className="stg-field-error">{errors.projectName}</small>
              )}
            </label>
            <label className="stg-field">
              نام تیم
              <input
                aria-label="نام تیم"
                value={value.teamName}
                maxLength={60}
                aria-invalid={!!errors.teamName}
                onChange={(event) =>
                  onChange({ ...value, teamName: event.target.value })
                }
              />
              {errors.teamName && (
                <small className="stg-field-error">{errors.teamName}</small>
              )}
            </label>
            <label className="stg-field">
              ناحیهٔ زمانی مرکز تنظیمات
              <select
                aria-label="ناحیه زمانی تنظیمات"
                value={value.timezone}
                onChange={(event) =>
                  onChange({
                    ...value,
                    timezone: event.target.value as GeneralValues["timezone"],
                  })
                }
              >
                <option value="Asia/Tehran">تهران · Asia/Tehran</option>
                <option value="UTC">UTC</option>
              </select>
              <small>نمایش زمان کلیدها، تحویل‌ها و تاریخچهٔ همین صفحه.</small>
            </label>
            <label className="stg-field">
              زبان و جهت پنل
              <input value="فارسی · راست‌به‌چپ" readOnly />
              <small>
                زبان فعلی پنل؛ سایر زبان‌ها در این نسخه فعال نیستند.
              </small>
            </label>
            <label className="stg-field stg-span-full">
              توضیح پروژه
              <textarea
                aria-label="توضیح پروژه"
                rows={3}
                value={value.description}
                maxLength={240}
                onChange={(event) =>
                  onChange({ ...value, description: event.target.value })
                }
              />
              {errors.description && (
                <small className="stg-field-error">{errors.description}</small>
              )}
            </label>
          </div>
        </div>
        <footer className="stg-card-actions">
          <button
            className="stg-primary-button"
            disabled={!dirty}
            type="submit"
          >
            <Save size={14} />
            ذخیرهٔ عمومی
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
            <Undo2 size={13} />
            برگرداندن تغییرات
          </button>
        </footer>
      </form>
      <section className="stg-card">
        <div className="stg-card-heading">
          <div>
            <Monitor size={18} />
            <div>
              <h2>ظاهر و تجربهٔ کاربری</h2>
              <p>انتخاب تم فوری است و با دکمهٔ هدر همگام می‌ماند.</p>
            </div>
          </div>
          <span className="stg-state active">ذخیره در مرورگر</span>
        </div>
        <div className="stg-card-body">
          <div
            className="stg-theme-options"
            role="group"
            aria-label="انتخاب تم پنل"
          >
            {[
              { id: "light", title: "روشن", icon: Sun },
              { id: "dark", title: "تیره", icon: Moon },
              { id: "system", title: "همراه سیستم", icon: Monitor },
            ].map((option) => (
              <button
                type="button"
                key={option.id}
                className={`stg-theme-option ${option.id}`}
                aria-pressed={preference === option.id}
                onClick={() => onTheme(option.id as ThemePreference)}
              >
                <span className="stg-theme-preview">
                  <i />
                  <i />
                  <i />
                </span>
                <span>
                  <option.icon size={15} />
                  {option.title}
                </span>
              </button>
            ))}
          </div>
          <p className="stg-help">
            تم فعلی: {theme === "dark" ? "تیره" : "روشن"} · اسکرول‌بار خطی و
            نازک · فونت فارسی محلی Vazirmatn
          </p>
        </div>
      </section>
      <section className="stg-card">
        <div className="stg-card-heading">
          <div>
            <Database size={18} />
            <div>
              <h2>مشخصات اتصال</h2>
              <p>اطلاعات معماری؛ اتصال یا احراز هویت از اینجا تغییر نمی‌کند.</p>
            </div>
          </div>
          <span className="stg-tag">خواندنی</span>
        </div>
        <dl className="stg-definition-list">
          <div>
            <dt>پایگاه دادهٔ پروژه</dt>
            <dd>
              <bdi>siem_db · MongoDB</bdi>
            </dd>
          </div>
          <div>
            <dt>مسیر REST API</dt>
            <dd>
              <bdi>/api/v1/</bdi>
            </dd>
          </div>
          <div>
            <dt>وضعیت این پنل</dt>
            <dd>ماک · بدون درخواست API</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
