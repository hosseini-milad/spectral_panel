import { useState } from "react";
import {
  keyScopes,
  keyKindLabels,
  webhookEvents,
  validateWebhookURL,
  type KeyKind,
  type MockAccessKey,
  type MockWebhook,
} from "../../data/settings";
export function KeyForm({
  onSave,
}: {
  onSave: (name: string, kind: KeyKind, scopes: string[], days: number) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<KeyKind>("api");
  const [scopes, setScopes] = useState<string[]>(["data:read"]);
  const [days, setDays] = useState(90);
  const [error, setError] = useState("");
  return (
    <form
      className="stg-modal-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim().length < 3 || (kind !== "signing" && !scopes.length)) {
          setError("نام حداقل سه نویسه و دست‌کم یک دسترسی لازم است.");
          return;
        }
        onSave(
          name.trim(),
          kind,
          kind === "signing" ? ["webhooks:sign"] : scopes,
          days,
        );
      }}
    >
      <p>کلید تولیدشده جعلی و غیرقابل استفاده است. هیچ رمز واقعی وارد نکنید.</p>
      <label className="stg-field">
        نام کلید
        <input
          aria-label="نام کلید"
          maxLength={60}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label className="stg-field">
        نوع کلید
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as KeyKind)}
        >
          {Object.entries(keyKindLabels).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="stg-checkbox-group">
        <legend>سطح دسترسی</legend>
        {kind === "signing" ? (
          <p>فقط امضای وب‌هوک</p>
        ) : (
          keyScopes.map((scope) => (
            <label key={scope.id}>
              <input
                type="checkbox"
                checked={scopes.includes(scope.id)}
                onChange={(e) =>
                  setScopes(
                    e.target.checked
                      ? [...scopes, scope.id]
                      : scopes.filter((s) => s !== scope.id),
                  )
                }
              />
              {scope.label}
            </label>
          ))
        )}
      </fieldset>
      <label className="stg-field">
        اعتبار
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((n) => (
            <option key={n} value={n}>
              {n} روز
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert" className="stg-field-error">
          {error}
        </p>
      )}
      <button className="stg-primary-button">ساخت کلید ماک</button>
    </form>
  );
}
export function TokenView({ token }: { token: string }) {
  const [show, setShow] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <div className="stg-modal-form">
      <p>
        این مقدار جعلی فقط همین بار نمایش داده می‌شود. پس از بستن پنجره، تنها
        چهار نویسهٔ آخر باقی می‌ماند.
      </p>
      <input
        aria-label="کلید نمایشی"
        dir="ltr"
        type={show ? "text" : "password"}
        value={token}
        readOnly
        autoComplete="off"
      />
      <div className="stg-modal-actions">
        <button className="stg-secondary-button" onClick={() => setShow(!show)}>
          {show ? "پنهان کردن" : "نمایش کلید"}
        </button>
        <button
          className="stg-primary-button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(token);
              setMessage("کلید جعلی کپی شد.");
            } catch {
              setMessage("کپی خودکار در این مرورگر در دسترس نیست.");
            }
          }}
        >
          کپی کلید
        </button>
      </div>
      <p role="status">{message}</p>
    </div>
  );
}
export function WebhookForm({
  initial,
  keys,
  onSave,
}: {
  initial?: MockWebhook;
  keys: MockAccessKey[];
  onSave: (value: Omit<MockWebhook, "id" | "version">) => void;
}) {
  const signers = keys.filter(
    (k) => k.kind === "signing" && k.status === "active",
  );
  const [value, setValue] = useState<Omit<MockWebhook, "id" | "version">>(
    initial
      ? { ...initial }
      : {
          name: "",
          url: "",
          events: ["job.failed"],
          signingKeyId: signers[0]?.id ?? "",
          enabled: true,
          timeoutSeconds: 10,
          retries: 3,
        },
  );
  const [error, setError] = useState("");
  return (
    <form
      className="stg-modal-form"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        const issue =
          validateWebhookURL(value.url.trim()) ||
          (value.name.trim().length < 3
            ? "نام حداقل سه نویسه لازم است."
            : "") ||
          (!value.events.length ? "حداقل یک رویداد انتخاب کنید." : "") ||
          (!signers.some((k) => k.id === value.signingKeyId)
            ? "یک کلید امضای فعال لازم است."
            : "") ||
          (!Number.isInteger(value.timeoutSeconds) ||
          value.timeoutSeconds < 1 ||
          value.timeoutSeconds > 60
            ? "مهلت باید عدد صحیح بین ۱ تا ۶۰ باشد."
            : "") ||
          (!Number.isInteger(value.retries) ||
          value.retries < 0 ||
          value.retries > 10
            ? "تلاش مجدد باید عدد صحیح بین ۰ تا ۱۰ باشد."
            : "");
        setError(issue);
        if (!issue)
          onSave({ ...value, name: value.name.trim(), url: value.url.trim() });
      }}
    >
      <p>
        فقط پیکربندی ماک. از نشانی نمونه و بدون اطلاعات محرمانه استفاده کنید.
      </p>
      <label className="stg-field">
        نام وب‌هوک
        <input
          aria-label="نام وب‌هوک"
          value={value.name}
          maxLength={60}
          onChange={(e) => setValue({ ...value, name: e.target.value })}
        />
      </label>
      <label className="stg-field">
        نشانی HTTPS
        <input
          aria-label="نشانی وب‌هوک"
          dir="ltr"
          placeholder="https://hooks.example.com/events"
          value={value.url}
          onChange={(e) => setValue({ ...value, url: e.target.value })}
        />
      </label>
      <fieldset className="stg-checkbox-group">
        <legend>رویدادهای پیشنهادی API</legend>
        {webhookEvents.map((event) => (
          <label key={event.id}>
            <input
              type="checkbox"
              checked={value.events.includes(event.id)}
              onChange={(e) =>
                setValue({
                  ...value,
                  events: e.target.checked
                    ? [...value.events, event.id]
                    : value.events.filter((id) => id !== event.id),
                })
              }
            />
            {event.label}
          </label>
        ))}
      </fieldset>
      <label className="stg-field">
        کلید امضا
        <select
          aria-label="کلید امضا"
          value={value.signingKeyId}
          onChange={(e) => setValue({ ...value, signingKeyId: e.target.value })}
        >
          <option value="">انتخاب کلید فعال</option>
          {signers.map((k) => (
            <option key={k.id} value={k.id}>
              {k.name}
            </option>
          ))}
        </select>
      </label>
      <div className="stg-form-grid">
        <label className="stg-field">
          مهلت پاسخ (ثانیه)
          <input
            type="number"
            value={
              Number.isNaN(value.timeoutSeconds) ? "" : value.timeoutSeconds
            }
            onChange={(e) =>
              setValue({
                ...value,
                timeoutSeconds:
                  e.target.value === "" ? NaN : Number(e.target.value),
              })
            }
          />
        </label>
        <label className="stg-field">
          تلاش مجدد
          <input
            type="number"
            value={Number.isNaN(value.retries) ? "" : value.retries}
            onChange={(e) =>
              setValue({
                ...value,
                retries: e.target.value === "" ? NaN : Number(e.target.value),
              })
            }
          />
        </label>
      </div>
      <label className="stg-ack">
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => setValue({ ...value, enabled: e.target.checked })}
        />
        فعال در سناریو
      </label>
      {error && (
        <p className="stg-field-error" role="alert">
          {error}
        </p>
      )}
      <button className="stg-primary-button">ذخیرهٔ وب‌هوک</button>
    </form>
  );
}
export function WebhookTest({
  hook,
  onRun,
}: {
  hook: MockWebhook;
  onRun: (
    event: MockWebhook["events"][number],
    outcome: "success" | "failure" | "timeout",
  ) => void;
}) {
  const [event, setEvent] = useState(hook.events[0]);
  const [outcome, setOutcome] = useState<"success" | "failure" | "timeout">(
    "success",
  );
  return (
    <div className="stg-modal-form">
      <p>
        بدون درخواست شبکه؛ یک تلاش فرضی ثبت می‌شود. سیاست تلاش مجدد اجرا
        نمی‌شود.
      </p>
      <label className="stg-field">
        رویداد
        <select
          value={event}
          onChange={(e) => setEvent(e.target.value as typeof event)}
        >
          {hook.events.map((id) => (
            <option key={id}>{id}</option>
          ))}
        </select>
      </label>
      <label className="stg-field">
        پاسخ فرضی
        <select
          aria-label="پاسخ فرضی"
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as typeof outcome)}
        >
          <option value="success">موفق · HTTP 200</option>
          <option value="failure">خطا · HTTP 500</option>
          <option value="timeout">پایان مهلت پاسخ</option>
        </select>
      </label>
      <pre dir="ltr">
        {JSON.stringify(
          {
            mock: true,
            event,
            run_id: "mock-run-001",
            signature: "MOCK_SIGNATURE_NOT_VALID",
          },
          null,
          2,
        )}
      </pre>
      <button
        className="stg-primary-button"
        onClick={() => onRun(event, outcome)}
      >
        ثبت نتیجهٔ شبیه‌سازی
      </button>
    </div>
  );
}
