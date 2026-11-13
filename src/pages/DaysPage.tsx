import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  isISODate,
  inspectionPath,
  parseChunkIndex,
} from "../lib/dayNavigation";
import {
  CalendarDays,
  Database,
  Layers3,
  CircleCheck,
  Search,
  ChevronDown,
  FlaskConical,
  ArrowUpLeft,
  CalendarSearch,
  FileText,
  Info,
} from "lucide-react";
import { dateLabel, dayStatusLabels } from "../data/days";
import { PersianCalendar } from "../components/days/PersianCalendar";
import { DayDetail } from "../components/days/DayDetail";
import "./days.css";

import {
  apiPath,
  type InventoryDay,
  type Page,
  displayNumber as number,
  inventorySummary as summarizeDay,
  observationTime,
} from "../api/days";
import { useApi, useDebounced } from "../hooks/useApi";
import { daySearch } from "../lib/daySearch";

export function DaysPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("day");
  const latest = useApi<Page<InventoryDay>>(apiPath("days/", { limit: 1 }));
  const selectedDate =
    requested && isISODate(requested)
      ? requested
      : (latest.data?.results[0]?.day ?? new Date().toISOString().slice(0, 10));
  const [expanded, setExpanded] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(0);
  const [calendarKey, setCalendarKey] = useState(0);
  const [selectedOnly, setSelectedOnly] = useState(Boolean(requested));
  const debouncedSearch = useDebounced(search);
  let searchQuery: Record<string, string> = {};
  let searchError = "";
  try {
    searchQuery = daySearch(debouncedSearch);
  } catch (error) {
    searchError = (error as Error).message;
  }
  const pageSize = 5;
  const listPath = apiPath("days/", {
    limit: pageSize,
    offset: page * pageSize,
    status: status === "all" ? undefined : status,
    ...(selectedOnly && !debouncedSearch
      ? { date_from: selectedDate, date_to: selectedDate }
      : searchQuery),
  });
  const list = useApi<Page<InventoryDay>>(searchError ? null : listPath);
  const detail = useApi<InventoryDay>(
    requested && !isISODate(requested)
      ? null
      : apiPath(`days/${selectedDate}/`),
  );
  const visible = list.data?.results ?? [];
  const filteredCount = list.data?.count ?? 0;
  const pageCount = Math.ceil(filteredCount / pageSize);
  const selected = detail.data;
  const totalRecords = visible.reduce((sum, day) => sum + day.raw_records, 0);
  const totalChunks = visible.reduce(
    (sum, day) => sum + day.observed_chunks,
    0,
  );
  const completedDays = visible.filter(
    (day) => day.status === "complete",
  ).length;
  useEffect(() => {
    setExpanded(selectedDate);
  }, [selectedDate]);
  useEffect(() => {
    if (list.data && page > 0 && page * pageSize >= list.data.count)
      setPage(Math.max(0, Math.ceil(list.data.count / pageSize) - 1));
  }, [list.data, page]);

  function setDate(date: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (next.get("day") !== date) {
        next.delete("chunk");
        next.delete("tab");
      }
      next.set("day", date);
      return next;
    });
  }
  function selectDate(date: string) {
    setDate(date);
    setExpanded(date);
    setSelectedOnly(true);
    setSearch("");
    setStatus("all");
    setPage(0);
  }
  function toggleDay(date: string) {
    setDate(date);
    setExpanded(expanded === date ? null : date);
    setCalendarKey((key) => key + 1);
  }
  const invalidChunk =
    params.has("chunk") &&
    (parseChunkIndex(params.get("chunk")) === undefined || !requested);
  if ((requested !== null && !isISODate(requested)) || invalidChunk) {
    return (
      <main id="main-content" className="main-content days-page" tabIndex={-1}>
        <div className="page-heading">
          <div>
            <h1>روزها و چانک‌ها</h1>
            <p className="page-description">انتخاب روز از آدرس صفحه</p>
          </div>
        </div>
        <div className="days-card invalid-day-link" role="alert">
          <CalendarSearch size={30} />
          <h2>
            {invalidChunk
              ? "شمارهٔ چانک آدرس معتبر نیست"
              : "تاریخ آدرس معتبر نیست"}
          </h2>
          <p>
            {invalidChunk
              ? "چانک باید شمارهٔ صحیح از صفر و همراه با روز مشخص باشد."
              : "پارامتر day باید تاریخ معتبر میلادی با قالب YYYY-MM-DD باشد."}
          </p>
          <Link className="days-text-button" to="/days">
            مشاهدهٔ روزهای موجود
            <ArrowUpLeft size={15} />
          </Link>
        </div>
      </main>
    );
  }
  return (
    <main id="main-content" className="main-content days-page" tabIndex={-1}>
      <div className="page-heading days-page-heading">
        <div>
          <p className="eyebrow">فضای کار / پایش داده‌ها</p>
          <h1>روزها و چانک‌ها</h1>
          <p className="page-description">
            از نمای روزانه تا جزئیات هر پارتیشن؛ مسیر پردازش داده را دنبال کنید.
          </p>
        </div>
        <span className="mock-badge">
          <FlaskConical size={15} />
          اطلاعات سرور
        </span>
      </div>
      <div className="days-notice">
        <Info size={16} />
        <span>
          اطلاعات ثبت‌شدهٔ روزها و چانک‌ها از سرور دریافت می‌شود؛ تکمیل پردازش
          در این صفحه مربوط به لایهٔ اول است.
        </span>
        <span className="snapshot-label">
          {selected
            ? `به‌روزرسانی ${observationTime(selected.updated_at)}`
            : "فهرست ثبت‌شده در سرور"}
        </span>
      </div>
      <section className="days-overview" aria-label="خلاصهٔ روزها">
        {[
          {
            label: "روزهای موجود",
            value: number(latest.data?.count),
            detail: "در فهرست سرور",
            icon: CalendarDays,
            tone: "green",
          },
          {
            label: "رکوردهای خام",
            value: list.data ? number(totalRecords) : "—",
            detail: "مجموع روزهای این صفحه",
            icon: Database,
            tone: "blue",
          },
          {
            label: "چانک‌های موجود",
            value: list.data ? number(totalChunks) : "—",
            detail: "روزهای این صفحه",
            icon: Layers3,
            tone: "purple",
          },
          {
            label: "روزهای تکمیل‌شده",
            value: list.data ? number(completedDays) : "—",
            detail: `در ${number(visible.length)} روز این صفحه`,
            icon: CircleCheck,
            tone: "amber",
          },
        ].map((metric) => (
          <div className="days-card overview-metric" key={metric.label}>
            <div>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <small>{metric.detail}</small>
            </div>
            <span className={`metric-icon ${metric.tone}`}>
              <metric.icon size={21} strokeWidth={1.6} />
            </span>
          </div>
        ))}
      </section>
      <div className="days-layout">
        <section
          className="days-card recent-days"
          aria-labelledby="recent-days-title"
        >
          <div className="recent-heading">
            <div>
              <h2 id="recent-days-title">
                روزهای اخیر{" "}
                <span className="count-badge">{number(list.data?.count)}</span>
              </h2>
              <p>برای مشاهدهٔ چانک‌ها و گزارش، یک روز را باز کنید.</p>
            </div>
            <CalendarDays size={19} />
          </div>
          <div className="days-toolbar">
            <label className="days-search">
              <Search size={16} />
              <input
                aria-label="جست‌وجوی روز"
                placeholder="جست‌وجوی تاریخ شمسی یا میلادی…"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setSelectedOnly(false);
                  setPage(0);
                }}
              />
            </label>
            <select
              aria-label="وضعیت روز"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setSelectedOnly(false);
                setPage(0);
              }}
            >
              <option value="all">همهٔ وضعیت‌ها</option>
              {Object.entries(dayStatusLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          {detail.error?.status === 404 && (
            <div className="no-day-data" role="status">
              <CalendarSearch size={25} />
              <div>
                <strong>برای {dateLabel(selectedDate)} داده‌ای نداریم.</strong>
                <p>یکی از روزهای نقطه‌دار تقویم یا فهرست زیر را انتخاب کنید.</p>
              </div>
            </div>
          )}
          <div
            className="days-table-scroll"
            role="region"
            aria-label="جدول روزهای اخیر"
            tabIndex={0}
          >
            <table className="recent-days-table">
              <thead>
                <tr>
                  <th scope="col">روز / تاریخ</th>
                  <th scope="col">رکورد خام</th>
                  <th scope="col">پوشش چانک</th>
                  <th scope="col">وضعیت روز</th>
                  <th scope="col">
                    <span className="sr-only">باز کردن روز</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((day) => {
                  const summary = summarizeDay(day);
                  const isOpen = expanded === day.day;
                  return (
                    <Fragment key={day.day}>
                      <tr
                        className={`day-row${selectedDate === day.day ? " selected-day" : ""}`}
                        onClick={() => toggleDay(day.day)}
                      >
                        <th scope="row">
                          <button
                            className="day-select"
                            aria-expanded={isOpen}
                            aria-controls={
                              isOpen ? `day-detail-${day.day}` : undefined
                            }
                            aria-label={`${isOpen ? "بستن" : "مشاهده"} روز ${dateLabel(day.day)}`}
                          >
                            <span
                              className={`day-calendar-icon${isOpen ? " chosen" : ""}`}
                            >
                              <CalendarDays size={19} />
                            </span>
                            <span>
                              {dateLabel(day.day)}
                              <small>
                                {new Intl.DateTimeFormat("fa-IR", {
                                  weekday: "long",
                                  timeZone: "UTC",
                                }).format(new Date(`${day.day}T12:00:00Z`))}
                                <span className="date-divider">·</span>
                                <bdi>{day.day}</bdi>
                              </small>
                            </span>
                          </button>
                        </th>
                        <td className="numeric-cell">
                          {number(summary.records)}
                          <small className="cell-caption">
                            {summary.volumeMB == null
                              ? "حجم اندازه‌گیری نشده"
                              : `${number(summary.volumeMB)} مگابایت`}
                          </small>
                        </td>
                        <td>
                          <span className="coverage-value">
                            {number(day.observed_chunks)}{" "}
                            <small>از {number(day.expected_chunks)}</small>
                          </span>
                          <progress
                            value={
                              day.expected_chunks == null
                                ? undefined
                                : day.observed_chunks
                            }
                            max={day.expected_chunks ?? 1}
                            aria-label={`پوشش ورودی ${dateLabel(day.day)}`}
                          />
                        </td>
                        <td>
                          <span className={`status-pill ${summary.status}`}>
                            <i />
                            {dayStatusLabels[summary.status]}
                          </span>
                        </td>
                        <td>
                          <div className="day-row-actions">
                            <Link
                              className="day-context-link"
                              to={inspectionPath(day.day)}
                              onClick={(event) => event.stopPropagation()}
                              aria-label={`گزارش روز ${day.day}`}
                            >
                              <FileText size={13} />
                              گزارش روز
                              <ArrowUpLeft size={13} />
                            </Link>
                            <ChevronDown
                              size={17}
                              className={`row-chevron${isOpen ? " open" : ""}`}
                            />
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="day-expanded-row">
                          <td colSpan={5}>
                            <DayDetail key={day.day} day={day} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
                {!visible.length && (
                  <tr>
                    <td className="table-empty" colSpan={5}>
                      <Search size={25} />
                      <strong
                        role={list.error || searchError ? "alert" : "status"}
                      >
                        {searchError ||
                          list.error?.message ||
                          (list.loading || search !== debouncedSearch
                            ? "در حال دریافت روزها…"
                            : "روزی با این فیلتر پیدا نشد.")}
                      </strong>
                      <button
                        className="days-text-button"
                        onClick={() => {
                          list.retry();
                          latest.retry();
                          detail.retry();
                          if (!list.error) {
                            setSearch("");
                            setSelectedOnly(false);
                            setStatus("all");
                            setPage(0);
                          }
                        }}
                      >
                        {list.error ? "تلاش دوباره" : "نمایش همهٔ روزها"}
                      </button>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="table-pagination">
            <span>
              {number(filteredCount)} روز
              {pageCount > 0 &&
                ` · صفحهٔ ${number(page + 1)} از ${number(pageCount)}`}
            </span>
            <div>
              <button
                aria-label="صفحهٔ قبلی روزها"
                disabled={page === 0 || list.loading}
                onClick={() => setPage(page - 1)}
              >
                قبلی
              </button>
              {Array.from(
                { length: Math.min(pageCount, 5) },
                (_, offset) =>
                  Math.min(Math.max(0, page - 2), Math.max(0, pageCount - 5)) +
                  offset,
              ).map((index) => (
                <button
                  key={index}
                  className={page === index ? "current-page" : ""}
                  aria-label={`صفحهٔ ${number(index + 1)} روزها`}
                  aria-current={page === index ? "page" : undefined}
                  onClick={() => setPage(index)}
                >
                  {number(index + 1)}
                </button>
              ))}
              <button
                aria-label="صفحهٔ بعدی روزها"
                disabled={page + 1 >= pageCount || list.loading}
                onClick={() => setPage(page + 1)}
              >
                بعدی
              </button>
            </div>
          </div>
        </section>
        <aside className="days-aside">
          <PersianCalendar
            key={calendarKey}
            selectedDate={selectedDate}
            onSelect={selectDate}
            live
            latestDate={latest.data?.results[0]?.day}
          />
          <section className="days-card selection-card">
            <div className="selection-label">
              <span className="outline-dot" />
              روز انتخاب‌شده
            </div>
            <h2>{dateLabel(selectedDate, true)}</h2>
            <p dir="ltr" className="selected-iso">
              {selectedDate}
            </p>
            {selected ? (
              <>
                <div className="selection-coverage">
                  <span>پوشش ورودی</span>
                  <strong>
                    {number(summarizeDay(selected).coverage)}
                    {selected.chunk_coverage_percent == null ? "" : "٪"}
                  </strong>
                </div>
                <progress
                  max={100}
                  value={summarizeDay(selected).coverage ?? undefined}
                  aria-label="پوشش ورودی روز انتخاب‌شده"
                />
                <div className="selection-facts">
                  <span>
                    <i className="legend-green" />
                    {number(summarizeDay(selected).complete)} چانک کامل
                  </span>
                  <span>
                    <i className="legend-amber" />
                    {number(summarizeDay(selected).missing)} چانک ناموجود
                  </span>
                </div>
                <button
                  className="days-text-button"
                  onClick={() => {
                    selectDate(selectedDate);
                    document
                      .getElementById("recent-days-title")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  مشاهدهٔ جزئیات روز
                  <ArrowUpLeft size={15} />
                </button>
              </>
            ) : (
              <p className="selection-empty">
                {detail.loading
                  ? "در حال دریافت اطلاعات روز…"
                  : detail.error?.status === 404
                    ? "داده‌ای برای این روز ثبت نشده است."
                    : (detail.error?.message ?? "اطلاعات روز در دسترس نیست.")}
              </p>
            )}
          </section>
          <p className="partition-note">
            <Info size={15} />
            پوشش ورودی با تکمیل پردازش فرق دارد؛ وجود همهٔ چانک‌ها به معنی تکمیل
            مراحل علمی نیست.
          </p>
        </aside>
      </div>
    </main>
  );
}
