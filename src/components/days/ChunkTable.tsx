import { Fragment, useState } from "react";
import { AlertCircle, ChevronDown, Check, Search, Layers3 } from "lucide-react";
import { dayStatusLabels, stages, normalizeSearch } from "../../data/days";
import {
  apiPath,
  type InventoryDay,
  type InventoryChunk,
  type ChunkPage,
  displayNumber as number,
  observationTime,
} from "../../api/days";
import { useApi, useDebounced } from "../../hooks/useApi";

export function chunkStages(chunk: InventoryChunk): (boolean | null)[] {
  return [
    chunk.normalization_complete,
    null,
    chunk.graph?.component_status === "complete" ? true : null,
    null,
    null,
  ];
}
export function ChunkTable({ day }: { day: InventoryDay }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const value = useDebounced(normalizeSearch(search));
  const match = /^(?:(?:chunk-|چانک\s*)?)(\d+)$/.exec(value);
  const searchError = Boolean(value && !match);
  const size = 4;
  const resource = useApi<ChunkPage>(
    searchError
      ? null
      : apiPath(`days/${day.day}/chunks/`, {
          limit: size,
          offset: page * size,
          status: status === "all" ? undefined : status,
          chunk_index: match ? Number(match[1]) : undefined,
        }),
  );
  const changed =
    resource.data && resource.data.snapshot_id !== day.snapshot_id;
  const visible = changed ? [] : (resource.data?.results ?? []);
  const count = Math.ceil((resource.data?.count ?? 0) / size);
  const message = searchError
    ? "شمارهٔ چانک را وارد کنید؛ شناسهٔ اجرا در این API گزارش نمی‌شود."
    : changed
      ? "اطلاعات روز تغییر کرده است؛ برای دریافت نسخهٔ جدید، روز را دوباره باز کنید."
      : (resource.error?.message ??
        (resource.loading
          ? "در حال دریافت چانک‌ها…"
          : "چانکی با این فیلتر پیدا نشد."));
  return (
    <div className="chunks-panel">
      <div className="chunk-toolbar">
        <div>
          <h3>
            چانک‌های روز <span>{number(day.observed_chunks)}</span>
          </h3>
          <p>چانک‌ها پارتیشن پردازش‌اند و معادل بازهٔ زمانی نیستند.</p>
        </div>
        <div className="table-controls">
          <label className="days-search">
            <Search size={15} />
            <input
              aria-label="جست‌وجوی چانک"
              placeholder="شمارهٔ چانک"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
                setExpanded(null);
              }}
            />
          </label>
          <select
            aria-label="وضعیت چانک"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(0);
              setExpanded(null);
            }}
          >
            <option value="all">همهٔ وضعیت‌ها</option>
            {Object.entries(dayStatusLabels).map(([value, label]) => (
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
              <th scope="col">ظرفیت رکورد خام</th>
              <th scope="col">وضعیت</th>
              <th scope="col">پیشرفت</th>
              <th scope="col">زمان سپری‌شده</th>
              <th scope="col">
                <span className="sr-only">جزئیات</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((chunk) => (
              <Fragment key={chunk.chunk_index}>
                <tr
                  className={
                    expanded === chunk.chunk_index ? "chunk-expanded" : ""
                  }
                  onClick={() =>
                    setExpanded(
                      expanded === chunk.chunk_index ? null : chunk.chunk_index,
                    )
                  }
                >
                  <th scope="row">
                    <button
                      className="chunk-name"
                      aria-expanded={expanded === chunk.chunk_index}
                      aria-controls={
                        expanded === chunk.chunk_index
                          ? `detail-${day.day}-${chunk.chunk_index}`
                          : undefined
                      }
                    >
                      <Layers3 size={16} />
                      <span>
                        چانک {number(chunk.chunk_index)}
                        <small dir="ltr">شناسهٔ اجرا گزارش نشده</small>
                      </span>
                    </button>
                  </th>
                  <td className="numeric-cell">
                    {number(chunk.expected_raw_records)}
                  </td>
                  <td>
                    <span className={`status-pill ${chunk.status}`}>
                      <i />
                      {dayStatusLabels[chunk.status]}
                    </span>
                  </td>
                  <td>
                    <div className="chunk-progress">
                      <span>—</span>
                      <progress
                        max={100}
                        value={0}
                        aria-label={`درصد پیشرفت چانک ${number(chunk.chunk_index)} گزارش نشده است`}
                      />
                    </div>
                  </td>
                  <td className="duration-cell">—</td>
                  <td>
                    <ChevronDown
                      size={16}
                      className={`row-chevron${expanded === chunk.chunk_index ? " open" : ""}`}
                    />
                  </td>
                </tr>
                {expanded === chunk.chunk_index && (
                  <tr>
                    <td colSpan={6} className="chunk-detail-cell">
                      <div
                        id={`detail-${day.day}-${chunk.chunk_index}`}
                        className="chunk-detail"
                      >
                        <div className="stage-list">
                          {stages.map((stage, index) => {
                            const ready = chunkStages(chunk)[index];
                            return (
                              <div
                                key={stage}
                                className={`stage-step ${ready ? "complete" : "pending"}`}
                              >
                                <span>
                                  {ready ? (
                                    <Check size={13} />
                                  ) : (
                                    number(index + 1)
                                  )}
                                </span>
                                <p>{stage}</p>
                                <small>
                                  {ready
                                    ? "تکمیل‌شده"
                                    : ready === false
                                      ? "ناقص"
                                      : "گزارش نشده"}
                                </small>
                              </div>
                            );
                          })}
                        </div>
                        <dl className="chunk-metrics">
                          {(
                            [
                              ["نرمال‌شده", chunk.normalized_records],
                              ["کاندید", chunk.candidate_records],
                              ["گره", chunk.graph?.nodes],
                              ["یال", chunk.graph?.edges],
                              ["مولفه", chunk.components],
                              ["نماینده", chunk.representatives],
                            ] as const
                          ).map(([label, value]) => (
                            <div key={label}>
                              <dt>{label}</dt>
                              <dd>{number(value)}</dd>
                            </div>
                          ))}
                        </dl>
                        {chunk.status === "attention" && (
                          <p className="chunk-error" role="note">
                            <AlertCircle size={16} />
                            اطلاعات ذخیره‌شدهٔ این چانک نیازمند بررسی است؛ این
                            وضعیت به معنی تشخیص حمله نیست.
                          </p>
                        )}
                        <p className="chunk-detail-note">
                          آخرین مشاهده: {observationTime(chunk.updated_at)} ·
                          وضعیت تکمیل مربوط به لایهٔ اول است؛ زمان، شناسهٔ اجرا
                          و درصد پیشرفت گزارش نشده‌اند.
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
                  <span role={resource.error || changed ? "alert" : "status"}>
                    {message}
                  </span>
                  {resource.error && (
                    <button
                      className="days-text-button"
                      onClick={resource.retry}
                    >
                      تلاش دوباره
                    </button>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="table-pagination">
        <span>
          {number(resource.data?.count)} چانک
          {count > 0 && ` · صفحهٔ ${number(page + 1)} از ${number(count)}`}
        </span>
        <div>
          <button
            aria-label="صفحهٔ قبلی چانک‌ها"
            disabled={page === 0 || resource.loading}
            onClick={() => {
              setPage(page - 1);
              setExpanded(null);
            }}
          >
            قبلی
          </button>
          <button
            aria-label="صفحهٔ بعدی چانک‌ها"
            disabled={page + 1 >= count || resource.loading || changed}
            onClick={() => {
              setPage(page + 1);
              setExpanded(null);
            }}
          >
            بعدی
          </button>
        </div>
      </div>
    </div>
  );
}
