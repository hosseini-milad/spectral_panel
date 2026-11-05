import { useState } from "react";
import { Search, Boxes, ArrowUpLeft } from "lucide-react";
import { dateLabel, number, normalizeSearch } from "../../data/days";
import {
  familyLabels,
  modelStatusLabels,
  type ModelRun,
} from "../../data/models";

export function ModelRegistry({
  runs,
  selectedId,
  onSelect,
}: {
  runs: ModelRun[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(0);
  const filtered = runs.filter(
    (run) =>
      (status === "all" || run.status === status) &&
      normalizeSearch(
        `${run.id} ${run.version} ${run.title} ${run.config.day} ${dateLabel(run.config.day)}`,
      ).includes(normalizeSearch(search)),
  );
  const pageSize = 5,
    pages = Math.ceil(filtered.length / pageSize);
  return (
    <section className="mdl-card mdl-registry" aria-labelledby="registry-title">
      <div className="mdl-section-heading">
        <div>
          <Boxes size={18} />
          <div>
            <h2 id="registry-title">فهرست نسخه‌های مدل</h2>
            <p>
              انتخاب نسخه فقط نمای صفحه را تغییر می‌دهد؛ استقرار یا فعال‌سازی
              انجام نمی‌شود.
            </p>
          </div>
        </div>
        <span className="mdl-count-badge">
          {number(runs.length)} نسخهٔ نمونه
        </span>
      </div>
      <div className="mdl-registry-toolbar">
        <label className="mdl-registry-search">
          <Search size={15} />
          <input
            aria-label="جست‌وجوی نسخه مدل"
            value={search}
            placeholder="نام، نسخه، روز یا شناسهٔ مدل…"
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
        </label>
        <select
          aria-label="وضعیت نسخه مدل"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(0);
          }}
        >
          <option value="all">همهٔ وضعیت‌ها</option>
          {Object.entries(modelStatusLabels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div
        className="mdl-table-scroll"
        role="region"
        aria-label="جدول نسخه‌های مدل"
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              {[
                "نسخه و مدل",
                "مسیر آموزش",
                "روز آموزش",
                "پیکربندی",
                "وضعیت",
                "مشاهده",
              ].map((label) => (
                <th scope="col" key={label}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered
              .slice(page * pageSize, (page + 1) * pageSize)
              .map((run) => (
                <tr
                  key={run.id}
                  className={selectedId === run.id ? "mdl-selected-row" : ""}
                >
                  <th scope="row">
                    <span className="mdl-registry-title">
                      <bdi>{run.version}</bdi>
                      {run.title}
                    </span>
                    <small dir="ltr">{run.id}</small>
                  </th>
                  <td>{familyLabels[run.config.family]}</td>
                  <td>{dateLabel(run.config.day)}</td>
                  <td>
                    <span>{number(run.config.epochs)} دوره</span>
                    <small>
                      Hidden {number(run.config.hidden_dim)} · Latent{" "}
                      {number(run.config.latent_dim)}
                    </small>
                  </td>
                  <td>
                    <span className={`mdl-state ${run.status}`}>
                      {modelStatusLabels[run.status]}
                    </span>
                  </td>
                  <td>
                    <button
                      className="mdl-text-button"
                      aria-label={`نمایش مدل ${run.version}`}
                      aria-current={selectedId === run.id ? "true" : undefined}
                      onClick={() => onSelect(run.id)}
                    >
                      {selectedId === run.id ? "انتخاب‌شده" : "جزئیات"}
                      <ArrowUpLeft size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            {!filtered.length && (
              <tr>
                <td colSpan={6} className="mdl-registry-empty">
                  نسخه‌ای با این فیلتر پیدا نشد.
                  <button
                    className="mdl-text-button"
                    onClick={() => {
                      setSearch("");
                      setStatus("all");
                      setPage(0);
                    }}
                  >
                    پاک‌کردن فیلترها
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mdl-table-pagination">
        <span>
          {number(filtered.length)} نسخه
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
    </section>
  );
}
