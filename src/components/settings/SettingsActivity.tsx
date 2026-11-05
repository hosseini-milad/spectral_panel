import { useState } from "react";
import { FileClock, Search } from "lucide-react";
import {
  categoryLabels,
  settingsTime,
  type SettingsAudit,
  type GeneralSettings,
} from "../../data/settings";
import { number, normalizeSearch } from "../../data/days";

export function SettingsActivity({
  entries,
  timezone,
}: {
  entries: SettingsAudit[];
  timezone: GeneralSettings["timezone"];
}) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [page, setPage] = useState(0);
  const filtered = entries.filter(
    (entry) =>
      (category === "all" || category === entry.category) &&
      normalizeSearch(`${entry.action} ${entry.target}`).includes(
        normalizeSearch(search),
      ),
  );
  const size = 8,
    pages = Math.ceil(filtered.length / size);
  return (
    <section className="stg-card">
      <div className="stg-card-heading">
        <div>
          <FileClock size={18} />
          <div>
            <h2>تاریخچهٔ تغییرات تنظیمات</h2>
            <p>رویدادهای نمونه و همین بازدید؛ لاگ ممیزی سرور نیست.</p>
          </div>
        </div>
        <span className="stg-tag">{number(entries.length)} رویداد</span>
      </div>
      <div className="stg-table-toolbar">
        <label className="stg-search">
          <Search size={15} />
          <input
            aria-label="جست‌وجوی تاریخچه"
            placeholder="عملیات یا شناسهٔ منبع…"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
        </label>
        <select
          aria-label="دستهٔ تاریخچه"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
            setPage(0);
          }}
        >
          <option value="all">همهٔ دسته‌ها</option>
          {Object.entries(categoryLabels).map(([key, label]) => (
            <option value={key} key={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div
        className="stg-table-scroll"
        tabIndex={0}
        role="region"
        aria-label="تاریخچهٔ تنظیمات"
      >
        <table>
          <thead>
            <tr>
              {["زمان", "عملیات", "منبع", "انجام‌دهنده", "وضعیت"].map(
                (label) => (
                  <th key={label} scope="col">
                    {label}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.slice(page * size, (page + 1) * size).map((entry) => (
              <tr key={entry.id}>
                <td>{settingsTime(entry.time, timezone)}</td>
                <td>
                  {entry.action}
                  <small>{categoryLabels[entry.category]}</small>
                </td>
                <td>
                  <bdi>{entry.target}</bdi>
                </td>
                <td>مدیر نمایشی</td>
                <td>
                  <span
                    className={`stg-state ${entry.outcome === "failed" ? "warning" : "active"}`}
                  >
                    {entry.outcome === "saved"
                      ? "ثبت محلی"
                      : entry.outcome === "simulated"
                        ? "شبیه‌سازی"
                        : "خطای نمونه"}
                  </span>
                </td>
              </tr>
            ))}
            {!filtered.length && (
              <tr>
                <td colSpan={5} className="stg-table-empty">
                  رویدادی با این فیلتر پیدا نشد.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="stg-pagination">
        <span>
          {number(filtered.length)} مورد
          {pages > 0 && ` · صفحهٔ ${number(page + 1)} از ${number(pages)}`}
        </span>
        <div>
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            قبلی
          </button>
          <button
            disabled={page + 1 >= pages}
            onClick={() => setPage(page + 1)}
          >
            بعدی
          </button>
        </div>
      </div>
      <p className="stg-help stg-help-padded">
        کلید خام، امضای واقعی یا نشانی کامل وب‌هوک در تاریخچه ذخیره نمی‌شود.
      </p>
    </section>
  );
}
