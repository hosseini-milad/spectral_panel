import { Fragment, useState } from "react";
import { AlertCircle, ChevronDown, Check, Search, Layers3 } from "lucide-react";
import {
  type ProcessingDay,
  type ChunkStatus,
  chunkStatusLabels,
  normalizeSearch,
  number,
  stages,
} from "../../data/days";

export function ChunkTable({ day }: { day: ProcessingDay }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const filtered = day.chunks.filter(
    (chunk) =>
      (status === "all" || chunk.status === status) &&
      normalizeSearch(
        `chunk-${chunk.index} چانک ${chunk.index} ${chunk.runId ?? ""}`,
      ).includes(normalizeSearch(search)),
  );
  const size = 4;
  const count = Math.ceil(filtered.length / size);
  const visible = filtered.slice(page * size, (page + 1) * size);

  return (
    <div className="chunks-panel">
      <div className="chunk-toolbar">
        <div>
          <h3>
            چانک‌های روز <span>{number(day.chunks.length)}</span>
          </h3>
          <p>چانک‌ها پارتیشن پردازش‌اند و معادل بازهٔ زمانی نیستند.</p>
        </div>
        <div className="table-controls">
          <label className="days-search">
            <Search size={15} />
            <input
              aria-label="جست‌وجوی چانک"
              placeholder="شمارهٔ چانک یا شناسهٔ اجرا"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
            />
          </label>
          <select
            aria-label="وضعیت چانک"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(0);
            }}
          >
            <option value="all">همهٔ وضعیت‌ها</option>
            {Object.entries(chunkStatusLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div
        className="days-table-scroll"
        tabIndex={0}
        role="region"
        aria-label="جدول چانک‌ها"
      >
        <table className="chunks-table">
          <thead>
            <tr>
              <th scope="col">چانک / اجرا</th>
              <th scope="col">رکورد خام</th>
              <th scope="col">وضعیت</th>
              <th scope="col">پیشرفت نمونه</th>
              <th scope="col">زمان سپری‌شده</th>
              <th scope="col">
                <span className="sr-only">جزئیات</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((chunk) => (
              <Fragment key={chunk.id}>
                <tr
                  className={expanded === chunk.id ? "chunk-expanded" : ""}
                  onClick={() =>
                    setExpanded(expanded === chunk.id ? null : chunk.id)
                  }
                >
                  <th scope="row">
                    <button
                      className="chunk-name"
                      aria-expanded={expanded === chunk.id}
                      aria-controls={
                        expanded === chunk.id ? `detail-${chunk.id}` : undefined
                      }
                    >
                      <Layers3 size={16} />
                      <span>
                        چانک {number(chunk.index)}
                        <small dir="ltr">{chunk.runId ?? "بدون اجرا"}</small>
                      </span>
                    </button>
                  </th>
                  <td className="numeric-cell">{number(chunk.records)}</td>
                  <td>
                    <span className={`status-pill ${chunk.status}`}>
                      <i />
                      {chunkStatusLabels[chunk.status]}
                    </span>
                  </td>
                  <td>
                    <div className="chunk-progress">
                      <span>{number(chunk.progress)}٪</span>
                      <progress
                        value={chunk.progress}
                        max={100}
                        aria-label={`پیشرفت ماک چانک ${number(chunk.index)}`}
                      />
                    </div>
                  </td>
                  <td className="duration-cell">
                    {chunk.durationSeconds
                      ? `${number(Math.floor(chunk.durationSeconds / 60))} د ${number(chunk.durationSeconds % 60)} ث`
                      : "—"}
                  </td>
                  <td>
                    <ChevronDown
                      size={16}
                      className={`row-chevron${expanded === chunk.id ? " open" : ""}`}
                    />
                  </td>
                </tr>
                {expanded === chunk.id && (
                  <tr>
                    <td colSpan={6} className="chunk-detail-cell">
                      <div id={`detail-${chunk.id}`} className="chunk-detail">
                        <div className="stage-list">
                          {stages.map((stage, index) => {
                            const state: ChunkStatus =
                              index < chunk.completedStages
                                ? "complete"
                                : index === chunk.completedStages
                                  ? chunk.status
                                  : "pending";
                            return (
                              <div
                                key={stage}
                                className={`stage-step ${state}`}
                              >
                                <span>
                                  {state === "complete" ? (
                                    <Check size={13} />
                                  ) : (
                                    number(index + 1)
                                  )}
                                </span>
                                <p>{stage}</p>
                                <small>{chunkStatusLabels[state]}</small>
                              </div>
                            );
                          })}
                        </div>
                        <dl className="chunk-metrics">
                          {[
                            ["نرمال‌شده", chunk.normalized],
                            ["کاندید", chunk.candidates],
                            ["گره", chunk.nodes],
                            ["یال", chunk.edges],
                            ["مولفه", chunk.components],
                            ["نماینده", chunk.representatives],
                          ].map(([label, value]) => (
                            <div key={label}>
                              <dt>{label}</dt>
                              <dd>{number(Number(value))}</dd>
                            </div>
                          ))}
                        </dl>
                        {chunk.error && (
                          <p className="chunk-error" role="note">
                            <AlertCircle size={16} />
                            {chunk.error}
                          </p>
                        )}
                        <p className="chunk-detail-note">
                          آخرین به‌روزرسانی نمونه: {chunk.updatedAt} · مقادیر
                          صفر در مراحل اجرا‌نشده، به معنی خروجی محاسبه‌شده
                          نیستند.
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {!visible.length && (
              <tr>
                <td colSpan={6} className="table-empty">
                  چانکی با این فیلتر پیدا نشد.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="table-pagination">
        <span>
          {number(filtered.length)} چانک
          {count > 0 && ` · صفحهٔ ${number(page + 1)} از ${number(count)}`}
        </span>
        <div>
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            قبلی
          </button>
          <button
            disabled={page + 1 >= count}
            onClick={() => setPage(page + 1)}
          >
            بعدی
          </button>
        </div>
      </div>
    </div>
  );
}
