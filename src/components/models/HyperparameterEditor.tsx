import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  Download,
  Save,
  RotateCcw,
  Copy,
  LockKeyhole,
  Info,
  SlidersHorizontal,
  ArrowUpLeft,
} from "lucide-react";
import { Link } from "react-router-dom";
import { mockDays, dateLabel, number } from "../../data/days";
import {
  availableGraphChunks,
  defaultNumericParameters,
  downloadModelJSON,
  familyLabels,
  numericFields,
  previewRequest,
  scorePolicies,
  validateModelEditor,
  type ModelConfig,
  type ModelEditor,
  type ModelErrors,
  type ModelFamily,
} from "../../data/models";

export function HyperparameterEditor({
  editor,
  setEditor,
  onLoadSelected,
  onSave,
}: {
  editor: ModelEditor;
  setEditor: Dispatch<SetStateAction<ModelEditor>>;
  onLoadSelected: () => void;
  onSave: (config: ModelConfig) => void;
}) {
  const [errors, setErrors] = useState<ModelErrors>({});
  const [message, setMessage] = useState("");
  const form = useRef<HTMLFormElement>(null);
  const isReference = editor.family === "normal-reference";
  function validate(action: "save" | "download") {
    const result = validateModelEditor(editor);
    setErrors(result.errors);
    setMessage("");
    if (!result.config) {
      requestAnimationFrame(() =>
        form.current
          ?.querySelector<HTMLElement>('[aria-invalid="true"]')
          ?.focus(),
      );
      return;
    }
    if (action === "save") onSave(result.config);
    else {
      downloadModelJSON(`mock-training-config-${editor.day}.json`, {
        mock: true,
        executed: false,
        parameter_source_model: editor.baseId,
        config: result.config,
        request_preview: previewRequest(result.config),
      });
      setMessage("تنظیمات ماک دانلود شد؛ هیچ درخواست آموزشی ارسال نشده است.");
    }
  }
  function changeFamily(value: ModelFamily) {
    setErrors({});
    setMessage("");
    setEditor((previous) => ({
      ...previous,
      family: value,
      fields:
        value === "normal-reference"
          ? {
              ...previous.fields,
              structure_weight: ".1",
              weight_loss_weight: ".05",
            }
          : previous.fields,
    }));
  }
  const groups = [
    {
      key: "architecture",
      title: "معماری انکدر",
      description: "ابعاد و عمق شبکه؛ گونهٔ نمایش، پارامتر آموزش نیست.",
    },
    {
      key: "training",
      title: "بودجه و تکرارپذیری آموزش",
      description: "محدوده‌های معتبر با قرارداد فعلی پروژه هماهنگ‌اند.",
    },
    {
      key: "loss",
      title: "وزن‌های تابع هدف",
      description: isReference
        ? "در مسیر مرجع رفتار، این وزن‌ها ثابت‌اند."
        : "تعادل بازسازی ویژگی، ساختار و وزن یال.",
    },
  ];
  return (
    <form
      className="mdl-editor"
      ref={form}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        validate("save");
      }}
    >
      <div className="mdl-card mdl-editor-context">
        <div>
          <SlidersHorizontal size={18} />
          <div>
            <h2>پیش‌نویس آموزش جدید</h2>
            <p>
              نسخهٔ ثبت‌شده تغییر نمی‌کند؛ فقط تنظیمات یک اجرای جدید را آماده
              می‌کنید.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="mdl-secondary-button"
          onClick={() => {
            onLoadSelected();
            setErrors({});
            setMessage("تنظیمات مدل انتخاب‌شده در پیش‌نویس کپی شد.");
          }}
        >
          <Copy size={14} />
          از مدل انتخاب‌شده
        </button>
        <div className="mdl-editor-base">
          منبع تنظیمات: <bdi>{editor.baseId}</bdi>
          <span>کپی پارامترها؛ بدون انتقال یا آموزش وزن‌ها</span>
        </div>
      </div>
      {Object.keys(errors).length > 0 && (
        <div className="mdl-validation-summary" role="alert">
          {number(Object.keys(errors).length)} مورد نیازمند اصلاح است. فیلدهای
          مشخص‌شده را بررسی کنید.
        </div>
      )}
      <section className="mdl-card mdl-form-section">
        <h3>نوع اجرا و دادهٔ ورودی</h3>
        <div className="mdl-form-grid">
          <label className="mdl-field">
            مسیر آموزش
            <select
              value={editor.family}
              aria-label="مسیر آموزش مدل"
              onChange={(event) =>
                changeFamily(event.target.value as ModelFamily)
              }
            >
              {Object.entries(familyLabels).map(([key, label]) => (
                <option value={key} key={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="mdl-field">
            {isReference ? "روز مرجع نرمال" : "روز آموزش"}
            <select
              aria-label="روز آموزش مدل"
              aria-invalid={!!errors.day}
              aria-describedby={
                errors.day ? "model-day-error" : "model-graphs-hint"
              }
              value={editor.day}
              onChange={(event) => {
                const day = event.target.value;
                setErrors({});
                setEditor((previous) => ({
                  ...previous,
                  day,
                  evaluateDays: previous.evaluateDays.filter(
                    (value) => value !== day,
                  ),
                }));
              }}
            >
              {mockDays.map((day) => (
                <option value={day.date} key={day.date}>
                  {dateLabel(day.date)}
                </option>
              ))}
            </select>
            <small id="model-graphs-hint">
              {number(availableGraphChunks(editor.day).length)} گراف چانک آماده
              در نمونه؛ حداقل {isReference ? "۴" : "۳"} لازم است.
            </small>
            {errors.day && (
              <span id="model-day-error" className="mdl-field-error">
                {errors.day}
              </span>
            )}
          </label>
        </div>
        {isReference && (
          <fieldset
            className="mdl-evaluation-days"
            aria-invalid={!!errors.evaluate_days}
            tabIndex={-1}
          >
            <legend>روزهای ارزیابی مستقل</legend>
            <div>
              {mockDays.map((day) => (
                <label key={day.date}>
                  <input
                    type="checkbox"
                    checked={editor.evaluateDays.includes(day.date)}
                    disabled={day.date === editor.day}
                    aria-label={`ارزیابی ${day.date}`}
                    onChange={(event) => {
                      const checked = event.target.checked;
                      setErrors({});
                      setEditor((previous) => ({
                        ...previous,
                        evaluateDays: checked
                          ? [...previous.evaluateDays, day.date]
                          : previous.evaluateDays.filter(
                              (value) => value !== day.date,
                            ),
                      }));
                    }}
                  />
                  {dateLabel(day.date)}
                </label>
              ))}
            </div>
            {errors.evaluate_days && (
              <p className="mdl-field-error">{errors.evaluate_days}</p>
            )}
            <small>
              روز آموزش نمی‌تواند روز ارزیابی باشد؛ استقلال واقعی شناسه‌ها باید
              هنگام اتصال بک‌اند بررسی شود.
            </small>
          </fieldset>
        )}
      </section>
      {groups.map((group) => (
        <section className="mdl-card mdl-form-section" key={group.key}>
          <div className="mdl-form-section-heading">
            <h3>{group.title}</h3>
            <span>{group.description}</span>
          </div>
          <div className="mdl-form-grid">
            {numericFields
              .filter((field) => field.group === group.key)
              .map((field) => {
                const fixed = isReference && field.group === "loss";
                return (
                  <label
                    className="mdl-field"
                    key={field.key}
                    htmlFor={`hp-${field.key}`}
                  >
                    <span>
                      {field.label}
                      {fixed && <LockKeyhole size={11} />}
                    </span>
                    <div className="mdl-number-input">
                      <input
                        id={`hp-${field.key}`}
                        name={field.key}
                        type="number"
                        inputMode={field.step === 1 ? "numeric" : "decimal"}
                        min={field.min}
                        max={field.max}
                        step={field.step}
                        value={editor.fields[field.key]}
                        readOnly={fixed}
                        aria-invalid={!!errors[field.key]}
                        aria-describedby={`hint-${field.key}${errors[field.key] ? ` error-${field.key}` : ""}`}
                        onChange={(event) => {
                          const value = event.target.value;
                          setErrors({});
                          setEditor((previous) => ({
                            ...previous,
                            fields: { ...previous.fields, [field.key]: value },
                          }));
                        }}
                      />
                      <code>{field.key}</code>
                    </div>
                    <small id={`hint-${field.key}`}>{field.hint}</small>
                    {errors[field.key] && (
                      <span
                        className="mdl-field-error"
                        id={`error-${field.key}`}
                      >
                        {errors[field.key]}
                      </span>
                    )}
                  </label>
                );
              })}
          </div>
        </section>
      ))}
      {isReference && (
        <section className="mdl-card mdl-form-section">
          <h3>کالیبراسیون رفتار</h3>
          <div className="mdl-form-grid">
            <label className="mdl-field" htmlFor="hp-alpha">
              سهم اسمی دُم بالایی (α)
              <div className="mdl-number-input">
                <input
                  id="hp-alpha"
                  name="alpha"
                  type="number"
                  step=".001"
                  min="0"
                  max="1"
                  value={editor.fields.alpha}
                  aria-invalid={!!errors.alpha}
                  aria-describedby={`hint-alpha${errors.alpha ? " error-alpha" : ""}`}
                  onChange={(event) => {
                    const value = event.target.value;
                    setErrors({});
                    setEditor((previous) => ({
                      ...previous,
                      fields: { ...previous.fields, alpha: value },
                    }));
                  }}
                />
                <code>alpha</code>
              </div>
              <small id="hint-alpha">
                بزرگ‌تر از صفر و کوچک‌تر از یک؛ تضمین FPR عملیاتی نیست.
              </small>
              {errors.alpha && (
                <span id="error-alpha" className="mdl-field-error">
                  {errors.alpha}
                </span>
              )}
            </label>
            <label className="mdl-field">
              سیاست امتیازدهی
              <select
                aria-label="سیاست امتیازدهی رفتار"
                dir="ltr"
                value={editor.policy}
                onChange={(event) =>
                  setEditor((previous) => ({
                    ...previous,
                    policy: event.target.value as ModelEditor["policy"],
                  }))
                }
              >
                {scorePolicies.map((policy) => (
                  <option key={policy} value={policy}>
                    {policy}
                  </option>
                ))}
              </select>
              <small>آستانه پس از کالیبراسیون مستقل تعیین می‌شود.</small>
            </label>
          </div>
        </section>
      )}
      <section className="mdl-card mdl-fixed-settings">
        <h3>
          <LockKeyhole size={14} />
          تنظیمات ثابت پیاده‌سازی فعلی
        </h3>
        <dl>
          {[
            ["Optimizer", "Adam"],
            ["Learning rate", "0.001"],
            ["Weight decay", "0.0001"],
            ["Gradient clip", "5"],
            ["Feature mask", "20%"],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <p>
          این مقادیر در مسیر فعلی پروژه قابل تنظیم از فرم اجرا نیستند و به
          درخواست ارسال نمی‌شوند.
        </p>
      </section>
      <div className="mdl-editor-actions">
        <button type="submit" className="mdl-primary-button">
          <Save size={15} />
          ثبت پیش‌نویس نسخه
        </button>
        <button
          type="button"
          className="mdl-secondary-button"
          onClick={() => validate("download")}
        >
          <Download size={14} />
          دریافت تنظیمات JSON
        </button>
        <button
          type="button"
          className="mdl-text-button"
          onClick={() => {
            setErrors({});
            setMessage("مقادیر عددی به پیش‌فرض پروژه برگشتند.");
            setEditor((previous) => ({
              ...previous,
              fields: Object.fromEntries(
                numericFields.map((field) => [
                  field.key,
                  String(defaultNumericParameters[field.key]),
                ]),
              ) as ModelEditor["fields"],
            }));
          }}
        >
          <RotateCcw size={13} />
          پیش‌فرض پروژه
        </button>
      </div>
      <p className="mdl-editor-feedback" role="status">
        {message ||
          "پیش‌نویس‌ها فقط در حافظهٔ همین صفحه‌اند؛ برای نگهداری، JSON را دانلود کنید. هیچ آموزش یا بازسازی واقعی اجرا نمی‌شود."}
      </p>
      <div className="mdl-form-footnote">
        <Info size={14} />
        <p>
          هر اجرای اصلی هر سه گونهٔ feature، graph و spectral را می‌سازد؛ انتخاب
          گونه در صفحهٔ مدل فقط برای مشاهدهٔ نتیجه است.
        </p>
        <Link to={`/operations?day=${editor.day}`}>
          آماده‌سازی داده
          <ArrowUpLeft size={13} />
        </Link>
      </div>
    </form>
  );
}
