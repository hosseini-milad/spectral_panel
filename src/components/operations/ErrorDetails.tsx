import { eventMessage, type OperationError } from "../../api/operations";
import { number } from "../../data/days";
const resources: Record<string, string> = {
  normalized_records: "رکورد نرمال‌شده",
  candidate_records: "کاندید",
  representatives: "نماینده",
  graphs: "گراف",
  components: "مولفه",
};
export function ErrorDetails({ error }: { error: OperationError }) {
  const c = error.context;
  return (
    <details className="op-error-details">
      <summary>{error.message || eventMessage(error.code)}</summary>
      <div className="op-error-explanation">
        <p>
          {error.suggestion ||
            "برای این خطای قدیمی جزئیات بیشتری ثبت نشده است؛ لاگ داخلی worker را با روز، شناسهٔ اجرا و چانک بررسی کنید."}
        </p>
        <dl>
          {c?.resource && (
            <div>
              <dt>خروجی مورد بررسی</dt>
              <dd>{resources[c.resource] ?? c.resource}</dd>
            </div>
          )}
          {c?.expected_count !== undefined && (
            <div>
              <dt>تعداد مورد انتظار</dt>
              <dd>{number(c.expected_count)}</dd>
            </div>
          )}
          {c?.actual_count !== undefined && (
            <div>
              <dt>تعداد ثبت‌شده</dt>
              <dd>{number(c.actual_count)}</dd>
            </div>
          )}
          {c?.timeout_seconds !== undefined && (
            <div>
              <dt>مهلت مرحله (ثانیه)</dt>
              <dd>{number(c.timeout_seconds)}</dd>
            </div>
          )}
          {c?.exit_code !== undefined && (
            <div>
              <dt>کد خروج فرایند</dt>
              <dd>{number(c.exit_code)}</dd>
            </div>
          )}
          <div>
            <dt>کد علت</dt>
            <dd>
              <bdi>{error.reason_code || error.code}</bdi>
            </dd>
          </div>
          {error.diagnostic_id && (
            <div>
              <dt>شناسهٔ پیگیری در لاگ سرور</dt>
              <dd>
                <bdi>{error.diagnostic_id}</bdi>
              </dd>
            </div>
          )}
        </dl>
      </div>
    </details>
  );
}
