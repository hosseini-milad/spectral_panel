import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { dayDetailsPath, isISODate } from "../lib/dayNavigation";
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
  Info,
} from "lucide-react";
import {
  mockDays,
  mockSnapshotDate,
  number,
  dateLabel,
  dayStatusLabels,
  normalizeSearch,
  summarizeDay,
} from "../data/days";
import { PersianCalendar } from "../components/days/PersianCalendar";
import { DayDetail } from "../components/days/DayDetail";
import "./days.css";

export function DaysPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("day");
  if (requested !== null && !isISODate(requested)) {
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
          <h2>تاریخ آدرس معتبر نیست</h2>
          <p>پارامتر day باید تاریخ معتبر میلادی با قالب YYYY-MM-DD باشد.</p>
          <Link
            className="days-text-button"
            to={dayDetailsPath(mockSnapshotDate)}
          >
            مشاهدهٔ آخرین روز نمونه
            <ArrowUpLeft size={15} />
          </Link>
        </div>
      </main>
    );
  }
  const initialDate = requested ?? mockSnapshotDate;
  return (
    <DaysExplorer
      key={initialDate}
      initialDate={initialDate}
      onDateChange={(date) => {
        if (params.get("day") === date) return;
        setParams((previous) => {
          const next = new URLSearchParams(previous);
          next.set("day", date);
          return next;
        });
      }}
    />
  );
}

function DaysExplorer({
  initialDate,
  onDateChange,
}: {
  initialDate: string;
  onDateChange: (date: string) => void;
}) {
  const [selectedDate, setSelectedDate] = useState(initialDate);
  const [expanded, setExpanded] = useState<string | null>(initialDate);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(() =>
    Math.max(
      0,
      Math.floor(mockDays.findIndex((day) => day.date === initialDate) / 5),
    ),
  );
  const [calendarKey, setCalendarKey] = useState(0);
  const filtered = mockDays.filter(
    (day) =>
      (status === "all" || summarizeDay(day).status === status) &&
      normalizeSearch(
        `${day.date} ${dateLabel(day.date, true)} ${new Intl.DateTimeFormat("fa-IR", { timeZone: "UTC", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(`${day.date}T12:00:00Z`))}`,
      ).includes(normalizeSearch(search)),
  );
  const pageSize = 5;
  const pageCount = Math.ceil(filtered.length / pageSize);
  const visible = filtered.slice(page * pageSize, (page + 1) * pageSize);
  const selected = mockDays.find((day) => day.date === selectedDate);
  const totalRecords = mockDays.reduce(
    (sum, day) => sum + summarizeDay(day).records,
    0,
  );
  const totalChunks = mockDays.reduce((sum, day) => sum + day.chunks.length, 0);
  const completedDays = mockDays.filter(
    (day) => summarizeDay(day).status === "complete",
  ).length;

  function selectDate(date: string) {
    onDateChange(date);
    setSelectedDate(date);
    setExpanded(date);
    setSearch("");
    setStatus("all");
    const index = mockDays.findIndex((day) => day.date === date);
    setPage(index < 0 ? 0 : Math.floor(index / pageSize));
  }
  function toggleDay(date: string) {
    onDateChange(date);
    setSelectedDate(date);
    setExpanded(expanded === date ? null : date);
    setCalendarKey((key) => key + 1);
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
          نسخهٔ ماک
        </span>
      </div>
      <div className="days-notice">
        <Info size={16} />
        <span>
          همهٔ داده‌ها، وضعیت‌ها و برآوردهای این صفحه نمایشی‌اند. هیچ پردازش
          واقعی اجرا نمی‌شود.
        </span>
        <span className="snapshot-label">
          نمونه تا {dateLabel(mockSnapshotDate)}
        </span>
      </div>
      <section className="days-overview" aria-label="خلاصهٔ روزهای نمونه">
        {[
          {
            label: "روزهای موجود",
            value: number(mockDays.length),
            detail: "در مجموعهٔ نمونه",
            icon: CalendarDays,
            tone: "green",
          },
          {
            label: "رکوردهای خام",
            value: number(totalRecords),
            detail: "مجموع روزهای نمونه",
            icon: Database,
            tone: "blue",
          },
          {
            label: "چانک‌های موجود",
            value: number(totalChunks),
            detail: "پارتیشن‌های ورودی",
            icon: Layers3,
            tone: "purple",
          },
          {
            label: "روزهای تکمیل‌شده",
            value: number(completedDays),
            detail: `از ${number(mockDays.length)} روز نمونه`,
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
                <span className="count-badge">{number(mockDays.length)}</span>
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
                  setPage(0);
                }}
              />
            </label>
            <select
              aria-label="وضعیت روز"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
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
          {!selected && (
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
                  const isOpen = expanded === day.date;
                  return (
                    <Fragment key={day.date}>
                      <tr
                        className={`day-row${selectedDate === day.date ? " selected-day" : ""}`}
                        onClick={() => toggleDay(day.date)}
                      >
                        <th scope="row">
                          <button
                            className="day-select"
                            aria-expanded={isOpen}
                            aria-controls={
                              isOpen ? `day-detail-${day.date}` : undefined
                            }
                            aria-label={`${isOpen ? "بستن" : "مشاهده"} روز ${dateLabel(day.date)}`}
                          >
                            <span
                              className={`day-calendar-icon${isOpen ? " chosen" : ""}`}
                            >
                              <CalendarDays size={19} />
                            </span>
                            <span>
                              {dateLabel(day.date)}
                              <small>
                                {new Intl.DateTimeFormat("fa-IR", {
                                  weekday: "long",
                                  timeZone: "UTC",
                                }).format(new Date(`${day.date}T12:00:00Z`))}
                                <span className="date-divider">·</span>
                                <bdi>{day.date}</bdi>
                              </small>
                            </span>
                          </button>
                        </th>
                        <td className="numeric-cell">
                          {number(summary.records)}
                          <small className="cell-caption">
                            ≈ {number(summary.volumeMB)} مگابایت
                          </small>
                        </td>
                        <td>
                          <span className="coverage-value">
                            {number(day.chunks.length)}{" "}
                            <small>از {number(day.expectedChunks)}</small>
                          </span>
                          <progress
                            value={day.chunks.length}
                            max={day.expectedChunks}
                            aria-label={`پوشش ورودی ${dateLabel(day.date)}`}
                          />
                        </td>
                        <td>
                          <span className={`status-pill ${summary.status}`}>
                            <i />
                            {dayStatusLabels[summary.status]}
                          </span>
                        </td>
                        <td>
                          <ChevronDown
                            size={17}
                            className={`row-chevron${isOpen ? " open" : ""}`}
                          />
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="day-expanded-row">
                          <td colSpan={5}>
                            <DayDetail key={day.date} day={day} />
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
                      <strong>روزی با این فیلتر پیدا نشد.</strong>
                      <button
                        className="days-text-button"
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
          <div className="table-pagination">
            <span>
              {number(filtered.length)} روز
              {pageCount > 0 &&
                ` · صفحهٔ ${number(page + 1)} از ${number(pageCount)}`}
            </span>
            <div>
              <button
                aria-label="صفحهٔ قبلی روزها"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                قبلی
              </button>
              {Array.from({ length: pageCount }, (_, index) => (
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
                disabled={page + 1 >= pageCount}
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
                  <strong>{number(summarizeDay(selected).coverage)}٪</strong>
                </div>
                <progress
                  max={100}
                  value={summarizeDay(selected).coverage}
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
                داده‌ای برای این روز در نمونه نیست.
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
