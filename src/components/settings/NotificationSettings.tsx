import { useState, type Dispatch, type SetStateAction } from "react";
import { Bell, Mail, Save, Eye } from "lucide-react";
import type { NotificationSettings as NotificationValues } from "../../data/settings";
import { SettingSwitch } from "./SettingsShared";

export function NotificationSettings({
  value,
  saved,
  onChange,
  onSave,
  onPreview,
}: {
  value: NotificationValues;
  saved: NotificationValues;
  onChange: Dispatch<SetStateAction<NotificationValues>>;
  onSave: () => void;
  onPreview: () => void;
}) {
  const [error, setError] = useState("");
  const dirty = JSON.stringify(value) !== JSON.stringify(saved);
  return (
    <form
      className="stg-card"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (
          value.emailEnabled &&
          !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.email.trim())
        ) {
          setError("یک نشانی ایمیل معتبر وارد کنید.");
          return;
        }
        setError("");
        onSave();
      }}
    >
      <div className="stg-card-heading">
        <div>
          <Bell size={18} />
          <div>
            <h2>ترجیحات اعلان</h2>
            <p>تنظیم کانال و رویداد؛ ایمیل یا اعلان واقعی ارسال نمی‌شود.</p>
          </div>
        </div>
        <span className="stg-tag">ماک</span>
      </div>
      <div className="stg-card-body">
        <div className="stg-setting-rows">
          {[
            {
              key: "inAppEnabled",
              title: "اعلان داخل پنل",
              detail: "نمایش نمونهٔ رویدادها در رابط کاربری.",
            },
            {
              key: "emailEnabled",
              title: "اعلان ایمیلی",
              detail: "فقط پیش‌نمایش؛ سرویس ارسال ایمیل متصل نیست.",
            },
          ].map((item) => (
            <div key={item.key}>
              <div>
                <h3>{item.title}</h3>
                <p>{item.detail}</p>
              </div>
              <SettingSwitch
                label={item.title}
                checked={value[item.key as "inAppEnabled" | "emailEnabled"]}
                onChange={(checked) =>
                  onChange({ ...value, [item.key]: checked })
                }
              />
            </div>
          ))}
        </div>
        <label className="stg-field stg-email-field">
          ایمیل دریافت‌کننده
          <div className="stg-input-icon">
            <Mail size={15} />
            <input
              type="email"
              dir="ltr"
              aria-label="ایمیل اعلان"
              value={value.email}
              placeholder="alerts@example.com"
              disabled={!value.emailEnabled}
              aria-invalid={!!error}
              onChange={(event) => {
                setError("");
                onChange({ ...value, email: event.target.value });
              }}
            />
          </div>
          {error && (
            <small className="stg-field-error" role="alert">
              {error}
            </small>
          )}
        </label>
        <fieldset className="stg-checkbox-group">
          <legend>رویدادهای مورد علاقه</legend>
          {[
            { key: "jobFailures", label: "خطای پردازش" },
            { key: "jobSuccesses", label: "تکمیل موفق عملیات" },
            { key: "modelUpdates", label: "نسخهٔ جدید مدل" },
            { key: "dailySummary", label: "خلاصهٔ روزانه" },
          ].map((item) => (
            <label key={item.key}>
              <input
                type="checkbox"
                checked={
                  value[
                    item.key as
                      | "jobFailures"
                      | "jobSuccesses"
                      | "modelUpdates"
                      | "dailySummary"
                  ]
                }
                onChange={(event) =>
                  onChange({ ...value, [item.key]: event.target.checked })
                }
              />
              {item.label}
            </label>
          ))}
        </fieldset>
      </div>
      <footer className="stg-card-actions">
        <button className="stg-primary-button" disabled={!dirty} type="submit">
          <Save size={14} />
          ذخیرهٔ اعلان‌ها
        </button>
        <button
          className="stg-secondary-button"
          type="button"
          onClick={onPreview}
        >
          <Eye size={14} />
          پیش‌نمایش اعلان
        </button>
        <button
          className="stg-text-button"
          type="button"
          disabled={!dirty}
          onClick={() => {
            onChange({ ...saved });
            setError("");
          }}
        >
          برگرداندن تغییرات
        </button>
      </footer>
    </form>
  );
}
